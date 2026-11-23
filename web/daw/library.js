// The Library dialog: saved projects and melodies, favorites, rename, export, delete.
import { tracksFromMelody } from "./model.js";
import { api, ask, askText, el, guard, toast } from "../shared/dom.js";

export function createLibrary({ files }) {
  let kind = "projects", onlyFav = false;
  const list = el("div"), tabs = el("div", { class: "tabs" });
  const dialog = el("dialog", { class: "wide" },
    el("div", { class: "head" }, el("h2", {}, "Library"), el("button", { onclick: () => dialog.close() }, "Close")), tabs, list);
  document.body.append(dialog);

  const tab = (label, k) => el("button", { "aria-pressed": String(kind === k), onclick: () => { kind = k; refresh(); } }, label);
  const refresh = guard(async () => {
    const data = await api("GET", "/api/library");
    const fav = el("input", { type: "checkbox", checked: onlyFav, onchange: () => { onlyFav = fav.checked; refresh(); } });
    tabs.replaceChildren(tab(`Projects (${data.projects.length})`, "projects"), tab(`Melodies (${data.melodies.length})`, "melodies"),
      el("label", {}, fav, " Favorites only"));
    const items = data[kind].filter((i) => !onlyFav || i.favorite);
    list.replaceChildren(...(items.length ? items.map(row) : [el("p", { class: "soft" }, onlyFav ? "No favorites here yet. Use the star next to an item." : kind === "projects" ? "No saved projects yet." : "No saved melodies yet. Use “Save track as melody” in the DAW, or the star in the Tune Generator.")]));
  });
  const then = (f) => guard(async () => { if ((await f()) !== false) dialog.close(); });
  function row(i) {
    const path = `/api/library/${kind}/${i.id}`, k = kind;
    const star = el("button", { class: "star", "aria-pressed": String(i.favorite), "aria-label": "Favorite", title: "Favorite",
      onclick: guard(async () => { await api("PUT", `${path}/favorite`, { favorite: !i.favorite }); refresh(); }) }, i.favorite ? "★" : "☆");
    const del = el("button", { onclick: guard(async () => {
      if ((await ask(`Delete "${i.name}"? The file moves to library/trash.`, [["yes", "Delete"], ["no", "Cancel"]])) !== "yes") return;
      await api("DELETE", path);
      refresh();
    }) }, "Delete");
    const what = el("span", { class: "what" }, i.name, el("span", { class: "soft" }, i.broken ? "  unreadable file" : `  ${i.bpm} BPM, ${new Date(i.modified * 1000).toLocaleString()}`));
    if (i.broken) return el("div", { class: "item" }, what, del);
    const open = k === "projects"
      ? [el("button", { class: "primary", onclick: then(() => files.openProject(i.id)) }, "Open")]
      : [el("button", { class: "primary", onclick: then(async () => files.openMelodyDoc(await files.melodyById(i.id))) }, "Open"),
        el("button", { onclick: then(async () => files.addTracks(tracksFromMelody(await files.melodyById(i.id)))) }, "Add to project")];
    return el("div", { class: "item" }, star, what, ...open,
      el("button", { onclick: guard(async () => {
        const name = await askText("New name", i.name);
        if (!name) return;
        await api("PATCH", path, { name });
        toast("Renamed.");
        refresh();
      }) }, "Rename"),
      el("button", { onclick: guard(() => files.exportItem(k, i.id)) }, "Export"), del);
  }
  return { open() { refresh(); dialog.showModal(); } };
}
