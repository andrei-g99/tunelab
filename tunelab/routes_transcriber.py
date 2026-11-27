"""HTTP API of the Melody Transcriber: one recording and one analysis at a time.

A recording lives in a temporary folder until it is replaced or the server stops; "keep" copies
it to the library.
"""
from __future__ import annotations

import atexit
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import capture, guide, library, models


def same_origin(request: Request) -> None:
    """Other websites open in the browser must not be able to start a recording. Browsers always
    send Origin with a POST; requests without it do not come from a web page."""
    origin = request.headers.get("origin")
    if origin is not None and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "request from another website refused")


router = APIRouter(prefix="/api/transcriber", dependencies=[Depends(same_origin)])


def _length(path: Path) -> float:
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError):
        return 0.0


CRASHED = "The analysis crashed. The terminal running Tunelab shows why."
COLUMNS = 20_000  # of highlight cells, far more than a recording has
Source = Literal["mix", "vocals", "rest"]
Run = tuple[Annotated[int, Field(ge=0, lt=guide.ROWS)], Annotated[int, Field(ge=0, le=COLUMNS)],
            Annotated[int, Field(ge=0, le=COLUMNS)]]


@contextmanager
def _unless_replaced():
    try:
        yield
    except FileNotFoundError:
        raise HTTPException(409, "the recording was replaced meanwhile") from None


class GuideRequest(BaseModel):
    source: Source
    melody: list[Run] = Field([], max_length=200_000)
    not_melody: list[Run] = Field([], max_length=200_000)
    only: bool = False


class Session:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.dir = Path(tempfile.mkdtemp(prefix="tunelab-"))
        self.id = secrets.token_hex(4)
        self.recorder: capture.Recorder | None = None
        self.worker: subprocess.Popen | None = None
        self.wav: Path | None = None
        self.seconds = 0.0
        self.kept = ""
        self.take = 0  # counts recordings, so the page knows when to load new audio
        self.step = self.error = self.notice = ""
        self.result: dict | None = None
        self.version = 0  # counts changes of the result
        self.work: Path | None = None  # what the analysis left behind for guiding
        self.facts: dict | None = None  # its info.json, once complete
        self.tool = threading.Lock()

    def state(self) -> str:
        """Also notices a recording that stopped by itself (length limit, or an error)."""
        with self.lock:
            if self.recorder and not self.recorder.running:
                self._finish_recording()
            if self.recorder:
                return "recording"
            if self.worker:
                return "analysing"
            return "ready" if self.wav else "idle"

    def _need(self, *allowed: str) -> None:
        if (state := self.state()) not in allowed:
            raise HTTPException(409, f"not possible now ({state})")

    def _clear(self) -> None:
        self.wav, self.seconds, self.kept, self.result = None, 0.0, "", None
        self.work = self.facts = None
        self.step = self.error = self.notice = ""
        for p in self.dir.iterdir():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()

    def record(self, stream: int) -> None:
        with self.lock:
            self._need("idle", "ready")
            recorder = capture.Recorder(stream)  # may refuse: then the previous take stays
            self._clear()
            self.recorder = recorder

    def _finish_recording(self) -> None:
        r, self.recorder = self.recorder, None
        r.stop()
        self.error = r.error
        if r.seconds < 1:
            self.error = r.error or "Less than one second was recorded. Was anything playing?"
            return
        self.take += 1
        path = self.dir / f"take-{self.take}.wav"
        r.save(path)
        self.wav, self.seconds = path, r.seconds
        if r.seconds >= capture.MAX_SECONDS:
            self.notice = f"Stopped at the limit of {capture.MAX_SECONDS} seconds."

    def stop(self) -> None:
        with self.lock:
            self._need("recording", "ready", "idle")  # it may have just stopped by itself
            if self.recorder:
                self._finish_recording()

    def open(self, id: str) -> None:
        with self.lock:
            self._need("idle", "ready")
            source = library.recording(id)
            self._clear()
            self.take += 1
            path = self.dir / f"take-{self.take}.wav"
            shutil.copyfile(source, path)
            self.wav, self.kept, self.seconds = path, id, _length(path)

    def keep(self, name: str) -> str:
        with self.lock:
            self._need("ready", "analysing")
            if not self.kept:
                self.kept = library.keep_recording(self.wav, name)
            return self.kept

    def analyse(self) -> None:
        with self.lock:
            self._need("ready")
            if self.work:
                shutil.rmtree(self.work, ignore_errors=True)
            self.result = self.facts = None
            self.work = work = Path(tempfile.mkdtemp(prefix="work-", dir=self.dir))
            out = work / "result.json"

            def finish(ok: bool) -> None:
                if (work / "info.json").exists():
                    self.facts = guide.info(work)
                if ok:
                    self.result = json.loads(out.read_text())

            self._start("Starting", ["tunelab.transcribe", str(self.wav), str(out), str(work)], finish)

    def guess(self, q: GuideRequest) -> None:
        with self.lock:
            self._need("ready")
            work = self._source(q.source)
            done = self.result["candidates"] if self.result else []
            name = f"Guided {1 + sum(bool(c.get('guided')) for c in done)}"
            marks, out = work / "marks.json", work / "guess.json"
            marks.write_text(json.dumps({**q.model_dump(), "name": name}))

            def finish(ok: bool) -> None:
                if ok:
                    c = {**json.loads(out.read_text()), "guided": True}
                    before = self.result or {"warning": "", "candidates": []}
                    self.result = {**before, "candidates": [*before["candidates"], c]}

            self._start("Following your highlights", ["tunelab.guide", "guess", str(work), str(marks), str(out)], finish)

    def _start(self, step: str, command: list[str], finish) -> None:
        self.error, self.step = "", step
        self.worker = subprocess.Popen([sys.executable, "-m", *command], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, text=True, errors="replace")
        threading.Thread(target=self._follow, args=(self.worker, finish), daemon=True).start()

    def _follow(self, worker: subprocess.Popen, finish) -> None:
        error = ""
        for line in worker.stdout:
            if line.startswith("@step "):
                self.step = line[6:].strip()
            elif line.startswith("@error "):
                error = line[7:].strip()
        code = worker.wait()
        with self.lock:
            if self.worker is not worker:
                return  # cancelled
            self.worker, self.step = None, ""
            if code:
                self.error = error or CRASHED
            try:
                finish(not code)
            except (OSError, ValueError) as e:
                self.error = f"The analysis gave no readable result: {e}"
            self.version += 1

    # ---------- for guiding by hand ----------
    def _source(self, source: str) -> Path:
        """The work folder, if it has this source."""
        with self.lock:
            if not self.facts or source not in self.facts["files"]:
                raise HTTPException(404, "not available for this recording")
            return self.work

    def _run_tool(self, *args: str) -> None:
        """A short job that the page waits for."""
        r = subprocess.run([sys.executable, "-m", "tunelab.guide", *args], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, text=True, errors="replace", timeout=120)
        if r.returncode:
            errors = [x[7:].strip() for x in r.stdout.splitlines() if x.startswith("@error ")]
            raise HTTPException(422, errors[-1] if errors else CRASHED)

    def picture(self, source: str) -> dict:
        work = self._source(source)
        meta = work / f"{source}.json"
        with self.tool, _unless_replaced():
            if not meta.exists():
                self._run_tool("picture", str(work), source)
            return json.loads(meta.read_text())

    def listen(self, q: GuideRequest) -> bytes:
        work = self._source(q.source)
        with self.tool, _unless_replaced():
            marks, out = work / "listen.json", work / "listen.wav"
            marks.write_text(q.model_dump_json())
            self._run_tool("listen", str(work), str(marks), str(out))
            return out.read_bytes()

    def file(self, source: str, kind: str) -> Path:
        with self.lock:
            work = self._source(source)
            path = Path(self.facts["files"][source]) if kind == "audio" else work / f"{source}.{kind}"
        if not path.exists():
            raise HTTPException(404, "not available for this recording")
        return path

    def cancel(self) -> None:
        with self.lock:
            worker, self.worker, self.step = self.worker, None, ""
        if worker:
            worker.kill()
            worker.wait()

    def close(self) -> None:
        self.cancel()
        if self.recorder:
            self.recorder.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def status(self) -> dict:
        with self.lock:
            state, r = self.state(), self.recorder
            return {"state": state, "seconds": r.seconds if r else self.seconds,
                    "level": r.level if r else 0, "waiting": bool(r and r.waiting),
                    "max_seconds": capture.MAX_SECONDS, "take": self.take, "kept": self.kept,
                    "step": self.step, "error": self.error, "notice": self.notice,
                    "result": self.version if self.result else 0, "neural": models.installed(),
                    "session": self.id, "guide": self._guide()}

    def _guide(self) -> dict | None:
        """What can be highlighted, and which source to begin with."""
        if not self.facts:
            return None
        return {"sources": list(self.facts["files"]), "source": "vocals" if self.facts["sung"] else "mix", **guide.GRID}


