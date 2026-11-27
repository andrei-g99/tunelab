"""Derive the main melody from an audio file and score it.

    uv run tunelab-extract song.mp3 --start 30 --seconds 20 --save

Steps: decode (ffmpeg) -> noise gate + drop percussion -> pitch salience by harmonic
summation -> smooth melody path (Viterbi) -> notes -> beat grid -> key -> notation.

Expect errors on dense mixes; best on a solo instrument, voice or a clear lead.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import librosa
import numpy as np
from scipy.io import wavfile
from scipy.ndimage import median_filter

from . import db
from .notation import TICKS, NotationError, Note, Tune, dump, pitch_name
from .scorer import score
from .synth import render

SR = 22050
HOP = 256
BPO = 36  # CQT bins per octave
F_LOW = 36  # C2
MAX_SECONDS = 600


def decode(path: Path, start: float = 0.0, seconds: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", str(start), "-i", str(path.resolve()),
           "-t", str(min(seconds or MAX_SECONDS, MAX_SECONDS)),
           "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        raise ValueError(f"ffmpeg could not read {path}: {r.stderr.decode(errors='replace').strip()}")
    y = np.frombuffer(r.stdout, dtype=np.float32).copy()
    if len(y) < SR:
        raise ValueError("less than one second of audio in that range")
    peak = np.abs(y).max()
    if peak < 1e-4:
        raise ValueError("audio is silent")
    return y / peak


def clean(y: np.ndarray) -> np.ndarray:
    """Spectral gate against steady noise, then keep the harmonic (non-drum) part."""
    s = librosa.stft(y, n_fft=2048, hop_length=HOP)
    mag = np.abs(s)
    # A sustained drone looks like noise to a percentile floor, so the floor per bin is
    # capped at the broadband level: hiss is flat across frequency, a held note is a peak.
    floor = np.percentile(mag, 10, axis=1)
    floor = np.minimum(floor, 2 * median_filter(floor, size=65))[:, None]
    gain = np.clip((mag - 2 * floor) / (mag + 1e-9), 0.02, 1.0)
    harm, _ = librosa.decompose.hpss(s * gain, margin=(1.0, 1.0))
    return librosa.istft(harm, hop_length=HOP, length=len(y))


# tuned on synthetic melody+chords mixes (see README for what that does and doesn't prove)
COMPRESS, SUB_OCT, SUB_TWELFTH, HEIGHT, JUMP = 0.5, 0.0, 0.0, 0.03, 0.06


def spectrum(y: np.ndarray) -> np.ndarray:
    """(pitches in thirds of a semitone, upwards from F_LOW x frames), 0..1, in the recording's own tuning"""
    tuning = float(librosa.estimate_tuning(y=y, sr=SR))
    n_bins = BPO * 7 + 6  # just over seven octaves, safely below Nyquist
    c = np.abs(librosa.cqt(y, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(F_LOW),
                           n_bins=n_bins, bins_per_octave=BPO, tuning=tuning * BPO / 12))
    return (c / (c.max() + 1e-9)) ** COMPRESS  # compress, so loud bass doesn't drown the lead


def salience(y: np.ndarray, lo: int, hi: int, anchor: int | None = None) -> np.ndarray:
    """(frames x candidate pitches in thirds of a semitone). anchor: the pitch with neutral weight, or lo."""
    c = spectrum(y)
    n_bins, per = len(c), BPO // 12
    cands = np.arange((lo - F_LOW) * per, (hi - F_LOW) * per + 1)
    sal = np.zeros((c.shape[1], len(cands)))
    for h in range(1, 7):
        idx = cands + int(round(BPO * np.log2(h)))
        ok = idx < n_bins
        sal[:, ok] += 0.75 ** (h - 1) * c[idx[ok]].T
    # energy an octave (or a twelfth) BELOW a candidate suggests it is only an overtone
    for d, w in ((12, SUB_OCT), (19, SUB_TWELFTH)):
        idx = cands - d * per
        ok = idx >= 0
        sal[:, ok] -= w * c[idx[ok]].T
    # a lead line usually sits above its accompaniment
    return np.maximum(sal, 0) * (1 + HEIGHT * (cands / per - ((lo if anchor is None else anchor) - F_LOW)))


