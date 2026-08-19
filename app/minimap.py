"""minimap — the little picture of the file down the right hand side.

It is drawn rather than rendered: every line becomes a row of small blocks,
one per run of non-space characters, indented the way the line is indented and
tinted by what the line mostly is — a comment, a string-ish line, or code. At
two pixels a line that reads as the shape of the file, which is all a minimap
is for. Drawing it as text would mean laying out the whole buffer twice.

The visible region is boxed, dragging or clicking scrolls the editor, and the
whole thing is one GtkDrawingArea so it costs nothing when it is switched off.
"""
import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import core  # noqa: E402

WIDTH = 110             # what VS Code gives it, near enough
LINE_HEIGHT = 2         # pixels per line of code
CHAR_WIDTH = 1          # pixels per character
MAX_LINES = 20000       # past this it is a smear anyway, so stop drawing


class Minimap(Gtk.DrawingArea):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.set_size_request(WIDTH, -1)
        self.get_style_context().add_class("minimap")
        self._colours = None
        self._redraw = None
        self._dragging = False

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.SCROLL_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._pressed)
        self.connect("button-release-event", self._released)
        self.connect("motion-notify-event", self._moved)
        self.connect("scroll-event", self._scrolled)

    # -- keeping up ------------------------------------------------------------
    def touch(self):
        """Something changed; redraw once the typing has stopped for a moment."""
        if self._redraw is not None:
            return
        self._redraw = GLib.timeout_add(120, self._redraw_now)

    def _redraw_now(self):
        self._redraw = None
        self.queue_draw()
        return False

    def restyle(self, theme):
        bg = theme["BG"]
        self._colours = {
            "bg": core.rgb(theme.get("MINIMAP_BG") or bg),
            "code": core.rgb(theme.get("SYN_VARIABLE") or core.mix(bg, theme["FG"], 0.65)),
            "comment": core.rgb(theme.get("SYN_COMMENT") or theme["DIM"]),
            "string": core.rgb(theme.get("SYN_STRING") or theme["ACCENT2"]),
            "view": core.rgb(theme["FG"]),
        }
        self.queue_draw()

    # -- drawing ---------------------------------------------------------------
    def _draw(self, _widget, ctx):
        if self._colours is None:
            self.restyle(self.editor.win.theme)
        colours = self._colours
        width = self.get_allocated_width()
        height = self.get_allocated_height()

        ctx.set_source_rgb(*[c / 255 for c in colours["bg"]])
        ctx.paint()

        doc = self.editor.doc()
        if doc is None:
            return False
        buf = doc.buffer
        total = min(buf.get_line_count(), MAX_LINES)
        if not total:
            return False

        # which slice of the file to draw: follow the editor when the file is
        # taller than the map, otherwise draw from the top
        rows = max(1, height // LINE_HEIGHT)
        first = 0
        if total > rows:
            here = buf.get_iter_at_mark(buf.get_insert()).get_line()
            first = max(0, min(total - rows, here - rows // 2))

        for index in range(first, min(total, first + rows)):
            start = buf.get_iter_at_line(index)
            end = start.copy()
            if not end.ends_line():
                end.forward_to_line_end()
            text = buf.get_text(start, end, False)
            if not text.strip():
                continue
            stripped = text.lstrip()
            indent = len(text) - len(stripped)
            kind = "code"
            head = stripped[:2]
            if head[:1] in "#" or head in ("//", "/*", "--") or stripped.startswith("*"):
                kind = "comment"
            elif stripped[:1] in "\"'":
                kind = "string"
            red, green, blue = colours[kind]
            ctx.set_source_rgba(red / 255, green / 255, blue / 255,
                                0.55 if kind == "comment" else 0.75)

            y = (index - first) * LINE_HEIGHT
            x = 2 + indent * CHAR_WIDTH
            # one block per run of non-spaces, so the shape of the code shows
            run = 0
            for char in stripped:
                if char == " ":
                    if run:
                        ctx.rectangle(x, y, run * CHAR_WIDTH, LINE_HEIGHT - 1)
                        x += (run + 1) * CHAR_WIDTH
                        run = 0
                    else:
                        x += CHAR_WIDTH
                else:
                    run += 1
                if x > width:
                    break
            if run and x < width:
                ctx.rectangle(x, y, min(run * CHAR_WIDTH, width - x), LINE_HEIGHT - 1)
            ctx.fill()

        # the box around what is actually on screen
        view_first, view_last = self.editor.visible_lines()
        if view_last > view_first:
            top = (view_first - first) * LINE_HEIGHT
            deep = max(LINE_HEIGHT, (view_last - view_first) * LINE_HEIGHT)
            red, green, blue = colours["view"]
            ctx.set_source_rgba(red / 255, green / 255, blue / 255, 0.10)
            ctx.rectangle(0, top, width, deep)
            ctx.fill()
        return False

    # -- driving it ------------------------------------------------------------
    def _line_at(self, y):
        doc = self.editor.doc()
        if doc is None:
            return 0
        total = min(doc.buffer.get_line_count(), MAX_LINES)
        rows = max(1, self.get_allocated_height() // LINE_HEIGHT)
        first = 0
        if total > rows:
            here = doc.buffer.get_iter_at_mark(doc.buffer.get_insert()).get_line()
            first = max(0, min(total - rows, here - rows // 2))
        return max(0, min(total - 1, first + int(y) // LINE_HEIGHT))

    def _pressed(self, _widget, event):
        self._dragging = True
        self.editor.scroll_to_line(self._line_at(event.y))
        return True

    def _released(self, *_):
        self._dragging = False
        return True

    def _moved(self, _widget, event):
        if self._dragging:
            self.editor.scroll_to_line(self._line_at(event.y))
        return True

    def _scrolled(self, _widget, event):
        step = 3 if event.direction == Gdk.ScrollDirection.DOWN else -3
        first, _last = self.editor.visible_lines()
        self.editor.scroll_to_line(max(0, first + step * 3))
        return True
