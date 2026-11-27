"""Melody Transcriber. No test needs a sound server, a graphics card or a network: `pactl` and
`parec` are replaced by scripts, and the neural models are switched off."""
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tunelab import capture, extract, guide, library, transcribe
from tunelab.documents import MelodyDoc
from tunelab.extract import SR
from tunelab.generator import Options, generate
from tunelab.melody_check import agreement
from tunelab.synth import render
from test_e2e import browser, server, sync_api  # noqa: F401

HOP = transcribe.HOP


def curve(*notes):
    """Pitch curve from (midi or None, seconds)."""
    hz = [np.full(round(d / HOP), 440 * 2 ** ((m - 69) / 12) if m else 0.0) for m, d in notes]
    return np.concatenate(hz)


def pitches(raw):
    return [p for _, _, p in raw]


# ---------- pitch curve to notes ----------
def test_notes_from_clean_curve():
    hz = curve((60, .5), (62, .4), (None, .3), (67, .6))
    raw = transcribe.notes_from_pitch(hz, hz > 0)
    assert pitches(raw) == [60, 62, 67]
    assert [(round(a, 2), round(b, 2)) for a, b, _ in raw] == [(0, .5), (.5, .9), (1.2, 1.8)]


def test_vibrato_stays_one_note():
    t = np.arange(0, 1.5, HOP)
    hz = 440 * 2 ** (0.7 * np.sin(2 * np.pi * 5.5 * t) / 12)
    assert pitches(transcribe.notes_from_pitch(hz, hz > 0)) == [69]


def test_mistuned_recording():
    hz = curve((60, .5), (62, .5), (64, .5), (65, .5)) * 2 ** (0.4 / 12)
    assert pitches(transcribe.notes_from_pitch(hz, hz > 0)) == [60, 62, 64, 65]


def test_blips_dropped_and_gaps_bridged():
    hz = curve((60, .3), (None, .02), (60, .3), (None, .5), (72, .03))
    assert pitches(transcribe.notes_from_pitch(hz, hz > 0)) == [60]


def test_repeated_notes_need_a_loudness_dip():
    hz = curve((60, 1.0))
    loud = np.ones(len(hz))
    assert len(transcribe.notes_from_pitch(hz, hz > 0, loud)) == 1
    loud[48:52] = [.5, .1, .1, .5]
    assert pitches(transcribe.notes_from_pitch(hz, hz > 0, loud)) == [60, 60]


def test_nothing_voiced():
    assert transcribe.notes_from_pitch(np.zeros(50), np.zeros(50, bool)) == []


# ---------- beats ----------
def test_grid_and_bars_from_beats():
    beats = 0.25 + np.arange(16) * 0.5  # 120 bpm
    raw = [(0.26 + i * 0.5, 0.26 + i * 0.5 + 0.4, 60 + i) for i in range(8)]
    t = transcribe.to_tune(raw, beats, beats[1::4])  # bars begin on the second beat
    assert (t.bpm, t.meter) == (120, (4, 4))
    assert [n.start for n in t.notes] == [12 * (3 + i) for i in range(8)]
    assert transcribe.to_tune(raw, beats, beats[::3]).meter == (3, 4)


def test_triplets_kept():
    beats = np.arange(12) * 0.6
    raw = [(i * 0.2, i * 0.2 + 0.19, 60 + i % 5) for i in range(18)]
    assert [n.start for n in transcribe.to_tune(raw, beats, beats[::4]).notes] == [4 * i for i in range(18)]


def test_beat_found_at_half_speed():
    beats = np.arange(10) * 1.0  # 60 bpm, but the notes are thirty-seconds of that
    raw = [(i * 0.125, i * 0.125 + 0.12, 60 + i % 5) for i in range(40)]
    t = transcribe.to_tune(raw, beats, beats[::4])
    assert t.bpm == 120 and len(t.notes) == 40
    # already fast enough: some notes are lost rather than writing it at 240 bpm
    raw = [(a / 2, b / 2, p) for a, b, p in raw]
    assert transcribe.to_tune(raw, beats / 2, beats[::4] / 2).bpm == 120


