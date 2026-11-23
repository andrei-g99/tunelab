"""Random mouse and keyboard input. Whatever happens, the state must stay consistent."""
import random

import pytest

from test_e2e import THREE, browser, daw, server  # noqa: F401  (fixtures)

KEYS = ["v", "b", "e", "Control+a", "Escape", "Control+c", "Control+x", "Control+v", "Control+d", "Delete",
        "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Shift+ArrowUp", "Shift+ArrowDown", "q", "=", "-", "f",
        "Control+z", "Control+z", "Control+Shift+z", "Space", "Enter"]

CHECK = """async () => {
  const m = await import('/web/daw/model.js'), s = tunelab.store, notes = s.track().notes;
  const bad = [];
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); // scroll events arrive with frames
  const ids = new Set(notes.map(n => n.id));
  if (ids.size !== notes.length) bad.push('duplicate ids');
  for (const id of s.state.selection) if (!ids.has(id)) bad.push('stale selection');
  if (tunelab.roll.busy()) bad.push('gesture left open');
  const px = tunelab.roll.view.px / 480;
  for (const n of notes) {
    if (![n.pitch, n.start, n.dur, n.vel].every(Number.isInteger) || n.start < 0 || n.dur < 1 || n.pitch < 0 || n.pitch > 127) bad.push('bad note ' + JSON.stringify(n));
    const b = tunelab.roll.noteBox(n.id);
    if (!b) { bad.push('note not drawn'); continue; }
    if (Math.abs(b.x - (tunelab.roll.originX() + n.start * px)) > 1 || Math.abs(b.width - n.dur * px) > 1) bad.push('picture differs from data');
  }
  if (notes.length) {
    const r = await fetch('/api/validate/projects', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({doc: m.projectToDoc(s.state.project)})});
    if (!r.ok) bad.push('not saveable: ' + await r.text());
  }
  return bad;
}"""


@pytest.mark.parametrize("seed", range(4))
def test_monkey(daw, seed):  # noqa: F811
    r = random.Random(seed)
    daw.set_notes(THREE)
    area = daw.page.locator("#roll").bounding_box()
    point = lambda: (area["x"] + r.uniform(5, area["width"] - 20), area["y"] + r.uniform(5, area["height"] - 20))  # noqa: E731

    def somewhere():
        """Often on or beside a note, so that moves and resizes really happen."""
        n = len(daw.notes())
        if n and r.random() < 0.7:
            x, y, w, h = daw.box(r.randrange(n))
            q = (x + r.choice([-3, w / 2, w + 3]), y + h / 2)
            if area["x"] + 60 < q[0] < area["x"] + area["width"] - 20 and area["y"] + 26 < q[1] < area["y"] + area["height"] - 20:
                return q
        return point()

    for step in range(90):
        if len(daw.notes()) > 150:
            daw.key("Control+a")
            daw.key("Delete")
        roll = r.random()
        if roll < 0.45:
            daw.key(r.choice(KEYS))
        elif roll < 0.85:
            a = somewhere()
            b = point() if r.random() < 0.4 else (a[0] + r.uniform(-150, 150), a[1] + r.uniform(-60, 60))
            drop = r.random() < 0.85
            daw.drag(a, b, mods=r.choice([(), (), ("Control",), ("Shift",), ("Alt",)]), steps=2, drop=drop)
            if not drop:
                daw.key(r.choice(["Escape", "Delete", "Control+z", "Space"]))
                daw.page.mouse.up()
        elif roll < 0.93:
            daw.page.mouse.move(*point())
            daw.page.mouse.wheel(r.choice([0, 100, -100]), r.choice([200, -200]))
        else:
            daw.page.mouse.dblclick(*point())
        daw.page.wait_for_timeout(15)
        assert daw.js(CHECK) == [], f"seed {seed} step {step}"
    daw.key("Escape")
    daw.js("() => { while (tunelab.store.canUndo()) tunelab.store.undo(); }")
    assert daw.js(CHECK) == []
