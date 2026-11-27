// The piano roll. Konva draws it and provides hit testing, the group-resize handles
// (Konva.Transformer) and rectangle intersection. Musical math lives in model.js.
/* global Konva */
import * as m from "./model.js";

const KEYS_W = 58, RULER_H = 24, PAD = 14, // PAD: room left of time 0 for the resize handle
  DRAG_PX = 4, HANDLE_W = 7,
  LIT_MS = 150; // a pressed key stays lit this long after release, so quick taps are visible
const PX_MIN = 8, PX_MAX = 600, ROW_MIN = 6, ROW_MAX = 36; // px per beat, px per semitone
const isBlack = (p) => [1, 3, 6, 8, 10].includes(p % 12);

export function createRoll({ scroller, store, settings, onPreview, onSeek }) {
  const s = store.state;
  const view = { px: 80, row: 16, playhead: 0 };
  const size = document.createElement("div");
  const holder = document.createElement("div");
  size.className = "roll-size";
  holder.className = "roll-holder";
  size.append(holder);
  scroller.append(size);

  const stage = new Konva.Stage({ container: holder, width: 100, height: 100 });
  const bg = new Konva.Layer({ listening: false });
  const noteLayer = new Konva.Layer();
  const over = new Konva.Layer();
  const frame = new Konva.Layer({ listening: false });
  stage.add(bg, noteLayer, over, frame);
  const ghosts = new Konva.Group({ listening: false });
  const noteGroup = new Konva.Group();
  noteLayer.add(ghosts, noteGroup);

  // ---------- coordinates ----------
  const ppt = () => view.px / m.PPQ;
  const ox = () => KEYS_W + PAD - scroller.scrollLeft; // screen x of tick 0
  const oy = () => RULER_H - scroller.scrollTop; // screen y of pitch 127's top
  const tickAt = (x) => (x - ox()) / ppt();
  const pitchAt = (y) => m.clamp(127 - Math.floor((y - oy()) / view.row), 0, 127);
  const noteX = (n) => n.start * ppt();
  const noteY = (n) => (127 - n.pitch) * view.row;
  const free = (e) => e && (e.altKey || e.ctrlKey || e.metaKey); // modifier that turns the grid off
  const snapTo = (t, e) => (s.snap <= 1 || free(e) ? Math.round(t) : Math.round(t / s.snap) * s.snap);
  const contentTicks = () => Math.max(m.projectEnd(s.project), view.playhead) + 8 * m.barTicks(s.project.meter);

  let colors = {};
  function readColors() {
    const css = getComputedStyle(document.documentElement);
    for (const k of ["roll", "roll-dark", "roll-out", "roll-line", "roll-beat", "roll-bar", "note", "note-sel", "ghost", "key-b", "key-w", "key-ink", "play", "card", "ink", "soft", "line", "accent"]) {
      colors[k] = css.getPropertyValue("--" + k).trim();
    }
  }
  readColors();

  // ---------- lit key: the pitch being pressed with the mouse ----------
  let lit = null, litTimer = 0;
  let held = new Set(); // pitches played with the computer keyboard
  const isLit = (p) => p === lit || held.has(p);
  function light(pitch) {
    clearTimeout(litTimer);
    if (pitch === lit) return;
    lit = pitch;
    bg.batchDraw();
    frame.batchDraw();
  }
  const unlight = () => { clearTimeout(litTimer); litTimer = setTimeout(() => light(null), LIT_MS); };
  /** Sound a pitch and light its key. Call before any other work, so the sound is not delayed. */
  function press(pitch, vel, secs) {
    onPreview(pitch, vel, secs);
    light(pitch);
  }

  // ---------- static drawing (visible area only) ----------
  function eachLine(f) {
    const bar = m.barTicks(s.project.meter), beat = (m.PPQ * 4) / s.project.meter[1];
    const step = s.snap > 1 && s.snap * ppt() >= 7 ? s.snap : beat * ppt() >= 7 ? beat : bar;
    const first = Math.max(0, tickAt(KEYS_W)), last = tickAt(stage.width());
    const mult = Math.max(1, Math.ceil(7 / (step * ppt()))); // very zoomed out: skip bars
    const inc = step * mult;
    for (let i = Math.floor(first / inc); i * inc <= last; i++) {
      const t = i * inc;
      f(Math.round(ox() + t * ppt()) + 0.5, t % bar === 0 ? "roll-bar" : t % beat === 0 ? "roll-beat" : "roll-line");
    }
    // bars and beats that do not fall on the chosen grid (e.g. triplets) still get drawn
    if (inc < bar && bar % inc) for (let i = Math.floor(first / bar); i * bar <= last; i++) f(Math.round(ox() + i * bar * ppt()) + 0.5, "roll-bar");
  }
  bg.add(new Konva.Shape({
    sceneFunc(ctx) {
      const W = stage.width(), H = stage.height();
      for (let p = pitchAt(RULER_H); p >= pitchAt(H); p--) {
        const y = oy() + (127 - p) * view.row;
        const out = settings().highlightScale && !m.inScale(p, s.project.key);
        ctx.fillStyle = colors[out ? "roll-out" : isBlack(p) ? "roll-dark" : "roll"];
        ctx.fillRect(KEYS_W, y, W, view.row);
        ctx.fillStyle = colors[p % 12 === 0 ? "roll-bar" : "roll-line"];
        ctx.fillRect(KEYS_W, y + view.row - 1, W, 1);
        if (isLit(p)) { ctx.fillStyle = colors["note-sel"] + "33"; ctx.fillRect(KEYS_W, y, W, view.row); }
      }
      eachLine((x, c) => { ctx.fillStyle = colors[c]; ctx.fillRect(x, RULER_H, 1, H); });
    },
  }));
  frame.add(new Konva.Shape({
    sceneFunc(ctx) {
      const W = stage.width(), H = stage.height();
      // keyboard
      ctx.font = "11px system-ui, sans-serif";
      ctx.textBaseline = "middle";
      for (let p = pitchAt(RULER_H); p >= pitchAt(H); p--) {
        const y = oy() + (127 - p) * view.row;
        ctx.fillStyle = colors[isLit(p) ? "note-sel" : isBlack(p) ? "key-b" : "key-w"];
        ctx.fillRect(0, y, KEYS_W - 1, view.row);
        ctx.fillStyle = colors["roll-bar"];
        ctx.fillRect(0, y + view.row - 0.5, KEYS_W - 1, 0.5);
        if (p % 12 === 0 || (view.row >= 14 && !isBlack(p))) {
          ctx.fillStyle = colors[isLit(p) ? "card" : "key-ink"];
          ctx.fillText(m.pitchName(p), 30, y + view.row / 2 + 0.5);
        }
      }
      ctx.fillStyle = colors.line;
      ctx.fillRect(KEYS_W - 1, 0, 1, H);
      // ruler
      ctx.fillStyle = colors.card;
      ctx.fillRect(0, 0, W, RULER_H);
      ctx.fillStyle = colors.line;
      ctx.fillRect(0, RULER_H - 1, W, 1);
      const bar = m.barTicks(s.project.meter);
      const every = Math.max(1, Math.ceil(38 / (bar * ppt())));
      ctx.save();
      ctx.beginPath();
      ctx.rect(KEYS_W, 0, W, RULER_H);
      ctx.clip();
      for (let i = Math.max(0, Math.floor(tickAt(KEYS_W) / bar / every) * every); i * bar <= tickAt(W); i += every) {
        const x = ox() + i * bar * ppt();
        ctx.fillStyle = colors["roll-bar"];
        ctx.fillRect(Math.round(x), 8, 1, RULER_H - 8);
        ctx.fillStyle = colors.soft;
        ctx.fillText(String(i + 1), x + 4, RULER_H / 2);
      }
      const px = ox() + view.playhead * ppt();
      ctx.fillStyle = colors.play;
      ctx.beginPath();
      ctx.moveTo(px - 6, 10); ctx.lineTo(px + 6, 10); ctx.lineTo(px, RULER_H - 1);
      ctx.fill();
      ctx.restore();
      ctx.fillStyle = colors.card;
      ctx.fillRect(0, 0, KEYS_W - 1, RULER_H - 1);
    },
  }));

  // ---------- overlay ----------
  const playLine = new Konva.Line({ listening: false, strokeWidth: 1.5 });
  const marquee = new Konva.Rect({ listening: false, visible: false, strokeWidth: 1, dash: [4, 3] });
  const ghostNote = new Konva.Rect({ listening: false, visible: false, opacity: 0.7, cornerRadius: 2 });
  const tr = new Konva.Transformer({
    rotateEnabled: false, flipEnabled: false, ignoreStroke: true, keepRatio: false,
    enabledAnchors: ["middle-left", "middle-right"], borderDash: [3, 3],
    anchorStyleFunc(a) {
      a.width(HANDLE_W);
      a.height(Math.max(12, view.row));
      // sit outside the notes, so short notes can still be grabbed
      a.offsetX(a.hasName("middle-left") ? HANDLE_W : 0);
      a.offsetY(a.height() / 2);
      a.cornerRadius(2);
    },
  });
  over.add(marquee, ghostNote, tr, playLine);

  // ---------- rendering ----------
  const rects = new Map(); // note id -> Konva.Rect
  const byRect = (node) => (node?.getAttr("noteId") !== undefined ? store.track().notes.find((n) => n.id === node.getAttr("noteId")) : undefined);
  let shown = { project: null, trackId: 0, selection: null, px: 0, row: 0 };

  function place(rect, n) {
    rect.setAttrs({ x: noteX(n), y: noteY(n) + 1, width: n.dur * ppt(), height: view.row - 2, scaleX: 1, scaleY: 1 });
  }
  function drawNotes(notes) {
    const alive = new Set();
    for (const n of notes) {
      alive.add(n.id);
      let r = rects.get(n.id);
      if (!r) {
        r = new Konva.Rect({ noteId: n.id, cornerRadius: 2, strokeWidth: 1, perfectDrawEnabled: false, shadowForStrokeEnabled: false, hitStrokeWidth: 0 });
        rects.set(n.id, r);
        noteGroup.add(r);
      }
      place(r, n);
      const sel = s.selection.has(n.id);
      r.setAttrs({ fill: colors[sel ? "note-sel" : "note"], stroke: colors.roll, opacity: 0.45 + 0.55 * (n.vel / 127) });
    }
    for (const [id, r] of rects) if (!alive.has(id)) { r.destroy(); rects.delete(id); }
  }
  function drawGhosts() {
    ghosts.destroyChildren();
    for (const t of s.project.tracks) {
      if (t.id === s.trackId) continue;
      for (const n of t.notes) ghosts.add(new Konva.Rect({ x: noteX(n), y: noteY(n) + 1, width: n.dur * ppt(), height: view.row - 2, fill: colors.ghost, opacity: 0.6, perfectDrawEnabled: false }));
    }
  }
  function syncTransformer() {
    const nodes = gesture?.kind === "marquee" || s.tool === "erase" ? [] : store.selected().map((n) => rects.get(n.id)).filter(Boolean);
    tr.nodes(nodes);
    tr.setAttrs({ anchorStroke: colors["note-sel"], anchorFill: colors.card, borderStroke: colors["note-sel"], borderEnabled: nodes.length > 1 });
    tr.moveToTop();
  }
  function redraw() {
    cancelGesture();
    if (shown.trackId !== s.trackId) { noteGroup.destroyChildren(); rects.clear(); }
    if (shown.project !== s.project || shown.trackId !== s.trackId || shown.px !== view.px || shown.row !== view.row) drawGhosts();
    drawNotes(store.track().notes);
    syncTransformer();
    playLine.stroke(colors.play);
    marquee.setAttrs({ stroke: colors.accent, fill: colors.accent + "22" });
    ghostNote.fill(colors["note-sel"]);
    holder.style.cursor = { select: "default", draw: "crosshair", erase: "not-allowed" }[s.tool];
    shown = { project: s.project, trackId: s.trackId, selection: s.selection, px: view.px, row: view.row };
    layout();
  }
  /** Scroll or size changed: move layers, no note work. */
  function layout() {
    size.style.width = `${KEYS_W + PAD + contentTicks() * ppt()}px`;
    size.style.height = `${RULER_H + 128 * view.row}px`;
    const w = scroller.clientWidth, h = scroller.clientHeight;
    if (stage.width() !== w || stage.height() !== h) stage.size({ width: Math.max(1, w), height: Math.max(1, h) });
    noteLayer.position({ x: ox(), y: oy() });
    const px = ox() + view.playhead * ppt();
    playLine.points([px, RULER_H, px, h]);
    tr.forceUpdate(); // its nodes moved with their layer
    stage.batchDraw();
  }

  // ---------- gestures ----------
  // One at a time. Each has move(x, y, event) for preview and end() to commit.
  let gesture = null, last = null;
  function cancelGesture() {
    if (!gesture) return false;
    const g = gesture;
    gesture = null;
    marquee.visible(false);
    ghostNote.visible(false);
    if (g.kind === "scale") tr.stopTransform();
    return true;
  }
  const finish = (f) => { gesture = null; marquee.visible(false); ghostNote.visible(false); f(); };

  function startMove(x, y, hit, wasSelected, additive) {
    const base = store.track().notes, ids = new Set(s.selection);
    const t0 = tickAt(x), p0 = pitchAt(y);
    let out = base, dragging = false, lastPitch = hit.pitch;
    gesture = {
      kind: "move",
      move(cx, cy, e) {
        if (!dragging && Math.hypot(cx - x, cy - y) < DRAG_PX) return;
        dragging = true;
        const raw = tickAt(cx) - t0;
        // relative snapping: moves by whole grid steps, so an off-grid note keeps its offset
        const dt = Math.abs(raw * ppt()) < DRAG_PX ? 0 : snapTo(raw, e);
        out = m.moveNotes(base, ids, dt, pitchAt(cy) - p0);
        for (const n of out) if (ids.has(n.id)) place(rects.get(n.id), n);
        const now = out.find((n) => n.id === hit.id).pitch;
        if (now !== lastPitch) { lastPitch = now; press(now, hit.vel, 0.15); }
        noteLayer.batchDraw();
      },
      end() {
        if (dragging) store.commitNotes(out);
        // a plain click on one note of a group picks just that note
        else if (wasSelected && !additive && ids.size > 1) store.select([hit.id]);
      },
    };
  }
  function startMarquee(x, y, additive) {
    const keep = additive ? new Set(s.selection) : new Set();
    const t0 = tickAt(x), c0 = y - oy();
    let ids = keep;
    gesture = {
      kind: "marquee",
      move(cx, cy) {
        // anchored in content coordinates, so scrolling while dragging extends the box
        const ax = ox() + t0 * ppt(), ay = oy() + c0;
        const box = { x: Math.min(ax, cx), y: Math.min(ay, cy), width: Math.abs(cx - ax), height: Math.abs(cy - ay) };
        marquee.setAttrs({ ...box, visible: true });
        ids = new Set(keep);
        for (const [id, r] of rects) {
          const hit = Konva.Util.haveIntersection(box, { x: r.x() + ox(), y: r.y() + oy(), width: r.width(), height: r.height() });
          if (hit) ids.add(id);
          r.fill(colors[ids.has(id) ? "note-sel" : "note"]);
        }
        stage.batchDraw();
      },
      end() { store.select(ids); },
    };
    tr.nodes([]);
  }
  function startDraw(x, y) {
    const t = Math.max(0, tickAt(x)), pitch = pitchAt(y), grid = s.snap;
    const start = grid > 1 ? Math.floor(t / grid) * grid : Math.round(t);
    let dur = Math.max(s.lastDur, m.MIN_DUR), sized = false;
    const show = () => {
      ghostNote.setAttrs({ x: ox() + start * ppt(), y: oy() + (127 - pitch) * view.row + 1, width: dur * ppt(), height: view.row - 2, visible: true });
      over.batchDraw();
    };
    press(pitch, s.lastVel, 0.2);
    show();
    gesture = {
      kind: "draw",
      move(cx, cy, e) {
        if (!sized && Math.abs(cx - x) < DRAG_PX) return;
        sized = true;
        const len = tickAt(cx) - start;
        dur = grid > 1 && !free(e) ? Math.max(1, Math.ceil(len / grid)) * grid : Math.max(m.MIN_DUR, Math.round(len));
        show();
      },
      end() {
        if (start + dur > m.MAX_TICK) return;
        const n = m.createNote(pitch, start, dur, s.lastVel);
        s.lastDur = dur;
        store.commitNotes([...store.track().notes, n], [n.id]);
      },
    };
  }
  function startErase(x, y) {
    const gone = new Set();
    const rub = (cx, cy) => {
      const n = byRect(stage.getIntersection({ x: cx, y: cy }));
      if (!n || gone.has(n.id)) return;
      gone.add(n.id);
      rects.get(n.id).visible(false);
      noteLayer.draw(); // refresh hit testing at once
    };
    gesture = {
      kind: "erase", move: rub,
      end() { for (const id of gone) rects.get(id)?.visible(true); store.commitNotes(m.deleteNotes(store.track().notes, gone)); },
    };
    rub(x, y);
  }
  function startSeek(x) {
    const go = (cx, cy, e) => onSeek(m.clamp(snapTo(tickAt(cx), e), 0, m.MAX_TICK));
    gesture = { kind: "seek", move: go, end() {} };
    go(x, 0, last?.e);
  }

  const point = (e) => {
    const r = holder.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  holder.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || gesture) return;
    document.activeElement?.blur?.(); // commit any text field being edited
    const [x, y] = point(e);
    last = { x, y, e };
    if (y < RULER_H) { if (x >= KEYS_W) startSeek(x); return; }
    if (x < KEYS_W) { press(pitchAt(y), s.lastVel, 0.4); return; }
    const target = stage.getIntersection({ x, y });
    if (target?.getParent() === tr) return; // Konva handles the resize handles itself
    if (s.tool === "erase") return startErase(x, y);
    const hit = byRect(target);
    const additive = e.shiftKey || e.ctrlKey || e.metaKey;
    if (!hit) return s.tool === "draw" ? startDraw(x, y) : startMarquee(x, y, additive);
    const was = s.selection.has(hit.id);
    if (additive && was) return store.select([...s.selection].filter((id) => id !== hit.id));
    press(hit.pitch, hit.vel, 0.2);
    const selection = was ? s.selection : new Set(additive ? [...s.selection, hit.id] : [hit.id]);
    store.set({ selection, lastDur: hit.dur, lastVel: hit.vel }); // one change, so one redraw
    startMove(x, y, hit, was, additive);
  });
  holder.addEventListener("dblclick", (e) => {
    const [x, y] = point(e);
    if (s.tool !== "select" || gesture || x < KEYS_W || y < RULER_H || stage.getIntersection({ x, y })) return;
    startDraw(x, y);
    const g = gesture;
    finish(g.end);
    unlight();
  });
  window.addEventListener("pointermove", (e) => {
    if (!gesture || gesture.kind === "scale") { if (gesture) last = { e }; return; }
    const [x, y] = point(e);
    last = { x, y, e };
    gesture.move(x, y, e);
  });
  window.addEventListener("pointerup", (e) => {
    if (e.button === 0) unlight();
    if (e.button === 0 && gesture && gesture.kind !== "scale") finish(gesture.end);
  });
  const abort = () => { unlight(); if (gesture) redraw(); };
  window.addEventListener("pointercancel", abort);
  window.addEventListener("blur", abort);
  holder.addEventListener("contextmenu", (e) => e.preventDefault());

  // ---------- resize / group scale ----------
  tr.on("transformstart", () => {
    const base = store.track().notes, ids = new Set(s.selection);
    gesture = { kind: "scale", base, ids, box: m.bounds(m.pick(base, ids)), left: tr.getActiveAnchor() === "middle-left", factor: 1 };
  });
  tr.boundBoxFunc((oldBox, newBox) => {
    const g = gesture;
    if (g?.kind !== "scale") return oldBox;
    const span = g.box.end - g.box.start;
    const edge = snapTo(tickAt(g.left ? newBox.x : newBox.x + newBox.width), last?.e);
    const origin = g.left ? g.box.end : g.box.start;
    const want = (g.left ? origin - edge : edge - origin) / span;
    g.origin = origin;
    g.factor = m.limitFactor(g.base, g.ids, origin, Math.max(want, 1e-6));
    const start = g.left ? origin - span * g.factor : origin;
    return { ...oldBox, x: ox() + start * ppt(), width: span * g.factor * ppt() };
  });
  tr.on("transformend", () => {
    const g = gesture;
    if (g?.kind !== "scale") return; // cancelled
    gesture = null;
    const out = m.scaleNotes(g.base, g.ids, g.origin ?? 0, g.factor);
    if (g.ids.size === 1) s.lastDur = m.pick(out, g.ids)[0].dur;
    if (out === g.base) redraw(); else store.commitNotes(out);
  });

  // ---------- zoom and scroll ----------
  function zoomX(factor, anchor = KEYS_W + (stage.width() - KEYS_W) / 2) {
    const t = tickAt(anchor);
    view.px = m.clamp(view.px * factor, PX_MIN, PX_MAX);
    redraw();
    scroller.scrollLeft = KEYS_W + PAD + t * ppt() - anchor;
    layout();
  }
  function zoomY(factor, anchor = stage.height() / 2) {
    const r = (anchor - oy()) / view.row;
    view.row = m.clamp(view.row * factor, ROW_MIN, ROW_MAX);
    redraw();
    scroller.scrollTop = RULER_H + r * view.row - anchor;
    layout();
  }
  function centerPitch(p) { scroller.scrollTop = RULER_H + (127.5 - p) * view.row - stage.height() / 2; }
  /** Show all notes of the active track (or of the project, when the track is empty). */
  function fit() {
    const own = store.track().notes;
    const b = m.bounds(own.length ? own : s.project.tracks.flatMap((t) => t.notes));
    const end = Math.max(m.projectEnd(s.project), 4 * m.barTicks(s.project.meter));
    view.px = m.clamp(((stage.width() - KEYS_W - PAD - 30) / end) * m.PPQ, PX_MIN, PX_MAX);
    if (b) view.row = m.clamp(Math.floor((stage.height() - RULER_H) / (b.high - b.low + 5)), 12, 22);
    redraw();
    scroller.scrollLeft = 0;
    centerPitch(b ? (b.low + b.high) / 2 : 66);
    layout();
  }
  scroller.addEventListener("wheel", (e) => {
    if (!e.ctrlKey && !e.metaKey && !e.altKey) return; // plain wheel scrolls natively
    e.preventDefault();
    if (gesture) return;
    const [x, y] = point(e);
    const f = Math.exp(-m.clamp(e.deltaY, -100, 100) * 0.002);
    if (e.altKey || e.shiftKey) zoomY(f, y); else zoomX(f, x);
  }, { passive: false });
  scroller.addEventListener("scroll", () => {
    layout();
    if (gesture?.move && last?.x !== undefined) gesture.move(last.x, last.y, last.e);
  });
  new ResizeObserver(() => layout()).observe(scroller);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { readColors(); shown.project = null; redraw(); });

  return {
    redraw, zoomX, zoomY, fit,
    busy: () => gesture !== null,
    /** Abort the current drag. Returns false when there was none. */
    cancel() { if (!gesture) return false; redraw(); return true; },
    setPlayhead(tick, follow) {
      if (view.playhead === tick) return;
      view.playhead = tick;
      const px = ox() + tick * ppt();
      if (follow && !gesture && (px > stage.width() - 20 || px < KEYS_W)) {
        layout(); // the content may have to grow before it can scroll that far
        scroller.scrollLeft = tick * ppt() - 40;
        layout(); // do not wait for the scroll event
      } else layoutPlayhead();
    },
    /** Light the keys of these pitches. */
    setHeld(pitches) { held = new Set(pitches); bg.batchDraw(); frame.batchDraw(); },
    held: () => [...held], // used by browser tests
    view, // read-only use by tests
    lit: () => lit, // used by browser tests
    originX: ox, // x of time 0 inside the roll, used by browser tests
    /** Screen rectangle of a note inside the roll, used by browser tests. */
    noteBox(id) { const r = rects.get(id)?.getClientRect({ skipStroke: true }); return r && { ...r }; },
  };
  function layoutPlayhead() {
    const px = ox() + view.playhead * ppt();
    playLine.points([px, RULER_H, px, stage.height()]);
    over.batchDraw();
    frame.batchDraw();
  }
}
