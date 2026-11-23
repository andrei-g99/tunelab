"""HTTP API of the DAW: library files, settings, notation conversion, scoring."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from . import library
from .documents import ConversionError, MelodyDoc, melody_from_tune, tune_from_melody
from .library import Kind
from .notation import NotationError, dump, parse
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