def test_no_beats_found():
    raw = [(i * 0.5, i * 0.5 + 0.4, 60 + i) for i in range(6)]
    t = transcribe.to_tune(raw, np.array([]), np.array([]))
    assert len(t.notes) == 6 and t.notes[0].start >= 0


def test_random_input_always_gives_valid_documents():
    rng = random.Random(1)
    for _ in range(200):
        raw, at = [], rng.uniform(0, 3)
        for _ in range(rng.randint(4, 40)):
            d = rng.uniform(.07, 1)
            raw.append((at, at + d, rng.randint(36, 90)))
            at += d + rng.choice([0, 0, .01, .4])
        beats = rng.uniform(0, 2) + np.cumsum([rng.uniform(.2, .9) for _ in range(rng.randint(0, 30))])
        down = beats[::rng.choice([1, 2, 3, 4, 5, 7])] if len(beats) else beats
        t = transcribe.to_tune(raw, beats, down)
        doc = transcribe.melody_from_tune(t, "x")
        assert doc.notes and all(a.start + a.dur <= b.start for a, b in zip(doc.notes, doc.notes[1:]))


def test_distinct_candidates():
    a = [(i, i + 1, 60 + i) for i in range(6)]
    b = [(i, i + 1, 80 - i) for i in range(6)]
    assert [n for n, _ in transcribe.distinct([("a", a), ("copy", a), ("short", a[:3]), ("b", b)])] == ["a", "b"]


def test_agreement():
    doc = MelodyDoc(notes=[dict(pitch=60 + i, start=i * 480, dur=480) for i in range(4)])
    up = MelodyDoc(notes=[dict(pitch=72 + i, start=i * 480, dur=480) for i in range(4)])
    assert agreement(doc, doc) == (1, 1)
    assert agreement(up, doc) == (0, 0)


# ---------- analysis ----------
def write_wav(path, y, sr):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes(np.repeat((y / np.abs(y).max() * 20000).astype("<i2"), 2).tobytes())


@pytest.fixture
def song(tmp_path):
    t = generate(Options("maj", bars=4), random.Random(5))
    write_wav(tmp_path / "song.wav", render(t, SR, pad=0.2), SR)
    return tmp_path / "song.wav"


def test_basic_method(song, monkeypatch):
    monkeypatch.setenv("TUNELAB_NO_GPU", "1")
    r = transcribe.transcribe(song)
    assert "not installed" in r["warning"] and len(r["candidates"]) == 1
    MelodyDoc.model_validate(r["candidates"][0]["melody"])


def test_failing_models_fall_back(song, monkeypatch):
    def broken(*a):
        raise RuntimeError("out of memory")
    monkeypatch.setattr(transcribe.models, "installed", lambda: True)
    monkeypatch.setattr(transcribe, "with_networks", broken)
    r = transcribe.transcribe(song)
    assert "out of memory" in r["warning"] and r["candidates"]


# ---------- recording ----------
PACTL = """#!/usr/bin/env python3
import os
print(open(os.environ["FAKE_STREAMS"]).read())
"""
PAREC = """#!/usr/bin/env python3
import os, sys, time
open(os.environ["FAKE_ARGS"], "a").write(" ".join(sys.argv[1:]) + "\\n")
data = open(os.environ["FAKE_SOUND"], "rb").read()[44:]
for i in range(0, len(data), 35280):  # faster than real time
    sys.stdout.buffer.write(data[i:i + 35280]); sys.stdout.buffer.flush(); time.sleep(0.02)
"""


