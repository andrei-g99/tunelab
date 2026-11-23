// Small helpers shared by both tools.
export const $ = (sel, root = document) => root.querySelector(sel);

/** el("button", {class: "x", onclick: f}, "text", childNode) */
export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "class") e.className = v;
    else if (k === "value" || k === "checked") e[k] = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  e.append(...children.filter((c) => c !== null && c !== undefined));
  return e;
}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}
export async function api(method, path, body) {
  let r;
  try {
    r = await fetch(path, { method, headers: body === undefined ? {} : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("Cannot reach the Tunelab server. Is it still running?", 0);
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(typeof j.detail === "string" ? j.detail : j.detail?.[0]?.msg ?? `Request failed (${r.status})`, r.status);
  return j;
}

/** Modal question. buttons: [[value, label], ...]; first is primary. Resolves to value, or null on Escape. */
export function ask(message, buttons) {
  return new Promise((resolve) => {
    const d = el("dialog", { class: "ask" }, el("p", {}, message),
      el("div", { class: "row end" }, ...buttons.map(([value, label], i) =>
        el("button", { class: i ? "" : "primary", onclick: () => d.close(String(value)) }, label))));
    d.addEventListener("close", () => { d.remove(); resolve(d.returnValue === "" ? null : d.returnValue); });
    document.body.append(d);
    d.showModal();
  });
}

/** Ask for a line of text. Resolves to trimmed text, or null when cancelled. */
export function askText(message, initial = "") {
  return new Promise((resolve) => {
    let result = null;
    const input = el("input", { value: initial, maxlength: 120, "aria-label": message });
    const form = el("form", { method: "dialog", onsubmit: () => { result = input.value.trim() || null; } },
      el("p", {}, message), input,
      el("div", { class: "row end" }, el("button", { class: "primary" }, "OK"),
        el("button", { type: "button", onclick: () => d.close() }, "Cancel")));
    const d = el("dialog", { class: "ask" }, form);
    d.addEventListener("close", () => { d.remove(); resolve(result); });
    document.body.append(d);
    d.showModal();
    input.select();
  });
}

let toastTimer;
export function toast(text, bad = false) {
  let t = $("#toast");
  if (!t) document.body.append((t = el("div", { id: "toast", role: "status", popover: "manual" })));
  t.textContent = text;
  t.classList.toggle("bad", bad);
  if (t.matches(":popover-open")) t.hidePopover();
  t.showPopover(); // popovers sit above open dialogs
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.hidePopover(), bad ? 6000 : 2500);
}
/** Run an async action, showing any failure. */
export const guard = (f) => async (...args) => {
  try { return await f(...args); } catch (e) { console.warn(e); toast(e.message || String(e), true); }
};

export function download(name, data, type) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
export const fileName = (name, ext) => (name.replace(/[^\p{L}\p{N} _-]+/gu, "").trim() || "untitled") + ext;
