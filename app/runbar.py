"""runbar — one strip that turns an unfamiliar folder into a running app.

Open a folder and this reads whatever manifests are in it, says what the
project is, offers the run targets the project itself declares, and tells you
whether its dependencies are installed. Install once, then Run. When whatever
you started prints a localhost address, an Open button appears next to it.

Everything runs in the shell panel below the editor rather than somewhere you
cannot see, so the output, the prompts and Ctrl+C all behave the way they would
if you had typed the command yourself.
"""
import os

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gdk, GLib, Gtk, Vte  # noqa: E402

import project as project_mod  # noqa: E402
import runner  # noqa: E402

WATCH_LINES = 60            # how much recent output to scan for an address


class RunBar(Gtk.Box):
    def __init__(self, view):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.view = view                 # the CodeView
        self.get_style_context().add_class("runbar")
        self.project = project_mod.Project(None)
        self.url = None
        self.running = False
        self._watch = None
        self._shell_pgid = None

        self.run_btn = Gtk.Button(label="▶  Run")
        self.run_btn.get_style_context().add_class("runbtn-main")
        self.run_btn.connect("clicked", lambda *_: self.toggle())
        self.pack_start(self.run_btn, False, False, 0)

        self.targets = Gtk.ComboBoxText()
        self.targets.set_tooltip_text("What to run")
        self.targets.connect("changed", lambda *_: self._sync())
        self.pack_start(self.targets, False, False, 0)

        self.summary = Gtk.Label(label="no folder open")
        self.summary.set_xalign(0.0)
        self.summary.get_style_context().add_class("runsummary")
        self.pack_start(self.summary, False, False, 0)

        self.state = Gtk.Label(label="")
        self.state.set_xalign(0.0)
        self.state.set_ellipsize(3)
        self.state.get_style_context().add_class("runstate")
        self.pack_start(self.state, True, True, 0)

        self.open_btn = Gtk.Button(label="Open in browser")
        self.open_btn.get_style_context().add_class("runopen")
        self.open_btn.connect("clicked", lambda *_: self.open_browser())
        self.open_btn.set_no_show_all(True)
        self.pack_end(self.open_btn, False, False, 0)

        self.install_btn = Gtk.Button(label="Install")
        self.install_btn.get_style_context().add_class("runinstall")
        self.install_btn.connect("clicked", lambda *_: self.install())
        self.install_btn.set_no_show_all(True)
        self.pack_end(self.install_btn, False, False, 0)

        rescan = Gtk.Button(label="↺")
        rescan.set_relief(Gtk.ReliefStyle.NONE)
        rescan.set_tooltip_text("Look at the folder again")
        rescan.get_style_context().add_class("iconbtn")
        rescan.connect("clicked", lambda *_: self.rescan())
        self.pack_end(rescan, False, False, 0)

    # -- what is in the folder -------------------------------------------------
    def rescan(self):
        root = self.view.root
        self.project = project_mod.detect(root)
        self._fill_targets()
        self._sync()
        return self.project

    def _fill_targets(self):
        self.targets.remove_all()
        self.choices = []
        for target in self.project.targets:
            self.choices.append(target)
            self.targets.append_text(target.label)
        path = self.view.editor.path
        if path:
            label, command = runner.command_for(path)
            if label:
                self.choices.append(project_mod.Target(
                    "this file: %s" % os.path.basename(path), command, False,
                    "run just the open file", label))
                self.targets.append_text(self.choices[-1].label)
        if self.choices:
            self.targets.set_active(0)

    def current_target(self):
        index = self.targets.get_active()
        if index is None or index < 0 or index >= len(getattr(self, "choices", [])):
            return None
        return self.choices[index]

    # -- appearance ------------------------------------------------------------
    def _sync(self):
        project = self.project
        self.summary.set_text(project.summary if project.root else "no folder open")

        pending = project.pending
        blocked = project.blocked
        self.install_btn.set_visible(bool(pending))
        if pending:
            self.install_btn.set_label("Install %s" % pending[0].label.split()[-1]
                                       if len(pending) == 1 else "Install (%d)" % len(pending))

        self.open_btn.set_visible(bool(self.url))
        if self.url:
            self.open_btn.set_label("Open %s" % self.url.replace("http://", "")
                                    .rstrip("/")[:34])

        self.run_btn.set_label("■  Stop" if self.running else "▶  Run")
        target = self.current_target()
        self.run_btn.set_sensitive(bool(target) or self.running)

        if self.running:
            self.state.set_text(self.url or "running…")
        elif blocked and not pending:
            self.state.set_text("cannot install: " + blocked[0].blocked)
        elif pending:
            need = ", ".join(s.label.lower() for s in pending)
            self.state.set_text("needs setup first: %s" % need)
        elif target is not None:
            self.state.set_text(target.detail or "")
        elif project.root:
            self.state.set_text("nothing here PrismStudio knows how to run")
        else:
            self.state.set_text("")

    # -- doing things ----------------------------------------------------------
    def install(self):
        command = self.project.install_command()
        if not command:
            self.view.status_message("nothing to install")
            return False
        self.view.show_shell()
        self._send(command)
        self.view.status_message("installing — watch the shell below")
        # re-check once it has had time to finish
        GLib.timeout_add_seconds(4, self._recheck_install)
        return True

    def _recheck_install(self):
        if self._busy():
            return True                  # still going, look again shortly
        self.rescan()
        if self.project.ready and not self.project.pending:
            self.view.status_message("dependencies installed — press Run")
        return False

    def toggle(self):
        return self.stop() if self.running else self.run()

    def run(self):
        target = self.current_target()
        if target is None:
            self.view.status_message("nothing selected to run")
            return False
        if self.project.pending:
            self.view.status_message("install the dependencies first")
            return False
        self.view.editor.flush()
        self.view.show_shell()
        self.url = None
        self._send(target.command)
        self.running = True
        self._start_watching()
        self._sync()
        self.view.status_message("running %s" % target.label)
        return True

    def stop(self):
        terminal = self.view.shell.term
        terminal.feed_child(b"\x03")     # the same Ctrl+C you would press
        self.running = False
        self.url = None
        self._stop_watching()
        self._sync()
        self.view.status_message("stopped")
        return True

    def _send(self, command):
        root = self.view.root or os.path.expanduser("~")
        line = "cd %s && %s\n" % (GLib.shell_quote(root), command)
        terminal = self.view.shell
        wait = getattr(terminal, "when_ready", None)
        if wait:
            wait(lambda: terminal.term.feed_child(line.encode()))
        else:
            terminal.term.feed_child(line.encode())
        terminal.term.grab_focus()

    # -- watching for an address ----------------------------------------------
    def _start_watching(self):
        self._stop_watching()
        self._seen_busy = False
        self._polls = 0
        self._watch = GLib.timeout_add(700, self._look)

    def _stop_watching(self):
        if self._watch:
            GLib.source_remove(self._watch)
            self._watch = None

    def _busy(self):
        """Is something other than the shell itself in the foreground?"""
        terminal = self.view.shell
        pty = terminal.term.get_pty()
        if pty is None or not terminal.pid:
            return False
        try:
            foreground = os.tcgetpgrp(pty.get_fd())
        except OSError:
            return False
        return foreground > 0 and foreground != terminal.pid

    def _recent_text(self):
        """The last screenful or so of shell output.

        The bounded call is preferred; the whole-screen one is the fallback for
        VTE builds that do not have it. The older get_text/get_text_range pair
        is deliberately not tried: on VTE 0.76 it fails an assertion rather
        than returning anything.
        """
        terminal = self.view.shell.term
        row = 0
        try:
            _col, row = terminal.get_cursor_position()
        except Exception:
            pass
        first = max(0, row - WATCH_LINES)
        for attempt in (
                lambda: terminal.get_text_range_format(Vte.Format.TEXT, first, 0, row, -1),
                lambda: terminal.get_text_format(Vte.Format.TEXT),
        ):
            try:
                got = attempt()
            except Exception:
                continue
            while isinstance(got, tuple) and got:
                got = got[0]
            if isinstance(got, str) and got:
                return got
        return ""

    def _look(self):
        if not self.running:
            self._watch = None
            return False
        if self.url is None:
            found = project_mod.find_url(self._recent_text())
            if found:
                self.url = found
                self._sync()
                self.view.status_message("serving on %s — click Open in browser" % found)
        busy = self._busy()
        if busy:
            self._seen_busy = True
        self._polls += 1
        # A command can take a moment to reach the shell, so do not call it
        # finished until we have actually seen it start, or waited long enough
        # that it clearly never will.
        if not busy and (self._seen_busy or self._polls > 14):
            self.running = False
            self._sync()
            self._watch = None
            return False
        return True

    def open_browser(self):
        if not self.url:
            return False
        try:
            Gtk.show_uri_on_window(self.view.win, self.url, Gdk.CURRENT_TIME)
        except Exception:
            GLib.spawn_async(["xdg-open", self.url],
                             flags=GLib.SpawnFlags.SEARCH_PATH)
        self.view.status_message("opened %s" % self.url)
        return True
