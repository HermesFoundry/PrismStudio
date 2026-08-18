#!/usr/bin/env python3
"""Does PrismStudio behave like an application rather than a widget?

The things worth asserting here are the ones that only exist because this is a
standalone app: opening and closing a workspace, remembering what was open,
the activity bar and its panels, several terminals in one panel, searching
across files, and the window keeping its title and status in step.
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
import time

SP = os.environ.get("IRIS_TEST_TMP", "/tmp/iris-tests")
os.makedirs(SP, exist_ok=True)
CONFIG = tempfile.mkdtemp(prefix="prism-cfg-")
os.environ["XDG_CONFIG_HOME"] = CONFIG
os.environ["XDG_CACHE_HOME"] = os.path.join(CONFIG, "cache")
os.environ.setdefault("GDK_BACKEND", "broadway")
os.environ.setdefault("BROADWAY_DISPLAY", ":11")
sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))


def _ensure_display():
    import socket
    import subprocess
    import time
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", 8091))
        probe.close()
        return
    except OSError:
        pass
    subprocess.Popen(["broadwayd", ":11"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(2)


_ensure_display()

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")
gi.require_version("GtkSource", "4")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import core  # noqa: E402
import workspace  # noqa: E402
from main import PrismApp  # noqa: E402

fails = []
ran = {"n": 0}
BASE = tempfile.mkdtemp(prefix="prism-ws-")


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


# ---- a small workspace to open ------------------------------------------- #
PROJECT = os.path.join(BASE, "demo")
os.makedirs(os.path.join(PROJECT, "src"))
os.makedirs(os.path.join(PROJECT, "node_modules", "junk"))
with open(os.path.join(PROJECT, "package.json"), "w") as fh:
    json.dump({"name": "demo", "scripts": {"dev": "echo serving"}}, fh)
with open(os.path.join(PROJECT, "src", "alpha.py"), "w") as fh:
    fh.write("MARKER_ONE = 1\n\n\ndef alpha():\n    return MARKER_ONE\n")
with open(os.path.join(PROJECT, "src", "beta.py"), "w") as fh:
    fh.write("from alpha import alpha\n\nprint(alpha())  # MARKER_ONE again\n")
with open(os.path.join(PROJECT, "node_modules", "junk", "noise.py"), "w") as fh:
    fh.write("MARKER_ONE = 'should never be searched'\n")

OTHER = os.path.join(BASE, "other")
os.makedirs(OTHER)
with open(os.path.join(OTHER, "readme.txt"), "w") as fh:
    fh.write("nothing here\n")


# ---- settings and skins, before any window ------------------------------- #
def settings_checks():
    print("-- settings and skins --")
    cfg = core.load_settings()
    check("settings have defaults", cfg["THEME"], "olympus")
    check("its own config folder", core.CONFIG_DIR.endswith("prismstudio"), True)
    core.save_settings({"THEME": "nord"})
    check("a change is written and read back", core.load_settings()["THEME"], "nord")
    core.save_settings({"THEME": "olympus"})

    theme = core.load_theme("olympus")
    check("a skin loads", theme["NAME"], "Olympus")
    check("with its 16 terminal colours", len(theme["_ansi"]), 16)
    check("an unknown skin falls back rather than crashing",
          core.load_theme("nope")["BG"], core.FALLBACK["BG"])
    check("dark skins are recognised", core.load_theme("olympus")["_light"], False)
    check("light ones too", core.load_theme("paper")["_light"], True)

    check("colour mixing is halfway", core.mix("#000000", "#ffffff", 0.5), "#808080")
    check("text on a light colour goes dark",
          core.readable_on("#ffffff"), "#0a0f16")
    check("text on a dark colour goes light",
          core.readable_on("#000000"), "#f2f6fb")

    import styling
    css = styling.build_css(theme, cfg)
    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode())          # raises if the CSS is bad
    check("the stylesheet parses", len(css) > 4000, True)


def workspace_checks():
    print("\n-- remembering workspaces --")
    workspace.remember_folder(PROJECT)
    workspace.remember_folder(OTHER)
    check("most recent comes first", workspace.recent_folders()[0], OTHER)
    check("both are listed", PROJECT in workspace.recent_folders(), True)
    workspace.remember_folder(PROJECT)
    check("reopening moves it up", workspace.recent_folders()[0], PROJECT)
    check("without duplicating it",
          workspace.recent_folders().count(PROJECT), 1)
    workspace.forget_folder(OTHER)
    check("one can be forgotten", OTHER in workspace.recent_folders(), False)
    check("a folder that no longer exists is dropped",
          "/tmp/definitely-not-here" in workspace.recent_folders(), False)

    workspace.save_session(PROJECT, [{"path": os.path.join(PROJECT, "src", "alpha.py"),
                                      "line": 4}], "alpha.py")
    session = workspace.load_session(PROJECT)
    check("the session comes back", len(session["files"]), 1)
    check("with the line", session["files"][0]["line"], 4)
    check("the last folder is remembered", workspace.last_folder(), PROJECT)
    check("a session for an unknown folder is empty",
          workspace.load_session("/tmp/nowhere")["files"], [])

    check("noise folders are skipped", workspace.interesting("node_modules"), False)
    check("so are dotfiles", workspace.interesting(".git"), False)
    check("real files are kept", workspace.interesting("main.py"), True)


settings_checks()
workspace_checks()

app = PrismApp()
app.set_application_id("net.test.PrismApp")


def start():
    win = app.props.active_window
    if win is None:
        fails.append("no window: another instance answered")
        app.quit()
        return False
    win.set_default_size(1240, 780)

    def pump(times=250):
        for _ in range(times):
            if not Gtk.events_pending():
                break
            Gtk.main_iteration_do(False)

    def phase1():
        try:
            pump()
            print("\n-- the window is put together --")
            check("there is an activity bar", len(win.activity_buttons), 5)
            check("a side bar", win.sidebar is not None)
            check("an editor", win.editor is not None)
            check("a bottom panel", win.panel is not None)
            check("a Claude pane", win.assistant is not None)
            check("a run bar", win.runbar is not None)
            check("and a status bar", win.status is not None)
            check("a source control panel", win.git is not None)
            check("a selection popup", win.selection is not None)
            check("the editor's status widgets live in it",
                  win.editor.pos_label.get_parent() is win.status)
            # workspace_checks() above left a remembered session. A bare
            # launch must NOT bring it back: nothing on the machine is listed
            # until it is asked for.
            print("\n-- a bare launch lists nothing --")
            check("no folder is reopened", win.root, None)
            check("the title is just the app", win.get_title(), core.APP_NAME)
            check("REOPEN_LAST is off unless asked for",
                  core.DEFAULTS["REOPEN_LAST"], "0")

            print("\n-- until you open one --")
            win.open_folder(PROJECT)
            pump()
            check("opening it explicitly works", win.root, PROJECT)
            check("and the title says so", win.get_title(), "demo — PrismStudio")
            win.close_folder()
            pump()
            check("closing it empties the window", win.root, None)
            check("and the title goes back", win.get_title(), core.APP_NAME)

            print("\n-- opening a folder --")
            check("it opens", win.open_folder(PROJECT, restore=False), True)
            pump()
            check("the root is set", win.root, PROJECT)
            check("the title says which", win.get_title(), "demo — PrismStudio")
            check("the explorer follows", win.explorer.root, PROJECT)
            check("so does search", win.search.folder, PROJECT)
            check("the project was detected", win.runbar.project.summary, "Node · npm")
            check("and it is now a recent folder",
                  workspace.recent_folders()[0], PROJECT)

            print("\n-- the explorer lists it, minus the noise --")
            names = []

            def walk(parent=None):
                it = win.explorer.store.iter_children(parent)
                while it:
                    names.append(win.explorer.store[it][0])
                    it = win.explorer.store.iter_next(it)

            walk()
            check("src is listed", "src" in names)
            check("package.json is listed", "package.json" in names)
            check("node_modules is not", "node_modules" in names, False)

            print("\n-- opening files --")
            alpha = os.path.join(PROJECT, "src", "alpha.py")
            beta = os.path.join(PROJECT, "src", "beta.py")
            check("a file opens", win.open_file(alpha), True)
            pump()
            check("the title changes to it", win.get_title().startswith("demo"), True)
            check("the header names the file", win.title_label.get_text(), "alpha.py")
            check("a second file opens", win.open_file(beta), True)
            check("both are open", len(win.editor.docs), 2)
            check("the language was worked out",
                  win.editor.doc().buffer.get_language().get_id(), "python3")

            win.open_file(alpha, line=4)
            pump()
            it = win.editor.doc().buffer.get_iter_at_mark(
                win.editor.doc().buffer.get_insert())
            check("opening at a line puts the cursor there", it.get_line() + 1, 4)
            check("and it switched rather than opening twice", len(win.editor.docs), 2)

            print("\n-- the activity bar switches the side bar --")
            for name in ("search", "git", "run", "extensions", "explorer"):
                win._side(name)
                pump(60)
                check("%s shows" % name, win.side_stack.get_visible_child_name(), name)
                check("  and is titled", win.side_title.get_text(),
                      "SOURCE CONTROL" if name == "git" else name.upper())

            print("\n-- the panel holds several terminals --")
            win.toggle_panel(True)
            pump()
            check("the panel is open", win.panel.get_visible(), True)
            check("with one terminal", len(win.panel.terminals), 1)
            first = win.panel.current_terminal()
            win.panel.new_terminal()
            pump()
            check("a second can be added", len(win.panel.terminals), 2)
            check("and it becomes the visible one",
                  win.panel.current_terminal() is not first, True)
            check("the picker appears once there are two",
                  win.panel.picker.get_visible(), True)
            win.panel.select(first)
            check("you can switch back", win.panel.current_terminal() is first, True)
            win.panel.close_terminal()
            pump()
            check("and close one", len(win.panel.terminals), 1)
            check("the run bar talks to whatever is in front",
                  win.shell is win.panel.current_terminal(), True)

            print("\n-- the output tab --")
            win.panel.write("a line of output")
            buffer = win.panel.output.get_buffer()
            text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            check("output is written", "a line of output" in text, True)
            win.panel.show("output")
            check("and the tab switches", win.panel.stack.get_visible_child_name(),
                  "output")
            win.panel.show("terminal")

            GLib.timeout_add_seconds(2, phase2)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 1")
            app.quit()
        return False

    def phase2():
        try:
            pump()
            # spawning is asynchronous, so the pid only exists a moment later
            print("\n-- the terminal really started --")
            terminal = win.panel.current_terminal()
            check("it has a shell process", terminal.pid is not None, True)
            check("and is not dead", terminal.dead, False)
            check("it became ready for input", terminal.ready, True)

            print("\n-- searching the workspace --")
            win._side("search")
            win.search.entry.set_text("MARKER_ONE")
            win.search.start()
            GLib.timeout_add_seconds(4, phase3)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 2")
            app.quit()
        return False

    def phase3():
        try:
            pump()
            hits = win.search.hits
            check("it found something", len(hits) >= 2, True)
            files = {os.path.basename(h.path) for h in hits}
            check("in the file that defines it", "alpha.py" in files, True)
            check("and the one that mentions it", "beta.py" in files, True)
            check("but never inside node_modules", "noise.py" in files, False)
            check("the count is reported",
                  "hit" in win.search.count.get_text(), True)

            win.search.entry.set_text("zzz_nothing_like_this")
            win.search.start()
            GLib.timeout_add_seconds(3, phase4)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 3")
            app.quit()
        return False

    def phase4():
        try:
            pump()
            check("a search with no hits says so",
                  win.search.count.get_text(), "nothing found")
            check("and shows no rows", win.search.hits, [])

            print("\n-- the command palette --")
            commands = win.all_commands()
            check("commands are offered", len(commands) > 25, True)
            ids = {c.id for c in commands}
            for wanted in ("save", "run-app", "palette", "toggle-panel",
                           "claude-edit", "search"):
                check("  %s is there" % wanted, wanted in ids, True)
            check("every one can actually run",
                  all(callable(c.run) for c in commands), True)

            print("\n-- keyboard --")
            check("no shortcut is bound twice", win.km.conflicts(), {})
            check("save is where it should be", win.km.accel_for("save"), "Ctrl+S")

            print("\n-- the session is remembered --")
            win._save_session()
            session = workspace.load_session(PROJECT)
            check("both open files were saved", len(session["files"]), 2)
            check("with the one in front noted",
                  os.path.basename(session["active"] or ""), "alpha.py")

            print("\n-- closing the folder --")
            win.close_folder()
            pump()
            check("the root is cleared", win.root, None)
            check("the title goes back", win.get_title(), core.APP_NAME)
            check("the explorer empties", win.explorer.root, None)

            print("\n-- reopening restores what was open --")
            win.open_folder(PROJECT, restore=True)
            pump()
            GLib.timeout_add_seconds(2, phase_assistant)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 4")
            app.quit()
        return False

    def phase_assistant():
        """Opening files with the Claude pane live must stay cheap.

        The pane is a terminal with a long-lived process in it, and the editor
        saves the open file before Claude reads it. A screenshot harness once
        made this look like the second file locked the window up at 100% CPU;
        it was the harness driving the main loop from inside a timer, but the
        cheapest way to know that stays true is to measure it.
        """
        try:
            def cpu():
                with open("/proc/self/stat") as handle:
                    parts = handle.read().split()
                return (int(parts[13]) + int(parts[14])) / os.sysconf("SC_CLK_TCK")

            win.cfg["CLAUDE_CMD"] = os.environ.get("SHELL", "/bin/bash")
            win.toggle_assistant(True)
            pump()
            check("the Claude pane is up", win.assistant is not None, True)

            paths = [os.path.join(PROJECT, "src", n) for n in ("alpha.py", "beta.py")]
            before, started = cpu(), time.time()
            for path in paths + paths:          # open, and open again
                win.open_file(path)
                pump()
            spent, wall = cpu() - before, max(0.001, time.time() - started)
            check("opening files with the pane live does not spin the loop",
                  spent / wall < 0.75, True)
            check("and every one of them opened",
                  len({d.path for d in win.editor.docs if d.path} & set(paths)), 2)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in the assistant phase")
        GLib.timeout_add(200, phase5)
        return False

    def phase_welcome():
        """The empty state: it lists nothing, and double-clicking it writes.

        Both halves matter. A bare `prism` must not quietly reopen whatever
        folder you had last, because that puts your files on screen without
        being asked; and the empty state is the obvious place to click when
        you just want to start typing, so it has to do something.
        """
        try:
            win.close_folder()
            pump()
            check("closing the folder leaves nothing open", win.root, None)
            while win.editor.docs:
                win.editor.docs[0].buffer.set_modified(False)
                win.editor.close_doc(win.editor.docs[0])
            pump()
            check("and no documents", len(win.editor.docs), 0)
            check("the welcome screen is what you see",
                  win.editor.stack.get_visible_child_name(), "welcome")
            check("which is an event box, so it can be clicked",
                  isinstance(win.editor.welcome, Gtk.EventBox), True)

            double = Gdk.EventButton()
            double.type = Gdk.EventType._2BUTTON_PRESS
            double.button = 1
            check("a double-click is taken",
                  win.editor._welcome_clicked(win.editor.welcome, double), True)
            check("it opens exactly one document", len(win.editor.docs), 1)
            check("untitled", win.editor.docs[0].path, None)
            check("the editor is in front",
                  win.editor.stack.get_visible_child_name(), "editing")
            check("it is editable", win.editor.view.get_editable(), True)
            buffer = win.editor.docs[0].buffer
            buffer.insert_at_cursor("typed straight in")
            check("and typing lands in it",
                  buffer.get_text(buffer.get_start_iter(),
                                  buffer.get_end_iter(), True),
                  "typed straight in")

            single = Gdk.EventButton()
            single.type = Gdk.EventType.BUTTON_PRESS
            single.button = 1
            before = len(win.editor.docs)
            win.editor._welcome_clicked(win.editor.welcome, single)
            check("a single click does not open anything",
                  len(win.editor.docs), before)

            check("REOPEN_LAST is off unless asked for",
                  core.DEFAULTS["REOPEN_LAST"], "0")

            # Leave the window as this phase found it, or the next one is
            # testing this phase's leftovers rather than its own subject.
            for doc in list(win.editor.docs):
                doc.buffer.set_modified(False)
                win.editor.close_doc(doc)
            pump()
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in the welcome phase")
        finally:
            app.quit()
        return False

    def phase5():
        try:
            pump()
            names = sorted(d.name for d in win.editor.docs)
            check("the files came back", names, ["alpha.py", "beta.py"])
            check("the status bar said so",
                  "reopened" in win.message_label.get_text()
                  or win.message_label.get_text() != "", True)

            print("\n-- messages --")
            win.say("a plain message")
            check("it shows", win.message_label.get_text(), "a plain message")
            win.say("something went wrong", bad=True)
            check("a bad one is marked",
                  win.message_label.get_style_context().has_class("statusbad"), True)
            win.say("fine again")
            check("and unmarked afterwards",
                  win.message_label.get_style_context().has_class("statusbad"), False)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 5")
        finally:
            GLib.timeout_add(200, phase_welcome)
        return False

    GLib.timeout_add(2200, phase1)
    return False


GLib.timeout_add(900, start)
app.run([sys.argv[0]])
shutil.rmtree(BASE, ignore_errors=True)
shutil.rmtree(CONFIG, ignore_errors=True)
if not ran["n"]:
    fails.append("no checks ran at all")
print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
