"""Guess a melody inside areas the user highlighted in a picture of the recording.

Runs as its own process, like transcribe.py, on the folder that `transcribe` filled:

    python -m tunelab.guide picture work/ SOURCE            draws SOURCE.strength, SOURCE.spectrum
    python -m tunelab.guide listen  work/ marks.json out    the sound inside the highlights
    python -m tunelab.guide guess   work/ marks.json out    a melody candidate

The highlights are a grid of cells, CELL seconds by 1 / PER semitone. The picture has the same
pitch range, in steps of a third of a semitone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import librosa
import numpy as np
from scipy.io import wavfile

from . import extract, models
from .transcribe import HOP, LEAD, Raw, candidate, load, sung_notes

LO, HI = extract.F_LOW, 96  # C2 to C7
CELL, PER = 0.05, 2
ROWS = (HI - LO) * PER + 1
POOL = 2  # analysis frames per column of the picture
OVERTONES = (12, 19, 24)  # semitones above the note they belong to
GRID = {"lo": LO, "hi": HI, "cell": CELL, "per": PER}

Runs = list[tuple[int, int, int]]  # row, first column, column after the last


class Marks:
    """only: where nothing is highlighted there is no melody; otherwise it is searched as usual."""

    def __init__(self, melody: Runs, not_melody: Runs, only: bool = False) -> None:
        self.only = only
        self.melody, self.not_melody = self._grid(melody), self._grid(not_melody)

    @staticmethod
    def _grid(runs: Runs) -> np.ndarray:
        g = np.zeros((max((b for _, _, b in runs), default=0) + 1, ROWS + 1), dtype=bool)
        for row, a, b in runs:
            g[a:b, row] = True
        return g  # the last row and column stay empty: places off the grid are sent there

    @staticmethod
    def _columns(grid: np.ndarray, times: np.ndarray) -> np.ndarray:
        return np.minimum((np.asarray(times) / CELL + 1e-6).astype(int), len(grid) - 1)

    def _at(self, grid: np.ndarray, times: np.ndarray, pitches: np.ndarray) -> np.ndarray:
        rows = np.rint((np.asarray(pitches) - LO) * PER).astype(int)
        rows[(rows < 0) | (rows >= ROWS)] = ROWS
        return grid[self._columns(grid, times)][:, rows]

    def painted(self, times: np.ndarray) -> np.ndarray:
        return self.melody.any(axis=1)[self._columns(self.melody, times)]

    def highlighted(self, times: np.ndarray, pitches: np.ndarray) -> np.ndarray:
        return self._at(self.melody, times, pitches)

    def allowed(self, times: np.ndarray, pitches: np.ndarray, lo: float = -np.inf, hi: float = np.inf) -> np.ndarray:
        """(times x pitches). lo, hi: the pitches searched at times without a highlight."""
        ok = self.highlighted(times, pitches)
        if not self.only:
            usual = (np.asarray(pitches) >= lo) & (np.asarray(pitches) <= hi)
            ok = ok | (~self.painted(times)[:, None] & usual[None])
        return ok & ~self._at(self.not_melody, times, pitches)


# ---------- picture ----------
def frame_times(n: int) -> np.ndarray:
    return np.arange(n) * extract.HOP / extract.SR


def strength(y: np.ndarray) -> np.ndarray:
    """How likely the melody is at each (frame, third of a semitone), comparable to the automatic search."""
    return extract.salience(y, LO, HI, anchor=LEAD[0])


def _bytes(a: np.ndarray) -> bytes:
    """(frames x pitches) as one byte each, row by row from the lowest pitch."""
    a = a[:len(a) - len(a) % POOL].reshape(-1, POOL, a.shape[1]).max(axis=1)
    top = np.percentile(a, 99.8) or 1
    return (np.clip(a / top, 0, 1) * 255).astype(np.uint8).T.tobytes()


def dim_overtones(sal: np.ndarray) -> np.ndarray:
    """For the eye only: fade what may be an overtone of a stronger note below."""
    below = np.zeros_like(sal)
    for d in OVERTONES:
        k = d * extract.BPO // 12
        below[:, k:] = np.maximum(below[:, k:], sal[:, :-k])
    return sal * np.minimum(1, sal / (below + 1e-9)) ** 2


def picture(work: Path, source: str) -> None:
    y = extract.decode(Path(info(work)["files"][source]))
    sal = strength(extract.clean(y))
    (work / f"{source}.strength").write_bytes(_bytes(dim_overtones(sal)))
    (work / f"{source}.spectrum").write_bytes(_bytes(extract.spectrum(y)[:sal.shape[1]].T))
    meta = {"columns": len(sal) // POOL, "rows": sal.shape[1], "seconds": len(y) / extract.SR,
            "step": POOL * extract.HOP / extract.SR, **GRID}
    (work / f"{source}.json").write_text(json.dumps(meta))  # last: marks the picture as complete


# ---------- sound inside the highlights ----------
def listen(y: np.ndarray, marks: Marks) -> np.ndarray:
    size, hop = 4096, 1024
    s = librosa.stft(y, n_fft=size, hop_length=hop)
    width = extract.SR / size
    f = np.arange(1, len(s)) * width
    times = np.arange(s.shape[1]) * hop / extract.SR
    keep = np.zeros(s.shape, dtype=bool)
    for i, hz in enumerate(f, 1):
        lo, hi = librosa.hz_to_midi([hz - width / 2, hz + width / 2])
        if lo > HI + 1:
            break
        # low bins are wider than a cell: keep one when any cell in it is highlighted
        keep[i] = marks.highlighted(times, np.arange(lo, hi + 1 / PER, 1 / PER)).any(axis=1)
    out = librosa.istft(s * keep, n_fft=size, hop_length=hop, length=len(y))
    peak = np.abs(out).max()
    if peak < 1e-4:
        raise ValueError("There is no sound inside the highlights.")
    return out / peak * 0.8


# ---------- guess ----------
def overtone_doubt(raw: list[Raw], sal: np.ndarray) -> float:
    """Share of the time in which the notes look like overtones: a note they could belong to is stronger."""
    per = extract.BPO // 12
    total = doubtful = 0.0
    for a, b, p in raw:
        x, y = (round(t * extract.SR / extract.HOP) for t in (a, b))
        part = sal[x:max(x + 1, y)]
        i = (p - LO) * per
        if not len(part) or not 1 <= i < sal.shape[1] - 1:
            continue
        level = lambda k: part[:, k - 1:k + 2].max(axis=1).mean()  # noqa: E731
        total += b - a
        doubtful += (b - a) * any(i - d * per >= 1 and level(i) < level(i - d * per) for d in OVERTONES)
    return doubtful / total if total else 0.0


def coverage(raw: list[Raw], marks: Marks) -> float:
    """Share of the highlighted time in which there are notes."""
    times = (np.flatnonzero(marks.melody.any(axis=1)) + 0.5) * CELL
    return float(np.mean([any(a <= t < b for a, b, _ in raw) for t in times])) if len(times) else 1.0


def guess(facts: dict, source: str, marks: Marks, name: str) -> dict:
    file = Path(facts["files"][source])
    y = extract.clean(extract.decode(file))
    sal = strength(y)
    if source == "vocals" or (source == "mix" and facts["sung"]):
        raw = sung_notes(models.rmvpe_session(), load(file), alone=source == "vocals", marks=marks)
    else:
        pitches = LO + np.arange(sal.shape[1]) * 12 / extract.BPO
        raw = extract.notes_from_salience(y, sal, LO, marks.allowed(frame_times(len(sal)), pitches, *LEAD))
    if not raw:
        raise ValueError("No notes found in the highlights. Try a wider brush, an octave lower, or another source.")
    out = candidate(name, raw, facts)
    inside = [n for n in raw if marks.painted(np.array([(n[0] + n[1]) / 2]))[0]]
    # on the test clips: at least 0.6 when highlighted well, under 0.1 for singing highlighted at an overtone
    if coverage(raw, marks) < 0.3:
        out["warning"] = "Few notes were found in the highlights. Try an octave lower, or another source."
    # at most 0.3 when highlighted well, nearly always over 0.6 at an overtone
    elif overtone_doubt(inside, sal) > 0.4:
        out["warning"] = ("Your highlights may be on overtones: a note an octave or more below is stronger. "
                          "If this sounds too high, highlight that one instead.")
    else:
        out["warning"] = ""
    return out


def info(work: Path) -> dict:
    return json.loads((work / "info.json").read_text())


def main() -> None:
    task, work = sys.argv[1], Path(sys.argv[2])
    try:
        if task == "picture":
            return picture(work, sys.argv[3])
        q = json.loads(Path(sys.argv[3]).read_text())
        marks, facts, out = Marks(q["melody"], q["not_melody"], q["only"]), info(work), Path(sys.argv[4])
        if task == "listen":
            y = listen(extract.decode(Path(facts["files"][q["source"]])), marks)
            wavfile.write(out, extract.SR, (y * 32767).astype(np.int16))
        else:
            out.write_text(json.dumps(guess(facts, q["source"], marks, q["name"])))
    except ValueError as e:
        print(f"@error {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
