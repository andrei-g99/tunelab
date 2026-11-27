// Data model and note operations. Pure functions: nothing here touches the page,
// and nothing modifies its arguments. Times are integer ticks, PPQ per quarter note.

export const PPQ = 480;
export const MIN_DUR = 10; // shortest note that editing can produce, in ticks
export const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export const SCALES = { maj: [0, 2, 4, 5, 7, 9, 11], min: [0, 2, 3, 5, 7, 8, 10], hmin: [0, 2, 3, 5, 7, 8, 11] };
export const MODE_LABELS = { maj: "major", min: "minor", hmin: "harmonic minor" };
export const SOUNDS = { soft: "Soft", sine: "Sine", square: "Square", saw: "Saw", epiano: "Electric piano", bell: "Bell" };
export const MAX_TICK = PPQ * 4 * 5000;

let counter = 0;
/** Session-only identity for notes and tracks; never saved. */
export const newId = () => ++counter;

export const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
export const noteEnd = (n) => n.start + n.dur;
export const barTicks = (meter) => (meter[0] * PPQ * 4) / meter[1];
export const pitchName = (p) => NAMES[p % 12] + (Math.floor(p / 12) - 1);

/** "C#4" or "Db4" or "61" to a MIDI number, or null. */
export function parsePitch(text) {
  const t = text.trim();
  if (/^\d+$/.test(t)) return +t <= 127 ? +t : null;
  const m = /^([a-gA-G])(#|b)?(-1|\d)$/.exec(t);
  if (!m) return null;
  const base = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[m[1].toUpperCase()];
  const p = (Number(m[3]) + 1) * 12 + base + (m[2] === "#" ? 1 : m[2] === "b" ? -1 : 0);
  return p >= 0 && p <= 127 ? p : null;
}

/** "1.5" or "1/3" (beats) to ticks, or null. */
export function parseBeats(text) {
  const m = /^\s*(\d*\.?\d+)\s*(?:\/\s*(\d+))?\s*$/.exec(text);
  if (!m || (m[2] !== undefined && +m[2] === 0)) return null;
  return Math.round((Number(m[1]) / (m[2] ? +m[2] : 1)) * PPQ);
}
export const formatBeats = (ticks) => String(+(ticks / PPQ).toFixed(3));

// ---------- construction ----------
export const createNote = (pitch, start, dur, vel = 100) => ({ id: newId(), pitch, start, dur, vel });
export const createTrack = (name, notes = [], sound = "soft") =>
  ({ id: newId(), name, sound, volume: -8, muted: false, solo: false, notes });
export const createProject = (name = "Untitled", extra = {}) =>
  ({ name, bpm: 100, meter: [4, 4], key: { tonic: 0, mode: "maj" }, tracks: [createTrack("Melody")], ...extra });

const withIds = (notes) => notes.map((n) => ({ ...n, id: newId() }));
const bare = ({ id, ...rest }) => rest;

/** Saved project document to the in-memory form. */
export const projectFromDoc = (d) => ({
  name: d.name, bpm: d.bpm, meter: d.meter, key: d.key,
  tracks: d.tracks.map((t) => ({ ...t, id: newId(), notes: withIds(t.notes) })),
});
export const projectToDoc = (p) => ({
  format: "tunelab-project", version: 1, name: p.name, bpm: p.bpm, meter: p.meter, key: p.key,
  tracks: p.tracks.map((t) => ({ ...bare(t), notes: t.notes.map(bare) })),
});
export const melodyToDoc = (p, track, name = track.name) => ({
  format: "tunelab-melody", version: 1, name, bpm: p.bpm, meter: p.meter, key: p.key, notes: track.notes.map(bare),
});

/** Tracks contained in a melody document: the melody, plus its chords if any. */
export function tracksFromMelody(d) {
  const tracks = [createTrack(d.name, withIds(d.notes))];
  if (d.accompaniment?.length) tracks.push({ ...createTrack("Chords", withIds(d.accompaniment), "sine"), volume: -14 });
  return tracks;
}
export const projectFromMelody = (d) =>
  ({ name: d.name, bpm: d.bpm, meter: d.meter, key: d.key, tracks: tracksFromMelody(d) });

// ---------- reading ----------
export const projectEnd = (p) => p.tracks.reduce((m, t) => t.notes.reduce((k, n) => Math.max(k, noteEnd(n)), m), 0);
export const pick = (notes, ids) => notes.filter((n) => ids.has(n.id));
/** Tracks that sound when playing: not muted and, if any track is solo, solo. */
export function audibleTracks(p) {
  const solo = p.tracks.some((t) => t.solo);
  return p.tracks.filter((t) => !t.muted && (!solo || t.solo));
}
/** Seconds from the start to the end of the last note. */
export const projectSeconds = (p) => (projectEnd(p) / PPQ) * (60 / p.bpm);

/** {start, end, low, high} of some notes, or null when there are none. */
export function bounds(notes) {
  if (!notes.length) return null;
  const b = { start: Infinity, end: 0, low: 127, high: 0 };
  for (const n of notes) {
    b.start = Math.min(b.start, n.start);
    b.end = Math.max(b.end, noteEnd(n));
    b.low = Math.min(b.low, n.pitch);
    b.high = Math.max(b.high, n.pitch);
  }
  return b;
}
export function inScale(pitch, key) {
  return SCALES[key.mode].includes((((pitch - key.tonic) % 12) + 12) % 12);
}
export function hasOverlap(notes) {
  const s = [...notes].sort((a, b) => a.start - b.start);
  let end = -1;
  for (const n of s) {
    if (n.start < end) return true;
    end = Math.max(end, noteEnd(n));
  }
  return false;
}

// ---------- note operations: (notes, ...) => new notes ----------
const mapPicked = (notes, ids, f) => notes.map((n) => (ids.has(n.id) ? f(n) : n));

/** Move a group. The whole group is limited together, so its shape never changes. */
export function moveNotes(notes, ids, dt, dp) {
  const b = bounds(pick(notes, ids));
  if (!b) return notes;
  const t = clamp(dt, -b.start, Math.max(0, MAX_TICK - b.end));
  const p = clamp(dp, -b.low, 127 - b.high);
  return t || p ? mapPicked(notes, ids, (n) => ({ ...n, start: n.start + t, pitch: n.pitch + p })) : notes;
}

/** Limit a stretch factor so that no note gets too short and nothing starts before 0. */
export function limitFactor(notes, ids, origin, factor) {
  const group = pick(notes, ids);
  const shortest = Math.min(...group.map((n) => n.dur));
  const b = bounds(group);
  let hi = Infinity;
  if (b.start < origin) hi = Math.min(hi, origin / (origin - b.start));
  if (b.end > origin) hi = Math.min(hi, (MAX_TICK - origin) / (b.end - origin));
  return clamp(factor, Math.min(1, MIN_DUR / shortest), hi);
}

/** Stretch a group in time about `origin`. Every start and end scales by the same factor. */
export function scaleNotes(notes, ids, origin, factor) {
  if (!ids.size) return notes;
  const f = limitFactor(notes, ids, origin, factor);
  if (f === 1) return notes;
  const at = (x) => Math.max(0, Math.round(origin + (x - origin) * f));
  return mapPicked(notes, ids, (n) => ({ ...n, start: at(n.start), dur: Math.max(1, at(noteEnd(n)) - at(n.start)) }));
}

export const patchNotes = (notes, ids, patch) => mapPicked(notes, ids, (n) => ({ ...n, ...patch }));
export const deleteNotes = (notes, ids) => notes.filter((n) => !ids.has(n.id));

/** Copies of `group`, shifted so the earliest one begins at `at`. */
export function copiesAt(group, at) {
  const b = bounds(group);
  if (!b) return [];
  return group.map((n) => ({ ...n, id: newId(), start: n.start - b.start + at }))
    .filter((n) => noteEnd(n) <= MAX_TICK);
}

/** Pull starts and/or ends towards a grid. strength 1 = exactly on the grid. */
export function quantizeNotes(notes, ids, grid, { starts = true, ends = false, strength = 1 } = {}) {
  const pull = (x) => Math.round(x + (Math.round(x / grid) * grid - x) * strength);
  return mapPicked(notes, ids, (n) => {
    const start = starts ? pull(n.start) : n.start;
    let end = ends ? pull(noteEnd(n)) : start + n.dur;
    if (end <= start) end = start + (ends ? grid : n.dur);
    return { ...n, start, dur: end - start };
  });
}

/** Make a group one note at a time: cut each note at the next start; of a chord keep the top note. */
export function removeOverlaps(notes, ids) {
  const group = pick(notes, ids).sort((a, b) => a.start - b.start || b.pitch - a.pitch);
  const kept = new Map();
  let last = null;
  for (const n of group) {
    if (last && n.start === last.start) continue;
    if (last && noteEnd(last) > n.start) kept.set(last.id, { ...last, dur: n.start - last.start });
    kept.set(n.id, n);
    last = n;
  }
  return notes.filter((n) => !ids.has(n.id) || kept.has(n.id)).map((n) => kept.get(n.id) ?? n);
}

/** Lengthen notes to reach the next start, when the gap is at most `maxGap`. */
export function closeGaps(notes, ids, maxGap) {
  const starts = [...new Set(pick(notes, ids).map((n) => n.start))].sort((a, b) => a - b);
  return mapPicked(notes, ids, (n) => {
    const next = starts.find((s) => s >= noteEnd(n));
    return next !== undefined && next > noteEnd(n) && next - noteEnd(n) <= maxGap ? { ...n, dur: next - n.start } : n;
  });
}

// ---------- project helpers ----------
export const updateTrack = (p, trackId, patch) =>
  ({ ...p, tracks: p.tracks.map((t) => (t.id === trackId ? { ...t, ...patch } : t)) });
export const mapAllNotes = (p, f) =>
  ({ ...p, tracks: p.tracks.map((t) => ({ ...t, notes: t.notes.map(f) })) });
