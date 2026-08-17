"""inline — ghost text at the cursor, and the bar that asks Claude for an edit.

The suggestion is never put in the buffer. It is painted over the view after
GTK has drawn the real text, so it cannot end up in your file, in your undo
history, or in a save you did not mean to make. Tab takes it, Escape drops it.
"""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

import core  # noqa: E402


def _rgb(value):
    colour = Gdk.RGBA()
    colour.parse(value)
    return colour


class Ghost:
    """What we think you are about to type, drawn but not written."""

    def __init__(self, view):
        self.view = view
        self.items = []
        self.index = 0
        self.anchor = None              # (buffer, offset) it was worked out at
        self.fg = _rgb("#7a8493")
        self.bg = _rgb("#0b1017")
        self.badge = _rgb("#4f8cc9")
        view.connect_after("draw", self._draw)

    # -- state -------------------------------------------------------------
    @property
    def text(self):
        if not self.items:
            return ""
        return self.items[self.index % len(self.items)].text

    @property
    def item(self):
        if not self.items:
            return None
        return self.items[self.index % len(self.items)]

    def show(self, items):
        items = [i for i in items if i.text.strip()]
        buf = self.view.get_buffer()
        offset = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        self.items = items
        self.index = 0
        self.anchor = (buf, offset) if items else None
        self.view.queue_draw()
        return bool(items)

    def add(self, item):
        """Fold a late arrival in at the front, if the cursor has not moved."""
        if not self.stale() and item.text.strip():
            self.items.insert(0, item)
            self.index = 0
            self.view.queue_draw()
            return True
        buf = self.view.get_buffer()
        offset = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        self.items = [item]
        self.index = 0
        self.anchor = (buf, offset)
        self.view.queue_draw()
        return True

    def stale(self):
        if not self.items or self.anchor is None:
            return True
        buf = self.view.get_buffer()
        if buf is not self.anchor[0]:
            return True
        return buf.get_iter_at_mark(buf.get_insert()).get_offset() != self.anchor[1]

    def clear(self):
        if not self.items:
            return False
        self.items = []
        self.anchor = None
        self.view.queue_draw()
        return True

    def cycle(self, step=1):
        if len(self.items) < 2:
            return False
        self.index = (self.index + step) % len(self.items)
        self.view.queue_draw()
        return True

    # -- taking it ---------------------------------------------------------
    def accept(self, how="all"):
        """Insert the suggestion (or its first word) as one undoable edit."""
        text = self.text
        if not text or self.stale():
            self.clear()
            return False
        if how == "word":
            text = self._first_word(text)
            if not text:
                return False
        buf = self.view.get_buffer()
        buf.begin_user_action()
        buf.insert_at_cursor(text)
        buf.end_user_action()
        if how == "word":
            rest = self.text[len(text):]
            self.items = []
            self.anchor = None
            if rest.strip():
                from assist import Suggestion
                self.show([Suggestion(rest, self.item.source if self.item else "local")])
        else:
            self.clear()
        self.view.scroll_mark_onscreen(buf.get_insert())
        return True

    @staticmethod
    def _first_word(text):
        if text.startswith("\n"):
            return "\n"
        i = 0
        while i < len(text) and text[i] in " \t":
            i += 1
        while i < len(text) and (text[i].isalnum() or text[i] == "_"):
            i += 1
        if i == 0:                      # punctuation run: take one character
            i = 1
        return text[:i]

    # -- looks -------------------------------------------------------------
    def restyle(self, theme):
        self.fg = _rgb(core.mix(theme["BG"], theme["FG"], 0.42))
        self.bg = _rgb(theme["BG"])
        self.badge = _rgb(theme["ACCENT"])

    def _draw(self, view, cr):
        text = self.text
        if not text or self.stale():
            return False
        window = view.get_window(Gtk.TextWindowType.TEXT)
        if window is None or not Gtk.cairo_should_draw_window(cr, window):
            return False

        buf = view.get_buffer()
        it = buf.get_iter_at_mark(buf.get_insert())
        rect = view.get_iter_location(it)
        x, y = view.buffer_to_window_coords(Gtk.TextWindowType.TEXT, rect.x, rect.y)

        cr.save()
        Gtk.cairo_transform_to_window(cr, view, window)

        lines = text.split("\n")
        layout = view.create_pango_layout("")
        _, line_height = self._extent(layout, "Mg")

        # the part that continues the line you are on
        first = lines[0]
        if first:
            layout.set_text(first, -1)
            Gdk.cairo_set_source_rgba(cr, self.fg)
            cr.move_to(x, y)
            PangoCairo.show_layout(cr, layout)

        # anything else goes underneath, on its own quiet slab
        rest = [ln for ln in lines[1:]]
        if rest:
            width = max(self._extent(layout, ln or " ")[0] for ln in rest) + 14
            left = view.get_left_margin()
            top = y + line_height
            cr.set_source_rgba(self.bg.red, self.bg.green, self.bg.blue, 0.94)
            cr.rectangle(left - 4, top, width, line_height * len(rest) + 4)
            cr.fill()
            Gdk.cairo_set_source_rgba(cr, self.badge)
            cr.rectangle(left - 4, top, 2, line_height * len(rest) + 4)
            cr.fill()
            Gdk.cairo_set_source_rgba(cr, self.fg)
            for n, line in enumerate(rest):
                layout.set_text(line, -1)
                cr.move_to(left + 4, top + 2 + n * line_height)
                PangoCairo.show_layout(cr, layout)

        cr.restore()
        return False

    @staticmethod
    def _extent(layout, text):
        layout.set_text(text, -1)
        return layout.get_pixel_size()


