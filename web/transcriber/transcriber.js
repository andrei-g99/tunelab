// The Melody Transcriber page: record a browser, compare the guessed melodies, send one to the DAW.
import { $, api, askText, el, guard, toast } from "../shared/dom.js";
import { createGuide } from "./guide.js";
import { createPlayer } from "./player.js";

const API = "/api/transcriber";
const PPQ = 480;
let status = null; // the last one received
let shownTake = -1, shownResult = 0;

const player = createPlayer({ volume: () => +$("#vol").value, allowed: () => status.state !== "recording" });
$("#vol").oninput = () => player.setVolume(+$("#vol").value);
const recordingUrl = () => `${API}/audio?of=${status.session}-${status.take}`; // a new url for each recording

// ---------- guesses ----------
function svg(tag, attrs) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}
function roll(doc) {
  const bar = PPQ * 4 * doc.meter[0] / doc.meter[1];
  const end = Math.max(...doc.notes.map((n) => n.start + n.dur)), length = Math.ceil(end / bar) * bar;
  let lo = Math.min(...doc.notes.map((n) => n.pitch)) - 1, hi = Math.max(...doc.notes.map((n) => n.pitch)) + 1;
  while (hi - lo < 14) { hi++; lo--; }
  const height = hi - lo + 1;
  const s = svg("svg", { class: "roll", viewBox: `0 0 ${length} ${height}`, preserveAspectRatio: "none", role: "img", "aria-label": `Piano roll, ${doc.notes.length} notes` });
  for (let x = bar; x < length; x += bar) s.append(svg("line", { class: "bar", x1: x, x2: x, y1: 0, y2: height }));
  for (const n of doc.notes) s.append(svg("rect", { class: "n", x: n.start, width: Math.max(1, n.dur - 24), y: hi - n.pitch, height: 0.9 }));
  const head = svg("line", { class: "head", x1: 0, x2: 0, y1: 0, y2: height, visibility: "hidden" });
  s.append(head);
  return [s, head];
}
const NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
const MODES = { maj: "major", min: "minor", hmin: "harmonic minor" };

function guessCard(c, title) {
  const doc = c.melody, perTick = 60 / doc.bpm / PPQ;
  const [picture, head] = roll(doc);
  const alone = el("button", { class: "primary" }, "Play guess");
  const moveHead = (t) => {
    head.setAttribute("visibility", t === null ? "hidden" : "visible");
    for (const x of ["x1", "x2"]) head.setAttribute(x, (t ?? 0) / perTick);
  };
  alone.onclick = guard(() => player.play(alone, {
    notes: doc.notes.map((n) => [n.start * perTick, (n.start + n.dur) * perTick, n.pitch]),
    onTime: moveHead,
  }));
  const both = el("button", { title: "The guess as performed, on top of the recording" }, "Play with original");
  both.onclick = guard(() => player.play(both, { notes: c.notes, sound: recordingUrl() }));

  let saved = null; // library id, so that Save and then Open does not store it twice
  const save = async (name) => {
    if (!saved) saved = (await api("POST", "/api/library/melodies", { doc: { ...doc, name } })).id;
    return saved;
  };
  const saveButton = el("button", {}, "Save to library");
  saveButton.onclick = guard(async () => {
    const name = await askText("Melody name", c.name);
    if (!name) return;
    await save(name);
    saveButton.disabled = true;
    toast(`Saved "${name}".`);
  });
  const open = el("button", { title: "Saves it to the library, then opens it" }, "Open in DAW");
  open.onclick = guard(async () => {
    const name = saved ? null : await askText("Melody name", c.name);
    if (!saved && !name) return;
    location.href = `/daw?melody=${encodeURIComponent(await save(name))}`;
  });
  return el("article", { class: "guess" },
    el("div", { class: "row" }, el("h2", {}, title),
      el("span", { class: "meta" }, `${doc.notes.length} notes, ${NAMES[doc.key.tonic]} ${MODES[doc.key.mode]}, ${doc.bpm} bpm, ${doc.meter.join("/")}`)),
    el("div", { class: "row" }, alone, both, saveButton, open),
    c.warning ? el("p", { class: "meta bad" }, c.warning) : null, picture);
}
let cards = new Map(); // by content: a card that stays keeps its state when another one is added
async function showResult() {
  const r = await api("GET", API + "/result");
  const old = cards;
  cards = new Map();
  const all = r.candidates.map((c, i) => {
    const key = JSON.stringify(c), card = old.get(key) || guessCard(c, c.guided ? c.name : `${i + 1}. ${c.name}`);
    cards.set(key, card);
    return card;
  });
  const guided = all.filter((_, i) => r.candidates[i].guided);
  $("#results").replaceChildren(...guided.reverse(), ...(r.warning ? [el("p", { class: "meta" }, r.warning)] : []),
    ...all.filter((_, i) => !r.candidates[i].guided));
  guide.setCandidates(r.candidates, guided.length ? r.candidates.length - 1 : 0);
}

