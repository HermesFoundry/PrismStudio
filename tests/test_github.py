#!/usr/bin/env python3
"""Cloning, publishing, and the GitHub CLI wrapper.

Nothing here needs a GitHub account or the network. What is worth asserting is
the part that is ours: that a URL turns into the right destination folder, that
a clone actually lands and is noticed, that the panel offers the right thing
for a folder that is not a repository and for one with no remote, and that the
wrapper never goes near a credential.

The clone is real — a git repository made in a temp folder and cloned from
disk — because every bug in that path was in the plumbing between the terminal
and the editor, not in the string handling.
"""
import os
import shutil
import subprocess
import sys
import tempfile

CONFIG = tempfile.mkdtemp(prefix="prism-gh-cfg-")
os.environ["XDG_CONFIG_HOME"] = CONFIG
os.environ["XDG_CACHE_HOME"] = os.path.join(CONFIG, "cache")
os.environ.setdefault("GDK_BACKEND", "broadway")
os.environ.setdefault("BROADWAY_DISPLAY", ":13")
sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))
os.makedirs(os.path.join(CONFIG, "prismstudio"), exist_ok=True)
with open(os.path.join(CONFIG, "prismstudio", "settings.conf"), "w") as handle:
    handle.write("THEME=olympus\nASSISTANT=0\nCLAUDE=0\nUPDATE_CHECK=0\n"
                 "CONFIRM_CLOSE=0\n")


def _ensure_display():
    import socket
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

import clone  # noqa: E402
import github  # noqa: E402
from main import PrismApp, PrismWindow  # noqa: E402

fails = []
ran = {"n": 0}


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


# ---- a repository to clone from ------------------------------------------ #
BASE = tempfile.mkdtemp(prefix="prism-gh-")
SOURCE = os.path.join(BASE, "source")
os.makedirs(SOURCE)
with open(os.path.join(SOURCE, "hello.py"), "w") as handle:
    handle.write("print('hi')\n")
for command in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=a@b", "-c", "user.name=a",
                 "commit", "-qm", "first"]):
    subprocess.run(command, cwd=SOURCE, check=True)

WORK = os.path.join(BASE, "work")
os.makedirs(WORK)


# ---- the wrapper, with no account ---------------------------------------- #
print("-- the gh wrapper --")
check("it knows whether gh is installed", github.available() in (True, False))
check("git is what does the cloning", "git clone" in github.clone_argv("u", "d"))
check("a path with a space is quoted",
      "'/tmp/a b'" in github.clone_argv("u", "/tmp/a b"), True)
check("create asks for a private repo by default",
      "--private" in github.create_argv("x", True, "", "/tmp"), True)
check("and public when told to",
      "--public" in github.create_argv("x", False, "", "/tmp"), True)
check("it sets origin", "--remote origin" in github.create_argv("x", True, "", "/tmp"))
check("and pushes", "--push" in github.create_argv("x", True, "", "/tmp"))

account = github.account()
check("an account object always comes back", isinstance(account, github.Account))
check("it has no token field", hasattr(account, "token"), False)
check("nothing in it looks like a token",
      any("gho_" in str(v) or "ghp_" in str(v) for v in vars(account).values()), False)
check("signing in never asks for the token",
      "--show-token" in github.login_argv("ssh"), False)
check("sign-in uses the device flow", "--web" in github.login_argv("ssh"))
check("the protocol is passed through",
      "--git-protocol https" in github.login_argv("https"), True)

keys = github.local_ssh_keys()
check("local keys are only the public halves",
      all(path.endswith(".pub") for path, _n, _c in keys), True)


# ---- the window ---------------------------------------------------------- #
app = PrismApp()
app.register()
holder = {}
app.connect("activate", lambda a: holder.setdefault("w", PrismWindow(a, WORK)))
app.activate()
win = holder["w"]


def pump(rounds=8):
    context = GLib.MainContext.default()
    for _ in range(rounds):
        while context.pending():
            context.iteration(False)


def buttons_in(widget, found=None):
    found = [] if found is None else found
    if isinstance(widget, Gtk.Button) and widget.get_label():
        found.append(widget.get_label())
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            buttons_in(child, found)
    return found


def phase1():
    try:
        print("-- the source control panel --")
        win.git.refresh()
        pump()
        labels = buttons_in(win.git)
        check("a plain folder is offered a repository", 
              any("Initialise" in text for text in labels), True)
        check("and a clone", any("Clone a repository" in text for text in labels), True)

        print("-- the clone dialog --")
        dialog = clone.CloneDialog(win)
        dialog.folder.set_text(WORK)
        dialog.url.set_text("git@github.com:owner/thing.git")
        check("an ssh URL names the folder", dialog.destination(),
              os.path.join(WORK, "thing"))
        dialog.url.set_text("https://github.com/owner/other")
        check("an https URL does too", dialog.destination(),
              os.path.join(WORK, "other"))
        dialog.url.set_text("https://github.com/owner/trailing/")
        check("a trailing slash is ignored", dialog.destination(),
              os.path.join(WORK, "trailing"))
        check("Clone is live once there is a URL",
              dialog.clone_button.get_sensitive(), True)
        dialog.url.set_text("")
        check("and dead without one", dialog.clone_button.get_sensitive(), False)
        check("it says who you are", "GitHub" in dialog.bar.label.get_text()
              or "signed in" in dialog.bar.label.get_text(), True)
        dialog.destroy()

        print("-- cloning for real --")
        target = os.path.join(WORK, "cloned")
        win._clone_arrived = lambda path: arrived.setdefault("path", path)
        win.clone_into(SOURCE, target)
        GLib.timeout_add_seconds(12, phase2)
    except Exception:
        import traceback
        traceback.print_exc()
        fails.append("exception in phase 1")
        app.quit()
    return False


arrived = {}
TARGET = os.path.join(WORK, "cloned")


def phase2():
    try:
        check("the clone landed", os.path.isdir(os.path.join(TARGET, ".git")), True)
        check("with its files", os.path.exists(os.path.join(TARGET, "hello.py")), True)
        check("and the editor noticed", arrived.get("path"), TARGET)

        print("-- a repository with no remote --")
        win.open_folder(TARGET)
        pump()
        subprocess.run(["git", "remote", "remove", "origin"], cwd=TARGET,
                       capture_output=True)
        win.git.set_root(TARGET)
        win.git.refresh()
        pump()
        labels = buttons_in(win.git)
        check("it offers to publish",
              any("Publish to GitHub" in text for text in labels), True)

        print("-- the publish dialog --")
        dialog = clone.PublishDialog(win)
        check("it suggests the folder's name", dialog.name.get_text(), "cloned")
        check("and defaults to private", dialog.private.get_active(), True)
        dialog.destroy()
    except Exception:
        import traceback
        traceback.print_exc()
        fails.append("exception in phase 2")
    finally:
        GLib.timeout_add(300, lambda: (app.quit(), False)[1])
    return False


GLib.timeout_add(1200, phase1)
app.run([sys.argv[0]])
shutil.rmtree(BASE, ignore_errors=True)
shutil.rmtree(CONFIG, ignore_errors=True)
if not ran["n"]:
    fails.append("no checks ran at all")
print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
