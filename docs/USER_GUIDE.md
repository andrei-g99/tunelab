# Tunelab user guide

Start with `uv run tunelab` and open <http://127.0.0.1:8321>. Stop it with Ctrl+C. The links at
the top left switch between the **DAW** and the **Tune Generator**.

## DAW

### First steps
1. Choose **Draw** (B) and click in the grid to place notes. Drag while placing to set the length.
2. Press Space to play or pause. Enter stops and returns to the start.
3. Press Ctrl+S to save.

Pitch goes up, time goes right. Click the keyboard on the left to hear a pitch, or the ruler on
top to move the playhead. Rows outside the chosen key are shaded.

### Tools
| Tool | Key | What it does |
|---|---|---|
| Select | V | Click a note, or drag a rectangle around several. Double-click empty space to add a note. |
| Draw | B | Click to place a note, drag to set its length. Existing notes can still be moved. |
| Erase | E | Click notes, or drag across them. |

### Editing notes
- **Move:** drag any selected note; the whole selection follows and keeps its shape.
- **Change length:** drag the small handle at either end of a selected note.
- **Scale a group:** select several notes and drag the handle at the left or right of the dashed
  box. Starts and lengths stretch by the same factor; pitches do not change.
- **Add to or remove from the selection:** Shift+click, or Shift+drag a rectangle.
- **Ignore the grid:** hold Ctrl or Alt *after* you have started dragging.
- **Cancel a drag:** Escape.
- **Exact values:** use the Pitch, Start, Length and Velocity fields at the bottom. Start and
  Length are in beats and accept `1.5` or `1/3`.

Moving snaps by whole grid steps, so a note that sits off the grid keeps its offset. Press Q to
snap note starts to the grid.

### Zoom and scroll
Ctrl+wheel zooms time around the pointer, Alt+wheel zooms pitch, `=` and `-` zoom time, F fits
everything. The wheel scrolls; Shift+wheel scrolls sideways. You can scroll during a drag.

### Tracks
Click a track to edit it; the other tracks show faintly behind. Each has a name, sound, volume,
mute (M) and solo (S). Notes may overlap, so chords are fine.

### Files
Everything you save is an ordinary file in the `library/` folder. Copy that folder to back it up.

| You want to | Use |
|---|---|
| Keep working on it later | **Save** (a project: all tracks, tempo, key) |
| Keep one tune for reuse | **Save as / export > Save track as melody** |
| Reopen, rename, star, delete | **Library** |
| Put a saved melody in this project | **Library > Melodies > Add to project** |
| Use it in other music software | **Export MIDI** |
| Share or back up with everything kept | **Export project (.json)** |

**Import** accepts Tunelab projects and melodies (`.json`), MIDI (`.mid`) and text notation
(`.tune`, `.txt`). From MIDI, only the first tempo and meter are used, and drums are skipped.

The star marks a favorite; tick **Favorites only** to filter. Deleted items move to
`library/trash/`. Renaming changes the title, not the file name on disk. A melody added to a
project follows that project's tempo.

Tunelab warns before you lose unsaved changes, and if a file was changed elsewhere (for example
in a second tab) it asks before overwriting.

### Fixing tempo and timing (Tools, T)
- **Change, keep the sound:** the tune sounds identical, but notes land differently on the grid.
  This repairs a wrongly detected tempo. *Best grid fits* suggests values; they are guesses and
  assume the first note is on a beat.
- **Change speed:** play faster or slower.
- **Tap:** tap the beat to measure a tempo.
- **Notes twice / half as long:** when everything is off by a factor of two.
- **Move first note to bar 1:** removes silence at the start.
- **Snap to grid:** 100% is exact, less only moves part of the way. Off-grid lengths too if ticked.
- **Close small gaps**, **Remove overlaps** (leaves one note at a time, keeping the top of chords).

Timing tools apply to the selection, or to the whole track when nothing is selected. Each is one
undo step. **Score this track** rates it with the generator's rules; this needs a track without
overlaps.

### Settings (Ctrl+,)
Editor options and every keyboard shortcut. Click a key and press the new combination; if it is
taken you can swap. Settings are kept in `library/settings.json`.

## Tune Generator
Choose how many tunes to generate and review the flagged ones. The score a tune needs is fixed
for each combination of scale, meter and length, so a weak batch may flag nothing. "Wildcards"
are random tunes the scorer did *not* pick. The star saves a tune to the library as a favorite
melody; **Open in DAW** edits it there, with its chords on a second track.

### Notation
    key=A:min bpm=100 meter=4/4
    [Am] A4:1 C5:1/2 E5:1/2 D5:3/2 C5:1/2 | [F] A4:1 -:1 C5:2 |

`pitch:beats`; `-` is a rest; `[Am]` a chord (major, `m`, `dim`, `aug`). A beat is a quarter note
and the finest step is 1/12 beat. Keys: `maj`, `min`, `hmin`. `pickup=1` for an upbeat. `|` must
fall on a bar boundary; leave it out where a note is held across one.

## Melody from audio
    uv run tunelab-extract song.mp3 --start 30 --seconds 20 --wav out.wav --save

`--save` puts it under Imported in the Tune Generator, where **Open in DAW** lets you correct it.
If it looks wrong, try `--low`/`--high`, `--bpm`, `--meter`, or a clearer section.

## Known limits
- No audio recording, effects, automation, loop playback or audio export (export MIDI instead).
- Chord names from a generated tune become notes in the DAW; the names are not kept.
- Resuming in the middle of a long note is silent until the next note starts.
- The scorer detects well-formed melodies, not good ones; about half of generated tunes outscore
  Jingle Bells. Its test set is 16 simple tunes encoded from memory.
- Audio extraction was measured only on synthetic recordings; expect more errors on real mixes.
- Very large tracks (thousands of notes) work but feel slower.
- Made for a mouse and keyboard. Tested in Chrome only. Black keys are named with sharps.
