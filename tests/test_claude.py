#!/usr/bin/env python3
"""Is Claude a guest rather than a fixture, and does going places stay quick?

Two things this release changed and neither can be checked by eye:

  *Claude is summoned.* Nothing is on screen and no process exists until you
  ask, it opens in the place you chose, and moving it between the three places
  keeps the session — it is a re-parent, not a restart. The whole point is lost
  if a move quietly kills whatever Claude was in the middle of, so the shell is
  a real one here and the check is that the same process is still on the other
  side of the move with its scrollback intact.

  *Going places.* Ctrl+P is a fuzzy list of the workspace's files, and the same
  box takes > for commands and : for a line. The list is walked off the main
  loop, so what is asserted is that it filters, not how fast it walks.
"""
import os
import shutil
import sys
import tempfile

SP = os.environ.get("IRIS_TEST_TMP", "/tmp/iris-tests")
os.makedirs(SP, exist_ok=True)
os.environ["XDG_CONFIG_HOME"] = os.path.join(SP, "xdg-prism-claude")
os.environ["XDG_CACHE_HOME"] = os.path.join(SP, "xdg-prism-claude", "cache")
os.environ.setdefault("GDK_BACKEND", "broadway")
os.environ.setdefault("BROADWAY_DISPLAY", ":14")
sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))


