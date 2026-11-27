import json
import random

import pytest
from fastapi.testclient import TestClient

from tunelab import db
from tunelab.check import load_reference
from tunelab.documents import ConversionError, MelodyDoc, NoteDoc, melody_from_tune, tune_from_melody
from tunelab.generator import Options, generate
from tunelab.scorer import score
from tunelab.server import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TUNELAB_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.setattr(db, "PATH", tmp_path / "t.db")
    return TestClient(app)


def project(name="My Song", **kw):
    return {"format": "tunelab-project", "version": 1, "name": name, "tracks": [
        {"name": "a", "notes": [{"pitch": 60, "start": 0, "dur": 480}]}], **kw}


def test_tune_round_trip():
    r = random.Random(1)
    for t in [generate(Options(), r) for _ in range(50)] + [t for _, _, t in load_reference()]:
        m = melody_from_tune(t, "x")
        back, rounded = tune_from_melody(m)
        shift = (-t.pickup) % t.bar
        assert not rounded
        assert [(n.pitch, n.start, n.dur) for n in back.notes] == [(n.pitch, n.start + shift, n.dur) for n in t.notes]
        assert all(back.bar_pos(a.start) == t.bar_pos(b.start) for a, b in zip(back.notes, t.notes))
        assert score(back)[0] > 0


def test_conversion_limits():
    def mel(*ns):
        return MelodyDoc(notes=[NoteDoc(pitch=p, start=s, dur=d) for p, s, d in ns])
    for bad in (mel(), mel((60, 0, 480), (64, 0, 480)), mel((60, 0, 960), (64, 480, 480))):
        with pytest.raises(ConversionError):
            tune_from_melody(bad)
    t, rounded = tune_from_melody(mel((60, 0, 490), (62, 485, 470)))
    assert rounded and t.notes[0].end <= t.notes[1].start


def test_library_lifecycle(client, tmp_path):
    a = client.post("/api/library/projects", json={"doc": project()}).json()
    b = client.post("/api/library/projects", json={"doc": project()}).json()
    assert (a["id"], b["id"]) == ("my-song", "my-song-2")
    got = client.get("/api/library/projects/my-song").json()
    assert got["rev"] == a["rev"] and got["doc"]["tracks"][0]["notes"][0]["pitch"] == 60
    s = client.put("/api/library/projects/my-song", json={"doc": project(bpm=77), "rev": a["rev"]})
    assert s.status_code == 200
    assert client.put("/api/library/projects/my-song", json={"doc": project(), "rev": a["rev"]}).status_code == 409
    assert client.get("/api/library/projects/my-song").json()["doc"]["bpm"] == 77
    assert client.put("/api/library/projects/my-song", json={"doc": project(), "rev": None}).status_code == 200
    assert client.put("/api/library/projects/my-song/favorite", json={"favorite": True}).status_code == 200
    assert client.patch("/api/library/projects/my-song", json={"name": "  Über  name "}).status_code == 200
    item = next(i for i in client.get("/api/library").json()["projects"] if i["id"] == "my-song")
    assert item["favorite"] and item["name"] == "Über name"
    assert client.delete("/api/library/projects/my-song").status_code == 200
    assert client.get("/api/library/projects/my-song").status_code == 404
    assert client.put("/api/library/projects/my-song", json={"doc": project(), "rev": None}).status_code == 404
    assert len(list((tmp_path / "lib/trash").iterdir())) == 1
    assert json.loads((tmp_path / "lib/favorites.json").read_text()) == []
    assert not list((tmp_path / "lib").rglob(".tmp-*"))


@pytest.mark.parametrize("bad", [
    {}, project(tracks=[]), project(bpm=5), project(extra=1), project(version=2), project(meter=[4, 3]),
    project(format="tunelab-melody"), project(tracks=[{"notes": [{"pitch": 128, "start": 0, "dur": 1}]}]),
    project(tracks=[{"notes": [{"pitch": 1, "start": -1, "dur": 1}]}]),
    project(tracks=[{"notes": [{"pitch": 1, "start": 0, "dur": 0}]}]), project(tracks=[{"sound": "x"}])])
