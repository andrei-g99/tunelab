"""Assembles the local web app. Serves two tools: the DAW and the Tune Generator."""
from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import library, routes_daw, routes_generator

WEB = Path(__file__).resolve().parent.parent / "web"
HOST, PORT = "127.0.0.1", 8321

app = FastAPI(title="tunelab")
# refuse requests that reach us under a foreign host name (DNS rebinding)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.include_router(routes_generator.router)
app.include_router(routes_daw.router)


@app.middleware("http")
async def revalidate(request: Request, call_next):
    """Browsers must check for newer files, so edits to web/ show up on reload."""
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


for _error, _status in ((library.NotFound, 404), (library.Conflict, 409), (library.Broken, 422)):
    def _handler(request: Request, exc: Exception, status: int = _status):
        return JSONResponse({"detail": str(exc)}, status)
    app.add_exception_handler(_error, _handler)


@app.get("/")
def index():
    return RedirectResponse("/daw")


@app.get("/daw")
def daw():
    return FileResponse(WEB / "daw" / "index.html")


@app.get("/generator")
def generator():
    return FileResponse(WEB / "generator" / "index.html")


app.mount("/web", StaticFiles(directory=WEB), name="web")


def main() -> None:
    uvicorn.run(app, host=HOST, port=PORT)
