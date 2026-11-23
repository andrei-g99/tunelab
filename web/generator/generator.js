// The Tune Generator page: generate batches, review flagged tunes, score typed melodies.
import { $, api as request, el as make, guard } from "../shared/dom.js";

const TICKS = 12;
const state = { show: "flagged", batch: "" };

// ---------- playback ----------
let ctx = null, current = null;
const spt = (t) => 60 / t.bpm / TICKS;

function voice(out, midi, at, secs, gain, type) {
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = type;
  o.frequency.value = 440 * 2 ** ((midi - 69) / 12);
  const end = at + secs;
  const atk = Math.min(0.012, secs / 4), rel = Math.min(0.06, secs / 3);
  g.gain.setValueAtTime(0, at);
  g.gain.linearRampToValueAtTime(gain, at + atk);
  g.gain.linearRampToValueAtTime(gain * 0.55, end - rel);
  g.gain.linearRampToValueAtTime(0, end);
  o.connect(g).connect(out);
  o.start(at);
  o.stop(end + 0.01);
}

function stop() {
  if (!current) return;
  cancelAnimationFrame(current.raf);
  current.master.gain.cancelScheduledValues(ctx.currentTime);
  current.master.gain.setTargetAtTime(0, ctx.currentTime, 0.01);
  const m = current.master;
  setTimeout(() => m.disconnect(), 120);
  current.btn.textContent = "Play";
  current.head.setAttribute("visibility", "hidden");
  current = null;
  $("#stop").disabled = true;
}

async function play(tune, btn, head) {
  const again = current && current.btn === btn;
  stop();
  if (again) return;
  ctx = ctx || new AudioContext();
  await ctx.resume();
  if (current) return; // another Play won while resuming
  const master = ctx.createGain(), soft = ctx.createBiquadFilter();
  soft.type = "lowpass"; soft.frequency.value = 5000;
  master.gain.value = +$("#vol").value;
  master.connect(soft).connect(ctx.destination);
  const t0 = ctx.currentTime + 0.08, k = spt(tune);
  const type = $("#wave").value;
  const loud = type === "square" || type === "sawtooth" ? 0.18 : 0.4;
  for (const [p, s, d] of tune.notes) voice(master, p, t0 + s * k, d * k * 0.96, loud, type);
  if ($("#chords").checked) tune.chords.forEach(([s, , pcs], i) => {
    const e = i + 1 < tune.chords.length ? tune.chords[i + 1][0] : tune.length;
    if (e > s) for (const pc of pcs) voice(master, 48 + pc, t0 + s * k, (e - s) * k * 0.96, 0.07, "sine");
  });
  current = { btn, head, master, raf: 0 };
  btn.textContent = "Stop";
  $("#stop").disabled = false;
  const tick = () => {
    if (!current || current.btn !== btn) return;
    const x = (ctx.currentTime - t0) / k;
    if (x > tune.length) return stop();
    head.setAttribute("visibility", x >= 0 ? "visible" : "hidden");
    head.setAttribute("x1", x); head.setAttribute("x2", x);
    current.raf = requestAnimationFrame(tick);
  };
  tick();
}
$("#stop").onclick = stop;
$("#vol").oninput = () => { if (current) current.master.gain.value = +$("#vol").value; };

