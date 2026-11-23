from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

PATH = Path(os.environ.get("TUNELAB_DB", Path(__file__).resolve().parent.parent / "data" / "tunes.db"))


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(PATH)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS tunes(
        id INTEGER PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP,
        source TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', batch TEXT NOT NULL DEFAULT '',
        notation TEXT NOT NULL, score REAL NOT NULL, parts TEXT NOT NULL, flag TEXT NOT NULL DEFAULT '')""")
    return c


def add(c: sqlite3.Connection, source: str, notation: str, score: float, parts: dict,
        flag: str = "", batch: str = "", name: str = "") -> int:
    return c.execute("INSERT INTO tunes(source,name,batch,notation,score,parts,flag) VALUES(?,?,?,?,?,?,?)",
                     (source, name, batch, notation, score, json.dumps(parts), flag)).lastrowid
