// The Tools dialog: tempo repair, note clean-up, scoring. Every action is one undo step.
import * as m from "./model.js";
import * as t from "./tempo.js";
import { api, el, guard, toast } from "../shared/dom.js";

export function createTools({ store }) {
  const s = store.state, body = el("div");
  const dialog = el("dialog", { class: "wide" },
    el("div", { class: "head" }, el("h2", {}, "Tools"), el("button", { onclick: () => dialog.close() }, "Close")), body);
  document.body.append(dialog);

  /** Selected notes, or the whole track when nothing is selected. */
  const target = () => (s.selection.size ? s.selection : new Set(store.track().notes.map((n) => n.id)));
  function change(project, done) {
    if (!project) return toast("That would make the project too long, or the tempo is outside 20 to 400.", true);
    if (project === s.project) return toast("Nothing to change.");
    store.commit(project);
    toast(done);
    draw();
  }
  function notes(f, done) {
    const before = store.track().notes, after = f(before, target());
    if (after.length === before.length && after.every((n, i) => n.start === before[i].start && n.dur === before[i].dur)) return toast("Nothing to change.");
    store.commitNotes(after);
    toast(done);
    draw();
  }
  const button = (label, onclick) => el("button", { onclick }, label);
  const section = (title, text, ...kids) => el("fieldset", {}, el("legend", {}, title), el("p", {}, text), ...kids);

  function tempoSection() {
    const bpm = el("input", { class: "short", value: s.project.bpm, "aria-label": "New tempo", inputmode: "decimal" });
    let taps = [];
    const tap = button("Tap", () => {
      const now = performance.now();
      if (taps.length && now - taps.at(-1) > 2500) taps = [];
      taps.push(now);
      const v = t.tapTempo(taps.slice(-9));
      tap.textContent = v ? `Tap (${v})` : `Tap (${taps.length})`;
      if (v) bpm.value = v;
    });
    const value = () => Math.round(Number(bpm.value) * 100) / 100;
    const found = t.suggestTempos(s.project);
    return section("Tempo", "Wrong detected tempo (bars and notes don't line up)? Change the tempo and keep the sound: notes move on the grid but play exactly as before.",
      el("div", { class: "row" }, el("label", {}, "BPM ", bpm), tap,
        button("Change, keep the sound", () => change(t.retempo(s.project, value()), "Tempo changed; it sounds the same.")),
        button("Change speed", () => change(t.validBpm(value()) ? { ...s.project, bpm: value() } : null, "Tempo changed."))),
      el("div", { class: "row", style: "margin-top:8px" },
        ...(found.length ? [el("span", { class: "soft" }, "Best grid fits (keep the sound):"), ...found.map((c) =>
          button(`${c.bpm} BPM, ${Math.round(c.fit * 100)}%`, () => change(t.retempo(s.project, c.bpm), "Tempo changed; it sounds the same.")))]
          : [el("span", { class: "soft" }, "Add at least 6 notes to get tempo suggestions.")])),
      el("div", { class: "row", style: "margin-top:8px" },
        button("Notes twice as long", () => change(t.stretchProject(s.project, 2), "Doubled all note times.")),
        button("Notes half as long", () => change(t.stretchProject(s.project, 0.5), "Halved all note times.")),
        button("Move first note to bar 1", () => change(t.alignToBar(s.project), "Moved the first note to bar 1."))));
  }
  function cleanupSection() {
    const grid = el("select", { "aria-label": "Grid" }, ...[[480, "1/4"], [240, "1/8"], [120, "1/16"], [60, "1/32"], [160, "1/8 triplet"], [80, "1/16 triplet"]].map(([v, l]) => el("option", { value: v }, l)));
    grid.value = [480, 240, 120, 60, 160, 80].includes(s.snap) ? s.snap : 120;
    const strength = el("select", { "aria-label": "Strength" }, ...[100, 75, 50, 25].map((v) => el("option", { value: v / 100 }, `${v}%`)));
    const ends = el("input", { type: "checkbox" });
    return section("Timing of notes", s.selection.size ? `Applies to the ${s.selection.size} selected notes.` : `Applies to all ${store.track().notes.length} notes of "${store.track().name}". Select notes first to limit it.`,
      el("div", { class: "row" }, el("label", {}, "Grid ", grid), el("label", {}, "Strength ", strength), el("label", {}, ends, " lengths too"),
        button("Snap to grid", () => notes((n, ids) => m.quantizeNotes(n, ids, +grid.value, { ends: ends.checked, strength: +strength.value }), "Snapped to the grid."))),
      el("div", { class: "row", style: "margin-top:8px" },
        button("Close small gaps", () => notes((n, ids) => m.closeGaps(n, ids, +grid.value), "Closed gaps up to one grid step.")),
        button("Remove overlaps", () => notes(m.removeOverlaps, "Made the notes one at a time."))));
  }
  function scoreSection() {
    const out = el("div");
    return section("Score", "Rate the current track with the Tune Generator's rules.",
      button("Score this track", guard(async () => {
        const r = await api("POST", "/api/melody/score", m.melodyToDoc(s.project, store.track()));
        out.replaceChildren(
          el("p", {}, r.score === null ? "Too short to score: needs at least 4 notes." : `Score ${r.score.toFixed(3)}. ` + Object.entries(r.parts).map(([k, v]) => `${k.replace("_", " ")} ${v.toFixed(2)}`).join(", ")),
          el("p", {}, r.rounded ? "Some timing was rounded to 1/12 beat for scoring." : ""));
      })), out);
  }
  const draw = () => body.replaceChildren(tempoSection(), cleanupSection(), scoreSection());
  return { open() { draw(); dialog.showModal(); } };
}
