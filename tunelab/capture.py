"""Record what one browser is playing (Linux, PulseAudio or PipeWire).

Only the chosen program's own output stream is tapped, never a device. NO_FALLBACK matters:
without it the sound server moves the recording to the default input, which is usually the
MICROPHONE, as soon as the stream ends.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import wave
from pathlib import Path

import numpy as np

RATE, CHANNELS, WIDTH = 44100, 2, 2
MAX_SECONDS = 120
BROWSERS = ("chrom", "firefox", "brave", "edge", "opera", "vivaldi", "librewolf", "zen")
NO_FALLBACK = "--property=node.dont-reconnect=true"


class CaptureError(ValueError):
    pass


def available() -> bool:
    return bool(shutil.which("pactl") and shutil.which("parec"))


def streams() -> list[dict]:
    """Browser output streams: {id, app, title, playing}, playing ones first."""
    if not available():
        raise CaptureError("pactl and parec are needed to record (package pulseaudio-utils).")
    try:
        r = subprocess.run(["pactl", "--format=json", "list", "sink-inputs"], capture_output=True,
                           timeout=5, env={**os.environ, "LC_ALL": "C.UTF-8"})
        found = json.loads(r.stdout or b"[]")
    except (subprocess.TimeoutExpired, ValueError) as e:
        raise CaptureError(f"Could not list what is playing: {e}") from None
    if r.returncode:
        raise CaptureError(f"Could not list what is playing: {r.stderr.decode(errors='replace').strip()}")
    out = []
    for s in found:
        p = s.get("properties", {})
        app = p.get("application.name") or p.get("application.process.binary") or ""
        if any(b in f"{app} {p.get('application.process.binary', '')}".lower() for b in BROWSERS):
            out.append({"id": s["index"], "app": app, "title": p.get("media.name", ""),
                        "playing": not s.get("corked", False)})
    return sorted(out, key=lambda s: (not s["playing"], s["id"]))


class Recorder:
    """Records one stream. If it disappears (pause, next video), waits for the same program to
    play again and carries on. Stops by itself after MAX_SECONDS."""

    def __init__(self, stream: int):
        chosen = next((s for s in streams() if s["id"] == stream), None)
        if chosen is None:
            raise CaptureError("That stream is gone. Start playback, refresh the list and try again.")
        self.app = chosen["app"]
        self.level = 0.0
        self.waiting = False  # True while there is no stream to record
        self.error = ""
        self._data = bytearray()
        self._limit = MAX_SECONDS * RATE * CHANNELS * WIDTH
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._thread = threading.Thread(target=self._run, args=(stream,), daemon=True)
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    @property
    def seconds(self) -> float:
        return len(self._data) / (RATE * CHANNELS * WIDTH)

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            if self._proc:
                self._proc.kill()
        self._thread.join(timeout=5)

    def save(self, path: Path) -> None:
        frame = CHANNELS * WIDTH
        with wave.open(str(path), "wb") as w:
            w.setnchannels(CHANNELS)
            w.setsampwidth(WIDTH)
            w.setframerate(RATE)
            w.writeframes(self._data[:len(self._data) // frame * frame])

    def _run(self, stream: int | None) -> None:
        try:
            while not self._stop.is_set() and len(self._data) < self._limit:
                if stream is not None:
                    self._record(stream)
                self.level, self.waiting = 0.0, True
                # a pause: the same program may come back under another stream id
                stream = None
                if not self._stop.wait(0.2):
                    stream = next((s["id"] for s in streams() if s["app"] == self.app), None)
        except (CaptureError, OSError) as e:
            self.error = str(e)
        finally:
            self.level, self.waiting = 0.0, False

    def _record(self, stream: int) -> None:
        cmd = ["parec", f"--monitor-stream={stream}", NO_FALLBACK, "--raw", "--format=s16le",
               f"--rate={RATE}", f"--channels={CHANNELS}", "--latency-msec=50",
               "--client-name=Tunelab"]
        with self._lock:
            if self._stop.is_set():
                return
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        proc = self._proc
        # a partial frame from an earlier attempt would swap the channels
        del self._data[len(self._data) // (CHANNELS * WIDTH) * (CHANNELS * WIDTH):]
        try:
            while chunk := proc.stdout.read1(16384):
                self.waiting = False
                self._data += chunk[:self._limit - len(self._data)]
                x = np.frombuffer(chunk[:len(chunk) // 2 * 2], dtype="<i2")
                self.level = float(np.abs(x.astype(np.int32)).max()) / 32768 if len(x) else 0.0
                if len(self._data) >= self._limit:
                    break
        finally:
            proc.kill()
            proc.wait()
            proc.stdout.close()
