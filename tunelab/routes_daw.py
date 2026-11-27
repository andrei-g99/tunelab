"""HTTP API of the DAW: library files, settings, notation conversion, scoring, MP3 encoding."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

from . import library
from .documents import ConversionError, MelodyDoc, melody_from_tune, tune_from_melody
from .library import Kind
from .notation import NotationError, dump, parse
from .routes_transcriber import same_origin
from .scorer import score

router = APIRouter(prefix="/api")


class SaveRequest(BaseModel):
    doc: dict
    rev: str | None = None  # null overwrites whatever is there


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class FavoriteRequest(BaseModel):
    favorite: bool


class Settings(BaseModel):
    previewNotes: bool = True
    followPlayhead: bool = True
    highlightScale: bool = True
    shortcuts: dict[Annotated[str, Field(max_length=40)], Annotated[str, Field(max_length=60)]] = {}


class NotationRequest(BaseModel):
    text: str = Field(max_length=200000)
    name: str = Field("Imported melody", max_length=120)


def _validated(kind: Kind, doc: dict):
    try:
        return library.MODELS[kind].model_validate(doc)
    except ValidationError as e:
        err = e.errors()[0]
        where = ".".join(str(x) for x in err["loc"])
        raise HTTPException(422, f"Not a valid file ({where}: {err['msg']})") from None


@router.get("/library")
def listing():
    return library.listing()


@router.get("/library/{kind}/{id}")
def get(kind: Kind, id: str):
    return library.get(kind, id)


@router.post("/library/{kind}")
def create(kind: Kind, q: SaveRequest):
    return library.create(kind, _validated(kind, q.doc))


@router.put("/library/{kind}/{id}")
def save(kind: Kind, id: str, q: SaveRequest):
    return library.save(kind, id, _validated(kind, q.doc), q.rev)


@router.patch("/library/{kind}/{id}")
def rename(kind: Kind, id: str, q: RenameRequest):
    return library.rename(kind, id, q.name)


@router.delete("/library/{kind}/{id}")
def delete(kind: Kind, id: str):
    library.delete(kind, id)
    return {}


@router.put("/library/{kind}/{id}/favorite")
def favorite(kind: Kind, id: str, q: FavoriteRequest):
    library.set_favorite(kind, id, q.favorite)
    return {}


@router.post("/validate/{kind}")
def validate(kind: Kind, q: SaveRequest):
    """Check an imported file without storing it; returns it with defaults filled in."""
    return _validated(kind, q.doc)


@router.get("/settings")
def get_settings():
    try:
        return Settings.model_validate(library.load_settings())
    except ValidationError:
        return Settings()


@router.put("/settings")
def put_settings(s: Settings):
    library.save_settings(s.model_dump())
    return s


@router.post("/notation/parse")
def parse_notation(q: NotationRequest):
    try:
        return melody_from_tune(parse(q.text), q.name)
    except NotationError as e:
        raise HTTPException(400, f"Notation error: {e}") from None
    except ValidationError as e:
        raise HTTPException(400, f"Notation out of range: {e.errors()[0]['msg']}") from None


@router.post("/melody/score")
def score_melody(m: MelodyDoc):
    """Score a DAW track and give its text notation. rounded: timing was not exact."""
    try:
        tune, rounded = tune_from_melody(m)
    except ConversionError as e:
        raise HTTPException(400, str(e)) from None
    s, parts = score(tune)
    return {"score": s if parts else None, "parts": parts, "notation": dump(tune), "rounded": rounded}


MAX_WAV = 128 * 1024 * 1024  # about 25 minutes of the mono 16-bit audio the DAW sends


def wav_to_mp3(wav: bytes, title: str) -> bytes:
    if shutil.which("ffmpeg") is None:
        raise HTTPException(503, "MP3 export needs ffmpeg, which is not installed. Export as WAV instead.")
    title = "".join(c for c in title if c.isprintable())
    # to a file, not a pipe: only then can ffmpeg write the header that gives players the duration
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.mp3"
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-f", "wav", "-i", "pipe:0", "-codec:a", "libmp3lame",
               "-q:a", "2", "-metadata", f"title={title}", str(out)]
        try:
            r = subprocess.run(cmd, input=wav, capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Converting to MP3 took too long.") from None
        if r.returncode or not out.exists():
            raise HTTPException(422, f"Could not convert to MP3: {r.stderr.decode(errors='replace').strip()[-300:]}")
        return out.read_bytes()


@router.post("/audio/mp3", dependencies=[Depends(same_origin)])
async def mp3(request: Request, title: Annotated[str, Query(max_length=200)] = ""):
    """WAV in, MP3 out. The DAW renders the audio itself, with the sounds it plays."""
    too_long = HTTPException(413, "Too long to export as audio.")
    if int(request.headers.get("content-length") or 0) > MAX_WAV:
        raise too_long
    wav = await request.body()
    if len(wav) > MAX_WAV:
        raise too_long
    return Response(await run_in_threadpool(wav_to_mp3, wav, title), media_type="audio/mpeg")
