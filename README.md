# Tunelab

Local tools for exploring melodies, used in the browser. Two separate tools:

- **DAW**: draw, edit, play, save, import and export melodies and multi-track projects.
- **Tune Generator**: generate melodies, score them with transparent rules, flag the best.
  Also includes a script that extracts a melody from an audio file.

Everything runs and stays on this computer.

    uv sync
    uv run tunelab            # then open http://127.0.0.1:8321

- [User guide](docs/USER_GUIDE.md)
- [Architecture](docs/ARCHITECTURE.md): how the code is organised
- [AGENTS.md](AGENTS.md): rules and checklists for changing the code

Needs Python 3.11+ with [uv](https://docs.astral.sh/uv/). `ffmpeg` is needed only for audio
extraction, Node.js only for developing the web part.
