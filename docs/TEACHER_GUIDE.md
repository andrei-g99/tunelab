# Tunelab for composition teachers

This guide is for a composition teacher whose student uses Tunelab. It explains what the tools do
in musical terms, what they assume, where they can be wrong, and how their output can be used in
lessons. The [user guide](USER_GUIDE.md) lists every button and key. This guide explains what
the results mean.

Tunelab is a sketchpad for **single-line melodies**, usually with a few chords underneath. It
is not a notation program and not a full studio. It runs on the student's own computer, and
nothing is uploaded.

## The three tools at a glance
| Tool | What the student does with it | What you will see from it |
|---|---|---|
| **DAW** | Writes and edits melodies on a piano roll, plays them, tries them out on the computer keyboard | Projects (several tracks), saved melodies, MIDI files |
| **Tune Generator** | Lets the computer write hundreds of short melodies, rates them, and listens to the best | Short tunes with a score and a breakdown of that score |
| **Melody Transcriber** | Records music playing in the browser and lets the computer guess its melody | A first draft of the melody, to be corrected in the DAW |

## Musical conventions and limits
These apply to all three tools. Point them out to the student when the result looks odd.

- **Pitch** uses MIDI numbers (C4 = middle C = 60). Black keys are always spelled with sharps,
  so E♭ shows as D♯. There is no enharmonic spelling and no clef.
- **Time:** a beat is always a quarter note, including in 6/8. The generator, the scorer and
  text notation work in steps of 1/12 of a beat, so sixteenths, triplets and their combinations
  fit; finer values are rounded. The DAW itself is finer.
- **Keys:** major, natural minor and harmonic minor. Other modes can be written, but the editor
  treats them as notes outside the key. Shading shows which rows are outside the chosen key.
- **Meters:** the DAW offers 2/4, 3/4, 4/4, 5/4, 6/4, 7/4, 2/2, 3/8, 6/8, 7/8, 9/8 and 12/8.
  There is one meter and one tempo per project. The generator writes only in 4/4 and 3/4.
- **Sound:** plain synthesizer voices (soft, sine, square, saw, electric piano, bell). There are no
  dynamics beyond per-note velocity, no articulation and no effects. Judge the notes, not the timbre.
- **Chords** are stored as notes on a second track. Chord *names* from the generator are lost
  when a tune moves to the DAW.
- **No score view.** If you prefer reading notation, ask the student to **Export MIDI**
  and open it in your notation software.

## DAW: writing and editing
The student places notes on a grid (pitch up, time right), moves and stretches them, and keeps
several tracks, such as a melody and a bass line. Every change can be undone.

What is useful in lessons:
- **Scaling a group of notes** (augmentation and diminution) stretches rhythms by any factor
  without changing pitches.
- **Tools (T)** include *Change, keep the sound*. It re-bars a passage that sounds right but
  sits wrongly on the grid, for example when the student set the wrong tempo. *Snap to grid*
  quantizes, fully or partly. *Notes twice / half as long* fixes a melody written in the wrong
  note values.
- **Score this track** applies the generator's rating (see below) to the student's own melody.
- **Keyboard (M)** turns the computer keyboard into a small piano with an octave selector,
  for trying ideas by ear. It only plays; nothing is recorded, so the student still writes
  the notes in by hand.

## Tune Generator: what the computer writes and how it rates it
The generator is deliberately simple and fully rule-based; nothing is learned from other music. It
helps to know the recipe, because its strengths and weaknesses follow from it.

**How a tune is built**
- It picks a key and a 4-bar chord loop from a short list of common progressions. Sections
  in the middle end open; the last one closes on the tonic.
- It invents a two-bar motif A and a contrasting B, makes variants A′ and A″, and arranges
  them in a form such as A A′ B C or A B A C.
- Rhythms come from a list of one-bar patterns. Pitches move mostly by step within A3–A5,
  and notes on strong beats are pulled onto chord tones.
- Every fourth bar breathes (a long note). The penultimate note leans into the tonic by step,
  and the last bar holds the tonic.

Expect correct, square and fairly predictable tunes. They rarely contain real surprises,
modulation, sequences or idiomatic writing for an instrument.

**How a tune is rated (0 to 1).** The score is a weighted average of seven parts, and the
student sees each part:

