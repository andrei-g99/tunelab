// Wires the DAW together: store, roll, player, panels, dialogs, shortcuts.
import { tinykeys } from "../vendor/tinykeys.mjs";
import { $, api, guard, toast } from "../shared/dom.js";
import * as m from "./model.js";
import { createFiles } from "./files.js";
import { createLibrary } from "./library.js";
import { createInspector, createToolbar, createTrackList } from "./panels.js";
import { createPiano } from "./piano.js";
import { createPlayer } from "./player.js";
import { createRoll } from "./roll.js";
import { createSettings } from "./settings.js";
import { ACTIONS, effectiveKeys } from "./shortcuts.js";
import { createStore } from "./store.js";
import { createTools } from "./tools.js";

const store = createStore();
const s = store.state;
let clipboard = [];

const settings = await createSettings((now) => { bindKeys(now.shortcuts); roll.redraw(); });

const preview = (pitch, vel, secs) => { if (settings.get().previewNotes) player.preview(s.trackId, pitch, vel, secs).catch(console.error); };
const roll = createRoll({ scroller: $("#roll"), store, settings: settings.get, onPreview: preview, onSeek: (t) => player.seek(t) });
const player = createPlayer({
  store,
  onFrame(tick) {
    roll.setPlayhead(tick, settings.get().followPlayhead && player.playing());
    const bar = m.barTicks(s.project.meter), beat = (m.PPQ * 4) / s.project.meter[1];
    $("#pos").textContent = `${Math.floor(tick / bar) + 1}.${Math.floor((tick % bar) / beat) + 1}`;
  },
  onState(on) { $("#b-play").textContent = on ? "Pause" : "Play"; },
});

// ---------- actions (ids match shortcuts.js) ----------
const notes = () => store.track().notes;
const step = () => (s.snap > 1 ? s.snap : 10);
function nudge(dt, dp) {
  if (!s.selection.size) return;
  store.commitNotes(m.moveNotes(notes(), s.selection, dt, dp));
  if (dp) { const n = store.selected()[0]; preview(n.pitch, n.vel, 0.15); }
}
function addCopies(group, at) {
  const copies = m.copiesAt(group, at);
  if (!copies.length) return;
  if (notes().length + copies.length > 20000) return toast("A track can hold 20,000 notes.", true);
  store.commitNotes([...notes(), ...copies], copies.map((n) => n.id));
}
const actions = {
  play: guard(async () => { if (!player.playing() && !m.projectEnd(s.project)) toast("Nothing to play yet. Draw some notes first."); else await player.toggle(); }),
  stop: () => player.stop(),
  save: guard(() => files.save()),
  open: () => library.open(),
  undo: () => store.undo(),
  redo: () => store.redo(),
  toolSelect: () => store.set({ tool: "select" }),
  toolDraw: () => store.set({ tool: "draw" }),
  toolErase: () => store.set({ tool: "erase" }),
  selectAll: () => store.select(notes().map((n) => n.id)),
  deselect: () => { if (!roll.cancel()) store.select([]); },
  copy: () => { if (s.selection.size) { clipboard = store.selected(); toast(`Copied ${clipboard.length} notes.`); } },
  cut: () => { if (s.selection.size) { clipboard = store.selected(); actions.delete(); } },
  paste: () => addCopies(clipboard, player.position()),
  duplicate: () => {
    const b = store.selectionBounds();
    if (!b) return;
    // keep the rhythm: repeat after a whole number of grid steps
    const span = b.end - b.start, at = s.snap > 1 ? Math.max(1, Math.ceil(span / s.snap - 1e-9)) * s.snap : span;
    addCopies(store.selected(), b.start + at);
  },
  delete: () => { if (s.selection.size) store.commitNotes(m.deleteNotes(notes(), s.selection)); },
  left: () => nudge(-step(), 0),
  right: () => nudge(step(), 0),
  up: () => nudge(0, 1),
  down: () => nudge(0, -1),
  octaveUp: () => nudge(0, 12),
  octaveDown: () => nudge(0, -12),
  quantize: () => {
    if (s.snap <= 1) return toast("Choose a grid first.", true);
    const ids = s.selection.size ? s.selection : new Set(notes().map((n) => n.id));
    const out = m.quantizeNotes(notes(), ids, s.snap);
    if (out.some((n, i) => n.start !== notes()[i].start)) store.commitNotes(out);
  },
  zoomIn: () => roll.zoomX(1.25),
  zoomOut: () => roll.zoomX(0.8),
  zoomFit: () => roll.fit(),
  piano: () => piano.toggle(),
  pianoDown: () => piano.shift(-1),
  pianoUp: () => piano.shift(1),
  tools: () => tools.open(),
  settings: () => settings.open(),
};

