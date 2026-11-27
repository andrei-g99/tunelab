"""Guess the main melody of a recording, as a few candidates to choose between by ear.

Runs as its own process (`python -m tunelab.transcribe in.wav out.json work/`), so that the server stays
responsive and graphics memory is free again afterwards. Prints "@step ..." lines as it goes.

    with the networks: vocals present? -> pitch of the singing, of the mix, and of the lead instrument
                       otherwise       -> lead instrument (extract.py), and RMVPE on the mix
    without:           extract.py only
Then for each: notes in seconds -> beat grid and bars -> key -> melody document.
"""
from __future__ import annotations

import json
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

import librosa
import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d

from . import extract, models
from .documents import melody_from_tune
from .notation import TICKS, Note, Tune

Raw = tuple[float, float, int]  # start seconds, end seconds, MIDI pitch
VOCAL_SHARE = 0.15  # loudness of the vocals relative to the mix, above which the clip is sung
MIN_NOTES = 4
HOP = models.RMVPE_HOP / models.RMVPE_SR


# ---------- pitch curve to notes ----------
def tuning_offset(midi: np.ndarray) -> float:
    """How far the recording is from A=440, in semitones, or 0 when there is no clear answer."""
    z = np.exp(2j * np.pi * midi).mean() if len(midi) else 0
    return float(np.angle(z) / (2 * np.pi)) if abs(z) > 0.2 else 0.0


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist()))


