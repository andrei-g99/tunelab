// Keyboard shortcuts: the list of actions, their default keys, and key capture.
// Key strings use tinykeys syntax; "$mod" is Ctrl (Cmd on a Mac).

export const ACTIONS = [
  // id, label, default key, options: typing = also works while a text field has focus
  ["play", "Play / pause", "Space"],
  ["stop", "Stop and return to start", "Enter"],
  ["save", "Save project", "$mod+KeyS", { typing: true }],
  ["open", "Open library", "$mod+KeyO", { typing: true }],
  ["undo", "Undo", "$mod+KeyZ"],
  ["redo", "Redo", "$mod+Shift+KeyZ"],
  ["toolSelect", "Select tool", "KeyV"],
  ["toolDraw", "Draw tool", "KeyB"],
  ["toolErase", "Erase tool", "KeyE"],
  ["selectAll", "Select all notes", "$mod+KeyA"],
  ["deselect", "Deselect / cancel drag", "Escape"],
  ["copy", "Copy", "$mod+KeyC"],
  ["cut", "Cut", "$mod+KeyX"],
  ["paste", "Paste at playhead", "$mod+KeyV"],
  ["duplicate", "Duplicate after selection", "$mod+KeyD"],
  ["delete", "Delete notes", "Delete"],
  ["left", "Move left by one grid step", "ArrowLeft", { repeat: true }],
  ["right", "Move right by one grid step", "ArrowRight", { repeat: true }],
  ["up", "Up a semitone", "ArrowUp", { repeat: true }],
  ["down", "Down a semitone", "ArrowDown", { repeat: true }],
  ["octaveUp", "Up an octave", "Shift+ArrowUp"],
  ["octaveDown", "Down an octave", "Shift+ArrowDown"],
  ["quantize", "Snap note starts to grid", "KeyQ"],
  ["zoomIn", "Zoom in", "Equal", { repeat: true }],
  ["zoomOut", "Zoom out", "Minus", { repeat: true }],
  ["zoomFit", "Zoom to fit", "KeyF"],
  ["tools", "Open Tools", "KeyT"],
  ["settings", "Open Settings", "$mod+Comma"],
].map(([id, label, key, opts = {}]) => ({ id, label, key, ...opts }));

/** Current key for every action: the user's overrides on top of the defaults. */
export function effectiveKeys(overrides = {}) {
  return Object.fromEntries(ACTIONS.map((a) => [a.id, overrides[a.id] ?? a.key]));
}

/** A keydown event as a key string, or null while only modifiers are held. */
export function keyFromEvent(e, isMac = false) {
  if (!e.code || ["Control", "Shift", "Alt", "Meta", "AltGraph"].includes(e.key)) return null;
  const mods = [];
  if (isMac ? e.metaKey : e.ctrlKey) mods.push("$mod");
  if (isMac ? e.ctrlKey : e.metaKey) mods.push(isMac ? "Control" : "Meta");
  if (e.altKey) mods.push("Alt");
  if (e.shiftKey) mods.push("Shift");
  return [...mods, e.code].join("+");
}

/** The other action already using a key, if any. */
export const conflict = (keys, id, key) => ACTIONS.find((a) => a.id !== id && keys[a.id] === key);

const PRETTY = { $mod: "Ctrl", Equal: "=", Minus: "-", Comma: ",", Period: ".", Slash: "/", ArrowLeft: "←", ArrowRight: "→", ArrowUp: "↑", ArrowDown: "↓", Semicolon: ";", Quote: "'", BracketLeft: "[", BracketRight: "]", Backslash: "\\", Backquote: "`" };
export function prettyKey(key, isMac = false) {
  return key.split("+").map((k) => (k === "$mod" && isMac ? "Cmd" : PRETTY[k] ?? k.replace(/^(Key|Digit)/, ""))).join(" + ");
}

/** Keys the browser itself keeps; binding them would not work. */
export const RESERVED = new Set(["$mod+KeyW", "$mod+KeyT", "$mod+KeyN", "$mod+Shift+KeyW", "$mod+Shift+KeyT", "$mod+Shift+KeyN", "$mod+Tab", "$mod+Shift+Tab", "Tab", "Shift+Tab", "F5", "F11", "F12", "$mod+KeyR"]);
