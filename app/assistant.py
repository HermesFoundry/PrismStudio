"""assistant — the Claude session, and the three places it is allowed to live.

Claude is not part of the furniture. Nothing is on screen and no process is
started until you ask for one; when you do, it opens where you last put it:

  panel    a tab in the drawer along the bottom, beside the terminals
  side     a pane down the right hand side of the editor
  window   its own window, for a second monitor

The widget is the same in all three, and moving it keeps the running session:
it is unparented and re-parented, not restarted, so whatever Claude was in the
middle of survives the move.

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

PLACES = [("panel", "In the bottom panel"),
          ("side", "Beside the editor"),
          ("window", "In its own window")]
PLACE_NAMES = dict(PLACES)


class Assistant(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self.get_style_context().add_class("assistpane")
        self.terminal = None

        # The head is only worth drawing where nothing else names the pane. In
        # the bottom panel the tab already says CLAUDE, so it is hidden there.
        self.head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.head.get_style_context().add_class("assisthead")
        title = Gtk.Label(label="CLAUDE")
        title.set_xalign(0.0)
        title.get_style_context().add_class("assistlabel")
        self.head.pack_start(title, True, True, 0)
        self._add_actions(self.head)
        self.head.set_no_show_all(True)
        self.pack_start(self.head, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.pack_start(self.body, True, True, 0)

    def _add_actions(self, box):
        box.pack_end(icon_button("window-close-symbolic", "✕",
                                 "Hide Claude   Ctrl+Shift+C",
                                 lambda *_: self.window.hide_claude()),
                     False, False, 0)
        box.pack_end(icon_button("view-refresh-symbolic", "restart",
                                 "Start Claude again",
                                 lambda *_: self.restart()), False, False, 0)
        box.pack_end(icon_button("view-fullscreen-symbolic", "move",
                                 "Where Claude opens",
                                 lambda b: self.window.claude_place_menu(b)),
                     False, False, 0)
        box.pack_end(icon_button("mail-send-symbolic", "point",
                                 "Point Claude at the open file   Ctrl+Alt+A",
                                 lambda *_: self.window.point_claude_at_current()),
                     False, False, 0)

    def show_head(self, wanted):
        """The head is redundant wherever the container already labels it."""
        self.head.set_visible(wanted)

    # -- the session -----------------------------------------------------------
    def started(self):
        return self.terminal is not None

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
        return True

    def focus(self):
        if self.terminal is not None:
            self.terminal.term.grab_focus()

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


class ClaudeWindow(Gtk.Window):
    """Claude on its own, for a second monitor.

    It holds the assistant widget rather than owning it: closing this window
    hands the widget back to the main window with the session still running.
    """

    def __init__(self, parent, assistant):
        super().__init__(title="Claude — %s" % (core.short_path(parent.root)
                                                if parent.root else core.APP_NAME))
        self.parent = parent
        self.set_default_size(560, 720)
        self.set_transient_for(parent)
        self.set_destroy_with_parent(True)
        self.get_style_context().add_class("prism")
        self.add(assistant)
        self.connect("delete-event", self._closed)

    def _closed(self, *_):
        self.parent.hide_claude()
        return True                     # hide_claude takes the widget out first
