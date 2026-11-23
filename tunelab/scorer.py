"""Rule-based discriminator: how "nice" is a tune, 0..1, with every sub-score visible.

All constants here are hand-set guesses from general melodic conventions. They are
generic, not personal taste. Edit freely, then run `uv run tunelab-check`.
"""
from __future__ import annotations

import math
from collections import Counter

from .notation import TICKS, Note, Tune

WEIGHTS = {
    "tonal": 1.0,  # notes belong to the key, weighty notes to the tonic triad
    "intervals": 1.5,  # mostly steps, some leaps, leaps get recovered
    "contour": 1.0,  # sensible range, direction, one clear high point
    "motif": 1.5,  # ideas come back, without being the same thing forever
    "rhythm": 1.0,  # some variety, anchored to the beat
    "cadence": 1.0,  # ends somewhere that feels like an ending
    "chord_fit": 1.0,  # strong-beat notes agree with the chord (if there are chords)
}


def bell(x: float, centre: float, width: float) -> float:
    return math.exp(-(((x - centre) / width) ** 2))


def plateau(x: float, lo: float, hi: float, soft: float) -> float:
    """1 inside [lo, hi], falling off smoothly outside."""
    if x < lo:
        return bell(x, lo, soft)
    return bell(x, hi, soft) if x > hi else 1.0


def is_strong(t: Tune, tick: int) -> bool:
    pos = t.bar_pos(tick)
    if pos == 0:
        return True
    num, den = t.meter
    half = t.bar // 2
    return pos == half and (num == 4 or (num == 6 and den == 8))


def tonal(t: Tune) -> float:
    total = sum(n.dur for n in t.notes)
    scale = t.scale_pcs()
    if t.mode == "hmin":
        scale = scale | {(t.tonic + 10) % 12}
    inside = sum(n.dur for n in t.notes if n.pitch % 12 in scale) / total
    third = 4 if t.mode == "maj" else 3
    triad = {(t.tonic + i) % 12 for i in (0, third, 7)}
    heavy = [n for n in t.notes if is_strong(t, n.start) or n.dur >= 2 * TICKS] or t.notes
    stable = sum(n.dur for n in heavy if n.pitch % 12 in triad) / sum(n.dur for n in heavy)
    return 0.65 * inside**3 + 0.35 * plateau(stable, 0.45, 0.85, 0.3)


def intervals(t: Tune) -> float:
    iv = [b.pitch - a.pitch for a, b in zip(t.notes, t.notes[1:])]
    n = len(iv)
    steps = sum(1 <= abs(i) <= 2 for i in iv) / n
    repeats = sum(i == 0 for i in iv) / n
    big = sum(abs(i) > 9 for i in iv) / n
    awkward = sum(abs(i) in (6, 10, 11) for i in iv) / n
    mean = sum(abs(i) for i in iv) / n
    leaps = [k for k in range(n - 1) if abs(iv[k]) >= 5]
    recovered = (sum(iv[k + 1] * iv[k] <= 0 and abs(iv[k + 1]) <= 4 for k in leaps) / len(leaps)
                 if leaps else 1.0)
    return (0.30 * plateau(steps, 0.4, 0.75, 0.25) + 0.10 * plateau(repeats, 0.0, 0.3, 0.25)
            + 0.25 * plateau(mean, 1.2, 2.6, 1.0) + 0.15 * recovered
            + 0.10 * max(0.0, 1 - 8 * big) + 0.10 * max(0.0, 1 - 8 * awkward))


def contour(t: Tune) -> float:
    p = [n.pitch for n in t.notes]
    rng = max(p) - min(p)
    moves = [b - a for a, b in zip(p, p[1:]) if b != a]
    turns = sum(a * b < 0 for a, b in zip(moves, moves[1:])) / max(1, len(moves) - 1)
    # high point: rare, and not right at the beginning
    top = [n for n in t.notes if n.pitch == max(p)]
    rarity = plateau(len(top) / len(p), 0.0, 0.15, 0.2)
    place = plateau(top[0].start / max(1, t.length), 0.15, 0.85, 0.3)
    return (0.35 * plateau(rng, 7, 14, 4) + 0.35 * plateau(turns, 0.25, 0.5, 0.15)
            + 0.15 * rarity + 0.15 * place)


