import assert from "node:assert/strict";
import { test } from "node:test";
import * as m from "../../web/daw/model.js";

const N = (pitch, start, dur) => m.createNote(pitch, start, dur);
const ids = (ns) => new Set(ns.map((n) => n.id));
const rand = (seed) => () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);

test("moving clamps the group as a whole", () => {
  const ns = [N(0, 100, 50), N(12, 300, 50)];
  const out = m.moveNotes(ns, ids(ns), -500, -5);
  assert.deepEqual(out.map((n) => [n.pitch, n.start]), [[0, 0], [12, 200]]);
  assert.equal(m.moveNotes(ns, ids(ns), 0, -5), ns, "no-op returns the same array");
  assert.equal(ns[0].start, 100, "input is untouched");
  const top = [N(120, 0, 10), N(127, 0, 10)];
  assert.equal(m.moveNotes(top, ids(top), 0, 12), top);
});

test("scaling keeps proportions, pitches and adjacency", () => {
  const r = rand(4);
  for (let k = 0; k < 300; k++) {
    let t = Math.floor(r() * 2000);
    const ns = [];
    for (let i = 0; i < 8; i++) { const d = 40 + Math.floor(r() * 900); ns.push(N(60 + i, t, d)); t += d; }
    const b = m.bounds(ns), f = 0.3 + r() * 3, origin = r() < 0.5 ? b.start : b.end;
    const lim = m.limitFactor(ns, ids(ns), origin, f);
    const out = m.scaleNotes(ns, ids(ns), origin, f);
    out.forEach((n, i) => {
      assert.equal(n.pitch, ns[i].pitch);
      assert.ok(Math.abs(n.start - (origin + (ns[i].start - origin) * lim)) <= 0.51);
      assert.ok(Math.abs(n.dur - ns[i].dur * lim) <= 1.01);
      assert.ok(n.start >= 0 && n.dur >= 1 && Number.isInteger(n.start) && Number.isInteger(n.dur));
      if (i) assert.equal(n.start, m.noteEnd(out[i - 1]), "touching notes stay touching");
    });
  }
});

test("scaling is limited by the shortest note and by time zero", () => {
  const ns = [N(60, 480, 20), N(62, 500, 480)];
  assert.equal(m.limitFactor(ns, ids(ns), 480, 0.01), 0.5);
  assert.ok(m.limitFactor(ns, ids(ns), 980, 100) <= 980 / 500 + 1e-9);
  const out = m.scaleNotes(ns, ids(ns), 980, 100);
  assert.equal(out[0].start, 0);
});

test("only picked notes change", () => {
  const ns = [N(60, 0, 100), N(62, 100, 100)];
  const one = new Set([ns[1].id]);
  assert.equal(m.scaleNotes(ns, one, 100, 2)[0], ns[0]);
  assert.equal(m.moveNotes(ns, one, 50, 0)[0], ns[0]);
  assert.deepEqual(m.deleteNotes(ns, one), [ns[0]]);
});

test("quantize", () => {
  const ns = [N(60, 130, 100), N(60, 250, 5)];
  const q = m.quantizeNotes(ns, ids(ns), 120, { starts: true, ends: true });
  assert.deepEqual(q.map((n) => [n.start, n.dur]), [[120, 120], [240, 120]]);
  const half = m.quantizeNotes([ns[0]], ids(ns), 120, { strength: 0.5 });
  assert.deepEqual([half[0].start, half[0].dur], [125, 100]);
});

test("removeOverlaps makes a single line, keeping the top of chords", () => {
  const ns = [N(60, 0, 500), N(64, 0, 500), N(67, 200, 100), N(50, 900, 10)];
  const out = m.removeOverlaps(ns, ids(ns));
  assert.equal(m.hasOverlap(out), false);
  assert.deepEqual(out.map((n) => [n.pitch, n.start, n.dur]), [[64, 0, 200], [67, 200, 100], [50, 900, 10]]);
});

test("closeGaps fills small gaps only", () => {
  const ns = [N(60, 0, 100), N(62, 120, 100), N(64, 900, 100)];
  assert.deepEqual(m.closeGaps(ns, ids(ns), 60).map((n) => n.dur), [120, 100, 100]);
});

test("copies and documents round-trip", () => {
  const p = m.createProject("X");
  p.tracks[0].notes = [N(60, 480, 240), N(62, 720, 240)];
  const c = m.copiesAt(p.tracks[0].notes, 5000);
  assert.deepEqual(c.map((n) => n.start), [5000, 5240]);
  assert.ok(c.every((n) => !p.tracks[0].notes.some((o) => o.id === n.id)));
  const doc = m.projectToDoc(p);
  assert.ok(!JSON.stringify(doc).includes('"id"'));
  assert.deepEqual(m.projectToDoc(m.projectFromDoc(JSON.parse(JSON.stringify(doc)))), doc);
});

test("text parsing", () => {
  assert.equal(m.parsePitch("C4"), 60);
  assert.equal(m.parsePitch("db4"), 61);
  assert.equal(m.parsePitch("Cb4"), 59);
  assert.equal(m.parsePitch("G#9"), null);
  assert.equal(m.parsePitch("x"), null);
  assert.equal(m.parseBeats("1/3"), 160);
  assert.equal(m.parseBeats("1.5"), 720);
  assert.equal(m.parseBeats("1/0"), null);
  assert.equal(m.parseBeats("-1"), null);
  for (let p = 0; p < 128; p++) assert.equal(m.parsePitch(m.pitchName(p)), p);
});

test("audible tracks: mute, then solo; projectSeconds follows the tempo", () => {
  const t = (name, extra) => ({ ...m.createTrack(name, [N(60, 0, 960)]), ...extra });
  const tracks = [t("a"), t("b", { muted: true }), t("c", { solo: true }), t("d", { solo: true, muted: true })];
  const p = m.createProject("P", { tracks, bpm: 120 });
  assert.deepEqual(m.audibleTracks(p).map((x) => x.name), ["c"]);
  assert.deepEqual(m.audibleTracks({ ...p, tracks: tracks.slice(0, 2) }).map((x) => x.name), ["a"]);
  assert.equal(m.projectSeconds(p), 1); // two beats at 120 BPM
});
