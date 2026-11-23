// Toolbar, track list and note inspector. Elements are created once and updated in
// place, so typing in a field is never interrupted by a redraw.
import * as m from "./model.js";
import { validBpm } from "./tempo.js";
import { $, ask, el, guard, toast } from "../shared/dom.js";

const SNAPS = [[1, "off"], [1920, "1 bar (4/4)"], [960, "1/2"], [480, "1/4"], [240, "1/8"], [120, "1/16"], [60, "1/32"], [320, "1/4 triplet"], [160, "1/8 triplet"], [80, "1/16 triplet"]];
const METERS = ["2/4", "3/4", "4/4", "5/4", "6/4", "7/4", "3/8", "6/8", "7/8", "9/8", "12/8", "2/2"];

const setValue = (input, v) => { if (document.activeElement !== input && input.value !== String(v)) input.value = v; };
/** Text field that commits on change; parse returns null for bad input, which restores the old value. */
function field(attrs, parse, commit, bad) {
  const input = el("input", attrs);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") input.blur();
    if (e.key === "Escape") { input.value = input.dataset.was ?? ""; input.blur(); }
  });
  input.addEventListener("focus", () => { input.dataset.was = input.value; });
  input.addEventListener("change", () => {
    if (input.value.trim() === "") { input.value = input.dataset.was ?? ""; return; }
    const v = parse(input.value);
    if (v === null) { toast(bad, true); input.value = input.dataset.was ?? ""; } else commit(v);
  });
  return input;
}

export function createToolbar(store, actions) {
  const s = store.state;
  const bpm = $("#bpm");
  const commitBpm = () => {
    const v = Math.round(Number(bpm.value) * 100) / 100;
    if (bpm.value.trim() && validBpm(v)) { if (v !== s.project.bpm) store.commit({ ...s.project, bpm: v }); } else toast("Tempo must be from 20 to 400.", true);
    bpm.value = s.project.bpm;
  };
  bpm.addEventListener("change", commitBpm);
  bpm.addEventListener("keydown", (e) => { if (e.key === "Enter") bpm.blur(); if (e.key === "Escape") { bpm.value = s.project.bpm; bpm.blur(); } });

  const meter = $("#meter"), tonic = $("#tonic"), mode = $("#mode"), snap = $("#snap");
  tonic.append(...m.NAMES.map((n, i) => el("option", { value: i }, n)));
  mode.append(...Object.entries(m.MODE_LABELS).map(([k, v]) => el("option", { value: k }, v)));
  snap.append(...SNAPS.map(([v, label]) => el("option", { value: v }, label)));
  const pickList = (sel, f) => sel.addEventListener("change", () => { f(sel.value); sel.blur(); });
  pickList(meter, (v) => store.commit({ ...s.project, meter: v.split("/").map(Number) }));
  pickList(tonic, (v) => store.commit({ ...s.project, key: { ...s.project.key, tonic: +v } }));
  pickList(mode, (v) => store.commit({ ...s.project, key: { ...s.project.key, mode: v } }));
  pickList(snap, (v) => store.set({ snap: +v }));
  for (const b of document.querySelectorAll("[data-tool]")) b.addEventListener("click", () => store.set({ tool: b.dataset.tool }));
  for (const [id, action] of Object.entries({ "#b-play": "play", "#b-stop": "stop", "#b-undo": "undo", "#b-redo": "redo", "#b-zin": "zoomIn", "#b-zout": "zoomOut", "#b-fit": "zoomFit" })) {
    $(id).addEventListener("click", () => actions[action]());
  }
  store.subscribe(() => {
    const p = s.project, name = p.meter.join("/");
    setValue(bpm, p.bpm);
    if (!meter.options.length) meter.append(...METERS.map((x) => el("option", {}, x)));
    if (![...meter.options].some((o) => o.value === name)) meter.append(el("option", {}, name));
    meter.value = name;
    tonic.value = p.key.tonic;
    mode.value = p.key.mode;
    snap.value = s.snap;
    for (const b of document.querySelectorAll("[data-tool]")) b.setAttribute("aria-pressed", b.dataset.tool === s.tool);
    $("#b-undo").disabled = !store.canUndo();
    $("#b-redo").disabled = !store.canRedo();
    $("#title").textContent = p.name + (store.dirty() ? " • unsaved" : "");
    document.title = (store.dirty() ? "• " : "") + p.name + " - Tunelab DAW";
  });
}

