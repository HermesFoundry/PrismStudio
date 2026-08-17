#!/usr/bin/env python3
"""Does the Run bar actually run things?

The fragile parts are the ones that touch the terminal: reading the shell's
output back to find the address a dev server printed, and knowing whether
something is still in the foreground. Both are checked against a real shell
here rather than mocked, because both broke silently on this machine's VTE.
"""
import json
import os
import shutil
import sys
import tempfile

SP = os.environ.get("IRIS_TEST_TMP", "/tmp/iris-tests")
os.makedirs(SP, exist_ok=True)
os.environ["XDG_CONFIG_HOME"] = os.path.join(SP, "xdg-prism-runbar")
os.environ.setdefault("GDK_BACKEND", "broadway")
os.environ.setdefault("BROADWAY_DISPLAY", ":13")
sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))


def _ensure_display():
    import socket
    import subprocess
    import time
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", 8093))
        probe.close()
        return
    except OSError:
        pass
    subprocess.Popen(["broadwayd", ":13"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(2)


_ensure_display()

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, Gtk  # noqa: E402

from main import PrismApp  # noqa: E402

fails = []
ran = {"n": 0}
BASE = tempfile.mkdtemp(prefix="prism-runbar-")
PORT = 5394


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


# a folder with no dependencies, so Run works straight away
READY = os.path.join(BASE, "ready")
os.makedirs(READY)
with open(os.path.join(READY, "package.json"), "w") as fh:
    json.dump({"name": "ready", "scripts": {"dev": "python3 serve.py"}}, fh)
with open(os.path.join(READY, "serve.py"), "w") as fh:
    # bind first, then announce, the way a real dev server does: the address
    # must not appear in the output before the port is actually open
    fh.write(
        "import http.server, socketserver\n"
        "socketserver.TCPServer.allow_reuse_address = True\n"
        "server = socketserver.TCPServer(('', %d), http.server.SimpleHTTPRequestHandler)\n"
        "print('  Local:   http://localhost:%d/', flush=True)\n"
        "server.serve_forever()\n" % (PORT, PORT))

# a folder that needs installing first
NEEDS = os.path.join(BASE, "needs")
os.makedirs(NEEDS)
with open(os.path.join(NEEDS, "package.json"), "w") as fh:
    json.dump({"name": "needs", "scripts": {"dev": "echo hi"},
               "dependencies": {"left-pad": "^1"}}, fh)

app = PrismApp()
app.set_application_id("net.test.PrismRunBar")


def start():
    win = app.props.active_window
    if win is None:
        fails.append("no window: another instance answered")
        app.quit()
        return False
    win.set_default_size(1300, 850)
    win.open_folder(READY, restore=False)
    win.toggle_panel(True)

    def pump(times=200):
        for _ in range(times):
            if not Gtk.events_pending():
                break
            Gtk.main_iteration_do(False)

    def phase1():
        try:
            view = win
            bar = win.runbar
            check("the code view has a run bar", bar is not None)

            bar.rescan()
            pump()
            print("\n-- a folder that is ready to run --")
            check("the project was recognised", bar.project.summary, "Node · npm")
            check("its script became a target", bar.choices[0].label, "npm run dev")
            check("nothing needs installing", bar.project.pending, [])
            check("so no Install button", bar.install_btn.get_visible(), False)
            check("the button offers to run", bar.run_btn.get_label().strip(), "▶  Run")
            check("no address yet", bar.url, None)
            check("and no Open button", bar.open_btn.get_visible(), False)

            print("\n-- the open file is offered as a target too --")
            view.editor.open(os.path.join(READY, "serve.py"))
            bar.rescan()
            pump()
            check("the open file is in the list",
                  any(c.label.startswith("this file:") for c in bar.choices))

            print("\n-- pressing Run --")
            bar.targets.set_active(0)
            check("that target is a web one", bar.current_target().web, True)
            bar.run()
            pump()
            check("it says it is running", bar.running, True)
            check("and the button offers to stop", bar.run_btn.get_label().strip(), "■  Stop")
            GLib.timeout_add_seconds(7, phase2)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 1")
            app.quit()
        return False

    def phase2():
        try:
            view = win
            bar = win.runbar
            pump()
            print("\n-- it found the address in the shell output --")
            check("the shell output could be read", bool(bar._recent_text()))
            check("the address was found", bar.url, "http://localhost:%d/" % PORT)
            check("so the Open button appeared", bar.open_btn.get_visible(), True)
            check("and the button names the address",
                  "localhost:%d" % PORT in bar.open_btn.get_label(), True)
            busy = bar._busy()
            if not busy:                    # say what the shell saw, do not guess
                print("   shell said:\n" + "\n".join(
                    "     | " + line for line in bar._recent_text().split("\n")[-12:]))
            check("the shell knows something is running", busy, True)

            print("\n-- it is really serving --")
            import urllib.request
            body = b""
            try:
                body = urllib.request.urlopen(bar.url, timeout=5).read()
            except Exception as exc:
                print("   fetch failed: %s" % exc)
            check("the page answers", len(body) > 0, True)

            print("\n-- stopping --")
            bar.stop()
            check("no longer running", bar.running, False)
            check("the address is dropped", bar.url, None)
            check("and the Open button goes", bar.open_btn.get_visible(), False)
            GLib.timeout_add_seconds(3, phase3)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 2")
            app.quit()
        return False

    def phase3():
        try:
            bar = win.runbar
            pump()
            check("the shell is idle again", bar._busy(), False)
            import urllib.request
            try:
                urllib.request.urlopen("http://localhost:%d/" % PORT, timeout=2)
                still = True
            except Exception:
                still = False
            check("and the port is closed", still, False)

            print("\n-- a folder whose dependencies are missing --")
            win.open_folder(NEEDS, restore=False)
            GLib.timeout_add_seconds(3, phase4)
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 3")
            app.quit()
        return False

    def phase4():
        try:
            bar = win.runbar
            bar.rescan()
            pump()
            check("it knows something is missing", bar.project.ready, False)
            check("an Install button appears", bar.install_btn.get_visible(), True)
            check("it says what is needed",
                  "needs setup first" in bar.state.get_text(), True)
            check("Run refuses until then", bar.run(), False)
            check("and nothing started", bar.running, False)
            check("there is a command it would run", bar.project.install_command(),
                  "npm install")
        except Exception:
            import traceback
            traceback.print_exc()
            fails.append("exception in phase 4")
        finally:
            app.quit()
        return False

    GLib.timeout_add(2400, phase1)
    return False


GLib.timeout_add(900, start)
app.run([sys.argv[0]])
shutil.rmtree(BASE, ignore_errors=True)
if not ran["n"]:
    fails.append("no checks ran at all")
print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
