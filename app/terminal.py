"""terminal — one VTE terminal, its child process and its colours.

Lives in its own module so the code view can embed one too.
"""
import os
import re

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gdk, GLib, Gtk, Pango, Vte  # noqa: E402

import core  # noqa: E402

URL_RE = (r"(?:https?://|www\.)[-\w.~:/?#\[\]@!$&'()*+,;=%]+")


class PrismTerminal(Gtk.Box):
    """A VTE terminal plus its scrollbar, and the logic to (re)start a child.

    It reports changes back through optional hooks on the window rather than
    calling into a tab strip, because in this app a terminal is one panel among
    several and the window may not want to know.
    """

    def __init__(self, win, argv, cwd=None, name=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.win = win
        self.argv = argv
        self.cwd = cwd or os.path.expanduser("~")
        self.custom_name = name
        self.is_claude = False
        # what to call this in messages: the command, not the shell wrapping it
        self.display_cmd = os.path.basename(argv[0])
        if len(argv) > 2 and argv[-2] == "-c":
            self.display_cmd = argv[-1].replace("exec ", "", 1).split()[0]
        self.dead = False
        self.pid = None
        # A freshly spawned shell is not reading its pty yet, so anything fed
        # to it in the first moments is simply lost. This flips once the shell
        # has actually put something on screen.
        self.ready = False

        self.term = Vte.Terminal()
        self.term.set_hexpand(True)
        self.term.set_vexpand(True)
        self.term.set_scroll_on_output(False)
        self.term.set_scroll_on_keystroke(True)
        self.term.set_mouse_autohide(True)
        self.term.set_allow_hyperlink(True)
        self.term.set_word_char_exceptions("-A-Za-z0-9,./?%&#:_=+@~")

        try:
            regex = Vte.Regex.new_for_match(URL_RE, -1, 0x00000400)  # PCRE2_MULTILINE
            self.url_tag = self.term.match_add_regex(regex, 0)
            self.term.match_set_cursor_name(self.url_tag, "pointer")
        except Exception:
            self.url_tag = -1

        self.term.connect("child-exited", self._child_exited)
        self.term.connect("contents-changed", self._first_output)
        self.term.connect("window-title-changed", lambda *_: self._changed())
        self.term.connect("bell", lambda *_: self._bell())
        self.term.connect("button-press-event", self._button_press)
        self.term.connect("key-press-event", self._key_press)

        scroll = Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL,
                               adjustment=self.term.get_vadjustment())

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.get_style_context().add_class("termbox")
        box.pack_start(self.term, True, True, 0)
        box.pack_start(scroll, False, False, 0)
        self.pack_start(box, True, True, 0)

    # -- lifecycle ---------------------------------------------------------- #
    def spawn(self):
        env = ["%s=%s" % (k, v) for k, v in os.environ.items()
               if k not in ("COLUMNS", "LINES", "TMUX", "TMUX_PANE")]
        env.append("TERM=xterm-256color")
        env.append("COLORTERM=truecolor")
        env.append("PRISM_STUDIO=1")
        try:
            self.term.spawn_async(
                Vte.PtyFlags.DEFAULT, self.cwd, self.argv, env,
                GLib.SpawnFlags.DEFAULT, None, None, -1, None, self._spawned)
        except TypeError:
            self.term.spawn_async(
                Vte.PtyFlags.DEFAULT, self.cwd, self.argv, env,
                GLib.SpawnFlags.DEFAULT, None, None, -1, None, self._spawned, None)

    def _first_output(self, *_):
        self.ready = True

    def when_ready(self, run, timeout_ms=4000):
        """Call `run` once the shell is listening, or give up and try anyway."""
        if self.ready:
            run()
            return
        state = {"done": False}

        def fire():
            if state["done"]:
                return False
            state["done"] = True
            run()
            return False

        handler = []

        def on_output(*_):
            if handler:
                self.term.disconnect(handler[0])
                del handler[:]
            GLib.idle_add(fire)

        handler.append(self.term.connect("contents-changed", on_output))
        GLib.timeout_add(timeout_ms, fire)

    def _spawned(self, terminal, pid, error, *_):
        if error:
            self.term.feed(("\r\n  could not start: %s\r\n" % error.message).encode())
            self.dead = True
        self.pid = pid
        self._changed()

    def _child_exited(self, _term, status):
        self.dead = True
        t = self.win.theme
        if os.WIFSIGNALED(status):
            what = "was killed by signal %d" % os.WTERMSIG(status)
        elif os.WIFEXITED(status):
            code = os.WEXITSTATUS(status)
            what = "exited" if code == 0 else "exited with status %d" % code
        else:
            what = "exited (%d)" % status
        self.term.feed(("\r\n\x1b[38;2;%d;%d;%dm  %s %s\x1b[0m — "
                        "press \x1b[1mEnter\x1b[0m to run it again, or close the tab\r\n"
                        % (*core.rgb(t["DIM"]), self.display_cmd, what)).encode())
        self._changed()

    def _key_press(self, _w, event):
        if self.dead and event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.dead = False
            self.term.reset(True, True)
            self.spawn()
            return True
        return False

    def _button_press(self, term, event):
        if event.button == 1 and (event.state & Gdk.ModifierType.CONTROL_MASK):
            uri = None
            if self.url_tag >= 0:
                match = term.match_check_event(event)
                uri = match[0] if match and match[0] else None
            if uri:
                if uri.startswith("www."):
                    uri = "https://" + uri
                Gtk.show_uri_on_window(self.win, uri, Gdk.CURRENT_TIME)
                return True
        if event.button == 3:
            self._context_menu(event)
            return True
        return False

    def _changed(self):
        hook = getattr(self.win, "terminal_changed", None)
        if hook:
            hook(self)

    def _bell(self):
        hook = getattr(self.win, "terminal_bell", None)
        if hook:
            hook(self)

    def _context_menu(self, event):
        menu = Gtk.Menu()

        def add(label, fn, enabled=True):
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(enabled)
            item.connect("activate", lambda *_: fn())
            menu.append(item)

        add("Copy", lambda: self.term.copy_clipboard_format(Vte.Format.TEXT),
            self.term.get_has_selection())
        add("Paste", self.term.paste_clipboard)
        add("Select all", self.term.select_all)
        menu.append(Gtk.SeparatorMenuItem())
        add("Clear", lambda: self.term.reset(True, True))
        menu.show_all()
        menu.popup_at_pointer(event)

    # -- appearance --------------------------------------------------------- #
    def restyle(self, t, cfg):
        def rgba(hexstr, alpha=1.0):
            c = Gdk.RGBA()
            c.parse(hexstr)
            c.alpha = alpha
            return c

        opacity = max(30, min(100, int(cfg.get("OPACITY", "100")))) / 100.0
        palette = [rgba(c) for c in t["_ansi"]]
        self.term.set_colors(rgba(t["FG"]), rgba(t["BG"], opacity), palette)
        self.term.set_color_cursor(rgba(t["ACCENT"]))
        self.term.set_color_cursor_foreground(rgba(t["ACTIVE_FG"]))
        self.term.set_color_highlight(rgba(t["ACCENT"]))
        self.term.set_color_highlight_foreground(rgba(t["ACTIVE_FG"]))
        self.term.set_clear_background(opacity >= 0.999)

        self.term.set_font(Pango.FontDescription.from_string(cfg.get("FONT", "Ubuntu Sans Mono 11")))
        self.term.set_scrollback_lines(int(cfg.get("SCROLLBACK", "50000") or 0))
        shape = {"block": Vte.CursorShape.BLOCK, "ibeam": Vte.CursorShape.IBEAM,
                 "underline": Vte.CursorShape.UNDERLINE}.get(cfg.get("CURSOR", "block"),
                                                             Vte.CursorShape.BLOCK)
        self.term.set_cursor_shape(shape)
        self.term.set_cursor_blink_mode(Vte.CursorBlinkMode.ON if cfg.get("CURSOR_BLINK", "1") == "1"
                                        else Vte.CursorBlinkMode.OFF)
        self.term.set_audible_bell(cfg.get("BELL", "0") == "1")

    def zoom(self, delta):
        scale = self.term.get_font_scale()
        self.term.set_font_scale(1.0 if delta == 0 else max(0.4, min(4.0, scale + delta)))

    # -- naming ------------------------------------------------------------- #
    @property
    def label(self):
        if self.custom_name:
            return self.custom_name
        title = (self.term.get_window_title() or "").strip()
        if title:
            # shells set "user@host: /some/path" — the directory is the useful bit
            m = re.match(r"^[^@\s]+@[^:\s]+:\s*(.+)$", title)
            if m:
                path = m.group(1).strip().rstrip("/")
                return (os.path.basename(path) or path)[:28]
            return title[:28]
        return os.path.basename(self.argv[0])[:28]


