"""Test the transcriber on clips whose melody you corrected by hand.

    uv run tunelab-melody-check clips/

The folder has dev/ and holdout/, each with pairs name.wav + name.json. The .json is a melody
exported from the DAW (Export track as melody) after correcting it. Tune only on dev.
"""
from __future__ import annotations

import argparse
import sys
from difflib import SequenceMatcher
from pathlib import Path

from .documents import MelodyDoc
from .transcribe import transcribe


def agreement(got: MelodyDoc, want: MelodyDoc) -> tuple[float, float]:
    """(pitches, pitches and lengths): 0..1 overlap of the note sequences. Transposing by octaves
    counts as wrong. Lengths are compared in sixteenths, so a halved tempo counts as wrong too."""
    def seq(d: MelodyDoc, rhythm: bool) -> list:
        ns = sorted(d.notes, key=lambda n: n.start)
        gaps = [b.start - a.start for a, b in zip(ns, ns[1:])] + [ns[-1].dur] if ns else []
        return [(n.pitch, round(g / 120)) if rhythm else n.pitch for n, g in zip(ns, gaps)]
    return tuple(SequenceMatcher(None, seq(got, r), seq(want, r), autojunk=False).ratio() for r in (False, True))


def main() -> None:
    ap = argparse.ArgumentParser(description="Test the Melody Transcriber on hand-corrected clips")
    ap.add_argument("folder", type=Path)
    a = ap.parse_args()
    tested = 0
    for part in ("dev", "holdout"):
        rows = []
        for wav in sorted((a.folder / part).glob("*.wav")):
            ref = wav.with_suffix(".json")
            if not ref.exists():
                print(f"{part}/{wav.name}: skipped, no {ref.name}")
                continue
            want = MelodyDoc.model_validate_json(ref.read_bytes())
            try:
                found = transcribe(wav)["candidates"]
            except ValueError as e:
                print(f"{part}/{wav.stem}: {e}")
                rows.append((0.0, 0.0, 0.0))
                continue
            got = [agreement(MelodyDoc.model_validate(c["melody"]), want) for c in found]
            rows.append((*got[0], max(g[0] for g in got)))
            print(f"{part}/{wav.stem}: pitches {rows[-1][0]:.2f}, with rhythm {rows[-1][1]:.2f}, "
                  f"best candidate {rows[-1][2]:.2f}")
        if rows:
            tested += len(rows)
            mean = [sum(c) / len(rows) for c in zip(*rows)]
            print(f"{part}: {len(rows)} clips, pitches {mean[0]:.2f}, with rhythm {mean[1]:.2f}, "
                  f"best candidate {mean[2]:.2f}\n")
    if not tested:
        sys.exit(f"no clips found in {a.folder}/dev or {a.folder}/holdout")


if __name__ == "__main__":
    main()
