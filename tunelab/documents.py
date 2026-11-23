"""File formats of the DAW: projects and melodies, as validated JSON documents.

Times are integer ticks, PPQ per quarter note. This is finer than the text notation
(notation.TICKS per beat) so that stretched groups and imported MIDI keep their shape.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .notation import TICKS, Note, Tune

PPQ = 480
SCALE = PPQ // TICKS
MAX_TICK = PPQ * 4 * 5000  # 5000 bars of 4/4

Tick = Annotated[int, Field(ge=0, le=MAX_TICK)]
Name = Annotated[str, Field(max_length=120)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteDoc(Strict):
    pitch: int = Field(ge=0, le=127)
    start: Tick
    dur: int = Field(ge=1, le=MAX_TICK)
    vel: int = Field(100, ge=1, le=127)


class KeyDoc(Strict):
    tonic: int = Field(0, ge=0, le=11)
    mode: Literal["maj", "min", "hmin"] = "maj"


class Music(Strict):
    """What projects and melodies share."""
    version: Literal[1] = 1
    name: Name = "Untitled"
    bpm: float = Field(100, ge=20, le=400)
    meter: tuple[Annotated[int, Field(ge=1, le=32)], Literal[2, 4, 8, 16]] = (4, 4)
    key: KeyDoc = KeyDoc()

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return " ".join(v.split()) or "Untitled"


class MelodyDoc(Music):
    format: Literal["tunelab-melody"] = "tunelab-melody"
    notes: list[NoteDoc] = Field(max_length=20000)
    # chord notes that came with a generated tune; becomes a second track in the DAW
    accompaniment: list[NoteDoc] = Field([], max_length=20000)
    source: str = Field("", max_length=120)  # e.g. "tune:12" when it came from the generator


class TrackDoc(Strict):
    name: Name = "Track"
    sound: Literal["soft", "sine", "square", "saw", "epiano", "bell"] = "soft"
    volume: float = Field(-8, ge=-48, le=6)  # dB
    muted: bool = False
    solo: bool = False
    notes: list[NoteDoc] = Field([], max_length=20000)


class ProjectDoc(Music):
    format: Literal["tunelab-project"] = "tunelab-project"
    tracks: list[TrackDoc] = Field(min_length=1, max_length=64)


def melody_from_tune(t: Tune, name: str, source: str = "") -> MelodyDoc:
    # the DAW has no pickup bars: shift so that barlines still fall where they did
    shift = (-t.pickup) % t.bar

    def doc(pitch: int, start: int, dur: int, vel: int) -> NoteDoc:
        return NoteDoc(pitch=pitch, start=(start + shift) * SCALE, dur=dur * SCALE, vel=vel)

    ends = [c.start for c in t.chords[1:]] + [t.length]
    return MelodyDoc(
        name=name, bpm=t.bpm, meter=t.meter, key=KeyDoc(tonic=t.tonic, mode=t.mode), source=source,
        notes=[doc(n.pitch, n.start, n.dur, 100) for n in t.notes],
        accompaniment=[doc(48 + pc, c.start, e - c.start, 60)
                       for c, e in zip(t.chords, ends) if e > c.start for pc in sorted(c.pcs)])


class ConversionError(ValueError):
    pass


def tune_from_melody(m: MelodyDoc) -> tuple[Tune, bool]:
    """Melody to notation's Tune. Returns (tune, rounded): rounded if timing was not exact.

    Raises ConversionError if notes overlap, since the notation is one note at a time.
    """
    if not m.notes:
        raise ConversionError("The track has no notes.")
    rounded = False
    out: list[Note] = []
    for n in sorted(m.notes, key=lambda n: (n.start, n.pitch)):
        start, end = round(n.start / SCALE), round((n.start + n.dur) / SCALE)
        rounded |= start * SCALE != n.start or end * SCALE != n.start + n.dur
        end = max(end, start + 1)
        if out and start < out[-1].end:
            # tolerate an overlap shorter than one notation tick; it is only rounding
            if out[-1].end - start > 1 or start <= out[-1].start:
                raise ConversionError("Notes overlap. Scoring and text notation need one note at a time; "
                                      "use Tools > Remove overlaps, or pick another track.")
            out[-1].dur = start - out[-1].start
            rounded = True
        out.append(Note(n.pitch, start, end - start))
    t = Tune(m.key.tonic, m.key.mode, round(m.bpm), m.meter, 0, out, [], out[-1].end)  # no chord symbols: scorer skips chord_fit
    t.length += -t.length % t.bar
    return t, rounded

