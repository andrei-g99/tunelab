"""Melody generator: scale + chords + a short motif that is repeated and varied."""
from __future__ import annotations

import random
from dataclasses import dataclass

from .notation import SCALES, TICKS, Chord, Note, Tune

# 4-bar chord loops as scale degrees (0 = tonic). "open" ends away from home.
OPEN = {
    "maj": [[0, 5, 3, 4], [0, 3, 0, 4], [0, 4, 5, 3], [0, 2, 3, 4], [5, 3, 0, 4], [0, 1, 4, 4]],
    "min": [[0, 5, 2, 6], [0, 3, 6, 6], [0, 6, 5, 6], [0, 5, 3, 4], [0, 2, 6, 3]],
    "hmin": [[0, 3, 0, 4], [0, 5, 3, 4], [0, 3, 4, 4], [5, 3, 0, 4]],
}
CLOSED = {
    "maj": [[0, 5, 4, 0], [0, 3, 4, 0], [5, 3, 4, 0], [3, 0, 4, 0], [0, 1, 4, 0]],
    "min": [[0, 5, 6, 0], [5, 2, 6, 0], [0, 3, 4, 0], [3, 5, 6, 0]],
    "hmin": [[0, 3, 4, 0], [5, 3, 4, 0], [3, 0, 4, 0]],
}
# one-bar rhythms in eighths-of-a-beat-friendly ticks (12 = one beat)
RHYTHMS = {
    (4, 4): [[12, 12, 12, 12], [12, 12, 24], [24, 12, 12], [18, 6, 12, 12], [18, 6, 24],
             [12, 6, 6, 12, 12], [12, 6, 6, 24], [6, 6, 12, 12, 12], [6, 6, 12, 24],
             [12, 12, 6, 6, 12], [18, 18, 12], [6, 12, 6, 12, 12], [12, 6, 6, 6, 6, 12],
             [36, 12], [9, 3, 12, 24], [6, 6, 6, 6, 12, 12], [18, 6, 18, 6]],
    (3, 4): [[12, 12, 12], [24, 12], [18, 6, 12], [12, 6, 6, 12], [6, 6, 12, 12],
             [12, 12, 6, 6], [18, 18], [24, 6, 6]],
}
FORMS = [["A", "A'", "B", "C"], ["A", "B", "A", "C"], ["A", "A'", "A''", "C"], ["A", "B", "A'", "C"]]
LOW, HIGH = 57, 81  # A3..A5


@dataclass
class Options:
    mode: str = "any"
    meter: str = "4/4"
    bars: int = 8
    bpm_lo: int = 80
    bpm_hi: int = 130


@dataclass
class Motif:
    rhythm: list[list[int]]  # per bar
    moves: list[list[int]]  # per bar, scale-degree steps; first entry of a bar is unused


