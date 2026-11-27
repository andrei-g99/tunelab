// Plays notes live with the computer keyboard, like a small MIDI keyboard. The key layout is in
// shortcuts.js. Nothing is recorded into the project.
import { $, el } from "../shared/dom.js";
import { pitchName } from "./model.js";
import { BLACK_KEYS, OCTAVE_MAX, OCTAVE_MIN, WHITE_KEYS, isPianoKey, pianoPitch, prettyKey } from "./shortcuts.js";

const WIDTH = 44; // of a white key, px; also in daw.css

/** typing(event): whether a control needs the key itself. */
export function createPiano({ store, player, roll, typing }) {
  const s = store.state, panel = $("#piano"), toggle = $("#b-piano");
  let on = false, octave = 4;
  const down = new Map(); // "key KeyA" or "mouse KeyA" -> pitch

  // ---------- notes ----------
  function showHeld() {
    roll.setHeld(down.values());
    for (const [code, b] of buttons) b.classList.toggle("down", ["key ", "mouse "].some((from) => down.has(from + code)));
  }
  function press(id, code) {
    const pitch = pianoPitch(code, octave);
    if (pitch === null || down.has(id)) return;
    player.press(id, s.trackId, pitch, s.lastVel).catch(console.error); // first: the sound must not wait
    down.set(id, pitch);
    showHeld();
  }
  function release(id) {
    if (!down.delete(id)) return;
    player.release(id);
    showHeld();
  }
  const releaseAll = () => { for (const id of [...down.keys()]) release(id); };

  // ---------- panel ----------
  const key = ([code, semitone], black) => {
    const b = el("button", { class: black ? "black" : "white", tabindex: -1 }, el("span", { class: "note" }), el("span", {}, prettyKey(code)));
    if (black) b.style.left = `${WHITE_KEYS.findLastIndex(([, w]) => w < semitone) * WIDTH + WIDTH}px`;
    b.addEventListener("pointerdown", (e) => {
      if (e.button) return;
      e.preventDefault(); // keep the focus where it is
      b.setPointerCapture(e.pointerId);
      press("mouse " + code, code);
    });
    b.addEventListener("lostpointercapture", () => release("mouse " + code));
    return [code, b];
  };
  const buttons = new Map([...WHITE_KEYS.map((k) => key(k, false)), ...BLACK_KEYS.map((k) => key(k, true))]);
  const pick = el("select", { "aria-label": "Octave", onchange: () => { setOctave(+pick.value); pick.blur(); } },
    ...Array.from({ length: OCTAVE_MAX - OCTAVE_MIN + 1 }, (_, i) => el("option", { value: OCTAVE_MIN + i }, `C${OCTAVE_MIN + i}`)));
  const lower = el("button", { "aria-label": "Octave down", onclick: () => setOctave(octave - 1) }, "−");
  const higher = el("button", { "aria-label": "Octave up", onclick: () => setOctave(octave + 1) }, "+");
  panel.append(el("div", { class: "row" }, el("span", {}, "Octave"), lower, pick, higher), el("div", { class: "keyboard" }, ...buttons.values()));

  function setOctave(n) {
    if (n < OCTAVE_MIN || n > OCTAVE_MAX) return;
    octave = n; // notes already held keep their pitch
    pick.value = n;
    lower.disabled = n === OCTAVE_MIN;
    higher.disabled = n === OCTAVE_MAX;
    for (const [code, b] of buttons) {
      const name = pitchName(pianoPitch(code, n));
      b.setAttribute("aria-label", name);
      b.firstChild.textContent = /^C\d/.test(name) ? name : "";
    }
  }
  function setOn(now) {
    on = now;
    if (!on) releaseAll();
    panel.hidden = !on;
    toggle.setAttribute("aria-pressed", on);
  }
  toggle.addEventListener("click", () => setOn(!on));
  setOctave(octave);
  setOn(false);

  // ---------- computer keyboard: before the shortcuts, which use some of the same keys ----------
  window.addEventListener("keydown", (e) => {
    if (!on || !isPianoKey(e.code) || e.isComposing || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
    if (document.querySelector("dialog[open]") || typing(e)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (!e.repeat) press("key " + e.code, e.code);
  }, true);
  window.addEventListener("keyup", (e) => release("key " + e.code), true);
  window.addEventListener("blur", releaseAll); // the key may be let go elsewhere
  document.addEventListener("visibilitychange", () => { if (document.hidden) releaseAll(); });

  return {
    toggle: () => setOn(!on),
    shift: (n) => { if (on) setOctave(octave + n); },
  };
}
