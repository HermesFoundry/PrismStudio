#!/usr/bin/env python3
"""Does the window actually look like the thing it is copying?

A skin can now name its own surfaces and its own token colours rather than
having them mixed out of two, which is the only way a palette borrowed from
somewhere else survives the trip. What is worth asserting is that the named
values arrive intact — a stylesheet that quietly derives its own greys is
exactly the bug this was written to catch — and that the pieces the shape
depends on are really there: breadcrumbs, a minimap, indent guides.
"""
import os
import sys
import tempfile

SP = os.environ.get("IRIS_TEST_TMP", "/tmp/iris-tests")
os.makedirs(SP, exist_ok=True)
os.environ["XDG_CONFIG_HOME"] = os.path.join(SP, "xdg-prism-look")
os.environ["XDG_CACHE_HOME"] = os.path.join(SP, "xdg-prism-look", "cache")
os.environ.setdefault("GDK_BACKEND", "broadway")
os.environ.setdefault("BROADWAY_DISPLAY", ":15")
sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))


def _ensure_display():
    import socket
    import subprocess
    import time
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", 8095))
        probe.close()
        return
    except OSError:
        pass
    subprocess.Popen(["broadwayd", ":15"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(2)


_ensure_display()

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, Gtk  # noqa: E402

import badges  # noqa: E402
import core  # noqa: E402
import sourcestyle  # noqa: E402
import styling  # noqa: E402
from main import PrismApp  # noqa: E402

fails = []
ran = {"n": 0}
BASE = tempfile.mkdtemp(prefix="prism-look-")


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


PROJECT = os.path.join(BASE, "demo")
os.makedirs(os.path.join(PROJECT, "src", "deep"), exist_ok=True)
SAMPLE = os.path.join(PROJECT, "src", "deep", "sample.py")
with open(SAMPLE, "w") as fh:
    fh.write("def outer():\n    if True:\n        return 1\n" * 20)


def skin_checks():
    print("-- a skin can name its own surfaces --")
    theme = core.load_theme("vscode")
    check("the skin loads", theme["NAME"], "VS Code Dark+")
    check("the editor colour is its own", theme["BG"], "#1e1e1e")
    check("and so is the activity bar", theme.get("SURFACE_ACTIVITY"), "#333333")
    check("and the status bar", theme.get("SURFACE_STATUS"), "#007acc")

    css = styling.build_css(theme, core.DEFAULTS)
    check("the stylesheet uses the named status bar",
          ".statusbar {" in css and "#007acc" in css.split(".statusbar {")[1][:120], True)
    check("and the named activity bar",
          "#333333" in css.split(".activitybar {")[1][:80], True)
    check("and the named tab colour", "#2d2d2d" in css, True)
    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode())        # raises if any of it is bad

    print("\n-- and its own token colours --")
    xml = sourcestyle.scheme_xml(theme)
    for what, colour in (("comments", "#6a9955"), ("strings", "#ce9178"),
                         ("keywords", "#569cd6"), ("control words", "#c586c0"),
                         ("functions", "#dcdcaa"), ("types", "#4ec9b0"),
                         ("the selection", "#264f78")):
        check("  %s" % what, colour in xml, True)

    print("\n-- skins that name nothing still work --")
    for name in ("olympus", "nord", "paper", "mono"):
        Gtk.CssProvider().load_from_data(
            styling.build_css(core.load_theme(name), core.DEFAULTS).encode())
    check("every shipped skin still builds a stylesheet", True, True)

    print("\n-- the file tiles --")
    check("a python file is py", badges.letters_for("main.py"), "py")
    check("json gets a symbol", badges.letters_for("package.json"), "{}")
    check("an unknown extension takes its first two",
          badges.letters_for("notes.rst"), "rs")
    tile = badges.badge("py", "#569cd6")
    check("and a tile is drawn at the size it is shown",
          (tile.get_width(), tile.get_height()), (16, 16))
    check("drawn once and kept", badges.badge("py", "#569cd6") is tile, True)


app = PrismApp()
app.set_application_id("net.test.PrismLook")


def start():
    win = app.props.active_window
    if win is None:
        fails.append("no window: another instance answered")
        app.quit()
        return False
    win.open_folder(PROJECT, restore=False)

    def pump(times=200):
        for _ in range(times):
            if not Gtk.events_pending():
                break
            Gtk.main_iteration_do(False)

    def phase1():
        try:
            print("\n-- breadcrumbs --")
            win.open_file(SAMPLE)
            pump()
            crumbs = [w.get_label() for w in win.editor.crumbs.get_children()
                      if isinstance(w, Gtk.Button)]
            check("one crumb per folder, and the file",
                  crumbs, ["src", "deep", "sample.py"])
            check("the strip is showing", win.editor.crumbs.get_visible(), True)
            win.cfg["BREADCRUMBS"] = "0"
            win.editor._sync_crumbs()
            check("and it can be switched off",
                  win.editor.crumbs.get_visible(), False)
            win.cfg["BREADCRUMBS"] = "1"
            win.editor._sync_crumbs()

            print("\n-- the minimap --")
            check("it is on by default", core.DEFAULTS["MINIMAP"], "1")
            check("the widget is there", win.editor.minimap is not None, True)
            win.editor.show_minimap(True)
            pump()
            check("and showing", win.editor.minimap.get_visible(), True)
            first, last = win.editor.visible_lines()
            check("it knows what is on screen", last >= first, True)
            win.editor.scroll_to_line(40)
            pump()
            check("and scrolling to a line works",
                  win.editor.visible_lines()[1] > 0, True)
            win.editor.show_minimap(False)
            pump()
            check("it can be switched off", win.editor.minimap.get_visible(), False)

            print("\n-- indent guides --")
            check("on by default", core.DEFAULTS["INDENT_GUIDES"], "1")
            check("the editor knows what colour to draw them",
                  win.editor._guide_rgba is not None, True)
            check("and the drawing hook says no to a plain expose",
                  win.editor._draw_guides(win.editor.view,
                                          _NullContext()), False)

            print("\n-- the menu bar is back where it belongs --")
            check("it is a real menu bar",
                  isinstance(win.app_menu, Gtk.MenuBar), True)
            check("with the groups on it", len(win.app_menu.get_children()) >= 6, True)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 1")
        finally:
            app.quit()
        return False

    GLib.timeout_add(1800, phase1)
    return False


class _NullContext:
    """Enough of a cairo context to prove the guide hook bails out safely."""

    def __getattr__(self, _name):
        return lambda *a, **k: None


skin_checks()
GLib.timeout_add(900, start)
app.run([sys.argv[0]])

import shutil  # noqa: E402
shutil.rmtree(BASE, ignore_errors=True)
if not ran["n"]:
    fails.append("no checks ran at all")
print("\n%d checks" % ran["n"])
print("ALL PASS" if not fails else "FAILED: %r" % fails)
sys.exit(1 if fails else 0)