@pytest.fixture
def fake_audio(tmp_path, song, monkeypatch):
    t = generate(Options("maj", bars=4), random.Random(5))
    write_wav(tmp_path / "play.wav", render(t, capture.RATE, pad=0.2), capture.RATE)
    (tmp_path / "args.txt").touch()
    folder = tmp_path / "bin"
    folder.mkdir()
    for name, text in (("pactl", PACTL), ("parec", PAREC)):
        (folder / name).write_text(text)
        (folder / name).chmod(0o755)
    (tmp_path / "streams.json").write_text(json.dumps([
        {"index": 7, "corked": False, "properties": {"application.name": "Spotify"}},
        {"index": 8, "corked": True, "properties": {"application.name": "Firefox", "media.name": "tab"}},
        {"index": 9, "corked": False, "properties": {"application.name": "Chromium", "media.name": "<b>Playback</b>"}}]))
    for k, v in {"PATH": f"{folder}:{os.environ['PATH']}", "FAKE_STREAMS": str(tmp_path / "streams.json"),
                 "FAKE_ARGS": str(tmp_path / "args.txt"), "FAKE_SOUND": str(tmp_path / "play.wav"),
                 "TUNELAB_NO_GPU": "1", "TUNELAB_LIBRARY": str(tmp_path / "lib"),
                 "TUNELAB_DB": str(tmp_path / "t.db")}.items():
        monkeypatch.setenv(k, v)
    return tmp_path


def wait_for(f, seconds=30):
    end = time.time() + seconds
    while not f():
        assert time.time() < end, "timed out"
        time.sleep(0.05)


def test_only_browsers_are_listed(fake_audio):
    assert [(s["id"], s["app"], s["playing"]) for s in capture.streams()] == [
        (9, "Chromium", True), (8, "Firefox", False)]


def test_never_falls_back_to_the_microphone(fake_audio):
    """Without this property the sound server records the default input once the stream ends."""
    r = capture.Recorder(9)
    wait_for(lambda: r.seconds > 1)
    r.stop()
    args = (fake_audio / "args.txt").read_text().splitlines()
    assert args and all("--property=node.dont-reconnect=true" in a and "--monitor-stream=9" in a for a in args)


def test_recording_continues_when_the_stream_comes_back(fake_audio):
    r = capture.Recorder(9)
    streams = json.loads((fake_audio / "streams.json").read_text())
    streams[2]["index"] = 12  # the fake parec ends by itself; the program now has another stream
    (fake_audio / "streams.json").write_text(json.dumps(streams))
    wait_for(lambda: "--monitor-stream=12" in (fake_audio / "args.txt").read_text())
    r.stop()
    assert not r.running
    # gone altogether: waits, and never touches another program
    (fake_audio / "streams.json").write_text(json.dumps(streams[:2]))
    (fake_audio / "args.txt").write_text("")
    with pytest.raises(capture.CaptureError):
        capture.Recorder(9)
    assert (fake_audio / "args.txt").read_text() == ""


def test_recording_stops_at_the_limit(fake_audio, monkeypatch):
    monkeypatch.setattr(capture, "MAX_SECONDS", 2)
    r = capture.Recorder(9)
    wait_for(lambda: not r.running)
    assert r.seconds == 2 and not r.error


@pytest.fixture
def client(fake_audio, monkeypatch):
    from tunelab import routes_transcriber as rt
    from tunelab.server import app
    s = rt.Session()
    monkeypatch.setattr(rt, "session", s)
    yield TestClient(app)
    s.close()
    assert not s.dir.exists()


URL = "/api/transcriber"


def test_other_websites_are_refused(client):
    for origin in ("https://evil.example", "http://localhost:3000", "null"):
        assert client.post(f"{URL}/record", json={"stream": 9}, headers={"Origin": origin}).status_code == 403
    assert client.get(f"{URL}/status").json()["state"] == "idle"
    assert client.post(f"{URL}/record", json={"stream": 9}, headers={"Origin": "http://testserver"}).status_code == 200