def _degree_pitch(tonic: int, mode: str, d: int) -> int:
    """Scale degree (any integer) to MIDI; degree 0 is the tonic near middle C."""
    base = 60 + tonic if tonic <= 6 else 48 + tonic
    return base + 12 * (d // 7) + SCALES[mode][d % 7]


def _triad(tonic: int, mode: str, degree: int, start: int) -> Chord:
    pcs = [(tonic + SCALES[mode][(degree + k) % 7]) % 12 for k in (0, 2, 4)]
    shape = ((pcs[1] - pcs[0]) % 12, (pcs[2] - pcs[0]) % 12)
    quality = {(4, 7): "", (3, 7): "m", (3, 6): "dim", (4, 8): "aug"}[shape]
    return Chord(start, pcs[0], quality)


def _move(r: random.Random) -> int:
    return r.choices([0, 1, -1, 2, -2, 3, -3, 4, -4],
                     [10, 26, 28, 9, 9, 4, 3, 3, 2])[0]


def _make_motif(r: random.Random, cells: list[list[int]]) -> Motif:
    first = r.choice(cells)
    second = first if r.random() < 0.35 else r.choice(cells)
    return Motif([first, second], [[_move(r) for _ in first], [_move(r) for _ in second]])


def _vary(r: random.Random, m: Motif, cells: list[list[int]]) -> Motif:
    """Keep the recognisable first bar; change how it continues."""
    kind = r.choice(["tail", "tail", "moves", "invert"])
    rhythm, moves = [list(b) for b in m.rhythm], [list(b) for b in m.moves]
    if kind == "tail":
        rhythm[1] = list(r.choice(cells))
        moves[1] = [_move(r) for _ in rhythm[1]]
    elif kind == "moves":
        moves[1] = [_move(r) for _ in rhythm[1]]
    else:
        moves[1] = [-x for x in moves[1]]
    return Motif(rhythm, moves)


def _nearest(target: int, allowed: set[int], near: int) -> int:
    """Degree closest to target whose class is allowed, preferring small motion."""
    return min((d for d in range(target - 4, target + 5) if d % 7 in allowed),
               key=lambda d: (abs(d - target), abs(d - near)))


def generate(opt: Options, r: random.Random) -> Tune:
    mode = r.choice(list(SCALES)) if opt.mode == "any" else opt.mode
    num, den = map(int, opt.meter.split("/"))
    cells = RHYTHMS[(num, den)]
    tonic = r.randrange(12)
    t = Tune(tonic, mode, r.randint(opt.bpm_lo, opt.bpm_hi), (num, den))
    bar = t.bar

    sections = opt.bars // 4
    degrees: list[int] = []
    for s in range(sections):
        degrees += r.choice((CLOSED if s == sections - 1 else OPEN)[mode])
    t.chords = [_triad(tonic, mode, d, i * bar) for i, d in enumerate(degrees)]

    motifs = {"A": _make_motif(r, cells)}
    motifs["B"] = _make_motif(r, cells)
    motifs["A'"] = _vary(r, motifs["A"], cells)
    motifs["A''"] = _vary(r, motifs["A"], cells)
    motifs["C"] = _vary(r, motifs[r.choice("AB")], cells)
    units = opt.bars // 2  # each unit is two bars
    form = list(r.choice(FORMS))
    if units > 4:
        form = r.choice(FORMS)[:3] + ["B"] + form
        form = form[:units]
    form = form[:units - 1] + ["C"]

    lo = next(d for d in range(-14, 14) if _degree_pitch(tonic, mode, d) >= LOW)
    hi = next(d for d in range(14, -14, -1) if _degree_pitch(tonic, mode, d) <= HIGH)
    centre = (lo + hi) // 2
    prev = centre + r.randint(-2, 2)

    for b in range(opt.bars):
        m = motifs[form[b // 2]]
        rhythm, moves = m.rhythm[b % 2], m.moves[b % 2]
        chord = {(degrees[b] + k) % 7 for k in (0, 2, 4)}
        start = b * bar
        if b == opt.bars - 1:  # ending: land on the tonic, stay there
            home = _nearest(prev, {0}, prev)
            home = home if lo <= home <= hi else _nearest(centre, {0}, prev)
            t.notes.append(Note(_degree_pitch(tonic, mode, home), start, bar))
            break
        # strengthen phrase ends: last bar of each 4-bar section breathes
        if b % 4 == 3:
            rhythm = [bar] if r.random() < 0.3 else [bar - TICKS, TICKS]
        pos = start
        for i, dur in enumerate(rhythm):
            step = moves[i] if i < len(moves) else _move(r)
            target = prev + step
            if target > hi or target < lo:
                target = prev - step
            # gently pull back towards the middle of the range
            if abs(target - centre) > 5 and r.random() < 0.5:
                target += 1 if target < centre else -1
            if i == 0 or (pos - start) == bar // 2:
                target = _nearest(target, chord, prev)
            last_of_phrase = b == opt.bars - 2 and i == len(rhythm) - 1
            if last_of_phrase:
                target = _nearest(prev, {1, 6}, prev)  # lean into the tonic by step
            target = max(lo, min(hi, target))
            t.notes.append(Note(_degree_pitch(tonic, mode, target), pos, dur))
            prev = target
            pos += dur
    t.length = opt.bars * bar
    return t


def random_notes(opt: Options, r: random.Random) -> Tune:
    """Structure-free baseline: in-key notes, random durations. Used for comparison only."""
    mode = r.choice(list(SCALES)) if opt.mode == "any" else opt.mode
    num, den = map(int, opt.meter.split("/"))
    t = Tune(r.randrange(12), mode, r.randint(opt.bpm_lo, opt.bpm_hi), (num, den))
    t.length = opt.bars * t.bar
    pool = [p for p in range(LOW, HIGH + 1) if p % 12 in t.scale_pcs()]
    pos = 0
    while pos < t.length:
        dur = min(r.choice([6, 12, 12, 18, 24]), t.length - pos)
        t.notes.append(Note(r.choice(pool), pos, dur))
        pos += dur
    return t
