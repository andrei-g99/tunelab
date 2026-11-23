// MIDI files <-> projects. `Midi` is the class from @tonejs/midi, passed in by the caller.
import { PPQ, clamp, createNote, createProject, createTrack } from "./model.js";

const METER_DENOMINATORS = [2, 4, 8, 16];

/** Read a .mid file. Only the first tempo and meter are used; drum channels are skipped. */
export function projectFromMidi(Midi, bytes, name) {
  let midi;
  try {
    midi = new Midi(bytes);
  } catch {
    throw new Error("This is not a readable MIDI file.");
  }
  const k = PPQ / midi.header.ppq;
  const at = (x) => Math.round(x * k);
  const tracks = midi.tracks.filter((t) => t.notes.length && t.channel !== 9).map((t, i) =>
    createTrack((t.name || `Track ${i + 1}`).slice(0, 120), t.notes.map((n) => {
      const start = at(n.ticks);
      return createNote(n.midi, start, Math.max(1, at(n.ticks + n.durationTicks) - start), clamp(Math.round(n.velocity * 127), 1, 127));
    })));
  if (!tracks.length) throw new Error("This MIDI file contains no melodic notes.");
  const bpm = midi.header.tempos[0]?.bpm ?? 120;
  const meter = midi.header.timeSignatures[0]?.timeSignature ?? [4, 4];
  return createProject(name, {
    bpm: clamp(Math.round(bpm * 100) / 100, 20, 400),
    meter: METER_DENOMINATORS.includes(meter[1]) && meter[0] >= 1 && meter[0] <= 32 ? [meter[0], meter[1]] : [4, 4],
    tracks,
  });
}

/** Write a project as .mid bytes. */
export function projectToMidi(Midi, p) {
  const midi = new Midi();
  const k = midi.header.ppq / PPQ;
  midi.header.name = p.name;
  midi.header.setTempo(p.bpm);
  midi.header.timeSignatures.push({ ticks: 0, timeSignature: [...p.meter] });
  p.tracks.forEach((t, i) => {
    const track = midi.addTrack();
    track.name = t.name;
    track.channel = (i % 15) + (i % 15 >= 9 ? 1 : 0); // skip channel 9, reserved for drums
    for (const n of t.notes) {
      track.addNote({ midi: n.pitch, ticks: Math.round(n.start * k), durationTicks: Math.max(1, Math.round(n.dur * k)), velocity: n.vel / 127 });
    }
  });
  return midi.toArray();
}