def test_api_flow(client, fake_audio):
    get = lambda p: client.get(URL + p)  # noqa: E731
    post = lambda p, **b: client.post(URL + p, json=b or None)  # noqa: E731
    assert get("/audio").status_code == get("/result").status_code == 404
    assert post("/analyse").status_code == 409
    assert post("/record", stream=99).status_code == 409
    assert post("/record", stream=9).json()["state"] == "recording"
    assert post("/record", stream=9).status_code == 409
    wait_for(lambda: get("/status").json()["seconds"] > 5)
    assert post("/stop").json()["state"] == "ready"
    assert get("/audio").content[:4] == b"RIFF"
    assert not (fake_audio / "lib" / "recordings").exists()  # temporary unless kept
    assert post("/keep", name="My täke").json()["kept"] == "my-take"
    assert get("/recordings").json() == ["my-take"]
    assert post("/analyse").json()["state"] == "analysing"
    wait_for(lambda: get("/status").json()["state"] == "ready")
    assert not get("/status").json()["error"]
    doc = get("/result").json()["candidates"][0]["melody"]
    assert client.post("/api/library/melodies", json={"doc": doc}).status_code == 200
    # cancelling, then opening the kept recording again
    assert post("/analyse").json()["state"] == "analysing"
    assert post("/cancel").json()["state"] == "ready"
    r = post("/recordings/my-take/open").json()
    assert r["state"] == "ready" and r["seconds"] > 5 and not r["result"]
    assert post("/recordings/..%2fx/open").status_code == 404
    assert post("/recordings/nope/open").status_code == 404


def test_silent_recording(client, fake_audio):
    write_wav(fake_audio / "play.wav", np.r_[1.0, np.zeros(capture.RATE * 3)], capture.RATE)
    raw = (fake_audio / "play.wav").read_bytes()
    (fake_audio / "play.wav").write_bytes(raw[:44] + bytes(len(raw) - 44))
    client.post(f"{URL}/record", json={"stream": 9})
    wait_for(lambda: client.get(f"{URL}/status").json()["seconds"] > 2)
    client.post(f"{URL}/stop")
    client.post(f"{URL}/analyse")
    wait_for(lambda: client.get(f"{URL}/status").json()["state"] == "ready")
    assert "silent" in client.get(f"{URL}/status").json()["error"]


def test_keeping_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setenv("TUNELAB_LIBRARY", str(tmp_path / "lib"))
    (tmp_path / "a.wav").write_bytes(b"one")
    assert [library.keep_recording(tmp_path / "a.wav", "x") for _ in range(2)] == ["x", "x-2"]


def test_stopping_the_server_deletes_the_recording(fake_audio, monkeypatch):
    tmp = fake_audio / "tmp"
    tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmp))
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "tunelab.server:app", "--port", "0", "--log-level", "info"],
                         stderr=subprocess.PIPE, text=True)
    url = next(re.search(r"http://[\d.:]+", x)[0] for x in p.stderr if "running on" in x)
    q = urllib.request.Request(url + URL + "/record", b'{"stream": 9}', {"Content-Type": "application/json"})
    assert json.load(urllib.request.urlopen(q))["state"] == "recording"
    assert list(tmp.iterdir())
    p.terminate()
    p.communicate(timeout=15)
    assert not list(tmp.iterdir())


# ---------- guiding by hand ----------
def box(t0, t1, lo, hi):
    """Runs of a rectangle in seconds and MIDI pitches."""
    return [(r, round(t0 / guide.CELL), round(t1 / guide.CELL))
            for r in range((lo - guide.LO) * guide.PER, (hi - guide.LO) * guide.PER + 1)]