def steps(midi: np.ndarray, change: float = 4.0) -> np.ndarray:
    """Nearest semitone at each frame, changing only when that pays off: the path that minimises
    the distance to the curve plus `change` per switch. Keeps vibrato and slides from splitting notes."""
    lo, hi = int(np.floor(midi.min())), int(np.ceil(midi.max()))
    cost = np.abs(midi[:, None] - np.arange(lo, hi + 1)[None])
    total, back = cost[0].copy(), np.zeros(cost.shape, dtype=np.int32)
    stay = np.arange(cost.shape[1])
    for i in range(1, len(cost)):
        best = int(total.argmin())
        back[i] = np.where(total <= total[best] + change, stay, best)
        total = np.minimum(total, total[best] + change) + cost[i]
    path = np.empty(len(cost), dtype=int)
    path[-1] = total.argmin()
    for i in range(len(cost) - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return path + lo


def _restrikes(loud: np.ndarray, a: int, b: int, margin: int = 8) -> list[int]:
    """Frames where one held pitch is clearly struck again: loudness dips and comes back."""
    out, last = [], a
    for i in range(a + margin, b - margin):
        v = loud[i]
        if (i - last >= margin and v == loud[max(a, i - margin):i + margin + 1].min()
                and v < 0.4 * min(loud[last:i].max(), loud[i:min(b, i + 30)].max())):
            out.append(i)
            last = i
    return out


def notes_from_pitch(hz: np.ndarray, voiced: np.ndarray, loud: np.ndarray | None = None,
                     hop: float = HOP, min_seconds: float = 0.07) -> list[Raw]:
    """Notes from a pitch curve. `loud` (per frame) is used to separate repeated notes."""
    voiced = voiced & np.isfinite(hz) & (hz > 0)
    if not voiced.any():
        return []
    midi = np.zeros(len(hz))
    midi[voiced] = 69 + 12 * np.log2(hz[voiced] / 440)
    midi[voiced] -= tuning_offset(midi[voiced])
    for a, b in _runs(~voiced):  # bridge dropouts of up to 30 ms
        if 0 < a and b < len(hz) and b - a <= 0.03 / hop and abs(midi[a - 1] - midi[b]) < 1:
            midi[a:b] = np.linspace(midi[a - 1], midi[b], b - a)
            voiced[a:b] = True
    least = max(1, round(min_seconds / hop))
    out: list[Raw] = []
    for a, b in _runs(voiced):
        if b - a < least:
            continue
        path = steps(median_filter(midi[a:b], size=3))
        cuts = [a, *(a + 1 + np.flatnonzero(np.diff(path))).tolist(), b]
        for s, e in zip(cuts, cuts[1:]):
            marks = [s, *(_restrikes(loud, s, e) if loud is not None else []), e]
            out += [(p * hop, q * hop, int(path[s - a])) for p, q in zip(marks, marks[1:]) if q - p >= least]
    return out


def sung_notes(session, y: np.ndarray, alone: bool, marks=None) -> list[Raw]:
    """Notes of the singing in mono audio at RMVPE_SR; alone: nothing else is in it.
    marks: optional guide.Marks, limiting where notes may be."""
    hz, conf = models.sung_pitch(session, y, marks and marks.allowed)
    loud = librosa.feature.rms(y=y, frame_length=1024, hop_length=models.RMVPE_HOP)[0]
    loud = uniform_filter1d(loud[:len(hz)], 3)
    least = 0.03 if alone else 0.1
    if marks:  # inside a highlight, believe weaker evidence
        least = np.where(marks.painted(np.arange(len(hz)) * HOP), 0.3 * least, least)
    voiced = conf > least
    if alone:  # ignore what leaks through the separation
        voiced &= loud > 0.03 * np.percentile(loud, 95)
    return notes_from_pitch(hz, voiced, loud if alone else None)


# ---------- beats and bars ----------
def to_tune(raw: list[Raw], beats: np.ndarray, downbeats: np.ndarray) -> Tune:
    """Snap to the beat grid: quarters of a beat, or thirds when those fit clearly better."""
    beats = np.asarray(beats, dtype=float)
    if len(beats) < 4:  # no pulse found: keep the timing, at an arbitrary tempo
        beats = raw[0][0] + np.arange(0, raw[-1][1] - raw[0][0] + 1, 0.6)
    step = float(np.median(np.diff(beats)))
    idx = np.arange(len(beats))

    def at(x: float) -> float:
        if x < beats[0]:
            return (x - beats[0]) / step
        if x > beats[-1]:
            return float(idx[-1] + (x - beats[-1]) / step)
        return float(np.interp(x, beats, idx))

    starts = np.array([at(a) for a, _, _ in raw])
    # fast notes sharing a sixteenth: the beat was found at half speed, so count twice as fast
    lost = len(raw) - len(np.unique(np.rint(starts * 4)))
    if lost > 0.05 * len(raw) and step > 0.65:  # below about 90 bpm
        halves = np.interp(np.arange(2 * len(beats) - 1) / 2, idx, beats)
        return to_tune(raw, halves, downbeats)

    def miss(div: int) -> float:  # average distance to the grid, relative to its spacing
        return float(np.abs(starts * div - np.rint(starts * div)).mean())

    grid = TICKS // 3 if miss(3) < 0.6 * miss(4) else TICKS // 4
    notes: list[Note] = []
    for a, b, p in raw:
        s = round(at(a) * TICKS / grid) * grid
        e = max(s + grid, round(at(b) * TICKS / grid) * grid)
        if notes and s <= notes[-1].start:  # two notes on one slot: keep the longer
            if e - s > notes[-1].dur:
                notes[-1] = Note(p, notes[-1].start, e - s)
            continue
        if notes and s - notes[-1].end <= grid:  # overlap, or a gap that is only articulation
            notes[-1].dur = s - notes[-1].start
        notes.append(Note(p, s, e - s))

    tune = Tune(0, "maj", int(np.clip(round(60 / step), 20, 400)), (4, 4))
    first = np.array([int(np.abs(beats - d).argmin()) for d in downbeats], dtype=int)
    if len(first) >= 2:
        size = int(np.median(np.diff(first)))
        tune.meter = {2: (2, 4), 3: (3, 4), 6: (3, 4)}.get(size, (4, 4))
        per_bar = tune.bar // TICKS
        phase = int(np.bincount(first % per_bar).argmax()) * TICKS
        shift = phase + (notes[0].start - phase) // tune.bar * tune.bar
        tune.notes = [Note(n.pitch, n.start - shift, n.dur) for n in notes]
    else:
        tune.notes = extract.align_bars(notes, tune.bar)
    tune.tonic, tune.mode = extract.estimate_key(tune.notes)
    tune.length = tune.notes[-1].end
    tune.length += -tune.length % tune.bar
    return tune


# ---------- candidates ----------
def distinct(found: list[tuple[str, list[Raw]]]) -> list[tuple[str, list[Raw]]]:
    """Drop candidates that are too short, or the same tune as an earlier one."""
    out: list[tuple[str, list[Raw]]] = []
    for name, raw in found:
        p = [n[2] for n in raw]
        same = any(SequenceMatcher(None, p, [n[2] for n in r], autojunk=False).ratio() > 0.97 for _, r in out)
        if len(raw) >= MIN_NOTES and not same:
            out.append((name, raw))
    return out


LEAD = (48, 88)  # pitches a lead instrument is looked for in


def lead_notes(wav: Path) -> list[Raw]:
    return extract.segment(extract.clean(extract.decode(wav)), *LEAD)


def rms(y: np.ndarray) -> float:
    return float(np.sqrt(np.mean(y ** 2)))


def load(path: Path) -> np.ndarray:
    return librosa.load(path, sr=models.RMVPE_SR, mono=True)[0]


def with_networks(wav: Path, work: Path, say) -> tuple[list[tuple[str, list[Raw]]], dict]:
    models.check_gpu()
    mix = load(wav)
    say("Separating the vocals")
    vocals, rest = models.separate(wav, work)
    voc = load(vocals)
    sung = rms(voc) > VOCAL_SHARE * rms(mix)
    say("Listening for the melody")
    session = models.rmvpe_session()
    on_mix = sung_notes(session, mix, alone=False)
    if sung:
        found = [("Vocals", sung_notes(session, voc, alone=True)), ("Vocals, from the full mix", on_mix),
                 ("Lead instrument", lead_notes(rest))]
    else:
        found = [("Lead instrument", lead_notes(wav)), ("Lead, second opinion", on_mix)]
    say("Finding the beat")
    y, sr = librosa.load(wav, sr=None, mono=True)
    beats, down = models.beats(y, sr)
    return found, {"files": {"mix": str(wav), "vocals": str(vocals), "rest": str(rest)}, "sung": sung,
                   "beats": beats.tolist(), "downbeats": down.tolist()}


def candidate(name: str, raw: list[Raw], info: dict) -> dict:
    tune = to_tune(raw, np.array(info["beats"]), np.array(info["downbeats"]))
    return {"name": name, "notes": raw, "melody": melody_from_tune(tune, name, "recording").model_dump()}


def transcribe(wav: Path, say=lambda step: None, work: Path | None = None) -> dict:
    """{"warning", "candidates": [{"name", "notes": performed timing, "melody": snapped document}]}
    work: a folder that receives what `guide.py` needs: info.json and the separated audio."""
    if work is None:
        with tempfile.TemporaryDirectory() as tmp:
            return transcribe(wav, say, Path(tmp))
    y = extract.decode(wav)  # also checks the length, and that it is not silent
    warning, found = "", None
    if models.installed():
        try:
            found, info = with_networks(wav, work, say)
        except Exception as e:  # e.g. out of graphics memory, or no network for the first download
            warning = f"The neural models failed, so the basic method was used: {e}"
            print(f"models failed: {e!r}", file=sys.stderr)
    else:
        warning = "The neural models are not installed (uv sync --extra gpu), so the basic method was used."
    if found is None:
        say("Listening for the melody")
        found = [("Basic method", lead_notes(wav))]
        info = {"files": {"mix": str(wav)}, "sung": False,
                "beats": extract.beat_grid(y, None).tolist(), "downbeats": []}
    (work / "info.json").write_text(json.dumps(info))  # also when nothing is found: guiding may help
    out = [candidate(name, raw, info) for name, raw in distinct(found)]
    if not out:
        raise ValueError("No melody found. Try a section where one line stands out.")
    return {"warning": warning, "candidates": out}


def main() -> None:
    wav, out, work = map(Path, sys.argv[1:4])
    try:
        result = transcribe(wav, lambda step: print(f"@step {step}", flush=True), work)
    except ValueError as e:
        print(f"@error {e}", flush=True)
        sys.exit(1)
    out.write_text(json.dumps(result))


if __name__ == "__main__":
    main()
