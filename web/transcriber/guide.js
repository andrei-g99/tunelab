// "Guide it myself": highlight the melody in a picture of the recording. The grid of highlights is
// in highlights.js; this file draws it and handles the mouse.
import { $, api, el, guard } from "../shared/dom.js";
import * as h from "./highlights.js";

const KEYS_W = 44, RULER_H = 22, ROW_MAX = 28, PX_MAX = 400; // px per semitone, per second
const NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
const isBlack = (p) => [1, 3, 6, 8, 10].includes(p % 12);
const noteName = (p) => NAMES[p % 12] + (Math.floor(p / 12) - 1);
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const clock = (s, digits = 0) => `${Math.floor(s / 60)}:${(s % 60).toFixed(digits).padStart(digits ? 3 + digits : 2, "0")}`;
const SOURCES = { mix: "Full recording", vocals: "Vocals only", rest: "Everything but the vocals" };
const TOOLS = { melody: h.MELODY, not: h.NOT, erase: h.NONE };
const API = "/api/transcriber";

export function createGuide({ player, post, status }) {
  const panel = $("#guide"), scroller = $("#g-scroll"), spacer = $("#g-space"), canvas = $("#g-canvas");
  const c2d = canvas.getContext("2d");
  let key = "", hist = null; // highlights of the recording `key`
  let tool = "melody", only = false, px = 60, row = 8, at = 0, now = null, hover = null;
  let stroke = null; // while dragging: {grid, last, kind}
  let candidates = [], pictures = new Map(), loading = "", failed = "", warning = "", fitted = false;
  let colors = {}, maskOf = null;
  const mask = document.createElement("canvas");

  // ---------- coordinates ----------
  const grid = () => status().guide;
  const seconds = () => status().seconds;
  const top = () => grid().hi + 1; // pitch at the upper edge
  const semitones = () => grid().hi - grid().lo + 2; // half a row of room at both ends
  const X = (t) => KEYS_W + t * px - scroller.scrollLeft;
  const Y = (p) => RULER_H + (top() - p) * row - scroller.scrollTop;
  const timeAt = (x) => clamp((x - KEYS_W + scroller.scrollLeft) / px, 0, seconds());
  const pitchAt = (y) => top() - (y - RULER_H + scroller.scrollTop) / row;
  const cell = (x, y) => [Math.floor(timeAt(x) / grid().cell), Math.round((pitchAt(y) - grid().lo) * grid().per)];
  const half = () => Math.round(+$("#g-size").value * grid().per);
  const minRow = () => (scroller.clientHeight - RULER_H) / semitones();
  const minPx = () => (scroller.clientWidth - KEYS_W) / Math.max(1, seconds());

  // ---------- highlights ----------
  const columns = () => Math.ceil(seconds() / grid().cell) + 1;
  const rows = () => (grid().hi - grid().lo) * grid().per + 1;
  const marks = () => ({
    source: $("#g-source").value, only,
    melody: h.toRuns(hist.grid, h.MELODY), not_melody: h.toRuns(hist.grid, h.NOT),
  });
  function store() { // survives a visit to the DAW and a reload
    for (const k of Object.keys(sessionStorage)) if (k.startsWith("tunelab-guide-") && k !== key) sessionStorage.removeItem(k);
    try { sessionStorage.setItem(key, JSON.stringify(marks())); } catch (e) { console.warn(e); }
  }
  function restore() {
    let m = {};
    try { m = JSON.parse(sessionStorage.getItem(key)) || {}; } catch (e) { console.warn(e); }
    hist = h.history(h.fromRuns(columns(), rows(), m.melody || [], m.not_melody || []));
    only = !!m.only;
    return m.source;
  }
  function change(next) {
    if (next === hist) return;
    hist = next;
    warning = "";
    store();
    refresh();
  }

  // ---------- drawing ----------
  function rgb(name) {
    const c = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    c.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    c.fillRect(0, 0, 1, 1);
    return [...c.getImageData(0, 0, 1, 1).data.slice(0, 3)];
  }
  function readColors() {
    for (const k of ["roll", "ink", "soft", "line", "accent", "bad", "note-sel", "key-b", "key-w", "key-ink", "play", "card"]) colors[k] = rgb("--" + k);
    maskOf = null;
    for (const p of pictures.values()) p.images = {};
  }
  const css = (name, alpha = 1) => `rgba(${colors[name].join(",")},${alpha})`;

  function image(p, kind) {
    if (!p.images[kind]) {
      const { columns: w, rows: n } = p.meta, c = document.createElement("canvas"), g = c.getContext("2d");
      c.width = w;
      c.height = n;
      const out = g.createImageData(w, n), from = colors.roll, to = colors.ink;
      for (let r = 0; r < n; r++) {
        for (let x = 0; x < w; x++) {
          const v = p[kind][r * w + x] / 255, k = ((n - 1 - r) * w + x) * 4;
          for (let i = 0; i < 3; i++) out.data[k + i] = from[i] + (to[i] - from[i]) * v;
          out.data[k + 3] = 255;
        }
      }
      g.putImageData(out, 0, 0);
      p.images[kind] = c;
    }
    return p.images[kind];
  }
  function drawMask(g) {
    if (maskOf === g) return;
    maskOf = g;
    mask.width = g.columns;
    mask.height = g.rows;
    const m = mask.getContext("2d"), out = m.createImageData(g.columns, g.rows);
    for (let r = 0; r < g.rows; r++) {
      for (let c = 0; c < g.columns; c++) {
        const v = h.cellAt(g, c, r);
        if (!v) continue;
        const k = ((g.rows - 1 - r) * g.columns + c) * 4;
        out.data.set(v === h.MELODY ? colors.accent : colors.bad, k);
        out.data[k + 3] = v === h.MELODY ? 105 : (r + c) % 4 < 2 ? 150 : 45; // striped, not only another color
      }
    }
    m.putImageData(out, 0, 0);
  }
  let queued = false;
  function draw() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; if (!panel.hidden && grid()) render(); });
  }
  function render() {
    const w = scroller.clientWidth, height = scroller.clientHeight, dpr = devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${height}px`;
    }
    const g = c2d, { lo, hi, per, cell: size } = grid();
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = css("roll");
    g.fillRect(0, 0, w, height);
    const p = pictures.get($("#g-source").value);
    if (p) {
      const { meta } = p, step = 12 / 36; // three rows per semitone
      g.imageSmoothingEnabled = true;
      g.drawImage(image(p, $("#g-view").value), X(0), Y(hi + step / 2), meta.columns * meta.step * px, meta.rows * step * row);
    }
    for (let q = lo; q <= hi; q++) {
      if (q % 12) continue;
      g.fillStyle = css("soft", 0.35);
      g.fillRect(0, Y(q - 0.5), w, 1);
    }
    const shown = stroke?.grid || hist.grid;
    drawMask(shown);
    g.imageSmoothingEnabled = false;
    g.drawImage(mask, X(0), Y(hi + 0.5 / per), shown.columns * size * px, shown.rows / per * row);

    const guess = candidates[+$("#g-guess-shown").value];
    if (guess) {
      g.lineWidth = 2;
      g.strokeStyle = css("note-sel");
      g.fillStyle = css("note-sel", 0.25);
      for (const [a, b, q] of guess.notes) {
        const box = [X(a) + 1, Y(q + 0.5) + 1, Math.max(2, (b - a) * px - 2), Math.max(2, row - 2)];
        g.fillRect(...box);
        g.strokeRect(...box);
      }
    }
    if (hover) { // the brush
      const r = half() / per + 0.5 / per, cx = X((Math.floor(timeAt(hover[0]) / size) + 0.5) * size);
      const q = Math.round(pitchAt(hover[1]) * per) / per;
      g.strokeStyle = css(tool === "not" ? "bad" : tool === "erase" ? "ink" : "accent");
      g.lineWidth = 2;
      g.strokeRect(cx - Math.max(3, 1.5 * size * px), Y(q + r), Math.max(6, 3 * size * px), 2 * r * row);
    }
    const line = now ?? at;
    g.fillStyle = css("play");
    if (X(line) >= KEYS_W) g.fillRect(X(line), 0, 2, height);

    // keyboard and ruler, on top of what scrolls under them
    for (let q = lo; q <= hi; q++) {
      g.fillStyle = css(isBlack(q) ? "key-b" : "key-w");
      g.fillRect(0, Y(q + 0.5), KEYS_W, row);
      if (hover && Math.round(pitchAt(hover[1])) === q) {
        g.fillStyle = css("note-sel");
        g.fillRect(0, Y(q + 0.5), KEYS_W, row);
      }
    }
    g.font = "11px system-ui, sans-serif";
    g.textBaseline = "middle";
    for (let q = lo; q <= hi; q++) {
      if (q % 12) continue;
      g.fillStyle = css("key-ink");
      g.fillText(noteName(q), 18, Y(q));
    }
    g.fillStyle = css("card");
    g.fillRect(0, 0, w, RULER_H);
    g.fillStyle = css("line");
    g.fillRect(0, RULER_H - 1, w, 1);
    g.fillRect(KEYS_W - 1, 0, 1, height);
    const every = [1, 2, 5, 10, 20, 30].find((s) => s * px >= 55) || 60;
    for (let s = 0; s <= seconds(); s += every) {
      if (X(s) < KEYS_W - 1) continue;
      g.fillStyle = css("soft");
      g.fillRect(X(s), RULER_H - 6, 1, 6);
      g.fillText(clock(s), X(s) + 3, RULER_H / 2 - 1);
    }
    if (X(line) >= KEYS_W) {
      g.fillStyle = css("play");
      g.fillRect(X(line) - 3, RULER_H - 8, 8, 8);
    }
    g.fillStyle = css("card");
    g.fillRect(0, 0, KEYS_W - 1, RULER_H - 1);
  }
  function layout() {
    row = clamp(row, minRow(), ROW_MAX);
    px = clamp(px, Math.min(minPx(), PX_MAX), PX_MAX);
    spacer.style.width = `${KEYS_W + seconds() * px}px`;
    spacer.style.height = `${RULER_H + semitones() * row}px`;
    draw();
  }
  function zoom(factor, x = (KEYS_W + scroller.clientWidth) / 2) {
    const t = (x - KEYS_W + scroller.scrollLeft) / px;
    px *= factor;
    layout();
    scroller.scrollLeft = t * px - (x - KEYS_W);
    draw();
  }
  function zoomPitch(factor, y) {
    const p = pitchAt(y);
    row *= factor;
    layout();
    scroller.scrollTop = (top() - p) * row - (y - RULER_H);
    draw();
  }

  // ---------- picture ----------
  const load = guard(async () => {
    const source = $("#g-source").value, mine = key;
    if (pictures.has(source) || loading === source) return;
    loading = source;
    failed = "";
    refresh();
    try {
      const meta = await api("POST", `${API}/guide/picture`, { source });
      const p = { meta, images: {} };
      await Promise.all(["strength", "spectrum"].map(async (kind) => {
        const r = await fetch(`${API}/guide/${source}/${kind}`);
        if (!r.ok) throw new Error("The picture could not be loaded.");
        p[kind] = new Uint8Array(await r.arrayBuffer());
      }));
      if (key === mine) pictures.set(source, p);
    } catch (e) {
      if (key === mine) failed = e.message;
    } finally {
      if (loading === source) loading = "";
      refresh();
    }
  });

  // ---------- playback ----------
  const follow = (t) => {
    now = t;
    if (t !== null) {
      const x = X(t);
      if (x > scroller.clientWidth - 10 || x < KEYS_W) scroller.scrollLeft = t * px - 20;
    }
    draw();
  };
  const sourceUrl = () => `${API}/guide/${$("#g-source").value}/audio?of=${encodeURIComponent(key)}`;
  const playSource = guard(() => player.play($("#g-play"), { sound: sourceUrl(), from: at, onTime: follow }));
  const playHighlights = guard(async () => {
    const button = $("#g-hear");
    if (player.isPlaying(button)) return player.stop();
    button.disabled = true; // until the sound is there
    try {
      const r = await fetch(`${API}/guide/listen`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(marks()) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "That did not work.");
      const sound = await r.arrayBuffer();
      button.disabled = false;
      await player.play(button, { sound, from: at, onTime: follow });
    } finally { refresh(); }
  });
  function seek(t) {
    at = t;
    const button = ["#g-play", "#g-hear"].map((s) => $(s)).find((b) => player.isPlaying(b));
    if (button) {
      player.stop();
      (button.id === "g-play" ? playSource : playHighlights)();
    }
    draw();
  }

  // ---------- mouse ----------
  const place = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button || !hist) return;
    const [x, y] = place(e);
    if (y < RULER_H) {
      if (x >= KEYS_W) seek(timeAt(x));
    } else if (x < KEYS_W) {
      player.note(clamp(Math.round(pitchAt(y)), grid().lo, grid().hi));
    } else {
      canvas.setPointerCapture(e.pointerId);
      const c = cell(x, y);
      stroke = { grid: h.paint(hist.grid, c, c, half(), TOOLS[tool]), last: c };
      draw();
    }
  });
  canvas.addEventListener("pointermove", (e) => {
    const [x, y] = place(e);
    hover = x >= KEYS_W && y >= RULER_H ? [x, y] : null;
    if (stroke) {
      const c = cell(x, y);
      stroke = { grid: h.paint(stroke.grid, stroke.last, c, half(), TOOLS[tool]), last: c };
    }
    $("#g-where").textContent = hover ? `${noteName(clamp(Math.round(pitchAt(y)), grid().lo, grid().hi))}, ${clock(timeAt(x), 1)}` : "";
    draw();
  });
  const finish = (keep) => {
    if (!stroke) return;
    const g = stroke.grid;
    stroke = null;
    if (keep) change(h.commit(hist, g));
    draw();
  };
  canvas.addEventListener("pointerup", () => finish(true));
  canvas.addEventListener("pointercancel", () => finish(false));
  canvas.addEventListener("pointerleave", () => { hover = null; $("#g-where").textContent = ""; draw(); });
  scroller.addEventListener("scroll", draw);
  scroller.addEventListener("wheel", (e) => {
    if (!e.ctrlKey && !e.altKey) return;
    e.preventDefault();
    const [x, y] = place(e), f = Math.exp(-e.deltaY * 0.002);
    if (e.ctrlKey) zoom(f, x); else zoomPitch(f, y);
  }, { passive: false });
  new ResizeObserver(() => { if (!panel.hidden && grid()) layout(); }).observe(scroller);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { readColors(); draw(); });
  readColors();

  // ---------- buttons and keys ----------
  const setTool = (name) => { tool = name; refresh(); };
  const doUndo = () => { if (!stroke) change(h.undo(hist)); };
  const doRedo = () => { if (!stroke) change(h.redo(hist)); };
  for (const b of panel.querySelectorAll("[data-tool]")) b.onclick = () => setTool(b.dataset.tool);
  $("#g-undo").onclick = doUndo;
  $("#g-redo").onclick = doRedo;
  $("#g-clear").onclick = () => {
    const g = hist.grid;
    if (!h.isEmpty(g, h.MELODY) || !h.isEmpty(g, h.NOT)) change(h.commit(hist, h.emptyGrid(g.columns, g.rows)));
  };
  $("#g-out").onclick = () => zoom(1 / 1.4);
  $("#g-in").onclick = () => zoom(1.4);
  $("#g-fit").onclick = () => { px = row = 0; layout(); };
  $("#g-size").oninput = () => { $("#g-size-text").textContent = `±${$("#g-size").value}`; draw(); };
  $("#g-view").onchange = $("#g-guess-shown").onchange = draw;
  $("#g-source").onchange = () => { player.stop(); store(); load(); refresh(); };
  $("#g-only").onchange = () => { only = $("#g-only").checked; store(); refresh(); };
  $("#g-play").onclick = playSource;
  $("#g-hear").onclick = playHighlights;
  $("#g-guess").onclick = guard(() => post("/guide/guess", marks()));
  // after a mouse click, Space should play rather than press the button again
  panel.addEventListener("click", (e) => { if (e.detail && e.target.closest("button, input[type=checkbox]")) document.activeElement.blur(); });
  document.addEventListener("keydown", (e) => {
    if (panel.hidden || !hist || document.querySelector("dialog[open]")) return;
    const k = e.key.toLowerCase(), box = e.target;
    if (k === "escape" && stroke) return finish(false);
    if (box.matches("select, textarea, input:not([type=range]):not([type=checkbox])")) return;
    if (e.ctrlKey || e.metaKey) {
      const f = k === "z" ? (e.shiftKey ? doRedo : doUndo) : k === "y" ? doRedo : null;
      if (f) { e.preventDefault(); f(); }
      return;
    }
    if (e.altKey) return;
    if (k === " " && !box.matches("button, input")) { e.preventDefault(); if (!e.repeat) playSource(); }
    if (k === "b") setTool("melody");
    if (k === "n") setTool("not");
    if (k === "e") setTool("erase");
  });

  function refresh() {
    if (!grid() || !hist) return;
    for (const b of panel.querySelectorAll("[data-tool]")) b.setAttribute("aria-pressed", b.dataset.tool === tool);
    const g = hist.grid, some = !h.isEmpty(g, h.MELODY), ready = status().state === "ready", s = status();
    $("#g-undo").disabled = !hist.past.length;
    $("#g-redo").disabled = !hist.future.length;
    $("#g-clear").disabled = !some && h.isEmpty(g, h.NOT);
    $("#g-hear").disabled = !some && !player.isPlaying($("#g-hear"));
    $("#g-guess").disabled = !ready || (only ? !some : $("#g-clear").disabled);
    $("#g-only").checked = only;
    const text = s.error || failed || (loading ? "Drawing the picture…" : s.state === "analysing" ? `${s.step}…`
      : warning ? warning : only ? "Paint over the whole melody: where nothing is painted there will be silence."
        : "Paint over the melody where the guess is wrong. Elsewhere the search works as usual.");
    if ($("#g-message").textContent !== text) $("#g-message").textContent = text;
    $("#g-message").classList.toggle("bad", !!(s.error || failed) || text === warning);
    draw();
  }

  return {
    /** Called with every new status. */
    update() {
      const s = status(), next = s.guide ? `tunelab-guide-${s.session}-${s.take}` : "";
      if (next !== key) {
        key = next;
        player.forget();
        stroke = null;
        hist = null;
        at = 0;
        now = null;
        fitted = false;
        failed = "";
        pictures = new Map();
        if (!key) panel.hidden = true;
        else {
          const source = restore();
          $("#g-source").replaceChildren(...s.guide.sources.map((x) => el("option", { value: x }, SOURCES[x])));
          $("#g-source").value = s.guide.sources.includes(source) ? source : s.guide.source;
        }
      }
      refresh();
    },
    /** The candidates on the page changed; show one of them. */
    setCandidates(list, index) {
      candidates = list;
      warning = list.at(-1)?.warning || "";
      $("#g-guess-shown").replaceChildren(el("option", { value: "-1" }, "No guess"),
        ...list.map((c, i) => el("option", { value: i }, c.name)));
      $("#g-guess-shown").value = String(list.length ? index : -1);
      refresh();
    },
    toggle() {
      panel.hidden = !panel.hidden;
      if (panel.hidden) return player.stop();
      if (!fitted) { px = Math.max(60, minPx()); row = 0; fitted = true; }
      layout();
      refresh();
      load();
    },
    get open() { return !panel.hidden; },
  };
}
