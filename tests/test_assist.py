#!/usr/bin/env python3
"""Does the assistant actually suggest, draw and accept?

The ghost text is painted rather than inserted, so a screenshot is the only
proof it appeared. What this can assert is the part that matters for
correctness: the engine picks the right completion, the ghost knows when it
has gone stale, Tab inserts exactly the suggested characters and nothing else,
and Claude's edits land in the buffer as one undoable change.
"""
import os
import sys

SP = os.environ.get("IRIS_TEST_TMP", "/tmp/iris-tests")
os.makedirs(SP, exist_ok=True)
os.environ["XDG_CONFIG_HOME"] = os.path.join(SP, "xdg-prism-assist")
os.environ.setdefault("GDK_BACKEND", "broadway")
os.environ.setdefault("BROADWAY_DISPLAY", ":12")
sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))


def _ensure_display():
    import socket
    import subprocess
    import time
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", 8092))
        probe.close()
        return
    except OSError:
        pass
    subprocess.Popen(["broadwayd", ":12"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(2)


_ensure_display()

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, Gtk  # noqa: E402

import assist  # noqa: E402

from main import PrismApp  # noqa: E402

fails = []
ran = {"n": 0}


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


# ---------------------------------------------------------------------------
# the engine on its own — no window needed
# ---------------------------------------------------------------------------
def engine_checks():
    print("\n-- the local engine --")
    eng = assist.LocalEngine()

    body = ("import socket\n"
            "sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "sock = socket.soc")
    counts = eng.words("k", body, 1)
    check("finishes a word from this file",
          eng.word(body, "\n", counts, "python3").text, "ket")
    check("offers the rest of a line you are repeating",
          eng.line_echo(body, "\n").text, "ket(socket.AF_INET, socket.SOCK_STREAM)")
    check("says nothing inside a word", eng.word("soc", "ket", counts, "python3"), None)
    check("says nothing after one letter", eng.word("s", "\n", counts, "python3"), None)
    check("says nothing on a short stem", eng.line_echo("import so", "\n"), None)
    check("knows language keywords",
          eng.word("de", "\n", {}, "python3").text, "f")
    check("prefers the longer line echo first",
          eng.suggest(body, "\n", counts, "python3")[0].source, "local")

    # a long completion must still beat a short one when it is the only match
    long_body = "self.buffer.set_highlight_matching_brackets(True)\nself.buffer.set_high"
    check("a long name is not rejected for being long",
          eng.word(long_body, "\n", eng.words("k2", long_body, 1),
                   "python3").text, "light_matching_brackets")

    check("the index is cached until the buffer changes",
          eng.words("k", body, 1) is eng.words("k", body, 1))
    check("a new revision rebuilds it",
          eng.words("k", body + "\nzebra_zebra = 1", 2).get("zebra_zebra"), 1)

    print("\n-- prompt shapes --")
    fill = assist.ClaudeEngine.fill_prompt("a.py", "python3", "x = 1\ny = ", "\nz = 3")
    check("the fill prompt marks the cursor", "<before>\nx = 1\ny = \n</before>" in fill)
    check("the fill prompt carries what follows", "<after>\n\nz = 3\n</after>" in fill)
    edit = assist.ClaudeEngine.edit_prompt("a.py", "python3", "rename it", "old()",
                                           "head\n", "\ntail")
    check("the edit prompt carries the instruction", "<instruction>\nrename it" in edit)
    check("the edit prompt isolates the fragment", "<fragment>\nold()\n</fragment>" in edit)

    print("\n-- tidying the model's answer --")
    check("a fenced reply is unwrapped",
          assist.strip_fence("```python\nreturn 1\n```"), "return 1")
    check("a bare reply is left alone", assist.strip_fence("return 1"), "return 1")
    check("an inner fence is not eaten",
          assist.strip_fence("x = '```'"), "x = '```'")


engine_checks()

# ---------------------------------------------------------------------------
# the ghost and the editor, in a real window
# ---------------------------------------------------------------------------
app = PrismApp()
app.set_application_id("net.test.PrismAssist")


def start():
    win = app.props.active_window
    if win is None:
        fails.append("no window: another instance answered")
        app.quit()
        return False
    win.set_default_size(1250, 820)
    win.open_folder(os.path.expanduser("~/PrismStudio/app"), restore=False)

    def later():
        try:
            editor = win.editor
            editor.open(os.path.expanduser("~/PrismStudio/app/assist.py"))
            for _ in range(200):
                if not Gtk.events_pending():
                    break
                Gtk.main_iteration_do(False)

            print("\n-- the editor is wired up --")
            check("the editor has an assistant", hasattr(editor, "local"))
            check("it has a ghost bound to the view", editor.ghost.view is editor.view)
            check("it has an edit bar", hasattr(editor, "editbar"))
            check("suggestions start on", editor.suggest_mode in ("local", "claude"))

            doc = editor.doc()
            buf = doc.buffer

            print("\n-- showing and taking a suggestion --")
            buf.set_text("value_from_the_file = 1\nvalue_")
            buf.place_cursor(buf.get_end_iter())
            editor.view.grab_focus()
            editor._suggest_local()
            check("something was suggested", bool(editor.ghost.items))
            # finishing the whole repeated line beats finishing one word, so it
            # is offered first and the word completion waits behind it
            check("the repeated line is offered first",
                  editor.ghost.text, "from_the_file = 1")
            check("the word completion is the alternative",
                  [s.text for s in editor.ghost.items[1:]], ["from_the_file"])
            check("the hint tells you how to take it",
                  "Tab" in editor.hint_label.get_text())
            check("and that there is another one",
                  "1 more" in editor.hint_label.get_text())

            before = doc.text()
            editor.ghost.cycle()
            check("Alt+] moves to the word completion",
                  editor.ghost.text, "from_the_file")
            editor.ghost.accept()
            check("Tab inserted exactly the suggestion",
                  doc.text(), before + "from_the_file")
            check("and the ghost is gone", editor.ghost.items, [])

            print("\n-- it knows when it is out of date --")
            buf.set_text("alpha_beta = 1\nalpha_")
            buf.place_cursor(buf.get_end_iter())
            editor._suggest_local()
            check("suggested again", bool(editor.ghost.items))
            buf.place_cursor(buf.get_start_iter())
            check("moving the cursor makes it stale", editor.ghost.stale())
            check("a stale suggestion refuses to be accepted", editor.ghost.accept(), False)
            check("and it cleared itself", editor.ghost.items, [])

            print("\n-- accepting one word at a time --")
            buf.set_text("do_a_thing(alpha, beta)\ndo_a_")
            buf.place_cursor(buf.get_end_iter())
            editor._suggest_local()
            editor.ghost.index = [i for i, s in enumerate(editor.ghost.items)
                                  if "(" in s.text][0] if any(
                                      "(" in s.text for s in editor.ghost.items) else 0
            whole = editor.ghost.text
            editor.ghost.accept("word")
            got = doc.text().split("\n")[-1]
            check("Ctrl+Right took only the first word", got.startswith("do_a_thing"))
            check("it did not take the whole line",
                  len(got) < len("do_a_") + len(whole))

            print("\n-- an edit that did not come from the keyboard --")
            buf.set_text("one\ntwo\nthree\n")
            doc.revision += 0
            editor._replace_range(doc, 4, 7, "TWO")
            check("the range was swapped", doc.text(), "one\nTWO\nthree\n")
            check("it is one undo step", buf.can_undo())
            buf.undo()
            check("undo puts it back", doc.text(), "one\ntwo\nthree\n")
            table = buf.get_tag_table()
            check("the change was tinted so you can see it",
                  table.lookup("prism-touched") is not None)

            print("\n-- spotting what somebody else changed --")
            from editor import _changed_span
            check("a middle edit is located",
                  _changed_span("aaa bbb ccc", "aaa XXX ccc"), (4, 7))
            check("an append is located",
                  _changed_span("aaa", "aaa bbb"), (3, 7))
            check("no change is an empty span",
                  _changed_span("same", "same")[0] >= _changed_span("same", "same")[1])

            print("\n-- the mode button --")
            editor.suggest_mode = "off"
            editor._sync_assist_button()
            check("off is labelled", editor.assist_btn.get_label(), "assist: off")
            check("cycling goes to the local tier", editor.cycle_suggest_mode(), "local")
            check("then to Claude", editor.cycle_suggest_mode(), "claude")
            check("then back to off", editor.cycle_suggest_mode(), "off")

            print("\n-- the edit bar survives a narrow pane --")
            editor.editbar.open()
            editor.editbar.entry.set_text("a fairly long instruction that fills the box")
            win.middle.set_position(430)        # squeeze the editor side
            for _ in range(200):
                if not Gtk.events_pending():
                    break
                Gtk.main_iteration_do(False)
            bar = editor.editbar.get_child()
            kids = bar.get_children()
            check("every control is still there", len(kids), 5)
            check("all of them are visible", all(k.get_visible() for k in kids))
            widths = {type(k).__name__ + (k.get_label() if isinstance(k, Gtk.Button) else ""):
                      k.get_allocation().width for k in kids}
            print("   widths:", widths)
            check("the Ask Claude button keeps its width",
                  widths.get("ButtonAsk Claude", 0) > 40)
            check("the close button keeps its width", widths.get("Button✕", 0) > 10)
            editor.editbar.close()

            print("\n-- nothing is drawn when there is nothing to draw --")
            editor.ghost.clear()
            check("no suggestion means no ghost text", editor.ghost.text, "")
            check("drawing an empty ghost is harmless",
                  editor.ghost._draw(editor.view, _fake_cr()), False)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception during the checks")
        finally:
            app.quit()
        return False

    GLib.timeout_add(2200, later)
    return False


def _fake_cr():
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
    return cairo.Context(surface)


GLib.timeout_add(900, start)
app.run([sys.argv[0]])
if not ran["n"]:
    fails.append("no checks ran at all")
print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