def test_marks():
    times, pitches = np.array([0.5, 1.5, 99.0]), np.array([20.0, 50.0, 60.0, 61.0, 100.0])
    m = guide.Marks(box(1, 2, 59, 60), [])
    assert m.painted(times).tolist() == [False, True, False]
    ok = m.allowed(times, pitches, 48, 88)
    assert ok.tolist() == [[False, True, True, True, False], [False, False, True, False, False],
                           [False, True, True, True, False]]
    assert guide.Marks(box(1, 2, 59, 60), [], only=True).allowed(times, pitches).sum() == 1
    ok = guide.Marks([], box(0, 1, 60, 60)).allowed(times, pitches)
    assert ok[0].tolist() == [True, True, False, True, True] and ok[1:].all()
    assert not guide.Marks([], [], only=True).allowed(times, pitches).any()


def write_lines(path, *lines):
    """Lines of half-second notes with overtones: (pitches, loudness), ..."""
    t = np.arange(0, 4, 1 / SR)
    y = np.zeros(len(t))
    for line, gain in lines:
        for i, p in enumerate(line):
            part = (t >= i / 2) & (t < (i + 1) / 2)
            x = t[part] - i / 2
            for k in range(1, 6):
                y[part] += gain / k * np.sin(2 * np.pi * k * 440 * 2 ** ((p - 69) / 12) * x) * np.minimum(1, 40 * np.minimum(x, 0.5 - x))
    write_wav(path, y, SR)


@pytest.fixture
def two_lines(tmp_path):
    """A loud low line and a soft high one; and its work folder."""
    write_lines(tmp_path / "two.wav", ((55, 57, 59, 60) * 2, 1.0), ((76, 74, 72, 71) * 2, 0.35))
    facts = {"files": {"mix": str(tmp_path / "two.wav")}, "sung": False,
             "beats": (np.arange(9) / 2).tolist(), "downbeats": [0, 2]}
    (tmp_path / "info.json").write_text(json.dumps(facts))
    return tmp_path, facts


def test_highlights_choose_the_line(two_lines):
    _, facts = two_lines
    low = guide.guess(facts, "mix", guide.Marks(box(0, 4, 53, 62), [], True), "x")
    high = guide.guess(facts, "mix", guide.Marks(box(0, 4, 69, 78), [], True), "x")
    assert pitches(low["notes"]) == [55, 57, 59, 60] * 2 and not low["warning"]
    assert pitches(high["notes"]) == [76, 74, 72, 71] * 2
    MelodyDoc.model_validate(high["melody"])
    # only the first half highlighted: the second half is empty, or searched as usual
    part = box(0, 2, 69, 78)
    assert pitches(guide.guess(facts, "mix", guide.Marks(part, [], True), "x")["notes"]) == [76, 74, 72, 71]
    both = guide.guess(facts, "mix", guide.Marks(part, []), "x")["notes"]
    assert pitches(both)[:4] == [76, 74, 72, 71] and both[-1][1] > 3.8
    with pytest.raises(ValueError, match="No notes"):
        guide.guess(facts, "mix", guide.Marks([], [], True), "x")


def test_nothing_highlighted_is_the_automatic_result(two_lines, song):
    for wav in (song, two_lines[0] / "two.wav"):
        facts = {"files": {"mix": str(wav)}, "sung": False, "beats": [], "downbeats": []}
        assert guide.guess(facts, "mix", guide.Marks([], []), "x")["notes"] == transcribe.lead_notes(wav)


def test_not_melody_removes_a_line(two_lines):
    _, facts = two_lines
    raw = guide.guess(facts, "mix", guide.Marks([], box(0, 4, 36, 66)), "x")["notes"]
    assert raw and min(pitches(raw)) > 66


def test_highlighting_overtones_warns(tmp_path):
    write_lines(tmp_path / "one.wav", ((55, 57, 59, 60) * 2, 1.0))
    facts = {"files": {"mix": str(tmp_path / "one.wav")}, "sung": False, "beats": [], "downbeats": []}
    for up in (12, 19, 24):
        r = guide.guess(facts, "mix", guide.Marks(box(0, 4, 54 + up, 61 + up), [], True), "x")
        assert "overtones" in r["warning"], up
    assert not guide.guess(facts, "mix", guide.Marks(box(0, 4, 53, 62), [], True), "x")["warning"]