def _ensure_display():
    import socket
    import subprocess
    import time
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", 8094))
        probe.close()
        return
    except OSError:
        pass
    subprocess.Popen(["broadwayd", ":14"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(2)


_ensure_display()

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, Gtk, Vte  # noqa: E402

import core  # noqa: E402
import palette as palette_mod  # noqa: E402
import workspace  # noqa: E402
from main import PrismApp  # noqa: E402

fails = []
ran = {"n": 0}
BASE = tempfile.mkdtemp(prefix="prism-claude-")


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


# a small workspace to go places in
PROJECT = os.path.join(BASE, "demo")
for folder in ("", "src", "src/deep", "docs"):
    os.makedirs(os.path.join(PROJECT, folder), exist_ok=True)
for name in ("readme.md", "src/main.py", "src/helper.py",
             "src/deep/buried_thing.py", "docs/notes.txt"):
    with open(os.path.join(PROJECT, name), "w") as fh:
        fh.write("print('hello')\n")
os.makedirs(os.path.join(PROJECT, "node_modules", "junk"), exist_ok=True)
with open(os.path.join(PROJECT, "node_modules", "junk", "index.js"), "w") as fh:
    fh.write("// should never be offered\n")

app = PrismApp()
app.set_application_id("net.test.PrismClaude")


def start():
    win = app.props.active_window
    if win is None:
        fails.append("no window: another instance answered")
        app.quit()
        return False
    # `cat` is a shell that stays up and echoes: a session that is easy to
    # recognise on the far side of a move.
    win.cfg["CLAUDE_CMD"] = "cat"
    win.set_default_size(1300, 850)
    win.open_folder(PROJECT, restore=False)

    def pump(times=200):
        for _ in range(times):
            if not Gtk.events_pending():
                break
            Gtk.main_iteration_do(False)

    def screen_text(terminal):
        got = terminal.term.get_text_format(Vte.Format.TEXT) or ""
        return got[0] if isinstance(got, tuple) else got

    def phase1():
        try:
            print("\n-- nothing until you ask --")
            check("Claude is built", win.assistant is not None)
            check("but it is not on screen", win.claude_showing(), False)
            check("and no session is running", win.assistant.started(), False)
            check("the setting agrees that it starts closed",
                  core.DEFAULTS["ASSISTANT"], "0")

            print("\n-- floating over the editor, the default --")
            check("the default place is floating",
                  core.DEFAULTS["CLAUDE_PLACE"], "float")
            win.cfg["CLAUDE_PLACE"] = "float"
            win.show_claude(focus=False, remember=False)
            pump()
            check("it is on screen", win.claude_showing(), True)
            check("in a window of its own", win.claude_window is not None, True)
            check("which is undecorated, so it reads as an overlay",
                  win.claude_window.get_decorated(), False)
            check("and nothing in the layout moved: the panel stayed shut",
                  win.panel.get_visible(), False)
            check("nor did a pane appear beside the editor",
                  win.assistant.get_parent() is not win.middle, True)
            win.hide_claude(remember=False)
            pump()
            check("Escape-and-gone leaves nothing behind",
                  win.claude_showing() or win.claude_window is not None, False)

            print("\n-- summoned into the bottom panel --")
            win.cfg["CLAUDE_PLACE"] = "panel"
            win.show_claude(focus=False, remember=False)
            pump()
            check("it is on screen", win.claude_showing(), True)
            check("in the panel", win.panel.claude_here(), True)
            check("the panel offers it as a tab",
                  win.panel.tab_claude.get_visible(), True)
            check("the panel is open", win.panel.get_visible(), True)
            check("a session started", win.assistant.started(), True)
            check("the editor kept the whole width",
                  win.assistant.get_parent() is not win.middle, True)
            first = win.assistant.terminal
            first.when_ready(lambda: first.term.feed_child(b"a-marked-session\n"))
            GLib.timeout_add_seconds(3, phase2)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 1")
            app.quit()
        return False

    def phase2():
        try:
            first = win.assistant.terminal
            check("the session says something recognisable",
                  "a-marked-session" in screen_text(first), True)

            print("\n-- moved beside the editor, session and all --")
            win.place_claude("side", remember=False)
            pump()
            check("it moved", win.claude_place(), "side")
            check("the panel let it go", win.panel.claude_here(), False)
            check("the panel still has its own tabs",
                  win.panel.tab_claude.get_visible(), False)
            check("the same session came with it",
                  win.assistant.terminal is first, True)
            check("nothing was restarted", first.dead, False)
            check("and its scrollback is intact",
                  "a-marked-session" in screen_text(first), True)

            print("\n-- and out into its own window --")
            win.place_claude("window", remember=False)
            pump()
            check("there is a window now", win.claude_window is not None, True)
            check("still the same session",
                  win.assistant.terminal is first, True)
            check("still alive", first.dead, False)

            print("\n-- put away --")
            win.hide_claude(remember=False)
            pump()
            check("nothing is on screen", win.claude_showing(), False)
            check("the window went with it", win.claude_window, None)
            check("but the session is still there for next time",
                  win.assistant.terminal is first and not first.dead, True)
            check("so summoning it again is the same session",
                  (win.show_claude(focus=False, remember=False)
                   and win.assistant.terminal is first), True)
            phase3()
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 2")
            app.quit()
        return False

    def phase3():
        try:
            print("\n-- going places --")
            files = workspace.walk_files(PROJECT)
            check("the workspace was walked", len(files), 5)
            check("and what is not interesting stayed out",
                  any("node_modules" in f for f in files), False)

            win._files, win._file_at = files, 1e18      # pretend it is fresh
            win._file_root = PROJECT
            box = palette_mod.Palette(win, win.all_commands(), files=files)
            check("an empty box offers every file", len(box.shown), 5)
            box.entry.set_text("buried")
            check("typing narrows it to one", [i.id for i in box.shown],
                  [os.path.join("src", "deep", "buried_thing.py")])
            box.entry.set_text("hlpr")
            check("a loose subsequence still finds it",
                  [i.id for i in box.shown], [os.path.join("src", "helper.py")])
            box.entry.set_text("mainpy")
            check("the file name outranks the folders",
                  box.shown[0].id, os.path.join("src", "main.py"))

            box.entry.set_text(">")
            check("a > turns it into the command list",
                  box.mode()[0], "commands")
            check("and the commands are there",
                  any(i.id == "quick-open" for i in box.shown), True)
            box.entry.set_text(":42")
            check("a : asks for a line", box.mode(), ("line", "42"))
            check("and offers exactly that", box.shown[0].label, "Go to line 42")
            box.destroy()

            print("\n-- Ctrl+Tab goes back, not along --")
            here = os.path.join(PROJECT, "src", "main.py")
            there = os.path.join(PROJECT, "src", "helper.py")
            third = os.path.join(PROJECT, "docs", "notes.txt")
            for path in (here, there, third):
                win.editor.open(path)
            pump()
            check("three files open", len(win.editor.docs) >= 3, True)
            check("sitting in the last one", win.editor.path, third)
            win.editor.recent_file()
            check("Ctrl+Tab goes back to the one before", win.editor.path, there)
            win.editor.recent_file()
            check("and again bounces back, not onward", win.editor.path, third)

            print("\n-- the editor only reads what it needs --")
            win.editor.new_file()
            doc = win.editor.doc()
            doc.buffer.set_text("x = 1\n" * 40000)      # a quarter of a megabyte
            _doc, before, after, _lang = win.editor._context()
            check("the context around the cursor is bounded",
                  len(before) + len(after) <= 10000 + 1, True)
            check("rather than the whole file",
                  doc.buffer.get_char_count() > 200000, True)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 3")
        finally:
            app.quit()
        return False

    GLib.timeout_add(2000, phase1)
    return False


GLib.timeout_add(900, start)
app.run([sys.argv[0]])

shutil.rmtree(BASE, ignore_errors=True)
if not ran["n"]:
    fails.append("no checks ran at all")
print("\n%d checks" % ran["n"])
print("ALL PASS" if not fails else "FAILED: %r" % fails)
sys.exit(1 if fails else 0)
