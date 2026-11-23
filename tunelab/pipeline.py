"""Generate a batch, score it, decide what deserves a human listen."""
from __future__ import annotations

import random
from dataclasses import dataclass
from difflib import SequenceMatcher

from .generator import Options, generate
from .notation import Tune, dump
from .scorer import score

REFERENCE_SIZE = 600


@dataclass
class Scored:
    tune: Tune
    text: str
    score: float
    parts: dict[str, float]
    flag: str = ""  # "", "top" or "wildcard"


def fingerprint(t: Tune) -> list[tuple[int, int]]:
    """Transposition-independent shape of a tune."""
    return [(b.pitch - a.pitch, a.dur) for a, b in zip(t.notes, t.notes[1:])]


def similar(a: list, b: list, limit: float = 0.75) -> bool:
    m = SequenceMatcher(None, a, b, autojunk=False)
    return m.real_quick_ratio() > limit and m.quick_ratio() > limit and m.ratio() > limit


_bars: dict[tuple, list[float]] = {}


def threshold(opt: Options, top_percent: float) -> float:
    """Score that only top_percent of a fixed reference batch reaches.

    Using a fixed yardstick (not the batch itself) means scores are comparable
    between runs, and a weak small batch can correctly flag nothing.
    """
    key = (opt.mode, opt.meter, opt.bars)
    if key not in _bars:
        r = random.Random(12345)
        _bars[key] = sorted((score(generate(opt, r))[0] for _ in range(REFERENCE_SIZE)), reverse=True)
    ref = _bars[key]
    return ref[min(len(ref) - 1, int(len(ref) * top_percent / 100))]


def run_batch(n: int, opt: Options, top_percent: float, known: list[list], seed: int | None = None
              ) -> tuple[list[Scored], float]:
    r = random.Random(seed)
    cut = threshold(opt, top_percent)
    batch = []
    for _ in range(n):
        t = generate(opt, r)
        s, parts = score(t)
        batch.append(Scored(t, dump(t), s, parts))
    batch.sort(key=lambda x: -x.score)
    seen = list(known)
    for x in batch:
        if x.score < cut:
            break
        fp = fingerprint(x.tune)
        if any(similar(fp, k) for k in seen):
            continue
        x.flag = "top"
        seen.append(fp)
    # a few picks the scorer did NOT choose, so its blind spots get heard too
    rest = [x for x in batch if x.score < cut]
    for x in r.sample(rest, min(len(rest), max(1, n // 100) if n >= 20 else 0)):
        x.flag = "wildcard"
    return batch, cut
