# Tunelab

Local tools for exploring melodies, used in the browser. Three separate tools:

- **DAW**: draw, edit, play, save, import and export melodies and multi-track projects.
- **Tune Generator**: generate melodies, score them with transparent rules, flag the best.
  Also includes a script that extracts a melody from an audio file.
- **Melody Transcriber**: record what a browser is playing and guess the main melody (Linux).

Everything runs and stays on this computer.

    uv sync
    uv run tunelab            # then open http://127.0.0.1:8321

For the Melody Transcriber's neural models (NVIDIA card, about 8 GB on disk): `uv sync --extra gpu`.

- [User guide](docs/USER_GUIDE.md)
- [Guide for composition teachers](docs/TEACHER_GUIDE.md): what the tools do in musical terms, and their limits
- [Architecture](docs/ARCHITECTURE.md): how the code is organised
- [AGENTS.md](AGENTS.md): rules and checklists for changing the code

Needs Python 3.11+ with [uv](https://docs.astral.sh/uv/). `ffmpeg` is needed only for audio
extraction and the transcriber, `pactl` and `parec` (pulseaudio-utils) to record, Node.js only for developing the web part.
