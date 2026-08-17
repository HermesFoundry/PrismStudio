#!/usr/bin/env python3
"""Do extensions load, register, and stay out of each other's way?

The important properties: a broken extension must not stop the good ones, a
disabled one must not run, an extension's completion provider must actually
reach the ghost text, and the command palette must find things by fuzzy name.
"""
import importlib
import os
import shutil
import sys
import tempfile

SP = os.environ.get("IRIS_TEST_TMP", "/tmp/iris-tests")
os.makedirs(SP, exist_ok=True)
HOME_CFG = tempfile.mkdtemp(prefix="prism-ext-")
os.environ["XDG_CONFIG_HOME"] = HOME_CFG
os.environ.setdefault("GDK_BACKEND", "broadway")
os.environ.setdefault("BROADWAY_DISPLAY", ":9")
sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))


def _ensure_display():
    import socket
    import subprocess
    import time
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", 8089))
        probe.close()
        return
    except OSError:
        pass
    subprocess.Popen(["broadwayd", ":9"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(2)


_ensure_display()

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import assist  # noqa: E402
import extensions  # noqa: E402
import palette  # noqa: E402

importlib.reload(extensions)

fails = []
ran = {"n": 0}
SHIPPED = os.path.expanduser("~/PrismStudio/extensions")


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


try:
    print("-- installing the two shipped examples --")
    for name in ("wordcount.py", "tidy.py"):
        ok, message = extensions.Registry.install_path(os.path.join(SHIPPED, name))
        check("installed %s" % name, ok, True)
    again, message = extensions.Registry.install_path(os.path.join(SHIPPED, "tidy.py"))
    check("installing twice is refused, not silently duplicated", again, False)
    check("and says why", "already installed" in message)

    bad, message = extensions.Registry.install_path("/no/such/thing.py")
    check("a missing path is refused", bad, False)

    print("\n-- loading --")
    reg = extensions.Registry()
    found = reg.load_all()
    check("both were found", sorted(e.name for e in found), ["tidy", "wordcount"])
    check("neither failed", [e.error for e in found], [None, None])
    check("blurbs come from the module",
          reg.extensions[1].blurb.startswith("Counts lines"))
    check("commands were registered",
          sorted(c.id for c in reg.commands), ["tidy.strip", "wordcount.count"])
    check("the save hook was registered", [n for n, _ in reg.on_save], ["tidy"])
    check("the completion provider was registered", [n for n, _ in reg.completers], ["tidy"])

    print("\n-- an extension's suggestion reaches the engine --")
    engine = assist.LocalEngine()
    engine.extra = reg.completer_functions()
    got = engine.suggest("# TO", "\n", {}, "python3")
    check("it offered something", bool(got))
    check("with the extension's text", got[0].text, "DO: ")
    check("and is labelled as coming from an extension", got[0].detail, "extension")
    check("it stays quiet when it has nothing",
          [s for s in engine.suggest("x = 1", "\n", {}, "python3") if s.detail == "extension"],
          [])

    print("\n-- a broken extension is contained --")
    with open(os.path.join(extensions.FOLDER, "broken.py"), "w") as fh:
        fh.write("import a_module_that_is_not_installed_anywhere\n\n"
                 "def register(iris):\n    pass\n")
    with open(os.path.join(extensions.FOLDER, "noregister.py"), "w") as fh:
        fh.write("# no register function at all\n")
    reg2 = extensions.Registry()
    reg2.load_all()
    broken = {e.name: e for e in reg2.extensions}
    check("the broken one is flagged", bool(broken["broken"].error))
    check("so is the one with no register()", bool(broken["noregister"].error))
    check("the message says what is missing",
          "register" in broken["noregister"].error)
    check("the good ones still loaded",
          [broken[n].error for n in ("tidy", "wordcount")], [None, None])
    check("and their commands are still there", len(reg2.commands), 2)
    check("the failures were logged", len(reg2.messages), 2)

    print("\n-- disabling --")
    extensions.Registry.set_disabled({"tidy", "broken", "noregister"})
    reg3 = extensions.Registry()
    reg3.load_all()
    check("tidy is off", {e.name: e.enabled for e in reg3.extensions}["tidy"], False)
    check("wordcount is still on",
          {e.name: e.enabled for e in reg3.extensions}["wordcount"], True)
    check("a disabled extension registers nothing", [n for n, _ in reg3.completers], [])
    check("only the enabled command remains",
          [c.id for c in reg3.commands], ["wordcount.count"])
    extensions.Registry.set_disabled(set())

    print("\n-- hooks fire, and a throwing hook does not escape --")
    reg4 = extensions.Registry()
    reg4.load_all()
    seen = []
    reg4.on_save.append(("test", lambda p: seen.append(p)))
    reg4.on_save.append(("boom", lambda p: 1 / 0))
    reg4.fire("on_save", "/tmp/x.py")
    check("the good hook ran", seen, ["/tmp/x.py"])
    check("the throwing one was caught and logged",
          any("boom" in m for m in reg4.messages))

    print("\n-- removing --")
    ok, message = extensions.Registry.remove("wordcount")
    check("removed", ok, True)
    check("it is gone from disk",
          "wordcount" not in [e.name for e in extensions.Registry.found()])
    ok, message = extensions.Registry.remove("wordcount")
    check("removing it twice is refused", ok, False)

    print("\n-- the command palette --")
    check("an exact substring scores best", palette.score("save", "Editor: save file"), 8)
    check("a subsequence still matches", palette.score("cmp", "Command palette") is not None)
    check("nonsense does not match", palette.score("zzq", "Command palette"), None)
    check("an empty search matches everything", palette.score("", "anything"), 0)

    commands = [extensions.Command("a", "Code: Have Claude change this", lambda: None),
                extensions.Command("b", "Tabs: New tab", lambda: None),
                extensions.Command("c", "Word count", lambda: None, "wordcount")]
    parent = Gtk.Window()
    parent.set_default_size(900, 700)
    pal = palette.Palette(parent, commands)
    check("everything shows with an empty box", len(pal.shown), 3)
    pal.entry.set_text("claude")
    pal.refilter()
    check("filtering narrows it", [c.id for c in pal.shown], ["a"])
    pal.entry.set_text("wrdct")
    pal.refilter()
    check("a loose subsequence still finds it", [c.id for c in pal.shown], ["c"])
    pal.entry.set_text("zzzzzz")
    pal.refilter()
    check("no match shows nothing", pal.shown, [])
    check("and does not crash the list", len(pal.list.get_children()), 0)

    pal.entry.set_text("")
    pal.refilter()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    check("the first row is selected so Enter always has a target",
          pal.list.get_selected_row() is not None)
    ran_it = []
    pal.shown[0].run = lambda: ran_it.append(1)
    pal.list.select_row(pal.list.get_row_at_index(0))
    pal.run_selected()
    check("Enter runs the selected command", ran_it, [1])

    print("\n-- placing it on screen --")
    pal2 = palette.Palette(parent, commands)
    pal2.show_all()
    pal2.place_over(parent)
    x, y = pal2.get_position()
    check("it never lands off the left edge", x >= 0)
    check("it never lands off the top edge", y >= 0)
    pal2.destroy()
    parent.destroy()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("exception during the checks")
finally:
    shutil.rmtree(HOME_CFG, ignore_errors=True)

if not ran["n"]:
    fails.append("no checks ran at all")
print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
