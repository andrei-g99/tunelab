// Tempo repair, used by the Tools dialog. Pure functions on projects.
import { MAX_TICK, PPQ, barTicks, bounds, mapAllNotes, noteEnd, projectEnd } from "./model.js";

export const MIN_BPM = 20;
export const MAX_BPM = 400;
export const validBpm = (x) => Number.isFinite(x) && x >= MIN_BPM && x <= MAX_BPM;

/** Multiply every time by `factor`, tempo unchanged. Returns null if it would not fit. */
export function stretchProject(p, factor) {
  if (!(factor > 0) || projectEnd(p) * factor > MAX_TICK) return null;
  const at = (x) => Math.round(x * factor);
  return mapAllNotes(p, (n) => ({ ...n, start: at(n.start), dur: Math.max(1, at(noteEnd(n)) - at(n.start)) }));
}

/** Change the tempo but keep every note sounding at the same moment. */
export function retempo(p, bpm) {
  if (!validBpm(bpm)) return null;
  const q = stretchProject(p, bpm / p.bpm);
  return q && { ...q, bpm };
}

/** Shift everything so the earliest note lands exactly on a barline (bar 1). */
export function alignToBar(p) {
  const b = bounds(p.tracks.flatMap((t) => t.notes));
  if (!b || b.start === 0) return p;
  return mapAllNotes(p, (n) => ({ ...n, start: n.start - b.start }));
}

/** Tempo from tap times in milliseconds, or null with fewer than three taps. */
export function tapTempo(times) {
  if (times.length < 3) return null;
  const bpm = (60000 * (times.length - 1)) / (times.at(-1) - times[0]);
  return validBpm(bpm) ? Math.round(bpm * 10) / 10 : null;
}

/** Mean distance of starts from a grid, 0 = all on it, 0.25 = no better than chance. */
function misfit(starts, grid) {
  return starts.reduce((s, x) => s + Math.abs(x / grid - Math.round(x / grid)), 0) / starts.length;
}

/**
 * Tempos at which the project's notes would line up best with the grid, best first.
 * Assumes the first note is on a beat. Returns [{bpm, fit}], fit 0..1.
 */
export function suggestTempos(p, count = 3) {
  const all = p.tracks.flatMap((t) => t.notes);
  const starts = [...new Set(all.map((n) => n.start))].sort((a, b) => a - b);
  if (starts.length < 6) return [];
  const rel = starts.map((s) => s - starts[0]);
  const cands = [];
  for (let bpm = 50; bpm <= 200; bpm += 0.5) {
    const s = rel.map((x) => (x * bpm) / p.bpm);
    const m = 0.35 * misfit(s, PPQ / 4) + 0.35 * misfit(s, PPQ / 2) + 0.3 * misfit(s, PPQ);
    cands.push({ bpm, fit: Math.max(0, 1 - 4 * m) });
  }
  const peaks = cands.filter((c, i) => c.fit >= (cands[i - 1]?.fit ?? -1) && c.fit > (cands[i + 1]?.fit ?? -1));
  const order = (c) => c.fit - 0.04 * Math.abs(Math.log2(c.bpm / 110)); // mild pull to ordinary tempos
  return peaks.sort((a, b) => order(b) - order(a)).slice(0, count);
}

export const barsLong = (p) => Math.ceil(projectEnd(p) / barTicks(p.meter));