export function createTrackList(store) {
  const s = store.state, box = $("#tracklist"), cards = new Map();
  const find = (id) => s.project.tracks.find((t) => t.id === id);
  const patch = (id, change) => store.commit(m.updateTrack(s.project, id, change));

  function build(id) {
    const name = field({ class: "name", "aria-label": "Track name", maxlength: 120 }, (v) => v.trim() || null, (v) => patch(id, { name: v }), "A track needs a name.");
    const mute = el("button", { title: "Mute", onclick: () => patch(id, { muted: !find(id).muted }) }, "M");
    const solo = el("button", { title: "Solo", onclick: () => patch(id, { solo: !find(id).solo }) }, "S");
    const sound = el("select", { "aria-label": "Sound", onchange: () => { patch(id, { sound: sound.value }); sound.blur(); } },
      ...Object.entries(m.SOUNDS).map(([k, v]) => el("option", { value: k }, v)));
    const volume = el("input", { type: "range", min: -48, max: 6, step: 1, "aria-label": "Volume", title: "Volume", onchange: () => { patch(id, { volume: +volume.value }); volume.blur(); } });
    const copy = el("button", { title: "Duplicate track", onclick: () => {
      const t = find(id);
      if (s.project.tracks.length >= 64) return toast("A project can have 64 tracks.", true);
      const dup = { ...m.createTrack(`${t.name} copy`.slice(0, 120), t.notes.map((n) => ({ ...n, id: m.newId() })), t.sound), volume: t.volume };
      store.commit({ ...s.project, tracks: [...s.project.tracks, dup] });
      store.setTrack(dup.id);
    } }, "⧉");
    const del = el("button", { title: "Delete track", onclick: guard(async () => {
      if (s.project.tracks.length === 1) return toast("A project needs at least one track.", true);
      const t = find(id);
      if (t.notes.length && (await ask(`Delete track "${t.name}" and its ${t.notes.length} notes? Undo brings it back.`, [["yes", "Delete"], ["no", "Cancel"]])) !== "yes") return;
      if (find(id) && s.project.tracks.length > 1) store.commit({ ...s.project, tracks: s.project.tracks.filter((x) => x.id !== id) });
    }) }, "×");
    for (const [b, label] of [[mute, "Mute"], [solo, "Solo"], [copy, "Duplicate track"], [del, "Delete track"]]) b.setAttribute("aria-label", label);
    const root = el("div", { class: "track", onpointerdown: () => store.setTrack(id) },
      el("div", { class: "row" }, name, copy, del), el("div", { class: "row" }, sound, mute, solo), el("div", { class: "row" }, volume));
    return { root, name, mute, solo, sound, volume, copy, del };
  }
  $("#b-addtrack").addEventListener("click", () => {
    if (s.project.tracks.length >= 64) return toast("A project can have 64 tracks.", true);
    const t = m.createTrack(`Track ${s.project.tracks.length + 1}`);
    store.commit({ ...s.project, tracks: [...s.project.tracks, t] });
    store.setTrack(t.id);
  });
  store.subscribe(() => {
    const ids = s.project.tracks.map((t) => t.id);
    for (const [id, c] of cards) if (!ids.includes(id)) { c.root.remove(); cards.delete(id); }
    s.project.tracks.forEach((t, i) => {
      let c = cards.get(t.id);
      if (!c) cards.set(t.id, (c = build(t.id)));
      if (box.children[i] !== c.root) box.insertBefore(c.root, box.children[i] ?? null);
      setValue(c.name, t.name);
      c.sound.value = t.sound;
      setValue(c.volume, t.volume);
      c.mute.setAttribute("aria-pressed", t.muted);
      c.solo.setAttribute("aria-pressed", t.solo);
      c.root.classList.toggle("active", t.id === s.trackId);
    });
  });
}

export function createInspector(store, actions) {
  const s = store.state, box = $("#inspector");
  const apply = (patch) => store.commitNotes(m.patchNotes(store.track().notes, s.selection, patch));
  const pitch = field({ "aria-label": "Pitch", title: "Note name such as C4 or F#5" }, m.parsePitch, (v) => apply({ pitch: v }), "Use a note name such as C4, F#5 or Bb3.");
  const start = field({ "aria-label": "Start in beats" }, (t) => { const v = m.parseBeats(t); return v !== null && v <= m.MAX_TICK / 2 ? v : null; }, (v) => {
    const b = store.selectionBounds();
    if (b) store.commitNotes(m.moveNotes(store.track().notes, s.selection, v - b.start, 0));
  }, "Use beats from the start, such as 4 or 1.5.");
  const length = field({ "aria-label": "Length in beats" }, (t) => { const v = m.parseBeats(t); return v >= m.MIN_DUR && v <= m.MAX_TICK / 2 ? v : null; }, (v) => {
    if (s.selection.size === 1) s.lastDur = v;
    apply({ dur: v });
  }, "Use a length in beats, such as 1, 0.5 or 1/3.");
  const vel = field({ "aria-label": "Velocity" }, (t) => (/^\s*\d+\s*$/.test(t) && +t >= 1 && +t <= 127 ? +t : null), (v) => { s.lastVel = v; apply({ vel: v }); }, "Velocity is a whole number from 1 to 127.");
  const info = el("span", { class: "soft" });
  const editor = el("div", { class: "row" },
    el("label", {}, "Pitch ", pitch), el("label", {}, "Start ", start), el("label", {}, "Length ", length), el("label", {}, "Velocity ", vel),
    el("button", { onclick: () => actions.duplicate() }, "Duplicate"), el("button", { onclick: () => actions.quantize() }, "Snap to grid"), el("button", { onclick: () => actions.delete() }, "Delete"));
  box.append(info, editor);
  const common = (notes, f) => (notes.every((n) => f(n) === f(notes[0])) ? f(notes[0]) : "");
  store.subscribe(() => {
    const sel = store.selected();
    editor.hidden = !sel.length;
    editor.style.display = sel.length ? "" : "none";
    if (!sel.length) {
      info.textContent = { select: "Drag to select notes. Double-click to add one.", draw: "Click to place a note, drag to set its length.", erase: "Click or drag over notes to erase them." }[s.tool];
      return;
    }
    info.textContent = sel.length === 1 ? "1 note" : `${sel.length} notes`;
    for (const [input, v] of [[pitch, common(sel, (n) => m.pitchName(n.pitch))], [start, m.formatBeats(m.bounds(sel).start)], [length, common(sel, (n) => m.formatBeats(n.dur))], [vel, common(sel, (n) => n.vel)]]) {
      setValue(input, v);
      input.placeholder = v === "" ? "mixed" : "";
    }
  });
}