session = Session()
atexit.register(session.close)  # for exits that skip the server's shutdown; closing twice is fine


class RecordRequest(BaseModel):
    stream: int


class KeepRequest(BaseModel):
    name: str = Field(max_length=120)


@router.get("/status")
def status():
    return session.status()


@router.get("/streams")
def streams():
    try:
        return capture.streams()
    except capture.CaptureError as e:
        raise HTTPException(503, str(e)) from None


@router.post("/record")
def record(q: RecordRequest):
    try:
        session.record(q.stream)
    except capture.CaptureError as e:
        raise HTTPException(409, str(e)) from None
    return session.status()


@router.post("/stop")
def stop():
    session.stop()
    return session.status()


@router.post("/analyse")
def analyse():
    session.analyse()
    return session.status()


@router.post("/cancel")
def cancel():
    session.cancel()
    return session.status()


@router.get("/result")
def result():
    if session.result is None:
        raise HTTPException(404, "no result yet")
    return session.result


@router.get("/audio")
def audio():
    if session.wav is None:
        raise HTTPException(404, "nothing recorded")
    return FileResponse(session.wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/guide/picture")
def picture(q: GuideRequest):
    return session.picture(q.source)


@router.post("/guide/listen")
def listen(q: GuideRequest):
    return Response(session.listen(q), media_type="audio/wav")


@router.post("/guide/guess")
def guess(q: GuideRequest):
    session.guess(q)
    return session.status()


@router.get("/guide/{source}/{kind}")
def guide_file(source: Source, kind: Literal["strength", "spectrum", "audio"]):
    return FileResponse(session.file(source, kind), headers={"Cache-Control": "no-store"},
                        media_type="audio/wav" if kind == "audio" else "application/octet-stream")


@router.get("/recordings")
def recordings():
    return library.recordings()


@router.post("/recordings/{id}/open")
def open_recording(id: str):
    session.open(id)
    return session.status()


@router.post("/keep")
def keep(q: KeepRequest):
    session.keep(q.name)
    return session.status()
