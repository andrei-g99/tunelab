# Tunelab user guide

Start with `uv run tunelab` and open <http://127.0.0.1:8321>. Stop it with Ctrl+C. The links at
the top left switch between the **DAW**, the **Tune Generator** and the **Melody Transcriber**.

## DAW

### First steps
1. Choose **Draw** (B) and click in the grid to place notes. Drag while placing to set the length.
2. Press Space to play or pause. Enter stops and returns to the start.
3. Press Ctrl+S to save.

Pitch goes up, time goes right. Click the keyboard on the left to hear a pitch, or the ruler on
top to move the playhead. Rows outside the chosen key are shaded. While you press a key, or click
or drag a note, its key and row light up.

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

### Playing with the computer keyboard (M)
**Keyboard**, under the tracks, turns the computer keyboard into a small piano, with the sound of the
active track. It plays only; notes are not recorded.

| Keys | Notes |
|---|---|
| A S D F G H J K L ; ' | White keys, from C to the F an octave higher |
| Q W, R T Y, O P, ] | Black keys |
| Z, X | Octave down, up; or choose it in the panel |

Hold several keys for chords; the panel can also be played with the mouse. While it is on, these keys
(and E, U, I, [ between them) do not trigger their shortcuts; the buttons and combinations
with Ctrl still work. Keys go by position, as on a US keyboard. Press M again to get the shortcuts back.

### Files
Everything you save is an ordinary file in the `library/` folder. Copy that folder to back it up.

| You want to | Use |
|---|---|
| Keep working on it later | **Save** (a project: all tracks, tempo, key) |
| Keep one tune for reuse | **Save as / export > Save track as melody** |
| Reopen, rename, star, delete | **Library** |
| Put a saved melody in this project | **Library > Melodies > Add to project** |
| Use it in other music software | **Export MIDI** |
| Listen to it anywhere, or send it | **Export audio (.mp3)** or **(.wav)** |
| Share or back up with everything kept | **Export project (.json)** |

**Export audio** sounds exactly like Play: same tempo, sounds, volumes and velocities, from the start
of bar 1 to the last note plus two seconds for the sound to fade. With several tracks it asks: the
**whole mix, as you hear it** (muted tracks left out, or only the solo ones), or **only the active
track**, whatever its mute. MP3 needs `ffmpeg`; WAV does not. Up to 20 minutes, in mono.

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

## Melody Transcriber
Records what a browser is playing and guesses the main melody. Linux only; nothing leaves this
computer. Install the neural models once with `uv sync --extra gpu`; the first analysis downloads
their weights (about 1 GB). Without them, or if they fail, a basic method is used and the page says so.

1. Start the music in any browser, then choose **Refresh** and pick that browser in the list.
   Tabs of one browser cannot always be told apart; the one that is playing comes first.
2. **Record** 10 to 60 seconds, then **Stop**. It stops by itself after 2 minutes. If playback
   pauses, recording waits and goes on when that browser plays again.
3. Compare the guesses. **Play guess** is the version on the beat grid, the one that is saved.
   **Play with original** puts the performed timing on top of the recording.
4. **Open in DAW** (saves to the library first) or **Save to library**. Fix mistakes in the DAW; a
   wrong tempo or a factor of two is quickest with Tools (T).

Only that browser's own output is recorded, never the microphone. A recording is temporary: it is
gone after the next one, or when Tunelab stops, unless you choose **Keep recording**, which puts it
in `library/recordings/`.

When vocals are found, the guesses are the singing, the singing heard in the full mix, and the lead
instrument. Otherwise they are two guesses at the lead instrument. Duplicates are left out.

### Guide it myself
When the guess follows the wrong line, show it where the melody is. This helps most with
instruments; singing is usually found better without help, unless you want another line.

1. Choose **Guide it myself** after an analysis. The picture has time to the right and pitch upwards.
   **Melody strength** fades overtones; **Spectrogram** shows the plain sound. The guess chosen
   under **with** is drawn on top in orange.
2. Paint with **Melody** (B) over the line you want, only roughly: about 3 semitones either side is
   good, narrower is worse. A tall brush marks whole areas. **Not melody** (N) excludes, **Erase** (E)
   removes. Ctrl+Z and Ctrl+Shift+Z undo and redo, Escape drops a stroke.
3. **Guess from highlights** adds a Guided guess below; each attempt is kept. Where nothing is
   painted, the search works as usual; with **Only use what I painted** there is silence instead.

**Source** chooses what is searched and played: the full recording, the vocals, or everything but the
vocals (for a riff under singing). Click the ruler to move the cursor, Space to play from there, the
keyboard to hear a pitch. **Hear highlighted** plays only the sound inside the highlights.

Overtones look like notes: prefer the lowest bright line of a sound. If your highlights seem to be on
overtones, or little is found in them, a warning says so; it can be wrong.

Ctrl+wheel zooms time, Alt+wheel pitch, Shift+wheel scrolls sideways. Highlights survive a reload and
a visit to the DAW, but are gone when you record or open something else or close the tab; **Guess
again** removes guided guesses that were not saved.

To measure quality, put clips with a corrected melody in `clips/dev/` and `clips/holdout/` as
`name.wav` and `name.json` (from **Export track as melody**) and run
`uv run tunelab-melody-check clips/`.

## Melody from audio
    uv run tunelab-extract song.mp3 --start 30 --seconds 20 --wav out.wav --save

`--save` puts it under Imported in the Tune Generator, where **Open in DAW** lets you correct it.
If it looks wrong, try `--low`/`--high`, `--bpm`, `--meter`, or a clearer section.

## Known limits
- No audio tracks in the DAW, effects, automation or loop playback.
- Chord names from a generated tune become notes in the DAW; the names are not kept.
- Resuming in the middle of a long note is silent until the next note starts.
- The scorer detects well-formed melodies, not good ones; about half of generated tunes outscore
  Jingle Bells. Its test set is 16 simple tunes encoded from memory.
- `tunelab-extract` was tuned only on synthetic recordings; expect more errors on real mixes.
- The transcriber guesses. On 33 short public test clips (ADC2004, MIREX05) its notes had the right
  pitch 87% of the time for singing (21 clips) and 79% for instruments (12 clips). Beats, bars and
  note boundaries were not measured. Slides and vibrato become plain notes.
- Rough highlights simulated from the known answers raised instruments from 79% to 89% and left singing
  at 86 to 87%. Real highlights are less exact. The overtone warning was set and tested on the same clips.
- Very large tracks (thousands of notes) work but feel slower.
- Made for a mouse and keyboard. Tested in Chrome only. Black keys are named with sharps.
