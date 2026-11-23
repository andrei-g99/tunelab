// Application state with undo. Views subscribe and re-read; only actions here change it.
import { bounds, createProject, updateTrack } from "./model.js";

const LIMIT = 200;

export function createStore() {
  const listeners = new Set();
  let past = [], future = [];
  const s = {
    project: createProject(), trackId: 0, selection: new Set(),
    tool: "select", snap: 240, lastDur: 480, lastVel: 100,
    file: null, // {id, rev} of the saved project, or null when never saved
    saved: null, // the project object as last saved; same object = no unsaved changes
  };
  s.trackId = s.project.tracks[0].id;
  s.saved = s.project;

  const emit = () => listeners.forEach((f) => f(s));
  const snapshot = () => ({ project: s.project, trackId: s.trackId, selection: s.selection });
  function fixRefs() {
    if (!s.project.tracks.some((t) => t.id === s.trackId)) s.trackId = s.project.tracks[0].id;
    const ids = new Set(api.track().notes.map((n) => n.id));
    if ([...s.selection].some((id) => !ids.has(id))) s.selection = new Set([...s.selection].filter((id) => ids.has(id)));
  }

  const api = {
    state: s,
    subscribe(f) { listeners.add(f); f(s); },
    track: () => s.project.tracks.find((t) => t.id === s.trackId),
    selected: () => api.track().notes.filter((n) => s.selection.has(n.id)),
    selectionBounds: () => bounds(api.selected()),
    dirty: () => s.project !== s.saved,
    canUndo: () => past.length > 0,
    canRedo: () => future.length > 0,

    /** Change view state only (tool, snap, ...); not undoable. */
    set(patch) { Object.assign(s, patch); emit(); },
    select(ids) { s.selection = new Set(ids); emit(); },
    setTrack(id) { if (id !== s.trackId) { s.trackId = id; s.selection = new Set(); emit(); } },

    /** Replace the project as one undo step. */
    commit(project, selection) {
      if (project === s.project) { if (selection) api.select(selection); return; }
      past.push(snapshot());
      if (past.length > LIMIT) past.shift();
      future = [];
      s.project = project;
      if (selection) s.selection = new Set(selection);
      fixRefs();
      emit();
    },
    /** Replace the active track's notes as one undo step. */
    commitNotes(notes, selection) {
      const project = notes === api.track().notes ? s.project : updateTrack(s.project, s.trackId, { notes });
      api.commit(project, selection);
    },
    undo() { travel(past, future); },
    redo() { travel(future, past); },

    /** Open a different project. saved=false marks it as having unsaved changes. */
    load(project, file, saved = true) {
      past = []; future = [];
      Object.assign(s, { project, file, trackId: project.tracks[0].id, selection: new Set(), saved: saved ? project : null });
      emit();
    },
    /** `sent` is now on disk in `file`. Edits made meanwhile stay unsaved. A new name applies to
     *  the current project without an undo step. */
    markSaved(sent, file, name = sent.name) {
      const untouched = s.project === sent;
      if (name !== s.project.name) s.project = { ...s.project, name };
      s.saved = untouched ? s.project : sent;
      s.file = file;
      emit();
    },
  };
  function travel(from, to) {
    if (!from.length) return;
    to.push(snapshot());
    Object.assign(s, from.pop());
    fixRefs();
    emit();
  }
  return api;
}
