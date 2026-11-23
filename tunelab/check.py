"""Does the scorer rank real melodies above broken versions of themselves?

    uv run tunelab-check

For each reference tune, builds damaged copies and reports how often the real one
scores higher (50% = coin flip). Chord-free, so the generator plays no part.
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from .generator import Options, generate
from .notation import Note, Tune, parse
from .scorer import score

REFERENCE = Path(__file__).resolve().parent.parent / "data" / "reference.txt"


def load_reference() -> list[tuple[str, str, Tune]]:
    blocks = re.split(r"^== ", REFERENCE.read_text(), flags=re.M)[1:]
    out = []
    for b in blocks:
        title, body = b.split("\n", 1)
        split, name = title.split(": ", 1)
        out.append((split, name, parse(body)))
    return out


def _rebuild(t: Tune, notes: list[Note]) -> Tune:
    return Tune(t.tonic, t.mode, t.bpm, t.meter, t.pickup, notes, [], t.length)


def shuffle_pitches(t: Tune, r: random.Random) -> Tune:
    """Keep the rhythm, scramble which pitch goes where."""
    p = [n.pitch for n in t.notes]
    r.shuffle(p)
    return _rebuild(t, [Note(q, n.start, n.dur) for q, n in zip(p, t.notes)])


def shuffle_notes(t: Tune, r: random.Random) -> Tune:
    """Scramble whole notes (pitch and duration together)."""
    items = [(n.pitch, n.dur) for n in t.notes]
    r.shuffle(items)
    out, pos = [], 0
    for p, d in items:
        out.append(Note(p, pos, d))
        pos += d
    return _rebuild(t, out)


def shuffle_durations(t: Tune, r: random.Random) -> Tune:
    """Keep the pitch order, scramble durations."""
    d = [n.dur for n in t.notes]
    r.shuffle(d)
    out, pos = [], 0
    for n, x in zip(t.notes, d):
        out.append(Note(n.pitch, pos, x))
        pos += x
    return _rebuild(t, out)


def random_scale(t: Tune, r: random.Random) -> Tune:
    """Keep the rhythm, draw random in-key pitches from the same range."""
    lo, hi = min(n.pitch for n in t.notes), max(n.pitch for n in t.notes)
    pool = [p for p in range(lo, hi + 1) if p % 12 in t.scale_pcs()]
    return _rebuild(t, [Note(r.choice(pool), n.start, n.dur) for n in t.notes])


DAMAGE = {"shuffled pitches": shuffle_pitches, "shuffled notes": shuffle_notes,
          "shuffled durations": shuffle_durations, "random in-key": random_scale}


def win_rates(split: str, copies: int = 100, seed: int = 1) -> dict[str, dict[str, float]]:
    r = random.Random(seed)
    res: dict[str, dict[str, float]] = {}
    for s, name, t in load_reference():
        if s != split:
            continue
        real = score(t)[0]
        res[name] = {"score": real}
        for label, f in DAMAGE.items():
            res[name][label] = sum(real > score(f(t, r))[0] for _ in range(copies)) / copies
    return res


def main() -> None:
    for split in ("dev", "holdout"):
        res = win_rates(split)
        print(f"\n{split}  (share of damaged copies the real tune beats)")
        print(f"{'':30}{'score':>7}" + "".join(f"{k:>20}" for k in DAMAGE))
        for name, row in res.items():
            print(f"{name:30}{row['score']:7.2f}" + "".join(f"{row[k]:20.0%}" for k in DAMAGE))
        print(f"{'MEAN':37}" + "".join(
            f"{sum(r[k] for r in res.values()) / len(res):20.0%}" for k in DAMAGE))
    # Harder question the damage test can't answer: can the scorer tell real from generated?
    r = random.Random(7)
    gen = [score(_rebuild(t, t.notes))[0] for t in (generate(Options(), r) for _ in range(1000))]
    print("\nshare of generated tunes (chords removed) scoring above each real tune:")
    for s, name, t in load_reference():
        real = score(t)[0]
        print(f"  {s:8} {name:30}{real:6.2f}{sum(g > real for g in gen) / len(gen):8.0%}")


if __name__ == "__main__":
    main()
