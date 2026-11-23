"""Tiny offline synth: tune -> audio. For tests and for hearing an extraction as a file."""
from __future__ import annotations

import numpy as np

from .notation import TICKS, Tune


def tone(pitch: float, secs: float, sr: int) -> np.ndarray:
    n = max(1, int(secs * sr))
    x = np.arange(n) / sr
    f = 440 * 2 ** ((pitch - 69) / 12)
    y = sum(a * np.sin(2 * np.pi * f * k * x) for k, a in ((1, 1), (2, .5), (3, .25), (4, .12)) if f * k < sr / 2)
    env = np.minimum(1, x / 0.01) * np.exp(-1.2 * x) * np.minimum(1, (n - np.arange(n)) / (0.03 * sr))
    return y * env


def render(t: Tune, sr: int = 22050, chords: float = 0.0, pad: float = 0.0) -> np.ndarray:
    spt = 60 / t.bpm / TICKS
    out = np.zeros(int((t.length * spt + pad + 0.5) * sr))

    def put(y: np.ndarray, at: float) -> None:
        i = int(at * sr)
        y = y[: len(out) - i]
        out[i:i + len(y)] += y

    for n in t.notes:
        put(0.3 * tone(n.pitch, n.dur * spt * 0.95, sr), pad + n.start * spt)
    if chords:
        ends = [c.start for c in t.chords[1:]] + [t.length]
        for c, e in zip(t.chords, ends):
            for pc in c.pcs:
                put(chords * tone(48 + pc, (e - c.start) * spt * 0.95, sr), pad + c.start * spt)
    return out