class EditBar(Gtk.Revealer):
    """Ctrl+I: say what you want changed, Claude rewrites just that part."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.set_transition_duration(110)
        self.pending = None

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.get_style_context().add_class("editbar")

        self.tag = Gtk.Label(label="edit")
        self.tag.get_style_context().add_class("editbartag")
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("what should Claude change here?")
        # a small minimum so a narrow pane shrinks the entry rather than
        # pushing the Ask Claude button off the end of the bar
        self.entry.set_width_chars(12)
        self.entry.connect("activate", lambda *_: self.submit())
        self.entry.connect("key-press-event", self._keys)

        self.note = Gtk.Label(label="")
        self.note.get_style_context().add_class("editbarnote")

        self.go = Gtk.Button(label="Ask Claude")
        self.go.get_style_context().add_class("editbargo")
        self.go.connect("clicked", lambda *_: self.submit())
        close = Gtk.Button(label="✕")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.get_style_context().add_class("iconbtn")
        close.connect("clicked", lambda *_: self.close())

        box.pack_start(self.tag, False, False, 0)
        box.pack_start(self.entry, True, True, 0)
        box.pack_start(self.note, False, False, 0)
        box.pack_end(close, False, False, 0)
        box.pack_end(self.go, False, False, 0)
        self.add(box)

    def _keys(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def open(self):
        doc = self.editor.doc()
        if doc is None:
            return
        buf = doc.buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            self.note.set_text("lines %d–%d" % (start.get_line() + 1, end.get_line() + 1))
        else:
            it = buf.get_iter_at_mark(buf.get_insert())
            self.note.set_text("line %d" % (it.get_line() + 1))
        self.show_all()
        self.set_reveal_child(True)
        self.entry.grab_focus()

    def close(self):
        self.set_reveal_child(False)
        self.note.set_text("")
        self.entry.set_text("")
        self.go.set_sensitive(True)
        self.editor.view.grab_focus()

    def busy(self, on, message=""):
        self.go.set_sensitive(not on)
        self.go.set_label("Working…" if on else "Ask Claude")
        if message:
            self.note.set_text(message)

    def submit(self):
        instruction = self.entry.get_text().strip()
        if not instruction:
            return
        self.busy(True, "Claude is reading it…")
        self.editor.claude_edit(instruction, self._finished)

    def _finished(self, ok, message):
        self.busy(False, message)
        if ok:
            GLib.timeout_add(400, lambda: (self.close(), False)[1])