def _grams(t: Tune, n: int) -> list[tuple]:
    """Transposition-tolerant n-note shapes: (coarse interval, duration) sequences."""
    def coarse(i: int) -> int:
        return (i > 0) - (i < 0) if abs(i) <= 2 else (2 if abs(i) <= 4 else 3) * (1 if i > 0 else -1)
    ns = t.notes
    return [tuple((coarse(ns[k + j + 1].pitch - ns[k + j].pitch), ns[k + j].dur) for j in range(n - 1))
            for k in range(len(ns) - n + 1)]


def motif(t: Tune) -> float:
    parts = []
    for n in (3, 4, 5):
        g = _grams(t, n)
        if len(g) >= 4:
            counts = Counter(g)
            parts.append(sum(c for c in counts.values() if c > 1) / len(g))
    repeated = sum(parts) / len(parts) if parts else 0.0
    g3 = _grams(t, 3)
    top = Counter(g3).most_common(1)[0][1] / len(g3) if g3 else 1.0
    return 0.8 * plateau(repeated, 0.5, 0.85, 0.3) + 0.2 * plateau(top, 0.0, 0.3, 0.2)


def rhythm(t: Tune) -> float:
    d = Counter(n.dur for n in t.notes)
    total = len(t.notes)
    ent = -sum(c / total * math.log2(c / total) for c in d.values())
    onsets = {n.start for n in t.notes}
    bars = range(t.pickup, max(t.pickup + 1, t.length), t.bar)
    downbeats = sum(b in onsets for b in bars) / len(bars)
    on_beat = sum(n.start % TICKS == 0 for n in t.notes) / total
    # do long notes start on beats rather than off them?
    long = [n for n in t.notes if n.dur >= 1.5 * TICKS]
    anchored = sum(n.start % TICKS == 0 for n in long) / len(long) if long else 1.0
    density = total / max(1, t.length / TICKS)
    return (0.25 * plateau(ent, 0.7, 1.9, 0.5) + 0.25 * plateau(downbeats, 0.7, 1.0, 0.3)
            + 0.2 * plateau(on_beat, 0.45, 1.0, 0.2) + 0.15 * anchored
            + 0.15 * plateau(density, 0.6, 2.0, 0.5))


def cadence(t: Tune) -> float:
    last, prev = t.notes[-1], t.notes[-2]
    degree = (last.pitch - t.tonic) % 12
    end = {0: 1.0, 7: 0.5, 4: 0.5, 3: 0.5}.get(degree, 0.0)
    approach = bell(max(0, abs(last.pitch - prev.pitch) - 2), 0, 3)
    mean = sum(n.dur for n in t.notes) / len(t.notes)
    length = min(1.0, last.dur / (1.5 * mean))
    # the note sustaining or ending at the halfway point is a phrase end
    mid = t.pickup + (t.length - t.pickup) // 2
    before: list[Note] = [n for n in t.notes if n.start < mid]
    rest = 0.0
    if before:
        rest = 0.5 * min(1.0, before[-1].dur / (1.5 * mean))
        rest += 0.5 * ((before[-1].pitch - t.tonic) % 12 in (0, 2, 3, 4, 7, 11))
    return (0.4 * end + 0.15 * approach + 0.2 * length
            + 0.1 * is_strong(t, last.start) + 0.15 * rest)


def chord_fit(t: Tune) -> float | None:
    if not t.chords:
        return None
    good = total = 0.0
    for n in t.notes:
        c = t.chord_at(n.start)
        if c is None:
            continue
        w = n.dur * (2 if is_strong(t, n.start) else 1)
        total += w
        good += w * (n.pitch % 12 in c.pcs)
    return plateau(good / total, 0.6, 0.9, 0.25) if total else None


PARTS = {"tonal": tonal, "intervals": intervals, "contour": contour, "motif": motif,
         "rhythm": rhythm, "cadence": cadence, "chord_fit": chord_fit}


def score(t: Tune) -> tuple[float, dict[str, float]]:
    if len(t.notes) < 4:
        return 0.0, {}
    parts = {k: v for k, f in PARTS.items() if (v := f(t)) is not None}
    w = sum(WEIGHTS[k] for k in parts)
    return (round(sum(WEIGHTS[k] * v for k, v in parts.items()) / w, 4),
            {k: round(v, 3) for k, v in parts.items()})