def test_empty_highlights_warn(two_lines):
    _, facts = two_lines
    r = guide.guess(facts, "mix", guide.Marks(box(0, 4, 69, 78), []), "x")
    assert guide.coverage(r["notes"], guide.Marks(box(0, 4, 69, 78), [])) > 0.8
    assert guide.coverage(r["notes"], guide.Marks([], [])) == 1
    late = guide.guess(facts, "mix", guide.Marks(box(3.5, 9, 69, 78), []), "x")
    assert "Few notes" in late["warning"]


def test_picture_fades_overtones():
    sal = np.full((4, 181), 0.01)
    sal[:, 60], sal[:, 96], sal[:, 130] = 1, 0.7, 0.7  # a note, its octave, and another note
    out = guide.dim_overtones(sal)
    assert out[0, 60] == 1 and out[0, 96] < 0.4 and out[0, 130] == 0.7


def test_listening_to_highlights(two_lines):
    y = extract.decode(two_lines[0] / "two.wav")
    out = guide.listen(y, guide.Marks(box(0, 2, 69, 78), []))
    assert len(out) == len(y)
    assert np.abs(out[int(2.3 * SR):]).max() < 0.02  # nothing highlighted there
    s = np.abs(np.fft.rfft(out))
    f = np.fft.rfftfreq(len(out), 1 / SR)
    assert s[(f > 400) & (f < 800)].sum() > 0.97 * s.sum()
    with pytest.raises(ValueError, match="no sound"):
        guide.listen(y, guide.Marks([], []))


def test_sung_notes_stay_inside_the_highlights(monkeypatch):
    """The network is replaced: it hears two pitches, the higher one more clearly."""
    def run(self, _, given):
        out = np.zeros((1, given["input"].shape[2], 360), dtype=np.float32)
        for pitch, sure in ((60, .05), (72, .9)):
            cents = 1200 * np.log2(440 * 2 ** ((pitch - 69) / 12) / 10)
            out[0, :, int(np.abs(transcribe.models.CENTS[4:-4] - cents).argmin())] = sure
        return [out]
    net = type("Net", (), {"run": run})()
    y = np.sin(np.arange(16000 * 2) / 9)
    got = lambda *marks: set(pitches(transcribe.sung_notes(net, y, False, *marks)))  # noqa: E731
    assert got() == {72}
    assert got(guide.Marks([], [])) == {72}
    assert got(guide.Marks(box(0, 2, 58, 62), [])) == {60}  # although it is below the usual threshold
    assert got(guide.Marks([], box(0, 2, 58, 62))) == {72}
    assert got(guide.Marks(box(0, 1, 58, 62), [], True)) == {60}


