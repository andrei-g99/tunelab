"""Browser tests: real mouse and keyboard against a temporary server and library.

Uses the installed Google Chrome, or Playwright's own Chromium (`uv run playwright install chromium`).
Skipped when neither is available.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = None
        for kw in ({"channel": "chrome"}, {}):
            try:
                b = p.chromium.launch(**kw, args=["--autoplay-policy=no-user-gesture-required"])
                break
            except sync_api.Error:
                continue
        if b is None:
            pytest.skip("no Chrome or Chromium available")
        yield b
        b.close()


@pytest.fixture
def server(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "TUNELAB_LIBRARY": str(tmp_path / "lib"), "TUNELAB_DB": str(tmp_path / "t.db")}
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "tunelab.server:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/api/library")
            break
        except OSError:
            time.sleep(0.1)
    yield url
    p.terminate()
    p.wait()


class Daw:
    def __init__(self, page, url):
        self.page, self.url = page, url
        self.open("/daw")

    def open(self, path):
        self.page.goto(self.url + path)
        self.page.wait_for_function("window.tunelab")
        self.page.wait_for_timeout(50)

    def js(self, code, arg=None):
        return self.page.evaluate(code, arg)

    def notes(self):
        return self.js("() => tunelab.store.track().notes.map(n => [n.pitch, n.start, n.dur])")

    def set_notes(self, notes):
        """Notes as [pitch, start, dur]; returns nothing, leaves them unselected."""
        self.js("""async (ns) => { const m = await import('/web/daw/model.js'); const s = tunelab.store;
            s.commitNotes(ns.map(([p, a, d]) => m.createNote(p, a, d)), []); tunelab.roll.fit(); }""", notes)

    def selected(self):
        return self.js("() => tunelab.store.selected().map(n => n.pitch)")

    def box(self, i):
        b = self.js("""(i) => { const r = document.querySelector('.roll-holder').getBoundingClientRect();
            const b = tunelab.roll.noteBox(tunelab.store.track().notes[i].id);
            return {x: b.x + r.x, y: b.y + r.y, w: b.width, h: b.height}; }""", i)
        return b["x"], b["y"], b["w"], b["h"]

    def mid(self, i):
        x, y, w, h = self.box(i)
        return x + w / 2, y + h / 2

    def px(self, ticks):
        return ticks * self.js("() => tunelab.roll.view.px") / 480

    def x0(self):
        """Screen x of time 0."""
        return self.page.locator("#roll").bounding_box()["x"] + self.js("() => tunelab.roll.originX()")

    def row(self):
        return self.js("() => tunelab.roll.view.row")

    def drag(self, a, b, mods=(), steps=8, drop=True):
        m = self.page.mouse
        m.move(*a)
        m.down()
        for k in mods:
            self.page.keyboard.down(k)
        m.move(a[0] + (b[0] - a[0]) * 0.5, a[1] + (b[1] - a[1]) * 0.5, steps=steps)
        m.move(*b, steps=steps)
        if drop:
            m.up()
        for k in mods:
            self.page.keyboard.up(k)

    def key(self, k):
        self.page.keyboard.press(k)


@pytest.fixture
def daw(browser, server):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, accept_downloads=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda c: errors.append(c.text) if c.type == "error" and "Failed to load resource" not in c.text else None)
    page.on("dialog", lambda d: d.accept())  # "leave page?" prompts
    yield Daw(page, server)
    ctx.close()
    assert errors == []


THREE = [[60, 0, 480], [64, 480, 240], [67, 960, 480]]


def test_draw_move_resize_undo(daw):
    daw.key("b")
    r = daw.page.locator("#roll").bounding_box()
    x0 = daw.x0()
    daw.page.mouse.click(x0 + daw.px(490), r["y"] + 200)
    (pitch, start, dur), = daw.notes()
    assert (start, dur) == (480, 480)
    # draw with drag sets the length
    daw.drag((x0 + daw.px(1930), r["y"] + 200), (x0 + daw.px(2590), r["y"] + 203))
    assert daw.notes()[1] == [pitch, 1920, 720]
    # move: right by two grid steps and up three rows
    daw.key("v")
    x, y = daw.mid(0)
    daw.drag((x, y), (x + daw.px(480), y - 3 * daw.row()))
    assert daw.notes()[0] == [pitch + 3, 960, 480]
    # small jitter is a click, not a move
    x, y = daw.mid(0)
    daw.drag((x, y), (x + 2, y + 1))
    assert daw.notes()[0] == [pitch + 3, 960, 480]
    # resize by the right handle
    bx, by, bw, bh = daw.box(0)
    daw.drag((bx + bw + 3, by + bh / 2), (bx + bw + 3 + daw.px(240), by + bh / 2))
    assert daw.notes()[0] == [pitch + 3, 960, 720]
    # and by the left one
    bx, by, bw, bh = daw.box(0)
    daw.drag((bx - 3, by + bh / 2), (bx - 3 - daw.px(240), by + bh / 2))
    assert daw.notes()[0] == [pitch + 3, 720, 960]
    for _ in range(5):
        daw.key("Control+z")
    assert daw.notes() == []
    for _ in range(5):
        daw.key("Control+Shift+z")
    assert daw.notes()[0] == [pitch + 3, 720, 960]


def test_vertical_move_keeps_offgrid_time_and_ctrl_ignores_grid(daw):
    daw.set_notes([[60, 37, 480]])
    x, y = daw.mid(0)
    daw.drag((x, y), (x + 1, y - 2 * daw.row()))
    assert daw.notes() == [[62, 37, 480]]
    x, y = daw.mid(0)
    daw.drag((x, y), (x + daw.px(100), y), mods=["Control"])
    assert abs(daw.notes()[0][1] - 137) < 12 and daw.notes()[0][1] % 240 != 37


def test_marquee_group_move_and_scale(daw):
    daw.set_notes(THREE)
    x0, y0, *_ = daw.box(2)
    xa, ya, _, ha = daw.box(0)
    _, _, w2, _ = daw.box(2)
    r = daw.page.locator("#roll").bounding_box()
    daw.drag((x0 + w2 + 25, y0 - 15), (r["x"] + 60, ya + ha + 10))
    assert daw.selected() == [60, 64, 67]
    x, y = daw.mid(1)
    daw.drag((x, y), (x + daw.px(240), y - 2 * daw.row()))
    assert daw.notes() == [[62, 240, 480], [66, 720, 240], [69, 1200, 480]]
    # a group cannot be pushed before time 0; its shape survives
    x, y = daw.mid(1)
    daw.drag((x, y), (x - daw.px(500), y))
    assert daw.notes() == [[62, 0, 480], [66, 480, 240], [69, 960, 480]]
    # stretch to double with the right handle (group box spans 69..62 rows)
    xs, ys, ws, hs = daw.box(2)
    xl, yl, wl, hl = daw.box(0)
    ymid = (ys + yl + hl) / 2
    daw.drag((xs + ws + 3, ymid), (xs + ws + 3 + daw.px(1440), ymid))
    assert daw.notes() == [[62, 0, 960], [66, 960, 480], [69, 1920, 960]]
    assert daw.selected() == [62, 66, 69]
    # squeeze back to half with the left handle: the end stays put
    xl, yl, wl, hl = daw.box(0)
    daw.drag((xl - 3, ymid), (xl - 3 + daw.px(1440), ymid))
    assert daw.notes() == [[62, 1440, 480], [66, 1920, 240], [69, 2400, 480]]
    daw.key("Control+z")
    daw.key("Control+z")
    assert daw.notes() == [[62, 0, 480], [66, 480, 240], [69, 960, 480]]


def test_left_handle_of_a_note_at_time_zero(daw):
    daw.set_notes([[60, 0, 960]])
    daw.page.mouse.click(*daw.mid(0))
    x, y, w, h = daw.box(0)
    daw.drag((x - 3, y + h / 2), (x - 3 + daw.px(480), y + h / 2))
    assert daw.notes() == [[60, 480, 480]]


def test_scale_past_the_other_edge_is_limited(daw):
    daw.set_notes(THREE)
    daw.key("Control+a")
    xs, ys, ws, hs = daw.box(2)
    xl, yl, wl, hl = daw.box(0)
    ymid = (ys + yl + hl) / 2
    daw.drag((xs + ws + 3, ymid), (xl - 30, ymid), mods=["Control"])
    n = daw.notes()
    assert [p for p, _, _ in n] == [60, 64, 67] and n[0][1] == 0
    assert all(d >= 10 for _, _, d in n) and abs(n[2][1] - 2 * n[1][1]) <= 2


def test_escape_cancels_drags(daw):
    daw.set_notes(THREE)
    daw.key("Control+a")
    x, y = daw.mid(1)
    daw.drag((x, y), (x + 100, y - 60), drop=False)
    daw.key("Escape")
    daw.page.mouse.up()
    assert daw.notes() == THREE
    assert abs(daw.mid(1)[0] - x) < 1, "the picture goes back too"
    xs, ys, ws, hs = daw.box(2)
    _, yl, _, hl = daw.box(0)
    daw.drag((xs + ws + 3, (ys + yl + hl) / 2), (xs + ws + 200, ys), drop=False)
    daw.key("Delete")  # ignored in the middle of a drag
    daw.key("Escape")
    daw.page.mouse.up()
    assert daw.notes() == THREE
    assert abs(daw.box(2)[2] - ws) < 1


def test_selection_clicks(daw):
    daw.set_notes(THREE)
    daw.page.mouse.click(*daw.mid(0))
    daw.page.keyboard.down("Shift")
    daw.page.mouse.click(*daw.mid(2))
    daw.page.keyboard.up("Shift")
    assert daw.selected() == [60, 67]
    daw.page.mouse.click(*daw.mid(0))
    assert daw.selected() == [60]
    r = daw.page.locator("#roll").bounding_box()
    daw.page.mouse.click(r["x"] + 800, r["y"] + 60)
    assert daw.selected() == []
    daw.page.mouse.dblclick(daw.x0() + daw.px(2410), r["y"] + 100)
    assert len(daw.notes()) == 4 and daw.notes()[3][1] == 2400


def test_erase_and_keys(daw):
    daw.set_notes(THREE)
    daw.key("e")
    xa, ya = daw.mid(0)
    xb, yb = daw.mid(2)
    daw.drag((xa, ya), (xb, yb), steps=30)
    assert 64 not in [n[0] for n in daw.notes()] or len(daw.notes()) < 3
    daw.key("Control+z")
    assert daw.notes() == THREE
    daw.key("v")
    daw.key("Control+a")
    for k in ("ArrowUp", "ArrowRight", "Shift+ArrowUp", "ArrowDown", "ArrowLeft", "Shift+ArrowDown"):
        daw.key(k)
    assert daw.notes() == THREE
    daw.key("Control+c")
    daw.js("() => tunelab.player.seek(1920)")
    daw.key("Control+v")
    assert daw.notes()[3:] == [[60, 1920, 480], [64, 2400, 240], [67, 2880, 480]]
    daw.key("Control+d")
    assert daw.notes()[6][1] == 1920 + 1440
    daw.key("Delete")
    assert len(daw.notes()) == 6
    daw.key("Control+a")
    daw.key("Control+x")
    assert daw.notes() == []


def test_typing_does_not_trigger_shortcuts(daw):
    daw.set_notes(THREE)
    daw.key("Control+a")
    name = daw.page.locator(".track input.name")
    name.click()
    name.fill("bev q")
    daw.page.keyboard.press("Delete")
    daw.page.keyboard.press("Control+a")
    daw.page.keyboard.press("Enter")
    assert daw.js("() => tunelab.store.track().name") == "bev q"
    assert daw.notes() == THREE and daw.js("() => tunelab.store.state.tool") == "select"


def test_escape_closes_menu_without_deselecting(daw):
    daw.set_notes(THREE)
    daw.key("Control+a")
    daw.page.locator("#b-more").click()
    daw.page.locator("#b-saveas").wait_for()
    daw.key("Escape")
    daw.page.locator("#b-saveas").wait_for(state="hidden")
    assert len(daw.selected()) == 3


def test_inspector(daw):
    daw.set_notes(THREE)
    daw.page.mouse.click(*daw.mid(1))
    daw.page.get_by_label("Pitch", exact=True).fill("F#4")
    daw.page.keyboard.press("Tab")
    daw.page.keyboard.type("2.5")
    daw.page.keyboard.press("Tab")
    daw.page.keyboard.type("1/3")
    daw.page.keyboard.press("Enter")
    assert daw.notes()[1] == [66, 1200, 160]
    f = daw.page.get_by_label("Velocity")
    f.fill("900")
    f.press("Enter")
    assert f.input_value() == "100"


def test_zoom_and_playhead(daw):
    daw.set_notes(THREE)
    x, y = daw.mid(2)
    before = daw.px(480)
    daw.page.mouse.move(x, y)
    daw.page.keyboard.down("Control")
    daw.page.mouse.wheel(0, -300)
    daw.page.wait_for_timeout(50)
    daw.page.keyboard.up("Control")
    assert daw.px(480) > before * 1.1
    assert abs(daw.mid(2)[0] - x) < 3, "zoom stays centred on the pointer"
    daw.key("f")
    r = daw.page.locator("#roll").bounding_box()
    daw.page.mouse.click(daw.x0() + daw.px(970), r["y"] + 12)
    assert daw.js("() => tunelab.player.position()") == 960
    # interaction stays right when scrolled
    daw.key("=")
    daw.key("=")
    daw.js("() => { const r = document.querySelector('#roll'); r.scrollLeft = 150; r.scrollTop += 40; }")
    daw.page.wait_for_timeout(50)
    x, y = daw.mid(2)
    daw.drag((x, y), (x + daw.px(240), y + daw.row()))
    assert daw.notes()[2] == [66, 1200, 480]


def test_playback(daw):
    daw.set_notes([[60, 0, 480], [64, 480, 480], [67, 960, 480], [60, 1440, 480]])
    daw.key("Space")
    daw.page.wait_for_timeout(900)
    assert daw.page.locator("#b-play").inner_text() == "Pause"
    assert daw.js("() => tunelab.player.position()") > 200
    daw.js("() => { const s = tunelab.store; s.commit({...s.state.project, bpm: 200}); }")
    daw.key("Space")
    daw.page.wait_for_timeout(50)
    at = daw.js("() => tunelab.player.position()")
    daw.page.wait_for_timeout(200)
    assert daw.js("() => tunelab.player.position()") == at > 0
    daw.key("Space")
    daw.page.wait_for_timeout(2500)
    assert daw.page.locator("#b-play").inner_text() == "Play", "stops by itself at the end"
    assert daw.js("() => tunelab.player.position()") == 0


def test_sound_is_produced(daw):
    daw.set_notes([[60, 0, 1920]])
    peak = daw.js("""async () => { const meter = new Tone.Meter(); Tone.getDestination().connect(meter);
        await tunelab.player.toggle(); let best = -Infinity;
        for (let i = 0; i < 20; i++) { await new Promise(r => setTimeout(r, 40)); best = Math.max(best, meter.getValue()); }
        tunelab.player.stop(); return best; }""")
    assert peak > -40


def test_clicks_sound_at_once(daw):
    """The sound is triggered inside the click, before the redraw, with no look-ahead added."""
    daw.set_notes(THREE)
    daw.js("""async () => { await Tone.start(); window.heard = []; window.redraws = 0;
        const P = Tone.PolySynth.prototype, o = P.triggerAttackRelease;
        P.triggerAttackRelease = function (n, d, t, v) { heard.push([t - Tone.immediate(), redraws]); return o.call(this, n, d, t, v); };
        tunelab.store.subscribe(() => { redraws++; }); redraws = 0; }""")
    daw.page.mouse.click(*daw.mid(1))
    assert daw.selected() == [64]
    r = daw.page.locator("#roll").bounding_box()
    daw.page.mouse.click(r["x"] + 20, r["y"] + 100)
    heard = daw.js("() => heard")
    assert len(heard) == 2 and all(abs(late) < 0.02 for late, _ in heard)
    assert heard[0][1] == 0, "sound comes before the redraw"


def test_pressed_key_lights_up(daw):
    daw.set_notes(THREE)
    lit = lambda: daw.js("() => tunelab.roll.lit()")  # noqa: E731
    x, y = daw.mid(1)
    daw.page.mouse.move(x, y)
    daw.page.mouse.down()
    assert lit() == 64
    daw.page.mouse.move(x, y - 2 * daw.row(), steps=4)
    assert lit() == 66, "follows a dragged note"
    daw.page.mouse.up()
    daw.page.wait_for_function("tunelab.roll.lit() === null")
    daw.page.mouse.move(daw.page.locator("#roll").bounding_box()["x"] + 20, daw.mid(0)[1])
    daw.page.mouse.down()
    daw.page.wait_for_timeout(250)
    assert lit() == 60, "stays lit while held"
    daw.page.mouse.up()
    daw.page.wait_for_function("tunelab.roll.lit() === null")


def test_tracks(daw):
    daw.set_notes(THREE)
    daw.page.get_by_text("Add track").click()
    assert daw.notes() == []
    daw.page.locator(".track select").nth(1).select_option("bell")
    daw.page.get_by_label("Mute").nth(1).click()
    t = daw.js("() => tunelab.store.state.project.tracks.map(t => [t.sound, t.muted, t.notes.length])")
    assert t == [["soft", False, 3], ["bell", True, 0]]
    daw.page.get_by_label("Delete track").nth(0).click()
    daw.page.get_by_role("button", name="Delete", exact=True).last.click()
    daw.page.wait_for_function("tunelab.store.state.project.tracks.length === 1")
    daw.key("Control+z")
    daw.page.locator(".track").nth(0).click(position={"x": 4, "y": 40})
    assert daw.notes() == THREE


def test_save_reload_conflict(daw, tmp_path):
    p = daw.page
    daw.set_notes(THREE)
    assert "unsaved" in p.locator("#title").inner_text()
    daw.key("Control+s")
    p.get_by_label("Project name").fill("First Song")
    daw.key("Enter")
    p.wait_for_function("!tunelab.store.dirty()")
    assert p.locator("#title").inner_text() == "First Song"
    daw.key("Control+a")
    daw.key("ArrowUp")
    daw.key("Control+s")
    p.wait_for_function("!tunelab.store.dirty()")
    saved = json.loads((tmp_path / "lib/projects/first-song.json").read_text())
    assert [n["pitch"] for n in saved["tracks"][0]["notes"]] == [61, 65, 68]
    daw.open("/daw")
    daw.key("Control+o")
    p.get_by_role("button", name="Open", exact=True).click()
    p.wait_for_function("tunelab.store.state.project.name === 'First Song'")
    assert daw.notes() == [[61, 0, 480], [65, 480, 240], [68, 960, 480]]
    saved["bpm"] = 55
    (tmp_path / "lib/projects/first-song.json").write_text(json.dumps(saved))
    daw.key("Control+a")
    daw.key("ArrowUp")
    daw.key("Control+s")
    p.get_by_role("button", name="Cancel").click()
    p.wait_for_timeout(100)
    assert json.loads((tmp_path / "lib/projects/first-song.json").read_text())["bpm"] == 55
    daw.key("Control+s")
    p.get_by_role("button", name="Overwrite it").click()
    p.wait_for_function("!tunelab.store.dirty()")
    assert json.loads((tmp_path / "lib/projects/first-song.json").read_text())["bpm"] == 100


def test_unsaved_guard(daw):
    p = daw.page
    daw.set_notes(THREE)
    p.locator("#b-new").click()
    p.get_by_role("button", name="Cancel").click()
    assert daw.notes() == THREE
    p.locator("#b-new").click()
    daw.key("Escape")
    assert daw.notes() == THREE
    p.locator("#b-new").click()
    p.get_by_role("button", name="Discard changes").click()
    p.wait_for_function("tunelab.store.track().notes.length === 0")


def test_export_import(daw, tmp_path):
    p = daw.page
    daw.set_notes(THREE)
    files = {}
    for b in ("#b-exp-project", "#b-exp-midi", "#b-exp-melody", "#b-exp-text"):
        p.locator("#b-more").click()
        with p.expect_download() as d:
            p.locator(b).click()
        files[b] = tmp_path / d.value.suggested_filename
        d.value.save_as(files[b])
    assert {f.suffix for f in files.values()} == {".json", ".mid", ".tune"}
    for b, f in files.items():
        daw.open("/daw")
        assert daw.notes() == []
        p.locator("#file").set_input_files(f)
        if b != "#b-exp-project":
            p.get_by_role("button", name="New project").click()
        p.wait_for_function("tunelab.store.track().notes.length === 3")
        assert daw.notes() == THREE, b
    p.locator("#file").set_input_files(files["#b-exp-midi"])
    p.get_by_role("button", name="Tracks in this project").click()
    p.wait_for_function("tunelab.store.state.project.tracks.length === 2")
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    p.locator("#file").set_input_files(bad)
    p.get_by_text("not a Tunelab project").wait_for()
    assert daw.js("() => tunelab.store.state.project.tracks.length") == 2


def test_melody_library_and_favorites(daw):
    p = daw.page
    daw.set_notes(THREE)
    p.locator("#b-more").click()
    p.locator("#b-savemelody").click()
    p.get_by_label("Melody name").fill("Hook")
    daw.key("Enter")
    p.get_by_text('Saved melody').wait_for()
    daw.key("Control+o")
    p.get_by_role("button", name="Melodies (1)").click()
    p.get_by_label("Favorite", exact=True).click()
    p.locator(".star[aria-pressed=true]").wait_for()
    p.get_by_label("Favorites only").check()
    p.get_by_role("button", name="Rename").click()
    p.get_by_label("New name").fill("Hook 2")
    daw.key("Enter")
    p.get_by_text("Hook 2").wait_for()
    p.get_by_role("button", name="Add to project").click()
    p.wait_for_function("tunelab.store.state.project.tracks.length === 2")
    assert daw.notes() == THREE
    daw.key("Control+o")
    p.get_by_role("button", name="Delete", exact=True).last.click()
    p.locator("dialog.ask").get_by_role("button", name="Delete").click()
    p.get_by_text("No favorites here yet").wait_for()


def test_rebinding_shortcuts(daw):
    p = daw.page
    daw.set_notes(THREE)
    p.locator("#b-settings").click()
    p.get_by_label("Change key for Draw tool").click()
    daw.key("g")
    p.wait_for_function("[...document.querySelectorAll('button.key')].some(b => b.textContent === 'G')")
    # taken key: swap
    p.get_by_label("Change key for Erase tool").click()
    daw.key("v")
    p.get_by_role("button", name="Swap").click()
    p.wait_for_function("document.querySelector('[aria-label=\"Change key for Select tool\"]').textContent === 'E'")
    daw.key("Escape")
    daw.key("g")
    assert daw.js("() => tunelab.store.state.tool") == "draw"
    daw.key("v")
    assert daw.js("() => tunelab.store.state.tool") == "erase"
    daw.open("/daw")
    daw.key("g")
    assert daw.js("() => tunelab.store.state.tool") == "draw", "kept after reload"
    daw.key("b")
    assert daw.js("() => tunelab.store.state.tool") == "draw"


def test_tempo_tools(daw):
    p = daw.page
    daw.set_notes([[60, i * 360, 300] for i in range(8)])  # really 133 bpm written at 100
    daw.key("t")
    p.get_by_label("New tempo").fill("133")
    p.get_by_role("button", name="Change, keep the sound").click()
    assert daw.js("() => tunelab.store.state.project.bpm") == 133
    assert all(abs(n[1] - i * 478.8) <= 1 for i, n in enumerate(daw.notes()))
    p.get_by_role("button", name="Snap to grid").click()
    assert all(n[1] == i * 480 for i, n in enumerate(daw.notes()))
    p.get_by_role("button", name="Score this track").click()
    p.get_by_text("Score 0.").wait_for()
    p.get_by_role("button", name="Notes half as long").click()
    assert daw.notes()[1][1] == 240
    daw.key("Escape")
    daw.key("Control+z")
    daw.key("Control+z")
    daw.key("Control+z")
    assert daw.js("() => tunelab.store.state.project.bpm") == 100 and daw.notes()[1][1] == 360


def test_generator_to_daw(daw):
    p = daw.page
    p.goto(daw.url + "/generator")
    p.locator("[name=count]").fill("60")
    p.locator("[name=top_percent]").fill("40")
    p.locator("#gen button").click()
    p.locator("#tunes .tune").first.wait_for()
    star = p.locator("#tunes .star").first
    star.click()
    p.locator("#tunes .star[aria-pressed=true]").first.wait_for()
    p.reload()
    p.locator("#tunes .star[aria-pressed=true]").first.wait_for()
    p.get_by_text("Open in DAW").first.click()
    p.wait_for_function("window.tunelab && tunelab.store.state.project.tracks.length === 2")
    assert len(daw.notes()) > 5 and p.url.endswith("/daw")
    daw.key("Control+o")
    p.get_by_role("button", name="Melodies (1)").wait_for()


def test_many_notes_stay_usable(daw):
    daw.set_notes([[48 + i % 36, i * 60, 60] for i in range(3000)])
    ms = daw.js("""() => { const t = performance.now(); tunelab.store.select(tunelab.store.track().notes.map(n => n.id));
        tunelab.store.select([]); return (performance.now() - t) / 2; }""")
    assert ms < 400
