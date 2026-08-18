#!/usr/bin/env python3
"""Copilot as a suggestion source.

Where a real `copilot-language-server` can be found, this drives it: the
handshake, the auth state it volunteers, a completion request, and the device
flow up to the point where a human has to type a code into a browser. That
last step needs a GitHub account with a Copilot subscription, so it is where
the test stops; everything before it is checked against the actual server
rather than a mock, because the whole point of this module is that it agrees
with a program we did not write.

With no server installed the protocol checks are skipped and the rest still
runs, so the suite is useful on a machine that has never heard of Copilot.

    npm install -g @github/copilot-language-server
    python3 tests/test_copilot.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

CONFIG = tempfile.mkdtemp(prefix="prism-cop-cfg-")
os.environ["XDG_CONFIG_HOME"] = CONFIG
os.environ["XDG_CACHE_HOME"] = os.path.join(CONFIG, "cache")
os.environ.setdefault("GDK_BACKEND", "broadway")
os.environ.setdefault("BROADWAY_DISPLAY", ":14")
sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))


def find_server():
    """Wherever it might be: the setting, the PATH, a local npm install."""
    candidates = [os.environ.get("COPILOT_CMD"), "copilot-language-server"]
    candidates += [
        os.path.expanduser("~/.npm-global/bin/copilot-language-server"),
        "/usr/local/bin/copilot-language-server",
        "/tmp/prism-demo/copilot/node_modules/.bin/copilot-language-server",
        os.path.join(os.path.expanduser("~"),
                     "node_modules/.bin/copilot-language-server"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if os.sep in candidate and os.access(candidate, os.X_OK):
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


SERVER = find_server()
os.makedirs(os.path.join(CONFIG, "prismstudio"), exist_ok=True)
with open(os.path.join(CONFIG, "prismstudio", "settings.conf"), "w") as handle:
    handle.write('THEME=olympus\nASSISTANT=0\nCLAUDE=0\nUPDATE_CHECK=0\n'
                 'CONFIRM_CLOSE=0\nCOPILOT_CMD="%s"\n'
                 % (SERVER or "copilot-language-server"))


def _ensure_display():
    import socket
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
from gi.repository import GLib  # noqa: E402

import copilot  # noqa: E402
from main import PrismApp, PrismWindow  # noqa: E402

fails = []
ran = {"n": 0}
skipped = {"n": 0}


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


def skip(label, why):
    skipped["n"] += 1
    print("  skip %s: %s" % (label, why))


# ---- finding it ---------------------------------------------------------- #
print("-- finding the server --")
check("a name that is not installed resolves to nothing",
      copilot.find("definitely-not-a-real-server-xyz"), None)
check("an empty command resolves to nothing", copilot.find(""), None)
check("a directory that is not executable is rejected",
      copilot.find("/etc/hostname"), None)
if SERVER:
    check("an absolute path is taken as it is", copilot.find(SERVER), SERVER)
    check("installed() agrees", copilot.installed(SERVER), True)
else:
    skip("resolving a real server", "none installed")

# ---- the wire ------------------------------------------------------------ #
BASE = tempfile.mkdtemp(prefix="prism-cop-")
SAMPLE = os.path.join(BASE, "m.py")
with open(SAMPLE, "w") as handle:
    handle.write("def add(a, b):\n    ")

app = PrismApp()
app.register()
holder = {}
app.connect("activate", lambda a: holder.setdefault("w", PrismWindow(a, BASE)))
app.activate()
win = holder["w"]

state = {}


def phase1():
    try:
        print("-- the client --")
        check("the window owns one", win.copilot is not None, True)
        check("it reports whether the server is there",
              win.copilot.available(), bool(SERVER))

        print("-- the suggestion cycle --")
        order = win.editor.suggest_order()
        check("off and file are always offered",
              order[:2], ["off", "local"])
        check("Claude stays out when it is switched off", "claude" in order, False)
        check("Copilot is offered exactly when it is installed",
              "copilot" in order, bool(SERVER))

        win.editor.suggest_mode = "local"
        win.editor.cycle_suggest_mode()
        check("cycling past file reaches Copilot when it is there",
              win.editor.suggest_mode, "copilot" if SERVER else "off")
        if SERVER:
            check("and the status button says so",
                  win.editor.assist_btn.get_label(), "assist: Copilot")

        if not SERVER:
            skip("the protocol", "no copilot-language-server installed")
            GLib.timeout_add(200, finish)
            return False

        win.open_file(SAMPLE)
        GLib.timeout_add_seconds(8, phase2)
    except Exception:
        import traceback
        traceback.print_exc()
        fails.append("exception in phase 1")
        GLib.timeout_add(200, finish)
    return False


def phase2():
    try:
        print("-- the handshake, against the real server --")
        server = win.copilot.server
        check("the server was started", server is not None and server.alive(), True)
        check("it finished initialising", server.ready, True)
        kind, message = win.copilot.status()
        check("it volunteered an auth state", kind in
              ("signed-out", "ready", "no-subscription", "error"), True)
        state["kind"] = kind
        if kind != "signed-out":
            skip("the signed-out path", "this machine is signed in as %r" % kind)
            GLib.timeout_add(200, finish)
            return False
        check("and it is that we are not signed in", kind, "signed-out")

        print("-- asking for a completion while signed out --")
        win.editor.request_copilot(automatic=False)
        GLib.timeout_add_seconds(6, phase3)
    except Exception:
        import traceback
        traceback.print_exc()
        fails.append("exception in phase 2")
        GLib.timeout_add(200, finish)
    return False


def phase3():
    try:
        check("no ghost text was invented", win.editor.ghost.item, None)
        check("and the reason is one a person can act on",
              win.editor._copilot_note, "not signed in to Copilot")

        print("-- the device flow, up to the browser --")
        win.copilot.server.sign_in(lambda code, url, error:
                                   state.update(code=code, url=url, error=error))
        GLib.timeout_add_seconds(8, phase4)
    except Exception:
        import traceback
        traceback.print_exc()
        fails.append("exception in phase 3")
        GLib.timeout_add(200, finish)
    return False


def phase4():
    try:
        check("signing in produced a device code", bool(state.get("code")), True)
        check("of the shape GitHub shows",
              bool(state.get("code")) and "-" in state["code"], True)
        check("pointing at github.com", "github.com" in state.get("url", ""), True)
        check("with no error", state.get("error"), "")
        print("     (stops here: finishing needs a Copilot subscription "
              "and a browser)")
    except Exception:
        import traceback
        traceback.print_exc()
        fails.append("exception in phase 4")
    GLib.timeout_add(200, finish)
    return False


def finish():
    app.quit()
    return False


GLib.timeout_add(1200, phase1)
app.run([sys.argv[0]])
shutil.rmtree(BASE, ignore_errors=True)
shutil.rmtree(CONFIG, ignore_errors=True)
if not ran["n"]:
    fails.append("no checks ran at all")
if skipped["n"]:
    print("\n%d skipped" % skipped["n"])
print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