def test_guide_api(client):
    get = lambda p: client.get(URL + p)  # noqa: E731
    post = lambda p, **b: client.post(URL + p, json=b or None)  # noqa: E731
    paint = {"source": "mix", "melody": box(0, 6, 48, 90)}
    assert get("/status").json()["guide"] is None
    for p in ("picture", "listen", "guess"):
        assert post(f"/guide/{p}", **paint).status_code in (404, 409)
    post("/record", stream=9)
    wait_for(lambda: get("/status").json()["seconds"] > 5)
    post("/stop")
    post("/analyse")
    wait_for(lambda: get("/status").json()["state"] == "ready")
    before = get("/status").json()
    assert before["guide"]["sources"] == ["mix"] and before["guide"]["source"] == "mix"
    assert get("/guide/mix/strength").status_code == 404  # not drawn yet
    meta = post("/guide/picture", source="mix").json()
    for kind in ("strength", "spectrum"):
        assert len(get(f"/guide/mix/{kind}").content) == meta["columns"] * meta["rows"]
    assert get("/guide/mix/audio").content[:4] == b"RIFF"
    assert post("/guide/listen", **paint).content[:4] == b"RIFF"
    r = post("/guide/listen", source="mix")
    assert r.status_code == 422 and "no sound" in r.json()["detail"]
    assert post("/guide/picture", source="vocals").status_code == 404
    assert get("/guide/..%2f..%2fx/audio").status_code in (404, 422)
    for bad in ([[guide.ROWS, 0, 1]], [[-1, 0, 1]], [[0, 0, 10 ** 9]], [[0, 1]], "x"):
        assert post("/guide/guess", source="mix", melody=bad).status_code == 422
    for n in (1, 2):
        assert post("/guide/guess", **paint).json()["state"] == "analysing"
        wait_for(lambda: get("/status").json()["state"] == "ready")
        assert not get("/status").json()["error"]
        found = get("/result").json()["candidates"]
        assert found[-1]["name"] == f"Guided {n}" and len(found) == 1 + n
        MelodyDoc.model_validate(found[-1]["melody"])
    assert get("/status").json()["result"] > before["result"]
    # a failed or cancelled guess keeps what was there
    post("/guide/guess", source="mix", only=True)
    wait_for(lambda: get("/status").json()["state"] == "ready")
    assert "No notes" in get("/status").json()["error"]
    post("/guide/guess", **paint)
    post("/cancel")
    assert len(get("/result").json()["candidates"]) == 3
    # other websites are refused; a new recording forgets everything
    assert client.post(f"{URL}/guide/guess", json=paint, headers={"Origin": "https://evil.example"}).status_code == 403
    post("/record", stream=9)
    assert get("/status").json()["guide"] is None and get("/guide/mix/audio").status_code == 404


def test_guiding_works_when_the_automatic_search_found_nothing(client, monkeypatch, tmp_path, two_lines):
    from tunelab import routes_transcriber as rt
    s = rt.session
    s.wav, s.seconds, s.work = two_lines[0] / "two.wav", 4.0, two_lines[0]
    s.facts = guide.info(two_lines[0])
    r = client.post(f"{URL}/guide/guess", json={"source": "mix", "melody": box(0, 4, 69, 78)})
    assert r.json()["state"] == "analysing" and r.json()["result"] == 0
    wait_for(lambda: client.get(f"{URL}/status").json()["state"] == "ready")
    assert [c["name"] for c in client.get(f"{URL}/result").json()["candidates"]] == ["Guided 1"]


# ---------- the page ----------
def test_page(fake_audio, browser, server):  # noqa: F811
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    expect = sync_api.expect
    page.goto(server + "/transcriber")
    expect(page.locator("#stream option").first).to_have_text("Chromium · <b>Playback</b>")
    page.click("#record")
    expect(page.locator("#record")).to_have_text("Stop")
    page.wait_for_function("document.querySelector('#time').textContent >= '0:06'")
    assert page.locator("#original").is_disabled()
    page.click("#record")
    expect(page.locator(".guess")).to_have_count(1, timeout=60000)
    for label in ("Play guess", "Play with original"):
        page.click(f"text={label}")
        expect(page.locator(".guess >> text=Stop")).to_have_count(1)
        page.click(".guess >> text=Stop")
        expect(page.locator(f"text={label}")).to_have_count(1)
    page.click("#original")
    expect(page.locator("#original")).to_have_text("Stop")
    page.click("#keep")
    page.fill("dialog input", "Take")
    page.click("dialog >> text=OK")
    expect(page.locator("#kept option")).to_have_text(["take"])
    page.click("#open")
    expect(page.locator(".guess")).to_have_count(1, timeout=60000)
    page.click("text=Open in DAW")
    page.fill("dialog input", "From the radio")
    page.click("dialog >> text=OK")
    page.wait_for_url("**/daw")
    page.wait_for_function("window.tunelab?.store.state.project.tracks[0].notes.length > 4")
    assert page.evaluate("window.tunelab.store.state.project.name") == "From the radio"
    assert not errors
    page.close()