def test_bad_documents(client, bad):
    assert client.post("/api/library/projects", json={"doc": bad}).status_code == 422
    assert client.post("/api/validate/projects", json={"doc": bad}).status_code == 422


@pytest.mark.parametrize("id", ["..%2Fsettings", "A", "a.b", "-x", "%2e%2e%2f%2e%2e%2fx"])
def test_bad_ids(client, id):
    assert client.get(f"/api/library/projects/{id}").status_code in (404, 405)
    assert client.delete(f"/api/library/projects/{id}").status_code in (404, 405)
    assert client.get("/api/library/secrets/x").status_code == 422


def test_damaged_files_do_not_break_the_library(client, tmp_path):
    client.post("/api/library/projects", json={"doc": project("good")})
    (tmp_path / "lib/projects/bad.json").write_text("{nope")
    (tmp_path / "lib/favorites.json").write_text("{nope")
    (tmp_path / "lib/settings.json").write_text('{"shortcuts": 5}')
    items = {i["id"]: i["broken"] for i in client.get("/api/library").json()["projects"]}
    assert items == {"good": False, "bad": True}
    assert client.get("/api/library/projects/bad").status_code == 422
    assert client.get("/api/settings").json()["previewNotes"] is True
    assert (tmp_path / "lib/favorites.json.broken").exists()


def test_settings(client):
    s = client.get("/api/settings").json()
    s["shortcuts"] = {"play": "KeyP"}
    assert client.put("/api/settings", json=s).status_code == 200
    assert client.get("/api/settings").json() == s


def test_generator_to_daw(client):
    client.post("/api/generate", json={"count": 30, "top_percent": 50, "seed": 1})
    row = client.get("/api/tunes").json()[0]
    m = client.get(f"/api/tunes/{row['id']}/melody").json()
    assert m["source"] == f"tune:{row['id']}" and m["accompaniment"] and m["notes"]
    assert client.post("/api/library/melodies", json={"doc": m}).status_code == 200
    assert client.get("/api/library").json()["melodies"][0]["source"] == m["source"]
    assert client.get("/api/tunes/99999/melody").status_code == 404
    r = client.post("/api/melody/score", json=m).json()
    assert r["score"] > 0 and not r["rounded"]
    back = client.post("/api/notation/parse", json={"text": r["notation"], "name": "n"}).json()
    assert back["notes"] == m["notes"]
    assert client.post("/api/notation/parse", json={"text": "junk"}).status_code == 400


def test_pages_and_host_check(client):
    for path in ("/daw", "/generator", "/web/daw/main.js", "/web/vendor/Tone.js"):
        r = client.get(path)
        assert r.status_code == 200 and "cache-control" in r.headers
    assert client.get("/").url.path == "/daw"
    assert client.get("/api/library", headers={"host": "evil.example"}).status_code == 400


def _wav(seconds=0.5, rate=8000):
    import io
    import math
    import struct
    import wave
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) for i in range(int(seconds * rate))))
    return out.getvalue()


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_mp3_export(client, monkeypatch):
    from tunelab import routes_daw
    r = client.post("/api/audio/mp3?title=My%20Song", content=_wav(), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content[:3] == b"ID3" and b"My Song" in r.content[:200]
    assert client.post("/api/audio/mp3", content=b"not audio").status_code == 422
    assert client.post("/api/audio/mp3", content=_wav(), headers={"Origin": "https://example.com"}).status_code == 403
    monkeypatch.setattr(routes_daw, "MAX_WAV", 100)
    assert client.post("/api/audio/mp3", content=_wav()).status_code == 413
    monkeypatch.setattr(routes_daw.shutil, "which", lambda _: None)
    monkeypatch.setattr(routes_daw, "MAX_WAV", 10**9)
    r = client.post("/api/audio/mp3", content=_wav())
    assert r.status_code == 503 and "WAV" in r.json()["detail"]
