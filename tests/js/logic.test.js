import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
import { projectFromMidi, projectToMidi } from "../../web/daw/midi.js";
import { createNote, createProject, createTrack, moveNotes } from "../../web/daw/model.js";
import { ACTIONS, BLACK_KEYS, OCTAVE_MAX, OCTAVE_MIN, RESERVED, WHITE_KEYS, conflict, effectiveKeys, isPianoKey, keyFromEvent, pianoPitch, prettyKey } from "../../web/daw/shortcuts.js";
import { createStore } from "../../web/daw/store.js";
import { alignToBar, retempo, stretchProject, suggestTempos, tapTempo } from "../../web/daw/tempo.js";

const { Midi } = createRequire(import.meta.url)("@tonejs/midi");
const project = (notes, extra) => createProject("P", { tracks: [createTrack("a", notes)], ...extra });
const seconds = (p) => p.tracks[0].notes.map((n) => (n.start / 480) * (60 / p.bpm));

test("store: undo, redo, dirty, pruned selection", () => {
  const s = createStore();
  assert.equal(s.dirty(), false);
  const n = createNote(60, 0, 480);
  s.commitNotes([n], [n.id]);
  assert.ok(s.dirty() && s.state.selection.has(n.id));
  s.commitNotes(moveNotes(s.track().notes, s.state.selection, 480, 0));
  s.undo();
  assert.equal(s.track().notes[0].start, 0);
  s.undo();
  assert.equal(s.dirty(), false, "undoing everything means nothing to save");
  assert.equal(s.state.selection.size, 0);
  s.redo(); s.redo();
  assert.equal(s.track().notes[0].start, 480);
  const before = s.state.project;
  s.commitNotes(s.track().notes);
  assert.equal(s.state.project, before, "a no-op is not an undo step");
  s.undo();
  s.commitNotes([]);
  assert.equal(s.canRedo(), false);
});

test("store: losing the active track falls back safely", () => {
  const s = createStore();
  const extra = createTrack("b", [createNote(60, 0, 10)]);
  s.commit({ ...s.state.project, tracks: [...s.state.project.tracks, extra] });
  s.setTrack(extra.id);
  s.select([extra.notes[0].id]);
  s.undo();
  assert.equal(s.track().name, "Melody");
  assert.equal(s.state.selection.size, 0);
  s.redo();
  assert.equal(s.state.project.tracks.length, 2);
});

test("tempo: retempo keeps the sound, suggestions recover the true tempo", () => {
  for (const [truth, wrong] of [[120, 90], [100, 150], [96, 128], [110, 110]]) {
    const beats = [0, 1, 1.5, 2, 3, 4, 4.5, 5, 6, 7, 8, 9, 9.5, 10, 12];
    const p = project(beats.map((b) => createNote(60, Math.round((b * 480 * wrong) / truth), 100)), { bpm: wrong });
    const got = suggestTempos(p).map((c) => c.bpm);
    assert.ok(got.includes(truth), `${truth} in ${got}`);
    const q = retempo(p, truth);
    seconds(q).forEach((x, i) => assert.ok(Math.abs(x - seconds(p)[i]) < 0.003));
  }
  assert.equal(retempo(project([]), 5), null);
  assert.equal(stretchProject(project([createNote(60, 9000000, 10)]), 10), null);
  assert.equal(alignToBar(project([createNote(60, 70, 10)])).tracks[0].notes[0].start, 0);
  assert.equal(tapTempo([0, 500, 1000]), 120);
  assert.equal(tapTempo([0, 500]), null);
});

test("MIDI round trip", () => {
  const p = project([createNote(60, 0, 480, 90), createNote(64, 0, 480, 64), createNote(62, 777, 13, 127)], { bpm: 133, meter: [6, 8] });
  p.tracks.push(createTrack("second", [createNote(40, 960, 240)]));
  const q = projectFromMidi(Midi, projectToMidi(Midi, p), "back");
  assert.equal(Math.round(q.bpm), 133);
  assert.deepEqual(q.meter, [6, 8]);
  const flat = (x) => x.tracks.map((t) => [t.name, t.notes.map((n) => [n.pitch, n.start, n.dur, n.vel]).sort((a, b) => a[1] - b[1] || a[0] - b[0])]);
  assert.deepEqual(flat(q), flat(p));
  assert.throws(() => projectFromMidi(Midi, new Uint8Array([1, 2, 3]), "x"));
  assert.throws(() => projectFromMidi(Midi, projectToMidi(Midi, project([])), "x"), /no melodic notes/);
});

test("shortcuts: defaults are unique and not reserved", () => {
  const keys = effectiveKeys();
  for (const a of ACTIONS) {
    assert.equal(conflict(keys, a.id, a.key), undefined, a.id);
    assert.ok(!RESERVED.has(a.key), a.id);
  }
  assert.equal(effectiveKeys({ play: "KeyP" }).play, "KeyP");
  const ev = (o) => ({ code: "KeyS", key: "s", ...o });
  assert.equal(keyFromEvent(ev({ ctrlKey: true, shiftKey: true })), "$mod+Shift+KeyS");
  assert.equal(keyFromEvent(ev({ metaKey: true }), true), "$mod+KeyS");
  assert.equal(keyFromEvent({ code: "ShiftLeft", key: "Shift", shiftKey: true }), null);
  assert.equal(prettyKey("$mod+Shift+KeyZ"), "Ctrl + Shift + Z");
});

test("piano keys: layout, range, and the keys that control it stay free", () => {
  const row = (keys) => keys.map(([code]) => prettyKey(code)).join("");
  assert.equal(row(WHITE_KEYS), "ASDFGHJKL;'");
  assert.equal(row(BLACK_KEYS), "QWRTYOP]");
  const all = [...WHITE_KEYS, ...BLACK_KEYS];
  assert.deepEqual(all.map(([c]) => pianoPitch(c, 4)).sort((a, b) => a - b), Array.from({ length: 19 }, (_, i) => 60 + i));
  for (const [c, n] of all) assert.equal([1, 3, 6, 8, 10].includes(n % 12), BLACK_KEYS.some(([b]) => b === c));
  for (const [c] of all) assert.ok(pianoPitch(c, OCTAVE_MIN) >= 0 && pianoPitch(c, OCTAVE_MAX) <= 127);
  assert.equal(pianoPitch("KeyE", 4), null);
  assert.ok(isPianoKey("KeyE") && !isPianoKey("KeyZ"));
  for (const id of ["piano", "pianoDown", "pianoUp", "play", "stop"]) assert.ok(!isPianoKey(effectiveKeys()[id]), id);
});
