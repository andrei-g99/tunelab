"""Local file storage for the DAW: one JSON file per project or melody.

    library/projects/<id>.json   library/melodies/<id>.json
    library/favorites.json       library/settings.json      library/trash/
    library/recordings/<id>.wav  (kept by the transcriber)

A file's id is its name without ".json". Ids never change; renaming changes the "name"
inside the document. Every write is atomic, and deleting moves the file to trash/.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from .documents import MelodyDoc, ProjectDoc

Kind = Literal["projects", "melodies"]
MODELS = {"projects": ProjectDoc, "melodies": MelodyDoc}
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
_lock = threading.RLock()


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Broken(Exception):
    pass


def root() -> Path:
    return Path(os.environ.get("TUNELAB_LIBRARY", Path(__file__).resolve().parent.parent / "library"))


def _write(path: Path, data: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, indent=1, ensure_ascii=False).encode()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return raw


def _rev(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def _path(kind: Kind, id: str) -> Path:
    if kind not in MODELS or not ID.fullmatch(id):
        raise NotFound(f"no such item: {kind}/{id}")
    return root() / kind / f"{id}.json"


def _load(kind: Kind, id: str) -> tuple[ProjectDoc | MelodyDoc, str]:
    try:
        raw = _path(kind, id).read_bytes()
    except FileNotFoundError:
        raise NotFound(f"no such item: {kind}/{id}") from None
    try:
        return MODELS[kind].model_validate_json(raw), _rev(raw)
    except ValidationError as e:
        raise Broken(f"{kind}/{id}.json is not a valid file: {e.errors()[0]['msg']}") from None


def _slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:60].strip("-") or "untitled"


def _read_json(name: str, default):
    try:
        return json.loads((root() / name).read_text())
    except FileNotFoundError:
        return default
    except ValueError:
        # keep the unreadable file for inspection instead of overwriting it later
        (root() / name).replace(root() / f"{name}.broken")
        return default


# ---------- items ----------
def favorites() -> set[str]:
    data = _read_json("favorites.json", [])
    return {x for x in data if isinstance(x, str)} if isinstance(data, list) else set()


def listing() -> dict[str, list[dict]]:
    with _lock:
        fav = favorites()
        out: dict[str, list[dict]] = {}
        for kind in MODELS:
            items = []
            for p in (root() / kind).glob("*.json"):
                if not ID.fullmatch(p.stem):
                    continue
                item = {"id": p.stem, "favorite": f"{kind}/{p.stem}" in fav,
                        "modified": p.stat().st_mtime, "broken": False, "source": ""}
                try:
                    doc, _ = _load(kind, p.stem)
                    item.update(name=doc.name, bpm=doc.bpm, source=getattr(doc, "source", ""))
                except Broken:
                    item.update(name=p.name, broken=True)
                items.append(item)
            out[kind] = sorted(items, key=lambda i: -i["modified"])
        return out


def get(kind: Kind, id: str) -> dict:
    with _lock:
        doc, rev = _load(kind, id)
        return {"id": id, "rev": rev, "doc": doc.model_dump()}


def create(kind: Kind, doc: ProjectDoc | MelodyDoc) -> dict:
    with _lock:
        base = _slug(doc.name)
        id, n = base, 1
        while _path(kind, id).exists():
            n += 1
            id = f"{base}-{n}"
        return {"id": id, "rev": _rev(_write(_path(kind, id), doc.model_dump()))}


def save(kind: Kind, id: str, doc: ProjectDoc | MelodyDoc, rev: str | None) -> dict:
    """Overwrite. If rev is given and the file has changed since, raises Conflict."""
    with _lock:
        path = _path(kind, id)
        if not path.exists():
            raise NotFound(f"no such item: {kind}/{id}")
        if rev is not None and _rev(path.read_bytes()) != rev:
            raise Conflict("This file was changed elsewhere since you opened it.")
        return {"id": id, "rev": _rev(_write(path, doc.model_dump()))}


def rename(kind: Kind, id: str, name: str) -> dict:
    with _lock:
        doc, rev = _load(kind, id)
        data = {**doc.model_dump(), "name": name}
        return save(kind, id, MODELS[kind].model_validate(data), rev)


def delete(kind: Kind, id: str) -> None:
    with _lock:
        path = _path(kind, id)
        if not path.exists():
            raise NotFound(f"no such item: {kind}/{id}")
        trash = root() / "trash"
        trash.mkdir(parents=True, exist_ok=True)
        os.replace(path, trash / f"{kind}-{id}-{time.time_ns()}.json")
        set_favorite(kind, id, False)


def set_favorite(kind: Kind, id: str, value: bool) -> None:
    with _lock:
        if value and not _path(kind, id).exists():
            raise NotFound(f"no such item: {kind}/{id}")
        fav = favorites()
        (fav.add if value else fav.discard)(f"{kind}/{id}")
        _write(root() / "favorites.json", sorted(fav))


# ---------- settings ----------
def load_settings() -> dict:
    with _lock:
        data = _read_json("settings.json", {})
        return data if isinstance(data, dict) else {}


def save_settings(data: dict) -> None:
    with _lock:
        _write(root() / "settings.json", data)


# ---------- kept recordings ----------
def recording(id: str) -> Path:
    path = root() / "recordings" / f"{id}.wav"
    if not ID.fullmatch(id) or not path.is_file():
        raise NotFound(f"no such recording: {id}")
    return path


def recordings() -> list[str]:
    """Ids, newest first."""
    with _lock:
        found = [p for p in (root() / "recordings").glob("*.wav") if ID.fullmatch(p.stem)]
        return [p.stem for p in sorted(found, key=lambda p: -p.stat().st_mtime)]


def keep_recording(source: Path, name: str) -> str:
    with _lock:
        folder = root() / "recordings"
        folder.mkdir(parents=True, exist_ok=True)
        base = _slug(name)
        id, n = base, 1
        while (folder / f"{id}.wav").exists():
            n += 1
            id = f"{base}-{n}"
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f, source.open("rb") as src:
                shutil.copyfileobj(src, f)
            os.replace(tmp, folder / f"{id}.wav")
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return id