| Part | Weight | Rewards |
|---|---|---|
| tonal | 1 | Notes in the key; strong and long notes on the tonic triad |
| intervals | 1.5 | Mostly steps, some leaps, leaps followed by a step back; few tritones and sevenths |
| contour | 1 | A range of about a seventh to a tenth, regular changes of direction, one high point that is not at the start |
| motif | 1.5 | Short shapes that come back, transposed or not, without one shape dominating |
| rhythm | 1 | Some variety of note values, notes on downbeats, long notes on the beat |
| cadence | 1 | Ends on the tonic (or the third or fifth), approached by step, on a long note and a strong beat; a breathing point halfway |
| chord fit | 1 | Notes on strong beats belong to the current chord (only when there are chords) |

The rules are textbook conventions for simple tonal melody, and their author set the numbers by
hand. **The score measures whether a tune is well-formed, not whether it is good.** About half of
the generated tunes score higher than *Jingle Bells*, and the rules were checked against only 16
simple tunes. A deliberately unconventional melody will score low, and that is fine.

**Flagged and wildcard tunes.** The top few percent are flagged. The cut-off is fixed for each
combination of scale, meter and length, so a weak batch may flag nothing. "Wildcards" are random
tunes that the scorer did *not* pick. They are there so that its blind spots can be heard.

## Melody Transcriber: a draft, not an answer
The student plays a recording in a browser (for example a song on a video site), records 10 to 60
seconds, and gets two or three guesses at the main melody: the sung line, or the lead instrument.
Models running on the student's computer (or a simpler method, without a suitable graphics
card) separate the voice from the accompaniment, follow its
pitch and find the beat.

What to expect:
- On public test clips, about **87% of notes had the right pitch for singing and 79% for
  instruments**. Beats, bar lines and note boundaries were not measured, and they are often
  the weaker part.
- Slides, vibrato and ornaments become plain notes. Octave errors and a tempo off by a factor
  of two are common. Fast passages, and a lead buried in a dense mix, come out worst.
- The saved version is rounded to quarters or thirds of a beat. **Play with original** plays
  the timing as performed, on top of the recording.
- With **Guide it myself**, the student paints the melody's region on a picture of the sound (a
  spectrogram). This mostly helps with instrumental leads. Overtones look like extra notes;
  the right line is usually the lowest bright one of a sound.

**For teaching,** the corrections are the valuable part. Comparing the guess with the
recording, then fixing pitches, rhythm and barring in the DAW, is dictation with a head start.
It is worth asking the student what they changed and why.

## Ideas for lessons
- **Dictation with a draft:** transcribe a short phrase, and have the student correct it by ear
  before checking it against a score.
- **Critique the machine:** pick a flagged tune and a wildcard. Which is better, and what does
  the score breakdown miss? This shows quickly what the rules can and cannot hear.
- **Motif development:** take a generated tune's A section and develop it by hand
  (sequence, inversion, augmentation with group scaling), then compare the motif score.
- **Rules as a checklist, not a goal:** after a student's tune is scored, discuss each low
  part. Is the weakness real, or a deliberate choice?
- **Re-barring:** change the project's meter, or use *Change, keep the sound*, to see how the same
  notes read with different bar lines.

## Getting the student's work
- **Export MIDI** opens in any notation program or DAW.
- **Export audio (.mp3 or .wav)** is the tune as Tunelab plays it, for listening anywhere. It uses
  the same plain synthesizer sounds, so judge the notes, not the timbre.
- **Export project (.json)** keeps everything, but needs Tunelab to open.
- Text notation, used by the generator, can be pasted into a message:

      key=A:min bpm=100 meter=4/4
      [Am] A4:1 C5:1/2 E5:1/2 D5:3/2 C5:1/2 | [F] A4:1 -:1 C5:2 |

  Each note is `pitch:beats`, `-` is a rest, and `[Am]` is a chord.
- Everything saved is an ordinary file in the student's `library/` folder.

## Keeping this guide up to date
This guide describes behaviour that changes as the code changes. **Agents and developers who
change Tunelab must update this guide in the same change** when they alter anything a teacher
would notice:
- the musical conventions (time units, keys, meters, spelling, sounds, rounding)
- how the generator builds tunes, or the scorer's parts, weights or meaning
- the transcriber's measured accuracy, methods or rounding, and its known failure cases
- import and export formats, or the tools and features named here

Keep the tone non-technical, give numbers only where they were measured, and state limits
plainly. If a section no longer matches the code, fix it or remove it; a wrong guide is worse
than a short one. `AGENTS.md` lists this guide among the documents to update.
