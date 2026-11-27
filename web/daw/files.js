// Opening, saving, importing and exporting. Talks to the server library and to local files.
/* global Midi */
import * as m from "./model.js";
import { projectFromMidi, projectToMidi } from "./midi.js";
import { render } from "./player.js";
import { encodeWav } from "./wav.js";
import { ApiError, api, ask, askText, download, fileName, toast } from "../shared/dom.js";

const MAX_AUDIO_MINUTES = 20;

export function createFiles({ store, onOpened }) {
  const s = store.state;
  let saving = false, rendering = false;

  function open(project, file, saved) {
    store.load(project, file, saved);
    onOpened();
  }
  /** Returns true when it is fine to replace the current project. */
  async function okToLeave() {
    if (!store.dirty()) return true;
    const a = await ask(`"${s.project.name}" has unsaved changes.`, [["save", "Save"], ["discard", "Discard changes"], ["cancel", "Cancel"]]);
    if (a === "save") return save();
    return a === "discard";
  }
  async function saveNew(message) {
    const name = await askText(message, s.project.name);
    if (!name) return false;
    const sent = s.project;
    const r = await api("POST", "/api/library/projects", { doc: m.projectToDoc({ ...sent, name }) });
    store.markSaved(sent, { id: r.id, rev: r.rev }, name);
    toast(`Saved "${name}".`);
    return true;
  }
  /** Save over the open file, or ask for a name the first time. Returns true when saved. */
  async function save() {
    if (saving) return false;
    saving = true;
    try {
      if (!s.file) return await saveNew("Project name");
      const sent = s.project, path = `/api/library/projects/${s.file.id}`, doc = m.projectToDoc(sent);
      let r;
      try {
        r = await api("PUT", path, { doc, rev: s.file.rev });
      } catch (e) {
        if (!(e instanceof ApiError) || ![404, 409].includes(e.status)) throw e;
        const gone = e.status === 404;
        const a = await ask(gone ? "The saved file no longer exists." : "This project's file was changed elsewhere since you opened it.",
          gone ? [["new", "Save as new project"], ["cancel", "Cancel"]] : [["new", "Save as new project"], ["over", "Overwrite it"], ["cancel", "Cancel"]]);
        if (a === "new") return await saveNew("Project name");
        if (a !== "over") return false;
        r = await api("PUT", path, { doc, rev: null });
      }
      store.markSaved(sent, { id: r.id, rev: r.rev });
      toast("Saved.");
      return true;
    } finally {
      saving = false;
    }
  }
  async function saveAs() {
    if (saving) return;
    saving = true;
    try { await saveNew("Save project as"); } finally { saving = false; }
  }
  async function saveMelody() {
    const t = store.track();
    if (!t.notes.length) return toast("This track has no notes yet.", true);
    const name = await askText("Melody name", t.name === "Melody" ? s.project.name : t.name);
    if (!name) return;
    await api("POST", "/api/library/melodies", { doc: m.melodyToDoc(s.project, t, name) });
    toast(`Saved melody "${name}".`);
  }

  async function newProject() {
    if (await okToLeave()) open(m.createProject(), null, true);
  }
  async function openProject(id) {
    if (!(await okToLeave())) return false;
    const r = await api("GET", `/api/library/projects/${id}`);
    open(m.projectFromDoc(r.doc), { id, rev: r.rev }, true);
    return true;
  }
  async function openMelodyDoc(doc) {
    if (!(await okToLeave())) return false;
    open(m.projectFromMelody(doc), null, false);
    return true;
  }
  /** Add tracks to the current project. Times stay in beats, so they follow its tempo. */
  function addTracks(tracks) {
    if (s.project.tracks.length + tracks.length > 64) return toast("A project can have 64 tracks.", true);
    const only = s.project.tracks[0];
    const blank = s.project.tracks.length === 1 && !only.notes.length; // replace the empty starter track
    store.commit({ ...s.project, tracks: [...(blank ? [] : s.project.tracks), ...tracks] });
    store.setTrack(tracks[0].id);
    onOpened();
  }
  async function melodyById(id) {
    return (await api("GET", `/api/library/melodies/${id}`)).doc;
  }

  /** Import a file chosen by the user: .json project or melody, .mid, .tune/.txt notation. */
  async function importFile(file) {
    if (file.size > 20e6) throw new Error("That file is too large (over 20 MB).");
    const base = file.name.replace(/\.[^.]+$/, "").slice(0, 120) || "Imported";
    let project;
    if (/\.midi?$/i.test(file.name)) {
      project = projectFromMidi(Midi, new Uint8Array(await file.arrayBuffer()), base);
      for (const t of project.tracks) if (t.notes.length > 20000) throw new Error("A track in this file has more than 20,000 notes.");
      if (project.tracks.length > 64) throw new Error("This file has more than 64 tracks.");
      if (m.projectEnd(project) > m.MAX_TICK) throw new Error("This file is too long.");
    } else {
      const text = await file.text();
      if (/\.json$/i.test(file.name)) {
        let doc;
        try { doc = JSON.parse(text); } catch { throw new Error("This file is not valid JSON."); }
        if (doc?.format === "tunelab-project") {
          const clean = await api("POST", "/api/validate/projects", { doc });
          if (await okToLeave()) open(m.projectFromDoc(clean), null, false);
          return;
        }
        if (doc?.format !== "tunelab-melody") throw new Error("This is not a Tunelab project or melody file.");
        project = m.projectFromMelody(await api("POST", "/api/validate/melodies", { doc }));
      } else {
        project = m.projectFromMelody(await api("POST", "/api/notation/parse", { text, name: base }));
      }
    }
    const a = await ask(`Import "${file.name}" as…`, [["new", "New project"], ["add", "Tracks in this project"], ["cancel", "Cancel"]]);
    if (a === "add") addTracks(project.tracks);
    else if (a === "new" && (await okToLeave())) open(project, null, false);
  }

  // ---------- export ----------
  const json = (doc) => JSON.stringify(doc, null, 1);
  const exportProject = (p = s.project) => download(fileName(p.name, ".project.json"), json(m.projectToDoc(p)), "application/json");
  const exportMidi = (p = s.project) => {
    if (!m.projectEnd(p)) return toast("There are no notes to export.", true);
    download(fileName(p.name, ".mid"), projectToMidi(Midi, p), "audio/midi");
  };
  function exportMelody() {
    const t = store.track();
    if (!t.notes.length) return toast("This track has no notes yet.", true);
    download(fileName(t.name, ".melody.json"), json(m.melodyToDoc(s.project, t)), "application/json");
  }
  async function exportText() {
    const r = await api("POST", "/api/melody/score", m.melodyToDoc(s.project, store.track()));
    download(fileName(store.track().name, ".tune"), r.notation + "\n", "text/plain");
    if (r.rounded) toast("Exported. Some timing was rounded to 1/12 beat, the finest the notation allows.");
  }
  /** Audio as heard when playing (mute and solo apply), or the active track alone. format: "mp3" or "wav". */
  async function exportAudio(format) {
    if (rendering) return toast("Already exporting audio, please wait.", true);
    const what = s.project.tracks.length === 1 ? "track"
      : await ask(`Export audio (.${format}) with this project's tempo, sounds and volumes.`,
        [["mix", "Whole mix, as you hear it"], ["track", `Only "${store.track().name}"`], ["cancel", "Cancel"]]);
    if (what !== "mix" && what !== "track") return;
    const p = s.project, t = store.track(), tracks = what === "mix" ? m.audibleTracks(p) : [t];
    if (!tracks.some((x) => x.notes.length)) return toast(what === "mix" ? "No notes can be heard. Check mute and solo." : "This track has no notes yet.", true);
    if (m.projectSeconds({ ...p, tracks }) > MAX_AUDIO_MINUTES * 60) return toast(`Too long to export as audio (more than ${MAX_AUDIO_MINUTES} minutes).`, true);
    const name = what === "track" && p.tracks.length > 1 ? `${p.name} - ${t.name}` : p.name;
    rendering = true;
    try {
      toast("Exporting audio…");
      const sampleRate = 44100, wav = encodeWav([await render(p, tracks, sampleRate)], sampleRate);
      if (format === "wav") download(fileName(name, ".wav"), wav, "audio/wav");
      else download(fileName(name, ".mp3"), await toMp3(wav, name), "audio/mpeg");
      toast("Exported.");
    } finally {
      rendering = false;
    }
  }
  async function toMp3(wav, title) {
    const r = await fetch(`/api/audio/mp3?title=${encodeURIComponent(title)}`, { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav })
      .catch(() => { throw new ApiError("Cannot reach the Tunelab server. Is it still running?", 0); });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      throw new ApiError(typeof j.detail === "string" ? j.detail : `Request failed (${r.status})`, r.status);
    }
    return r.arrayBuffer();
  }
  async function exportItem(kind, id) {
    const { doc } = await api("GET", `/api/library/${kind}/${id}`);
    download(fileName(doc.name, kind === "projects" ? ".project.json" : ".melody.json"), json(doc), "application/json");
  }

  return { save, saveAs, saveMelody, newProject, openProject, openMelodyDoc, melodyById, addTracks, importFile, exportProject, exportMidi, exportAudio, exportMelody, exportText, exportItem };
}