// ---------- recording ----------
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

const loadStreams = guard(async () => {
  const list = await api("GET", API + "/streams"), box = $("#stream"), before = box.value;
  box.replaceChildren(...list.map((s) => el("option", { value: s.id }, [s.app, s.title, s.playing ? "" : "(paused)"].filter(Boolean).join(" · "))));
  if (!list.length) box.append(el("option", { value: "" }, "No browser is playing sound"));
  if (list.some((s) => String(s.id) === before)) box.value = before;
  draw();
});
const loadKept = guard(async () => {
  const ids = await api("GET", API + "/recordings");
  $("#kept").replaceChildren(...ids.map((id) => el("option", { value: id }, id)));
  if (!ids.length) $("#kept").append(el("option", { value: "" }, "No kept recordings"));
  draw();
});

function message() {
  const s = status;
  if (s.error) return [s.error, true];
  if (s.state === "recording") return [s.waiting ? "Nothing is playing; waiting for it to continue…" : `Recording. Stops by itself at ${clock(s.max_seconds)}.`];
  if (s.state === "analysing") return [s.guide ? `${s.step}…` : `${s.step}… The first time, models are downloaded, which takes a few minutes.`];
  if (s.notice) return [s.notice];
  if (s.state === "ready") return [s.kept ? `Kept as "${s.kept}".` : "This recording is temporary. Keep it if you want it later."];
  return ["Start the music in your browser, refresh the list, then record 10 to 60 seconds."];
}
function draw() {
  if (!status) return;
  const s = status, busy = s.state === "recording" || s.state === "analysing";
  const [text, bad] = message();
  if ($("#message").textContent !== text) $("#message").textContent = text;
  $("#message").classList.toggle("bad", !!bad);
  const b = $("#record");
  b.textContent = s.state === "recording" ? "Stop" : s.state === "analysing" ? "Cancel" : "Record";
  b.classList.toggle("recording", s.state === "recording");
  b.disabled = !busy && !$("#stream").value;
  $("#time").textContent = clock(s.seconds);
  $("#meter span").style.width = `${Math.round(s.level * 100)}%`;
  $("#meter").setAttribute("aria-valuenow", Math.round(s.level * 100));
  $("#stream").disabled = $("#refresh").disabled = busy;
  $("#original").disabled = s.state === "idle" || s.state === "recording";
  $("#again").disabled = s.state !== "ready";
  $("#keep").disabled = !["ready", "analysing"].includes(s.state) || !!s.kept;
  $("#open").disabled = busy || !$("#kept").value;
  $("#guide-toggle").disabled = !s.guide;
  guide.update();
  $("#guide-toggle").setAttribute("aria-pressed", guide.open);
}
async function apply(next) {
  const before = status;
  status = next;
  if (status.take !== shownTake || status.state === "recording" || (shownResult && !status.result)) {
    if (shownResult || status.state === "recording") { player.stop(); $("#results").replaceChildren(); }
    cards = new Map();
    guide.setCandidates([], 0);
    shownTake = status.take;
    shownResult = 0;
  }
  draw();
  if (status.result && shownResult !== status.result) {
    shownResult = status.result;
    await showResult();
  }
  // a new recording is analysed right away, also when it stopped at the length limit
  if (before?.state === "recording" && status.state === "ready") await post("/analyse");
}
async function post(path, body) { await apply(await api("POST", API + path, body)); }
const guide = createGuide({ player, post, status: () => status });
$("#guide-toggle").onclick = () => { guide.toggle(); draw(); };

$("#record").onclick = guard(async () => {
  if (status.state === "recording") return post("/stop");
  if (status.state === "analysing") return post("/cancel");
  player.stop();
  await post("/record", { stream: +$("#stream").value });
});
$("#refresh").onclick = loadStreams;
$("#original").onclick = guard(() => player.play($("#original"), { sound: recordingUrl() }));
$("#again").onclick = guard(() => post("/analyse"));
$("#keep").onclick = guard(async () => {
  const name = await askText("Recording name", "recording");
  if (!name) return;
  await post("/keep", { name });
  await loadKept();
});
$("#open").onclick = guard(async () => {
  player.stop();
  await post(`/recordings/${encodeURIComponent($("#kept").value)}/open`);
  await post("/analyse");
});

async function poll() {
  try {
    const seen = status, next = await api("GET", API + "/status");
    if (status === seen) await apply(next); // else a click was answered meanwhile: this is out of date
  } catch (e) { console.warn(e); }
  const busy = status && (status.state === "recording" || status.state === "analysing");
  setTimeout(poll, busy ? 120 : 1000);
}
await Promise.all([loadStreams(), loadKept()]);
poll();
