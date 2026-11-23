# Instructions for agents

Read `docs/ARCHITECTURE.md` first. Priorities, in order: correct, simple, maintainable. Prefer
plain code over clever optimizations, and an existing library over a home-made widget.

## Rules
- **Never touch user data**: `library/` and `data/tunes.db`. For experiments set
  `TUNELAB_LIBRARY` and `TUNELAB_DB` to a temporary location.
- No build step or framework for the web part. Vanilla ES modules.
- Music logic goes in the pure modules (`model.js`, `tempo.js`) with a unit test, not in UI code.
- Never modify notes, tracks or projects in place. All changes go through `store.commit`.
- One user action is one undo step.
- `web/vendor/` is generated. To change a version: edit `package.json`, then
  `npm install --ignore-scripts && npm run vendor`.
- Keep the DAW and the Tune Generator separate: they share only `web/shared/` and the API.
- User-chosen text reaches the page through `el()`/`textContent`, never `innerHTML`.
- Update `docs/USER_GUIDE.md` when behaviour changes, `docs/ARCHITECTURE.md` when structure does.
- Run `uv run pytest` and `npm test` before saying something works. Look at screenshots for
  visual changes: tests missed a resize handle hidden behind the keyboard.

## How to
**Add a keyboard action:** add a line to `ACTIONS` in `shortcuts.js`, and a function with the same
id to `actions` in `main.js`. Settings picks it up by itself.

**Add a sound:** `SOUNDS` in `model.js`, `SYNTHS` in `player.js`, `TrackDoc.sound` in
`documents.py`. All three.

**Add a note tool:** a pure function in `model.js` plus test, then a button in `tools.js`.

**Add a field to projects or tracks:** give it a default in `documents.py` so that old files still
open, then set it in `createTrack`/`createProject` and in `projectFromDoc`/`projectToDoc`
(project fields are listed there by hand). An incompatible change needs a new `version` and a
migration in `library._load`.

**Add a gesture:** a `startX` function in `roll.js` that sets `gesture = {kind, move, end}`;
preview in `move`, commit in `end`.

**Change scoring:** edit `scorer.py`, then run `uv run tunelab-check`. Tune only on "dev" tunes;
"holdout" is for testing.

## Pitfalls
- Reading layout right after setting `scrollLeft` is fine, but the scroll *event* comes a frame
  later. Call `layout()` yourself.
- `store.commitNotes` from inside a gesture's `move` would cancel that gesture.
- Konva: use `ignoreStroke` and no `padding` on the Transformer, or the box no longer equals the
  notes' true extent.
- Buttons lose focus after a mouse click on purpose, so Space plays instead of re-clicking.
- Closing a `<dialog>` resolves `ask()` in a later task; tests must wait for the effect.
