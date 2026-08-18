"""updates — tells you when there is a newer PrismStudio, and nothing else.

The app asks a URL for a small JSON file, compares the version in it against
the one it is running, and if that is newer it shows a *What's new* card the
first time you open the app after it lands. Dismiss it and it does not come
back for that version.

What it sends: a plain GET, with a `User-Agent` of `PrismStudio/<version>` and
nothing more. No identifier, no machine details, no record of what you had
open, no cookies. What it stores: the time of the last check and the version
you last dismissed, in `~/.cache/prismstudio/updates.json`, so it does not ask
the server on every launch and does not nag you twice about the same release.

Turn it off with `UPDATE_CHECK=0` and it never opens a socket. Point
`UPDATE_URL` somewhere else and it asks that instead.

The check is on a thread, every failure is silent, and nothing about startup
waits for it: an unreachable server costs the app nothing at all.
"""
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.request

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import core

STATE = os.path.join(core.CACHE, "updates.json")
TIMEOUT = 6              # seconds; the app never waits on this, but be polite
FIRST_CHECK_MS = 4000    # let the window settle before touching the network
MAX_BYTES = 64 * 1024    # a manifest is a few hundred bytes; refuse a firehose


# --------------------------------------------------------------------------- #
# versions
# --------------------------------------------------------------------------- #
def parse_version(text):
    """`1.2.3-beta.2` -> (1, 2, 3, 0, 'beta.2'). Junk sorts oldest."""
    text = (text or "").strip().lstrip("vV")
    match = re.match(r"^(\d+(?:\.\d+)*)(?:[-+](.*))?$", text)
    if not match:
        return ()
    numbers = tuple(int(part) for part in match.group(1).split("."))
    numbers += (0,) * (4 - len(numbers)) if len(numbers) < 4 else ()
    # A release beats its own pre-releases: 1.1.0 is newer than 1.1.0-rc1.
    return numbers + (1, "") if not match.group(2) else numbers + (0, match.group(2))


def is_newer(candidate, current):
    """True when `candidate` is a version after `current`."""
    left, right = parse_version(candidate), parse_version(current)
    if not left:
        return False
    if not right:
        return True
    return left > right


# --------------------------------------------------------------------------- #
# the manifest
# --------------------------------------------------------------------------- #
class Release:
    """One entry from the manifest, with everything optional but the version."""

    def __init__(self, data):
        self.version = str(data.get("version", "")).strip()
        self.released = str(data.get("released", "")).strip()
        self.title = str(data.get("title", "")).strip()
        self.url = str(data.get("url", "")).strip()
        self.command = str(data.get("command", "")).strip()
        self.important = bool(data.get("important"))
        notes = data.get("notes") or []
        if isinstance(notes, str):
            notes = [notes]
        self.notes = [str(n).strip() for n in notes if str(n).strip()][:12]

    @property
    def valid(self):
        return bool(parse_version(self.version))

    @property
    def heading(self):
        return self.title or ("%s %s" % (core.APP_NAME, self.version))


def parse_manifest(raw):
    """Accept either a single release object or `{"releases": [...]}`."""
    data = json.loads(raw)
    if isinstance(data, dict) and isinstance(data.get("releases"), list):
        entries = [Release(item) for item in data["releases"]
                   if isinstance(item, dict)]
        entries = [item for item in entries if item.valid]
        if not entries:
            return None
        entries.sort(key=lambda item: parse_version(item.version))
        return entries[-1]
    if isinstance(data, dict):
        release = Release(data)
        return release if release.valid else None
    return None


def fetch(url, timeout=TIMEOUT):
    """Get the manifest. Raises; the caller is the one that stays quiet."""
    request = urllib.request.Request(url, headers={
        "User-Agent": "%s/%s" % (core.APP_NAME, core.VERSION),
        "Accept": "application/json",
    })
    context = ssl.create_default_context() if url.startswith("https") else None
    with urllib.request.urlopen(request, timeout=timeout,
                                context=context) as response:
        return parse_manifest(response.read(MAX_BYTES).decode("utf-8", "replace"))


# --------------------------------------------------------------------------- #
# what we remember between launches
# --------------------------------------------------------------------------- #
def read_state():
    try:
        with open(STATE, "r") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_state(data):
    try:
        os.makedirs(core.CACHE, exist_ok=True)
        with open(STATE, "w") as handle:
            json.dump(data, handle, indent=2)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# the check