const files = createFiles({ store, onOpened() { player.stop(); roll.fit(); } });
const library = createLibrary({ files });
const tools = createTools({ store });
createToolbar(store, actions);
createTrackList(store);
createInspector(store, actions);
store.subscribe(() => roll.redraw());
store.subscribe(() => player.update(s.project));

// ---------- keyboard ----------
const TEXT = "input:not([type=checkbox]):not([type=range]):not([type=file]), textarea";
const piano = createPiano({ store, player, roll, typing: (e) => e.target.matches?.(`${TEXT}, select`) });
let unbind = () => {};
function bindKeys(overrides) {
  unbind();
  const keys = effectiveKeys(overrides);
  const map = {};
  // keys the user chose come last, so that they win over the default of a newer action
  for (const a of [...ACTIONS].sort((x, y) => (x.id in overrides) - (y.id in overrides))) {
    map[keys[a.id]] = (e) => {
      if (e.repeat && !a.repeat) return e.preventDefault();
      if (document.querySelector("dialog[open]")) { if (a.id === "save" || a.id === "open") e.preventDefault(); return; }
      if (a.id === "deselect" && $("#more").matches(":popover-open")) return; // Escape just closes the menu
      if (e.target.matches?.(TEXT)) {
        if (!a.typing) return;
        e.target.blur(); // commit what was typed
      }
      // a control reached with Tab keeps its own keys
      if (["Space", "Enter"].includes(e.code) && e.target.matches?.("button, a, select, input")) return;
      if (e.code.startsWith("Arrow") && e.target.matches?.("select, input")) return;
      if (roll.busy() && a.id !== "deselect") return e.preventDefault(); // no edits in the middle of a drag
      e.preventDefault();
      actions[a.id]();
    };
  }
  unbind = tinykeys(window, map, { ignore: (e) => e.isComposing });
}
bindKeys(settings.get().shortcuts);
// After a mouse click, give focus back so that Space plays instead of pressing the button again.
document.addEventListener("click", (e) => { if (e.detail > 0 && !e.target.closest("dialog")) e.target.closest("button")?.blur(); });

// ---------- buttons ----------
const on = (id, f) => $(id).addEventListener("click", guard(async () => { $("#more").hidePopover(); await f(); }));
$("#more").addEventListener("toggle", (e) => {
  if (e.newState !== "open") return;
  const b = $("#b-more").getBoundingClientRect(), box = $("#more");
  box.style.top = `${b.bottom + 4}px`;
  box.style.left = `${Math.max(4, Math.min(b.left, innerWidth - box.offsetWidth - 4))}px`;
});
on("#b-new", files.newProject);
on("#b-library", actions.open);
on("#b-import", () => $("#file").click());
on("#b-save", files.save);
on("#b-saveas", files.saveAs);
on("#b-savemelody", files.saveMelody);
on("#b-exp-project", () => files.exportProject());
on("#b-exp-midi", () => files.exportMidi());
on("#b-exp-mp3", () => files.exportAudio("mp3"));
on("#b-exp-wav", () => files.exportAudio("wav"));
on("#b-exp-melody", files.exportMelody);
on("#b-exp-text", files.exportText);
on("#b-tools", actions.tools);
on("#b-settings", actions.settings);
$("#file").addEventListener("change", guard(async (e) => {
  const f = e.target.files[0];
  e.target.value = ""; // allow choosing the same file again
  if (f) await files.importFile(f);
}));
window.addEventListener("beforeunload", (e) => { if (store.dirty()) e.preventDefault(); });

// ---------- start ----------
roll.fit();
await guard(async () => {
  const q = new URLSearchParams(location.search);
  if (!q.has("tune") && !q.has("melody")) return;
  const doc = q.has("tune") ? await api("GET", `/api/tunes/${encodeURIComponent(q.get("tune"))}/melody`) : await files.melodyById(encodeURIComponent(q.get("melody")));
  await files.openMelodyDoc(doc);
  history.replaceState(null, "", "/daw");
})();
window.tunelab = { store, roll, player, actions }; // for browser tests and the console
