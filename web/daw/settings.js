// User settings, stored by the server in library/settings.json, and the Settings dialog.
import { ACTIONS, RESERVED, conflict, effectiveKeys, keyFromEvent, prettyKey } from "./shortcuts.js";
import { api, ask, el, guard, toast } from "../shared/dom.js";

export const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
const OPTIONS = [
  ["previewNotes", "Play notes while editing"],
  ["followPlayhead", "Scroll along during playback"],
  ["highlightScale", "Shade rows outside the key"],
];

export async function createSettings(onChange) {
  let current = { previewNotes: true, followPlayhead: true, highlightScale: true, shortcuts: {} };
  try { current = await api("GET", "/api/settings"); } catch (e) { toast(e.message, true); }

  const store = guard(async (next) => {
    current = await api("PUT", "/api/settings", next);
    onChange(current);
    draw();
  });
  const body = el("div");
  const dialog = el("dialog", { class: "wide" },
    el("div", { class: "head" }, el("h2", {}, "Settings"), el("button", { onclick: () => dialog.close() }, "Close")), body);
  document.body.append(dialog);
  let stopCapture = () => {};
  dialog.addEventListener("close", () => stopCapture());

  function capture(action, button) {
    stopCapture();
    button.textContent = "Press keys…";
    const onKey = guard(async (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.repeat) return;
      const key = keyFromEvent(e, isMac);
      if (!key) return; // only modifiers so far
      stopCapture();
      if (RESERVED.has(key)) return toast(`${prettyKey(key, isMac)} belongs to the browser.`, true);
      const keys = effectiveKeys(current.shortcuts), other = conflict(keys, action.id, key);
      if (other && (await ask(`${prettyKey(key, isMac)} is used for "${other.label}". Swap the two?`, [["yes", "Swap"], ["no", "Cancel"]])) !== "yes") return;
      const next = { ...current.shortcuts, [action.id]: key };
      if (other) next[other.id] = keys[action.id];
      await store({ ...current, shortcuts: next });
    });
    window.addEventListener("keydown", onKey, true);
    stopCapture = () => { window.removeEventListener("keydown", onKey, true); stopCapture = () => {}; draw(); };
  }
  function draw() {
    const keys = effectiveKeys(current.shortcuts);
    body.replaceChildren(
      el("fieldset", {}, el("legend", {}, "Editor"), ...OPTIONS.map(([k, label]) => {
        const box = el("input", { type: "checkbox", checked: current[k], onchange: () => store({ ...current, [k]: box.checked }) });
        return el("label", { class: "check" }, box, " " + label);
      })),
      el("fieldset", {}, el("legend", {}, "Keyboard shortcuts"),
        el("p", {}, "Click a key, then press the new combination."),
        el("div", { class: "keys" }, ...ACTIONS.flatMap((a) => {
          const changed = keys[a.id] !== a.key;
          const b = el("button", { class: "key", "aria-label": `Change key for ${a.label}`, onclick: () => capture(a, b) }, prettyKey(keys[a.id], isMac));
          const reset = el("button", { disabled: !changed, onclick: () => {
            const other = conflict(keys, a.id, a.key);
            if (other) return toast(`${prettyKey(a.key, isMac)} is now used for "${other.label}". Change that one first.`, true);
            const { [a.id]: _, ...rest } = current.shortcuts;
            store({ ...current, shortcuts: rest });
          } }, "Reset");
          return [el("span", {}, a.label), b, reset];
        })),
        el("div", { class: "row end" }, el("button", { onclick: () => store({ ...current, shortcuts: {} }) }, "Reset all shortcuts"))),
      el("fieldset", {}, el("legend", {}, "Mouse"), el("p", {},
        "Ctrl + wheel zooms time, Alt + wheel zooms pitch, Shift + wheel scrolls sideways. Shift + click adds to the selection. Hold Ctrl or Alt while dragging to ignore the grid.")));
  }
  return { get: () => current, open() { draw(); dialog.showModal(); } };
}