# --------------------------------------------------------------------------- #
class Updates:
    """Owns the check, the throttle and the card. One per window."""

    def __init__(self, window):
        self.window = window
        self.busy = False
        self.latest = None       # the newest Release we have heard about
        self._timer = None

    # -- settings ---------------------------------------------------------- #
    @property
    def enabled(self):
        return self.window.cfg.get("UPDATE_CHECK", "1") == "1"

    @property
    def url(self):
        return self.window.cfg.get("UPDATE_URL", core.DEFAULTS["UPDATE_URL"]).strip()

    @property
    def interval(self):
        try:
            return max(0.0, float(self.window.cfg.get("UPDATE_INTERVAL", "20"))) * 3600
        except ValueError:
            return 20 * 3600

    # -- lifecycle --------------------------------------------------------- #
    def start(self):
        """Called once the window is up. Does nothing if it is switched off."""
        if not self.enabled or not self.url:
            return
        if not self.due():
            # Still show a release that arrived while the app was closed and
            # was never acknowledged.
            GLib.idle_add(self._show_remembered)
            return
        self._timer = GLib.timeout_add(FIRST_CHECK_MS, self._start_now)

    def _start_now(self):
        self._timer = None
        self.check()
        return False

    def stop(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None

    def due(self):
        last = read_state().get("last_check", 0)
        try:
            last = float(last)
        except (TypeError, ValueError):
            last = 0
        return (time.time() - last) >= self.interval

    # -- doing it ---------------------------------------------------------- #
    def check(self, manual=False):
        """Ask the server, off the main loop. Silent unless there is news."""
        if self.busy:
            return
        if not self.url:
            if manual:
                self.window.say("No update URL is set", bad=True)
            return
        self.busy = True
        if manual:
            self.window.say("Checking for updates…")
        threading.Thread(target=self._work, args=(self.url, manual),
                         daemon=True).start()

    def _work(self, url, manual):
        try:
            release = fetch(url)
            error = None
        except Exception as exc:                       # network, DNS, JSON, TLS
            release, error = None, exc
        GLib.idle_add(self._done, release, error, manual)

    def _done(self, release, error, manual):
        self.busy = False
        state = read_state()
        state["last_check"] = time.time()

        if release is None:
            write_state(state)
            if manual:
                reason = "could not reach the update server"
                if error and isinstance(error, urllib.error.HTTPError):
                    reason = "the update server answered %s" % error.code
                elif error and isinstance(error, ValueError):
                    reason = "the update server sent something unreadable"
                self.window.say("Update check failed — %s" % reason, bad=True)
            return False

        self.latest = release
        state["latest"] = {
            "version": release.version, "released": release.released,
            "title": release.title, "url": release.url,
            "command": release.command, "important": release.important,
            "notes": release.notes,
        }
        write_state(state)

        if not is_newer(release.version, core.VERSION):
            if manual:
                self.window.say("PrismStudio %s is the latest version" % core.VERSION)
            return False
        if not manual and state.get("dismissed") == release.version:
            return False
        self.present(release)
        return False

    def _show_remembered(self):
        """A release we already fetched but the user has not seen yet."""
        state = read_state()
        data = state.get("latest")
        if not isinstance(data, dict):
            return False
        release = Release(data)
        if not release.valid or not is_newer(release.version, core.VERSION):
            return False
        self.latest = release
        if state.get("dismissed") == release.version:
            return False
        self.present(release)
        return False

    def dismiss(self, version):
        state = read_state()
        state["dismissed"] = version
        write_state(state)

    def present(self, release):
        WhatsNew(self.window, self, release).show_all()


# --------------------------------------------------------------------------- #
# the card
# --------------------------------------------------------------------------- #
class WhatsNew(Gtk.Dialog):
    """A quiet card: what changed, and how to get it. Never modal-and-stuck."""

    def __init__(self, window, updates, release):
        Gtk.Dialog.__init__(self, transient_for=window, modal=False)
        self.parent = window
        self.updates = updates
        self.release = release
        self.set_title("Update available")
        self.set_default_size(460, -1)
        self.set_resizable(False)
        self.get_style_context().add_class("prefs")
        self.get_style_context().add_class("whatsnew")

        box = self.get_content_area()
        box.set_spacing(0)
        box.set_border_width(0)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        top.set_border_width(20)
        top.get_style_context().add_class("wnhead")
        icon = os.path.join(core.ROOT, "packaging", "icons", "64.png")
        if os.path.exists(icon):
            try:
                from gi.repository import GdkPixbuf
                image = Gtk.Image.new_from_pixbuf(
                    GdkPixbuf.Pixbuf.new_from_file_at_size(icon, 52, 52))
                image.set_valign(Gtk.Align.START)
                top.pack_start(image, False, False, 0)
            except Exception:
                pass

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        heading = Gtk.Label(label=release.heading, xalign=0)
        heading.get_style_context().add_class("wntitle")
        heading.set_line_wrap(True)
        titles.pack_start(heading, False, False, 0)

        line = "You have %s" % core.VERSION
        if release.released:
            line = "%s  ·  released %s" % (line, release.released)
        subtitle = Gtk.Label(label=line, xalign=0)
        subtitle.get_style_context().add_class("wnsub")
        titles.pack_start(subtitle, False, False, 0)
        top.pack_start(titles, True, True, 0)
        box.pack_start(top, False, False, 0)

        if release.important:
            flag = Gtk.Label(label="Recommended for everyone", xalign=0)
            flag.get_style_context().add_class("wnflag")
            box.pack_start(flag, False, False, 0)

        if release.notes:
            notes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
            notes.set_border_width(20)
            notes.get_style_context().add_class("wnnotes")
            for text in release.notes:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
                bullet = Gtk.Label(label="•", xalign=0)
                bullet.set_valign(Gtk.Align.START)
                bullet.get_style_context().add_class("wnbullet")
                row.pack_start(bullet, False, False, 0)
                label = Gtk.Label(label=text, xalign=0)
                label.set_line_wrap(True)
                label.set_max_width_chars(52)
                label.get_style_context().add_class("wnnote")
                row.pack_start(label, True, True, 0)
                notes.pack_start(row, False, False, 0)
            box.pack_start(notes, False, False, 0)

        if release.command:
            how = Gtk.Label(label=release.command, xalign=0)
            how.get_style_context().add_class("wncmd")
            how.set_selectable(True)
            how.set_line_wrap(True)
            box.pack_start(how, False, False, 0)

        self.add_button("Skip this version", 1)
        if release.url:
            self.add_button("Release notes", 3)
        self.add_button("Later", 2)
        primary = self.add_button("Update now", 4) if release.command \
            else self.add_button("Got it", 2)
        self.set_default_response(4 if release.command else 2)
        self.connect("response", self._respond)
        self.get_action_area().get_style_context().add_class("wnactions")
        for button in self.get_action_area().get_children():
            button.get_style_context().add_class("wnbtn")
        primary.get_style_context().add_class("wnprimary")
        self.connect("map", lambda *_: self.place_over(window))

    def place_over(self, parent):
        """Sit over the middle of the window. CENTER_ON_PARENT centres on
        (0, 0) when the parent has no usable origin yet, which puts half the
        card off the edge of the screen."""
        width, height = self.get_size()
        try:
            origin_x, origin_y = parent.get_position()
        except Exception:
            origin_x, origin_y = 0, 0
        alloc = parent.get_allocation()
        x = origin_x + max(0, (alloc.width - width) // 2)
        y = origin_y + max(0, (alloc.height - height) // 3)
        screen = self.get_screen()
        if screen is not None:
            x = max(0, min(x, max(0, screen.get_width() - width)))
            y = max(0, min(y, max(0, screen.get_height() - height)))
        self.move(x, y)

    def _respond(self, _dialog, response):
        if response == 1:
            self.updates.dismiss(self.release.version)
            self.parent.say("Skipping %s" % self.release.version)
        elif response == 3 and self.release.url:
            Gtk.show_uri_on_window(self.parent, self.release.url, 0)
            return                                   # leave the card open
        elif response == 4 and self.release.command:
            self.updates.dismiss(self.release.version)
            self._run_update()
        self.destroy()

    def _run_update(self):
        """Type the update into a terminal and run it, where you can watch."""
        self.parent.toggle_panel(True)
        # The app updates itself from wherever it is installed, not from
        # whatever folder happens to be open.
        self.parent.panel.run(self.release.command, cwd=core.ROOT)
        self.parent.say("Updating in the terminal — restart when it finishes")
