import random

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tunelab.check import DAMAGE, load_reference, win_rates
from tunelab.extract import SR, extract
from tunelab.generator import Options, generate, random_notes
from tunelab.notation import NotationError, dump, parse
from tunelab.pipeline import fingerprint, run_batch, similar
from tunelab.scorer import score
from tunelab.synth import render


def test_reference_parses():
    assert len(load_reference()) == 16


def test_notation_details():
    t = parse("key=Bb:maj bpm=90 meter=3/4 pickup=1\nCb4:1 | -:1 [Gm] F#5:1/3 A4:2/3 -:1 |")
    assert [n.pitch for n in t.notes] == [59, 78, 69]
    assert (t.tonic, t.pickup, t.length, t.chords[0].label) == (10, 12, 48, "Gm")
    assert dump(parse(dump(t))) == dump(t)


@pytest.mark.parametrize("bad", ["", "C4:1", "key=C:maj", "key=C:maj C4:0", "key=C:maj H4:1", "key=C:maj C4:1/7",
                                 "key=C:maj C4:1 | D4:3", "key=C:maj [Cfoo] C4:1", "key=C:maj meter=0/4 C4:1",
                                 "key=C:maj bpm=0 C4:1", "key=C:maj C4:1/0"])
def test_notation_rejects(bad):
    with pytest.raises(NotationError):
        parse(bad)


@pytest.mark.parametrize("mode", ["maj", "min", "hmin"])
@pytest.mark.parametrize("meter", ["4/4", "3/4"])
@pytest.mark.parametrize("bars", [4, 8, 16])
def test_generator(mode, meter, bars):
    r = random.Random(1)
    opt = Options(mode, meter, bars)
    for _ in range(40):
        t = generate(opt, r)
        assert t.length == bars * t.bar == sum(n.dur for n in t.notes)
        assert all(n.pitch % 12 in t.scale_pcs() for n in t.notes)
        assert t.notes[-1].pitch % 12 == t.tonic
        p = parse(dump(t))
        assert (p.notes, p.chords, p.length) == (t.notes, t.chords, t.length)


@pytest.mark.parametrize("split", ["dev", "holdout"])
def test_real_beats_damaged(split):
    res = win_rates(split, copies=60)
    for label in DAMAGE:
        assert sum(r[label] for r in res.values()) / len(res) > 0.85, label


def test_generated_beats_random():
    r = random.Random(2)
    g = sorted(score(generate(Options(), r))[0] for _ in range(100))
    b = sorted(score(random_notes(Options(), r))[0] for _ in range(100))
    assert g[10] > b[90]


def test_flagging():
    batch, cut = run_batch(400, Options(), 5, [], seed=3)
    top = [x for x in batch if x.flag == "top"]
    assert top and all(x.score >= cut for x in top)
    assert all(x.score < cut for x in batch if x.flag == "wildcard")
    fps = [fingerprint(x.tune) for x in top]
    assert not any(similar(a, b) for i, a in enumerate(fps) for b in fps[:i])
    again, _ = run_batch(400, Options(), 5, fps, seed=3)
    assert not any(x.flag == "top" for x in again)


def test_extract_solo():
    from difflib import SequenceMatcher
    t = generate(Options("maj", bars=4), random.Random(5))
    y = render(t, SR, pad=0.2)
    e = extract(y / np.abs(y).max())
    assert SequenceMatcher(None, [n.pitch for n in t.notes], [n.pitch for n in e.notes]).ratio() > 0.85
    assert dump(parse(dump(e))) == dump(e)


def test_extract_silence():
    with pytest.raises(ValueError):
        extract(np.zeros(SR * 3, dtype=np.float32))


def test_api(tmp_path, monkeypatch):
    from tunelab import db
    monkeypatch.setattr(db, "PATH", tmp_path / "t.db")
    from tunelab.server import app
    c = TestClient(app)
    assert c.get("/").status_code == 200
    g = c.post("/api/generate", json={"count": 120, "top_percent": 20, "seed": 1}).json()
    rows = c.get("/api/tunes").json()
    assert len(rows) == g["flagged"] + g["wildcards"] > 0
    assert c.post("/api/generate", json={"count": 0}).status_code == 422
    assert c.post("/api/score", json={"notation": "nope"}).status_code == 400
    assert c.post("/api/score", json={"notation": rows[0]["notation"], "save": True, "name": "x"}).json()["score"] == rows[0]["score"]
    assert len(c.get("/api/tunes?show=imported").json()) == 1
