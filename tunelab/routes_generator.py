"""HTTP API of the Tune Generator."""
from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db
from .documents import melody_from_tune
from .generator import Options
from .notation import NotationError, Tune, dump, parse
from .pipeline import fingerprint, run_batch
from .scorer import score

router = APIRouter(prefix="/api")


class GenerateRequest(BaseModel):
    count: int = Field(200, ge=1, le=5000)
    mode: Literal["any", "maj", "min", "hmin"] = "any"
    meter: Literal["4/4", "3/4"] = "4/4"
    bars: Literal[4, 8, 16] = 8
    top_percent: float = Field(3, gt=0, le=100)
    seed: int | None = None


class ScoreRequest(BaseModel):
    notation: str = Field(max_length=20000)
    save: bool = False
    name: str = Field("", max_length=120)


def playable(t: Tune) -> dict:
    return {"bpm": t.bpm, "bar": t.bar, "pickup": t.pickup, "length": t.length,
            "notes": [[n.pitch, n.start, n.dur] for n in t.notes],
            "chords": [[c.start, c.label, sorted(c.pcs)] for c in t.chords]}


def row_json(r) -> dict:
    return {"id": r["id"], "created": r["created"], "source": r["source"], "name": r["name"],
            "batch": r["batch"], "notation": r["notation"], "score": r["score"],
            "parts": json.loads(r["parts"]), "flag": r["flag"], "tune": playable(parse(r["notation"]))}


@router.post("/generate")
def generate(q: GenerateRequest):
    c = db.connect()
    try:
        known = [fingerprint(parse(r["notation"])) for r in
                 c.execute("SELECT notation FROM tunes WHERE flag='top' ORDER BY id DESC LIMIT 1000")]
        opt = Options(mode=q.mode, meter=q.meter, bars=q.bars)
        batch, cut = run_batch(q.count, opt, q.top_percent, known, q.seed)
        bid = str(time.time_ns())
        with c:
            for x in batch:
                db.add(c, "generated", x.text, x.score, x.parts, x.flag, bid)
        s = [x.score for x in batch]
        return {"batch": bid, "generated": len(batch), "threshold": cut, "best": s[0],
                "median": s[len(s) // 2], "above": sum(v >= cut for v in s),
                "flagged": sum(x.flag == "top" for x in batch),
                "wildcards": sum(x.flag == "wildcard" for x in batch)}
    finally:
        c.close()


@router.get("/tunes")
def tunes(show: Literal["flagged", "all", "imported"] = "flagged", batch: str = "", limit: int = 100):
    where = {"flagged": "flag != ''", "all": "source = 'generated'",
             "imported": "source != 'generated'"}[show]
    args: list = []
    if batch:
        where += " AND batch = ?"
        args.append(batch)
    c = db.connect()
    try:
        rows = c.execute(f"SELECT * FROM tunes WHERE {where} ORDER BY score DESC, id DESC LIMIT ?",
                         (*args, max(1, min(limit, 500)))).fetchall()
        return [row_json(r) for r in rows]
    finally:
        c.close()


@router.get("/tunes/{id}/melody")
def tune_melody(id: int):
    """A stored tune as a DAW melody document."""
    c = db.connect()
    try:
        r = c.execute("SELECT * FROM tunes WHERE id = ?", (id,)).fetchone()
    finally:
        c.close()
    if r is None:
        raise HTTPException(404, "no such tune")
    return melody_from_tune(parse(r["notation"]), r["name"] or f"Tune {id}", f"tune:{id}")


@router.post("/score")
def score_text(q: ScoreRequest):
    try:
        t = parse(q.notation)
    except NotationError as e:
        raise HTTPException(400, str(e)) from None
    s, parts = score(t)
    text = dump(t)
    if q.save:
        c = db.connect()
        try:
            with c:
                db.add(c, "typed", text, s, parts, name=q.name)
        finally:
            c.close()
    return {"score": s, "parts": parts, "notation": text, "source": "typed", "flag": "",
            "name": q.name, "tune": playable(t)}