def test_guide_page(fake_audio, browser, server):  # noqa: F811
    page = browser.new_page(viewport={"width": 1300, "height": 1100})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    expect = sync_api.expect
    page.goto(server + "/transcriber")
    page.click("#record")
    page.wait_for_function("document.querySelector('#time').textContent >= '0:06'")
    assert page.locator("#guide-toggle").is_disabled()
    page.click("#record")
    expect(page.locator(".guess")).to_have_count(1, timeout=60000)
    expect(page.locator("#guide")).to_be_hidden()
    page.click("#guide-toggle")
    expect(page.locator("#g-message")).to_contain_text("Paint over", timeout=30000)
    expect(page.locator("#g-guess")).to_be_disabled()
    expect(page.locator("#g-hear")).to_be_disabled()
    expect(page.locator("#g-guess-shown option")).to_have_text(["No guess", "Basic method"])

    at = page.locator("#g-canvas").bounding_box()

    def drag(x0, y0, x1, y1):
        page.mouse.move(at["x"] + x0, at["y"] + y0)
        page.mouse.down()
        page.mouse.move(at["x"] + x1, at["y"] + y1, steps=4)
        page.mouse.up()

    saved = lambda: page.evaluate("JSON.parse(Object.values(sessionStorage)[0] || '{}')")  # noqa: E731
    drag(60, 250, 600, 250)
    expect(page.locator("#g-guess")).to_be_enabled()
    runs = saved()["melody"]
    assert len(runs) == 13 and all(b - a > 80 for _, a, b in runs)  # +-3 semitones, in halves
    page.keyboard.press("n")
    drag(60, 400, 300, 400)
    assert saved()["not_melody"] and saved()["melody"] == runs
    page.keyboard.press("Control+z")
    assert not saved()["not_melody"]
    page.keyboard.press("Control+Shift+z")
    assert saved()["not_melody"]
    page.keyboard.press("e")
    drag(60, 400, 300, 400)
    assert not saved()["not_melody"]
    page.keyboard.press("b")
    # Escape drops a stroke that is being drawn
    page.mouse.move(at["x"] + 100, at["y"] + 120)
    page.mouse.down()
    page.mouse.move(at["x"] + 300, at["y"] + 120)
    page.keyboard.press("Escape")
    page.mouse.up()
    assert saved()["melody"] == runs
    # the ruler seeks and the keyboard plays; neither paints
    page.mouse.click(at["x"] + 300, at["y"] + 8)
    page.mouse.click(at["x"] + 10, at["y"] + 200)
    assert saved()["melody"] == runs
    for key in ("#g-play", "#g-hear"):
        page.click(key)
        expect(page.locator(key)).to_have_text("Stop", timeout=20000)
        page.click(key)
        expect(page.locator(key)).not_to_have_text("Stop")
    page.keyboard.press(" ")
    expect(page.locator("#g-play")).to_have_text("Stop")
    page.keyboard.press(" ")
    expect(page.locator("#g-play")).to_have_text("Play source")
    page.select_option("#g-view", "spectrum")
    page.click("#g-in")
    page.click("#g-fit")

    page.click("#g-guess")
    expect(page.locator(".guess h2")).to_have_text(["Guided 1", "1. Basic method"], timeout=60000)
    assert page.locator("#g-guess-shown option:checked").text_content() == "Guided 1"
    page.evaluate("document.querySelector('#g-size').value = 1")
    page.click("#g-clear")
    expect(page.locator("#g-message.bad")).to_have_count(0)  # a warning ends when the highlights change
    page.click("#g-undo")
    page.check("#g-only")
    page.reload()  # highlights stay, and so do the guesses
    expect(page.locator(".guess")).to_have_count(2)
    page.click("#guide-toggle")
    expect(page.locator("#g-only")).to_be_checked()
    assert saved()["melody"] == runs
    page.click("#g-clear")
    expect(page.locator("#g-guess")).to_be_disabled()
    assert saved()["melody"] == []
    assert not errors
    page.close()
