"""selection — the little bar that appears when you highlight something.

Select some text and a small popup follows the selection with the two or three
things you actually want to do with it. It is deliberately quiet: it waits
until you have stopped dragging, it never steals focus, and it disappears the
moment the selection does, so it can be ignored completely by anyone who would
rather use the keyboard.

Which actions it offers depends on what is switched on. With the assistant
turned off it is still useful, because searching and copying do not need one.
"""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

SETTLE_MS = 260          # quiet time after the selection stops changing
MAX_CHARS = 20000        # past this it is a select-all, not an intention


class SelectionBar:
    """A popover of actions for whatever is selected in the editor."""

    def __init__(self, window, editor):
        self.window = window
        self.editor = editor
        self.view = editor.view
        self._timer = None
        self._anchor = None
        self._suppressed = False

        self.popover = Gtk.Popover.new(self.view)
        self.popover.set_position(Gtk.PositionType.TOP)
        self.popover.set_modal(False)          # never steal the keyboard
        self.popover.get_style_context().add_class("selbar")

        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.box.set_border_width(4)
        self.popover.add(self.box)

        self.view.connect("button-release-event", lambda *_: self._changed())
        self.view.connect("key-release-event", self._key_release)
        self.view.connect("scroll-event", lambda *_: self.hide())
        self.view.connect("focus-out-event", lambda *_: self.hide())

    # -- what goes on it -------------------------------------------------------
    def actions(self):
        """(label, tooltip, callback) for the current selection."""
        out = [("Search", "Find this across the workspace   Ctrl+Shift+F",
                self._search)]
        if self.window.assistant_enabled:
            out = [("Ask Claude", "Point Claude at this   Ctrl+Alt+A", self._ask),
                   ("Change…", "Have Claude rewrite it   Ctrl+I", self._change)] + out
        out.append(("Copy", "Copy   Ctrl+C", self._copy))
        return out

    def _rebuild(self):
        for child in self.box.get_children():
            self.box.remove(child)
        for label, tip, fn in self.actions():
            button = Gtk.Button(label=label)
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_tooltip_text(tip)
            button.get_style_context().add_class("selbtn")
            button.connect("clicked", (lambda f: lambda *_: self._run(f))(fn))
            self.box.pack_start(button, False, False, 0)
        self.box.show_all()

    def _run(self, fn):
        self.hide()
        fn()

    # -- deciding whether to show ---------------------------------------------
    def _key_release(self, _widget, event):
        # only a shift-arrow style selection should raise it, not ordinary typing
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            self._changed()
        else:
            self.hide()
        return False

    def _changed(self):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(SETTLE_MS, self._settled)
        return False

    def _settled(self):
        self._timer = None
        if self._suppressed:
            return False
        doc = self.editor.doc()
        if doc is None or not doc.buffer.get_has_selection():
            self.hide()
            return False
        start, end = doc.buffer.get_selection_bounds()
        if end.get_offset() - start.get_offset() > MAX_CHARS:
            self.hide()
            return False
        self.show_at(start, end)
        return False

    def show_at(self, start, end):
        """Sit just above the selection, or below it near the top of the view."""
        rect = self.view.get_iter_location(start)
        end_rect = self.view.get_iter_location(end)
        x, y = self.view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y)
        x2, _ = self.view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, end_rect.x, end_rect.y)
        if end.get_line() != start.get_line():
            x2 = x + 220                       # a multi-line block: centre roughly
        point = Gdk.Rectangle()
        point.x = int(min(x, x2) + abs(x2 - x) / 2)
        point.y = int(y)
        point.width = 1
        point.height = int(rect.height)
        # near the very top there is no room above, so flip underneath
        self.popover.set_position(Gtk.PositionType.BOTTOM if point.y < 48
                                  else Gtk.PositionType.TOP)
        self._rebuild()
        self.popover.set_pointing_to(point)
        self.popover.popup()
        self._anchor = (start.get_offset(), end.get_offset())

    def hide(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        self._anchor = None
        self.popover.popdown()
        return False

    def suppress(self, on):
        """Held down while a dialog or the edit bar is doing the talking."""
        self._suppressed = on
        if on:
            self.hide()

    # -- the actions -----------------------------------------------------------
    def _ask(self):
        self.editor.ask_claude()

    def _change(self):
        self.editor.editbar.open()

    def _search(self):
        self.window.focus_search()

    def _copy(self):
        doc = self.editor.doc()
        if doc is None:
            return
        doc.buffer.copy_clipboard(Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD))
        self.window.say("copied")
