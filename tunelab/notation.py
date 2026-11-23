"""The tune text format, and the Tune object everything else works on.

    key=A:min bpm=100 meter=4/4 pickup=1
    [Am] A4:1 C5:1/2 E5:1/2 D5:3/2 C5:1/2 | [F] A4:1 -:1 C5:2 |

PITCH:DURATION, durations in quarter-note beats (1, 1/2, 3/4, 1/3). "-" is a rest.
[Am] is a chord from that point on. "|" must fall on a bar boundary; a note that
sustains across a boundary simply has no "|" there. Internally: 12 ticks per beat.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

TICKS = 12
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
LETTERS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SCALES = {
    "maj": [0, 2, 4, 5, 7, 9, 11],
    "min": [0, 2, 3, 5, 7, 8, 10],
    "hmin": [0, 2, 3, 5, 7, 8, 11],
}
QUALITIES = {"": (0, 4, 7), "m": (0, 3, 7), "dim": (0, 3, 6), "aug": (0, 4, 8)}


class NotationError(ValueError):
    pass


@dataclass
class Note:
    pitch: int  # MIDI number
    start: int  # ticks
    dur: int  # ticks

    @property
    def end(self) -> int:
        return self.start + self.dur


@dataclass
class Chord:
    start: int
    root: int  # pitch class
    quality: str

    @property
    def pcs(self) -> set[int]:
        return {(self.root + i) % 12 for i in QUALITIES[self.quality]}

    @property
    def label(self) -> str:
        return NAMES[self.root] + self.quality


@dataclass
class Tune:
    tonic: int
    mode: str
    bpm: int
    meter: tuple[int, int] = (4, 4)
    pickup: int = 0
    notes: list[Note] = field(default_factory=list)
    chords: list[Chord] = field(default_factory=list)
    length: int = 0  # ticks, includes trailing rests

    @property
    def bar(self) -> int:
        return self.meter[0] * 4 * TICKS // self.meter[1]

    def bar_pos(self, tick: int) -> int:
        return (tick - self.pickup) % self.bar

    def scale_pcs(self) -> set[int]:
        return {(self.tonic + s) % 12 for s in SCALES[self.mode]}

    def chord_at(self, tick: int) -> Chord | None:
        current = None
        for c in self.chords:
            if c.start > tick:
                break
            current = c
        return current


def pitch_name(p: int) -> str:
    return f"{NAMES[p % 12]}{p // 12 - 1}"


def _pc(text: str) -> int:
    pc = LETTERS[text[0]]
    return (pc + text.count("#") - text[1:].count("b")) % 12


def _ticks(text: str) -> int:
    try:
        t = Fraction(text) * TICKS
    except (ValueError, ZeroDivisionError):
        raise NotationError(f"bad duration '{text}'") from None
    if t.denominator != 1 or t <= 0:
        raise NotationError(f"duration '{text}' must be positive and a multiple of 1/{TICKS} beat")
    return int(t)


def parse(text: str) -> Tune:
    head = dict(re.findall(r"\b(key|bpm|meter|pickup)=(\S+)", text))
    body = re.sub(r"\b(key|bpm|meter|pickup)=\S+", " ", text)
    m = re.fullmatch(r"([A-G][#b]?):(maj|min|hmin)", head.get("key", ""))
    if not m:
        raise NotationError("need key=<tonic>:<maj|min|hmin>, e.g. key=A:min")
    mm = re.fullmatch(r"(\d{1,2})/(2|4|8)", head.get("meter", "4/4"))
    if not mm or int(mm[1]) == 0:
        raise NotationError("bad meter, use e.g. 4/4, 3/4 or 6/8")
    bpm_text = head.get("bpm", "100")
    if not bpm_text.isdigit() or not 20 <= int(bpm_text) <= 400:
        raise NotationError("bpm must be a whole number from 20 to 400")
    pickup_text = head.get("pickup", "0")
    t = Tune(_pc(m[1]), m[2], int(bpm_text), (int(mm[1]), int(mm[2])),
             0 if pickup_text == "0" else _ticks(pickup_text))
    pos = 0
    for tok in re.findall(r"\[[^\]]*\]|\||[^\s|\[\]]+", body):
        if tok == "|":
            if t.bar_pos(pos):
                raise NotationError(f"barline at beat {pos / TICKS:g} is not on a bar boundary")
        elif tok[0] == "[":
            cm = re.fullmatch(r"\[([A-G][#b]?)(m|dim|aug|)\]", tok)
            if not cm:
                raise NotationError(f"unknown chord '{tok}'")
            t.chords.append(Chord(pos, _pc(cm[1]), cm[2]))
        else:
            nm = re.fullmatch(r"(-|([A-G][#b]?)(\d)):(\S+)", tok)
            if not nm:
                raise NotationError(f"unknown token '{tok}'")
            dur = _ticks(nm[4])
            if nm[1] != "-":
                # octave follows the written letter, so Cb4 is B3
                p = (int(nm[3]) + 1) * 12 + LETTERS[nm[2][0]]
                p += nm[2].count("#") - nm[2][1:].count("b")
                t.notes.append(Note(p, pos, dur))
            pos += dur
    t.length = pos
    if not t.notes:
        raise NotationError("no notes")
    return t


def dump(t: Tune) -> str:
    head = f"key={NAMES[t.tonic]}:{t.mode} bpm={t.bpm} meter={t.meter[0]}/{t.meter[1]}"
    if t.pickup:
        head += f" pickup={Fraction(t.pickup, TICKS)}"
    events: list[tuple[str, int, int]] = []  # text prefix, start, dur
    pos = 0
    for n in t.notes:
        if n.start > pos:
            events.append(("-", pos, n.start - pos))
        events.append((pitch_name(n.pitch), n.start, n.dur))
        pos = n.end
    if t.length > pos:
        events.append(("-", pos, t.length - pos))
    chords = {c.start: c.label for c in t.chords}
    # split rests at chord changes so every chord has an event to attach to
    split: list[tuple[str, int, int]] = []
    for name, s, d in events:
        cuts = [c for c in sorted(chords) if s < c < s + d] if name == "-" else []
        for a, b in zip([s, *cuts], [*cuts, s + d]):
            split.append((name, a, b - a))
    out = []
    for name, s, d in split:
        if s and t.bar_pos(s) == 0:
            out.append("|")
        if s in chords:
            out.append(f"[{chords[s]}]")
        out.append(f"{name}:{Fraction(d, TICKS)}")
    if t.bar_pos(t.length) == 0:
        out.append("|")
    return head + "\n" + " ".join(out)