def melody_path(sal: np.ndarray) -> np.ndarray:
    """Viterbi: strong salience at each frame, paying for pitch movement."""
    n, k = sal.shape
    d = np.abs(np.subtract.outer(np.arange(k), np.arange(k))) / (BPO // 12)
    cost = JUMP * np.minimum(d, 12)
    cost[d > 0] += 0.15
    best = sal[0].copy()
    back = np.zeros((n, k), dtype=np.int32)
    for i in range(1, n):
        m = best[None, :] - cost
        back[i] = m.argmax(axis=1)
        best = m[np.arange(k), back[i]] + sal[i]
    path = np.empty(n, dtype=int)
    path[-1] = best.argmax()
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return path


def segment(y: np.ndarray, lo: int, hi: int) -> list[tuple[float, float, int]]:
    """(start seconds, end seconds, MIDI pitch)"""
    return notes_from_salience(y, salience(y, lo, hi), lo)


def notes_from_salience(y: np.ndarray, sal: np.ndarray, lo: int,
                        allowed: np.ndarray | None = None) -> list[tuple[float, float, int]]:
    """allowed: where notes may be, same shape as sal; nothing is found elsewhere."""
    if allowed is not None:
        sal = sal * allowed
    path = melody_path(sal)
    pitch = np.rint(lo + path / (BPO // 12)).astype(int)
    pitch = median_filter(pitch, size=7)
    strength = sal[np.arange(len(path)), path]
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    n = min(len(rms), len(strength))
    pitch, strength, rms = pitch[:n], strength[:n], rms[:n]
    heard = strength if allowed is None else strength[strength > 0]  # else a small area would count as silence
    if not len(heard):
        return []
    voiced = (strength > 0.35 * np.percentile(heard, 90)) & (rms > 0.05 * np.percentile(rms, 95))

    onset_env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    onsets = set(librosa.onset.onset_detect(onset_envelope=onset_env, sr=SR, hop_length=HOP,
                                            backtrack=False, delta=0.12).tolist())
    notes: list[list[int]] = []
    for i in range(n):
        if not voiced[i]:
            continue
        cur = notes[-1] if notes else None
        # a re-strike of the same pitch: an onset well into the current note
        restrike = cur and i in onsets and i - cur[0] > 8
        if cur and cur[1] == i and cur[2] == pitch[i] and not restrike:
            cur[1] = i + 1
        else:
            notes.append([i, i + 1, int(pitch[i])])
    min_frames = int(0.07 * SR / HOP)
    sec = HOP / SR
    kept = [x for x in notes if x[1] - x[0] >= min_frames]
    # merge fragments of one note separated by a tiny glitch
    merged: list[list[int]] = []
    for x in kept:
        if merged and merged[-1][2] == x[2] and x[0] - merged[-1][1] < min_frames and x[0] not in onsets:
            merged[-1][1] = x[1]
        else:
            merged.append(list(x))
    return [(a * sec, b * sec, p) for a, b, p in merged]


def estimate_key(notes: list[Note]) -> tuple[int, str]:
    """Krumhansl-Kessler profile match on a duration-weighted pitch histogram."""
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    h = np.zeros(12)
    for n in notes:
        h[n.pitch % 12] += n.dur
    if np.count_nonzero(h) < 2:
        return int(h.argmax()), "maj"
    best = max(((np.corrcoef(np.roll(p, k), h)[0, 1], k, m)
                for k in range(12) for m, p in (("maj", major), ("min", minor))))
    tonic, mode = best[1], best[2]
    if mode == "min" and h[(tonic + 11) % 12] > h[(tonic + 10) % 12]:
        mode = "hmin"
    return tonic, mode


def beat_grid(y: np.ndarray, bpm: float | None) -> np.ndarray:
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    kw = {"bpm": bpm} if bpm else {}
    _, beats = librosa.beat.beat_track(onset_envelope=env, sr=SR, hop_length=HOP, trim=False, **kw)
    times = librosa.frames_to_time(beats, sr=SR, hop_length=HOP)
    if len(times) < 4:
        step = 60 / (bpm or 100)
        times = np.arange(0, len(y) / SR + step, step)
    return times


def quantize(raw: list[tuple[float, float, int]], beats: np.ndarray, bpm: float | None
             ) -> tuple[list[Note], int]:
    step = float(np.median(np.diff(beats)))
    idx = np.arange(len(beats))

    def to_beat(x: float) -> float:
        if x < beats[0]:
            return (x - beats[0]) / step
        if x > beats[-1]:
            return idx[-1] + (x - beats[-1]) / step
        return float(np.interp(x, beats, idx))

    grid = TICKS // 4
    spans = [(to_beat(a) * TICKS, to_beat(b) * TICKS, p) for a, b, p in raw]
    # beat trackers find the spacing well but often sit slightly off the notes
    starts = np.array([s for s, _, _ in spans])
    offs = np.arange(-grid, grid, 0.25)
    def miss(o: float) -> float:
        z = starts - o
        return float(np.abs(z - 2 * grid * np.rint(z / (2 * grid))).mean())
    off = min(offs, key=miss)
    out: list[Note] = []
    for a, b, p in spans:
        s = int(round((a - off) / grid)) * grid
        e = max(s + grid, int(round((b - off) / grid)) * grid)
        if out and s <= out[-1].start:  # two notes landed on the same slot: keep the longer
            if e - s > out[-1].dur:
                out[-1] = Note(p, s, e - s)
            continue
        if out and out[-1].end > s:
            out[-1].dur = s - out[-1].start
        out.append(Note(p, s, e - s))
    # small gaps are articulation, not rests
    for a, b in zip(out, out[1:]):
        if 0 < b.start - a.end <= 2 * grid:
            a.dur = b.start - a.start
    if out and out[-1].dur % TICKS:
        out[-1].dur += TICKS - out[-1].dur % TICKS
    return out, int(round(np.clip(60 / step, 20, 400)))


def align_bars(notes: list[Note], bar: int) -> list[Note]:
    """Shift so the most heavily accented beat of the bar (long notes) becomes beat 1."""
    weight = [0.0] * (bar // TICKS)
    for n in notes:
        if n.start % TICKS == 0:
            weight[(n.start // TICKS) % len(weight)] += n.dur ** 1.5
    first = notes[0].start // TICKS * TICKS
    weight[(first // TICKS) % len(weight)] *= 1.3  # excerpts usually begin on beat 1
    down = int(np.argmax(weight)) * TICKS
    shift = down + ((notes[0].start - down) // bar) * bar
    return [Note(n.pitch, n.start - shift, n.dur) for n in notes]


def extract(y: np.ndarray, lo: int = 48, hi: int = 88, bpm: float | None = None,
            meter: tuple[int, int] = (4, 4)) -> Tune:
    if not np.any(np.abs(y) > 1e-6):
        raise ValueError("audio is silent")
    c = clean(y)
    raw = segment(c, lo, hi)
    if len(raw) < 4:
        raise ValueError("found fewer than 4 notes; try another section or --low/--high")
    notes, tempo = quantize(raw, beat_grid(y, bpm), bpm)
    tune = Tune(0, "maj", tempo, meter)
    tune.notes = align_bars(notes, tune.bar)
    tune.tonic, tune.mode = estimate_key(tune.notes)
    tune.length = tune.notes[-1].end
    tune.length += -tune.length % tune.bar
    return tune


def _pitch(text: str) -> int:
    m = re.fullmatch(r"([A-Ga-g])(#|b)?(\d)", text)
    if not m:
        raise argparse.ArgumentTypeError("use a note name such as C3 or F#5")
    return int(librosa.note_to_midi(text))


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract and score the main melody of an audio file")
    ap.add_argument("audio", type=Path)
    ap.add_argument("--start", type=float, default=0, help="seconds into the file")
    ap.add_argument("--seconds", type=float, default=30, help="how much to analyse")
    ap.add_argument("--low", type=_pitch, default=48, help="lowest melody note (default C3)")
    ap.add_argument("--high", type=_pitch, default=88, help="highest melody note (default E6)")
    ap.add_argument("--bpm", type=float, help="tempo hint, if the detected one is wrong")
    ap.add_argument("--meter", choices=["4/4", "3/4", "2/4", "6/8"], default="4/4")
    ap.add_argument("--wav", type=Path, help="write the extracted melody as synth audio")
    ap.add_argument("--save", action="store_true", help="show it in the web page under Imported")
    a = ap.parse_args()
    if not a.audio.is_file():
        sys.exit(f"no such file: {a.audio}")
    if a.start < 0 or a.seconds <= 0 or a.low < F_LOW or a.high > 96 or a.low >= a.high:
        sys.exit("check --start/--seconds, and keep --low/--high within C2..C7")
    if a.bpm is not None and not 30 <= a.bpm <= 300:
        sys.exit("--bpm must be between 30 and 300")
    num, den = map(int, a.meter.split("/"))
    try:
        tune = extract(decode(a.audio, a.start, a.seconds), a.low, a.high, a.bpm, (num, den))
    except (ValueError, NotationError) as e:
        sys.exit(str(e))
    s, parts = score(tune)
    text = dump(tune)
    print(text)
    print(f"\n{len(tune.notes)} notes, {pitch_name(min(n.pitch for n in tune.notes))} to "
          f"{pitch_name(max(n.pitch for n in tune.notes))}\nscore {s:.2f}")
    for k, v in parts.items():
        print(f"  {k:10} {v:.2f}")
    if a.wav:
        audio = render(tune, SR)
        wavfile.write(a.wav, SR, (audio / np.abs(audio).max() * 0.9 * 32767).astype(np.int16))
        print(f"wrote {a.wav}")
    if a.save:
        c = db.connect()
        with c:
            db.add(c, "audio", text, s, parts, name=a.audio.name)
        c.close()
        print("saved: see the Imported tab")


if __name__ == "__main__":
    main()
