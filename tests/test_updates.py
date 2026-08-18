#!/usr/bin/env python3
"""Does the update check behave itself?

The interesting properties are not "does it parse JSON". They are: it never
tells you about a version you already have, it does not nag about one you
skipped, it stays quiet when the server is down, and it does not open a socket
at all when it is switched off. Everything here runs against a real HTTP
server on a loopback port, because every bug this path has had was in the
network handling rather than the comparison.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import gi

CONFIG = tempfile.mkdtemp(prefix="prism-upd-")
os.environ["XDG_CONFIG_HOME"] = CONFIG
os.environ["XDG_CACHE_HOME"] = os.path.join(CONFIG, "cache")
sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))

from gi.repository import GLib  # noqa: E402

import core  # noqa: E402
import updates  # noqa: E402

fails = []
ran = {"n": 0}


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


# ---- a server that answers whatever the test puts in BODY ---------------- #
BODY = {"payload": "", "status": 200, "hits": 0, "agents": []}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        BODY["hits"] += 1
        BODY["agents"].append(self.headers.get("User-Agent", ""))
        self.send_response(BODY["status"])
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(BODY["payload"].encode())

    def log_message(self, *_):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
PORT = server.server_address[1]
URL = "http://127.0.0.1:%d/updates.json" % PORT
threading.Thread(target=server.serve_forever, daemon=True).start()


# ---- comparing versions -------------------------------------------------- #
print("-- versions --")
check("a later patch is newer", updates.is_newer("1.0.1", "1.0.0"))
check("a later minor is newer", updates.is_newer("1.1.0", "1.0.9"))
check("the same version is not", updates.is_newer("1.0.0", "1.0.0"), False)
check("an older one is not", updates.is_newer("0.9.9", "1.0.0"), False)
check("short forms still compare", updates.is_newer("2.0", "1.9.9"))
check("a v prefix is tolerated", updates.is_newer("v1.2.0", "1.1.0"))
check("a release beats its own rc", updates.is_newer("1.1.0", "1.1.0-rc2"))
check("an rc does not beat the release", updates.is_newer("1.1.0-rc2", "1.1.0"), False)
check("junk never looks newer", updates.is_newer("banana", "1.0.0"), False)
check("junk on our side loses", updates.is_newer("1.0.0", "banana"))


# ---- the manifest -------------------------------------------------------- #
print("-- the manifest --")
BODY["payload"] = json.dumps({
    "version": "9.9.9", "released": "2026-08-18", "title": "Nine",
    "notes": ["one", "two", ""], "url": "https://example.invalid/notes",
    "command": "git pull", "important": True})
release = updates.fetch(URL)
check("version read", release.version, "9.9.9")
check("blank notes dropped", release.notes, ["one", "two"])
check("flagged important", release.important, True)
check("the user agent is only the app and its version",
      BODY["agents"][-1], "%s/%s" % (core.APP_NAME, core.VERSION))

BODY["payload"] = json.dumps({"releases": [
    {"version": "1.0.0"}, {"version": "3.0.0"}, {"version": "2.0.0"}]})
check("a list yields the newest", updates.fetch(URL).version, "3.0.0")

BODY["payload"] = json.dumps({"releases": [{"nope": 1}]})
check("a list of junk yields nothing", updates.fetch(URL), None)

BODY["payload"] = "not json at all"
try:
    updates.fetch(URL)
    check("bad json raises", False)
except ValueError:
    check("bad json raises", True)

BODY["payload"] = json.dumps({"version": "9.9.9"})
BODY["status"] = 404
try:
    updates.fetch(URL)
    check("a 404 raises", False)
except Exception:
    check("a 404 raises", True)
BODY["status"] = 200

try:
    updates.fetch("http://127.0.0.1:1/updates.json", timeout=2)
    check("a dead port raises", False)
except Exception:
    check("a dead port raises", True)


# ---- the window's behaviour --------------------------------------------- #
print("-- deciding whether to show the card --")


class FakeWindow:
    """Everything Updates touches on a window, and nothing else."""

    def __init__(self, **settings):
        self.cfg = dict(core.DEFAULTS)
        self.cfg.update(settings)
        self.said = []
        self.shown = []

    def say(self, text, bad=False):
        self.said.append((text, bad))


def make(**settings):
    settings.setdefault("UPDATE_URL", URL)
    checker = updates.Updates(FakeWindow(**settings))
    checker.present = lambda release: checker.parent_shown.append(release)
    checker.parent_shown = []
    return checker


def pump(times=6):
    """start() defers the no-network path to idle, so give idle a turn."""
    context = GLib.MainContext.default()
    for _ in range(times):
        while context.pending():
            context.iteration(False)


def run(checker, manual=False):
    """Do the network part on this thread so the test stays linear."""
    try:
        release, error = updates.fetch(checker.url), None
    except Exception as exc:
        release, error = None, exc
    checker._done(release, error, manual)
    return checker.parent_shown


os.makedirs(core.CACHE, exist_ok=True)
updates.write_state({})

BODY["payload"] = json.dumps({"version": "9.9.9", "notes": ["new thing"]})
checker = make()
check("a newer version shows the card", len(run(checker)), 1)

BODY["payload"] = json.dumps({"version": core.VERSION})
checker = make()
check("the version we run shows nothing", len(run(checker)), 0)

BODY["payload"] = json.dumps({"version": "0.0.1"})
checker = make()
check("an older version shows nothing", len(run(checker)), 0)

BODY["payload"] = json.dumps({"version": "9.9.9"})
checker = make()
checker.dismiss("9.9.9")
check("a skipped version does not come back", len(run(checker)), 0)
check("but asking for it directly still shows it", len(run(checker, manual=True)), 1)
check("skipping is remembered on disk", updates.read_state().get("dismissed"), "9.9.9")

updates.write_state({})
checker = make()
run(checker)
check("the check is timestamped", updates.read_state().get("last_check", 0) > 0, True)
check("and the release is remembered",
      updates.read_state().get("latest", {}).get("version"), "9.9.9")

print("-- failure is quiet --")
checker = updates.Updates(FakeWindow(UPDATE_URL="http://127.0.0.1:1/x.json"))
checker.present = lambda release: fails.append("showed a card on a dead server")
checker.parent_shown = []
try:
    release = updates.fetch(checker.url, timeout=2)
except Exception as exc:
    checker._done(None, exc, False)
check("a dead server says nothing at all", checker.window.said, [])
try:
    updates.fetch(checker.url, timeout=2)
except Exception as exc:
    checker._done(None, exc, True)
check("but asking by hand gets an answer", len(checker.window.said), 1)
check("and it is marked as a problem", checker.window.said[-1][1], True)

print("-- switched off --")
before = BODY["hits"]
checker = make(UPDATE_CHECK="0")
checker.start()
check("start() with UPDATE_CHECK=0 opens no socket", BODY["hits"], before)
check("and reports itself off", checker.enabled, False)

checker = make(UPDATE_URL="")
checker.start()
check("no address means no request", BODY["hits"], before)

print("-- the throttle --")
updates.write_state({"last_check": 0})
checker = make(UPDATE_INTERVAL="20")
check("an ancient check is due", checker.due(), True)
import time  # noqa: E402
updates.write_state({"last_check": time.time()})
check("a fresh one is not", checker.due(), False)
updates.write_state({"last_check": time.time() - 21 * 3600})
check("21 hours later it is again", checker.due(), True)
updates.write_state({"last_check": time.time()})
checker = make(UPDATE_INTERVAL="0")
check("an interval of 0 means every launch", checker.due(), True)

print("-- a release that landed while the app was closed --")
updates.write_state({"last_check": time.time(),
                     "latest": {"version": "9.9.9", "notes": ["missed it"]}})
checker = make()
checker.start()
pump()
check("it is shown on the next launch without asking the server",
      len(checker.parent_shown), 1)
check("and no request was made", BODY["hits"], before)

updates.write_state({"last_check": time.time(), "dismissed": "9.9.9",
                     "latest": {"version": "9.9.9"}})
checker = make()
checker.start()
pump()
check("unless it was skipped", len(checker.parent_shown), 0)

updates.write_state({"last_check": time.time(),
                     "latest": {"version": "0.0.1"}})
checker = make()
checker.start()
pump()
check("an old remembered release is ignored", len(checker.parent_shown), 0)

print("-- a corrupt state file --")
with open(updates.STATE, "w") as handle:
    handle.write("{{{ not json")
check("unreadable state reads as empty", updates.read_state(), {})
checker = make()
check("and the app still thinks a check is due", checker.due(), True)

server.shutdown()
shutil.rmtree(CONFIG, ignore_errors=True)
if not ran["n"]:
    fails.append("no checks ran at all")
print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