// ---------- drawing ----------
const el = (tag, cls, text) => make(tag, { class: cls || undefined }, text);
function svg(tag, attrs) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}
function roll(t) {
  const ps = t.notes.map((n) => n[0]);
  let lo = Math.min(...ps) - 1, hi = Math.max(...ps) + 1;
  while (hi - lo < 14) { hi++; lo--; }
  const s = svg("svg", { class: "roll", viewBox: `0 0 ${t.length} ${hi - lo + 1}`, preserveAspectRatio: "none", role: "img" });
  s.setAttribute("aria-label", `Piano roll, ${t.notes.length} notes`);
  for (let x = t.pickup; x < t.length; x += t.bar) if (x) s.append(svg("line", { class: "bar", x1: x, x2: x, y1: 0, y2: hi - lo + 1 }));
  for (const [p, at, d] of t.notes) s.append(svg("rect", { class: "n", x: at, width: Math.max(1, d - 0.8), y: hi - p, height: 0.9 }));
  const head = svg("line", { class: "head", x1: 0, x2: 0, y1: 0, y2: hi - lo + 1, visibility: "hidden" });
  s.append(head);
  return [s, head];
}
/** Saves the tune to the library as a favorite melody; clicking again removes the favorite. */
function starButton(r) {
  const saved = () => melodies.find((x) => x.source === `tune:${r.id}`);
  const b = make("button", { class: "star", title: "Favorite (saves to the library)", "aria-label": "Favorite" });
  const draw = () => {
    const on = !!saved()?.favorite;
    b.textContent = on ? "★" : "☆";
    b.setAttribute("aria-pressed", on);
  };
  b.onclick = guard(async () => {
    b.disabled = true;
    try {
      const want = !saved()?.favorite;
      await loadMelodies();
      let id = saved()?.id;
      if (!id) id = (await request("POST", "/api/library/melodies", { doc: await request("GET", `/api/tunes/${r.id}/melody`) })).id;
      await request("PUT", `/api/library/melodies/${id}/favorite`, { favorite: want });
      await loadMelodies();
    } finally { b.disabled = false; draw(); }
  });
  draw();
  return b;
}
function card(r) {
  const c = el("article", "tune"), top = el("div", "cardhead");
  const btn = el("button", "play", "Play");
  const [pic, head] = roll(r.tune);
  btn.onclick = () => play(r.tune, btn, head);
  top.append(btn, el("span", "score", r.score.toFixed(3)));
  if (r.flag) top.append(el("span", "tag " + r.flag, r.flag === "top" ? "flagged" : "wildcard"));
  if (r.name) top.append(el("span", "meta", r.name));
  top.append(el("span", "meta", r.notation.split("\n")[0]));
  if (r.id) top.append(el("span", "meta", "#" + r.id), starButton(r), make("a", { class: "open", href: `/daw?tune=${r.id}` }, "Open in DAW"));
  const parts = el("div", "parts");
  for (const [k, v] of Object.entries(r.parts)) parts.append(el("span", v < 0.7 ? "low" : "", `${k.replace("_", " ")} ${v.toFixed(2)}`));
  const d = el("details"); d.append(el("summary", "", "Notation"), el("pre", "", r.notation));
  c.append(top, pic, parts, d);
  return c;
}

// ---------- data ----------
const api = (path, body) => request(body ? "POST" : "GET", path, body);
function say(id, text, bad) { const m = $(id); m.textContent = text; m.classList.toggle("bad", !!bad); }

let melodies = []; // library melodies, to know which tunes are already favorites
async function loadMelodies() { melodies = (await api("/api/library")).melodies; }

let loads = 0;
async function load() {
  const mine = ++loads;
  const q = new URLSearchParams({ show: state.show });
  if ($("#latest").checked && state.batch && state.show !== "imported") q.set("batch", state.batch);
  const box = $("#tunes");
  try {
    const [rows] = await Promise.all([api("/api/tunes?" + q), loadMelodies()]);
    if (mine !== loads) return;
    if (current && box.contains(current.btn)) stop();
    const empty = { flagged: "Nothing flagged yet. Generate a batch, or raise the top %.", all: "Nothing generated yet.", imported: "Nothing here yet. Save a typed melody, or run tunelab-extract with --save." };
    box.replaceChildren(...(rows.length ? rows.map(card) : [el("p", "empty", empty[state.show])]));
  } catch (e) {
    if (mine === loads) box.replaceChildren(el("p", "empty", "Could not load tunes: " + e.message));
  }
}
function setTab(show) {
  state.show = show;
  document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.show === show));
}
document.querySelectorAll("#tabs button").forEach((b) => b.onclick = () => { setTab(b.dataset.show); load(); });
$("#latest").onchange = load;

$("#gen").onsubmit = async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target), b = ev.target.querySelector("button");
  b.disabled = true; say("#gen-msg", "Generating…");
  try {
    const r = await api("/api/generate", { count: +f.get("count"), mode: f.get("mode"), meter: f.get("meter"), bars: +f.get("bars"), top_percent: +f.get("top_percent") });
    state.batch = r.batch;
    const dup = r.above - r.flagged;
    say("#gen-msg", `${r.generated} generated, ${r.flagged} flagged` + (r.wildcards ? ` plus ${r.wildcards} wildcard${r.wildcards > 1 ? "s" : ""}` : "") +
      (dup ? `, ${dup} skipped as near-duplicates` : "") + `. Flag line ${r.threshold.toFixed(3)}, best ${r.best.toFixed(3)}, median ${r.median.toFixed(3)}.`);
    setTab("flagged");
    await load();
  } catch (e) { say("#gen-msg", e.message, true); }
  b.disabled = false;
};
$("#typed").onsubmit = async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target), save = ev.submitter?.value === "save";
  try {
    const r = await api("/api/score", { notation: f.get("notation"), name: f.get("name"), save });
    if (current && $("#preview").contains(current.btn)) stop();
    say("#typed-msg", save ? "Saved under Imported." : "");
    $("#preview").replaceChildren(card(r));
    if (save && state.show === "imported") load();
  } catch (e) { say("#typed-msg", e.message, true); }
};
load();
