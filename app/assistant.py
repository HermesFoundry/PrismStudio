"""assistant — the Claude pane down the right hand side.

It is a real Claude Code session in a terminal, started in the workspace
folder, plus the small amount of chrome that makes it part of the editor: a
button to point it at whatever file you are looking at, and a restart.

Nothing is sent anywhere on your behalf. Pointing Claude at a file types a
reference into its prompt and leaves the cursor there; you say what you want
and press return yourself.
"""
import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

import core  # noqa: E402
from explorer import icon_button  # noqa: E402
from terminal import PrismTerminal  # noqa: E402


class Assistant(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self.get_style_context().add_class("assistpane")
        self.terminal = None

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        head.get_style_context().add_class("assisthead")
        title = Gtk.Label(label="CLAUDE")
        title.set_xalign(0.0)
        title.get_style_context().add_class("assistlabel")
        head.pack_start(title, True, True, 0)

        head.pack_end(icon_button("window-close-symbolic", "✕",
                                  "Hide this pane   Ctrl+Shift+C",
                                  lambda *_: self.window.toggle_assistant()),
                      False, False, 0)
        head.pack_end(icon_button("view-refresh-symbolic", "restart",
                                  "Start Claude again",
                                  lambda *_: self.restart()), False, False, 0)
        head.pack_end(icon_button("mail-send-symbolic", "point",
                                  "Point Claude at the open file   Ctrl+Shift+A",
                                  lambda *_: self.window.point_claude_at_current()),
                      False, False, 0)
        self.pack_start(head, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.pack_start(self.body, True, True, 0)

    # -- the session -----------------------------------------------------------
    def start(self, cwd=None):
        if self.terminal is not None:
            return self.terminal
        command = self.window.cfg.get("CLAUDE_CMD", "claude") or "claude"
        shell = self.window.cfg.get("SHELL") or os.environ.get("SHELL", "/bin/bash")
        where = cwd or self.window.root or os.path.expanduser("~")
        self.terminal = PrismTerminal(self.window, [shell, "-l", "-c", command],
                                      cwd=where, name="claude")
        self.terminal.is_claude = True
        self.body.pack_start(self.terminal, True, True, 0)
        self.terminal.show_all()
        self.terminal.spawn()
        self.terminal.restyle(self.window.theme, self.window.cfg)
        return self.terminal

    def restart(self):
        if self.terminal is not None:
            self.body.remove(self.terminal)
            self.terminal.destroy()
            self.terminal = None
        self.start()
        self.window.say("Claude restarted")

    def send(self, text, focus=True):
        """Type something into Claude's prompt without pressing return."""
        terminal = self.start()
        terminal.term.feed_child(text.encode())
        if focus:
            terminal.term.grab_focus()
        return True

    def point_at(self, path, first, last=None):
        """A reference to a file, for you to finish the sentence."""
        base = self.window.root or os.path.dirname(path)
        try:
            relative = os.path.relpath(path, base)
        except ValueError:
            relative = path
        if relative.startswith(".."):
            relative = path
        if last and last != first:
            reference = "@%s lines %d-%d: " % (relative, first, last)
        else:
            reference = "@%s line %d: " % (relative, first)
        self.send(reference)
        self.window.say("pointed Claude at %s — say what you want, then Enter"
                        % os.path.basename(path))
        return True

    def restyle(self, theme, cfg):
        if self.terminal is not None:
            self.terminal.restyle(theme, cfg)
