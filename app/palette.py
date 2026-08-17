"""palette — Ctrl+Shift+P: every command in one searchable list.

Built-in commands and anything extensions registered end up in the same place,
which is the only reason an extension is discoverable at all. Type to filter,
Enter to run, Escape to leave.
"""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402


def score(needle, hay):
    """Loose subsequence match. Returns None for no match, lower is better."""
    if not needle:
        return 0
    needle, hay = needle.lower(), hay.lower()
    if needle in hay:
        return hay.index(needle)
    pos, gaps, last = 0, 0, -1
    for ch in needle:
        found = hay.find(ch, pos)
        if found < 0:
            return None
        if last >= 0:
            gaps += found - last - 1
        last, pos = found, found + 1
    return 200 + gaps


class Palette(Gtk.Window):
    def __init__(self, parent, commands):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_decorated(False)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.set_default_size(620, 420)
        self.get_style_context().add_class("palette")
        self.commands = commands
        self.shown = []

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Type a command")
        self.entry.connect("changed", lambda *_: self.refilter())
        self.entry.connect("activate", lambda *_: self.run_selected())
        self.entry.connect("key-press-event", self._keys)
        box.pack_start(self.entry, False, False, 0)

        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.list.connect("row-activated", lambda *_: self.run_selected())
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.list)
        box.pack_start(scroll, True, True, 0)

        self.add(box)
        self.connect("key-press-event", self._keys)
        self.refilter()

    # -- the list ----------------------------------------------------------
    def refilter(self):
        text = self.entry.get_text().strip()
        scored = []
        for cmd in self.commands:
            hit = score(text, cmd.label + " " + cmd.id)
            if hit is not None:
                scored.append((hit, cmd))
        scored.sort(key=lambda pair: (pair[0], pair[1].label))
        self.shown = [cmd for _s, cmd in scored]

        for child in self.list.get_children():
            self.list.remove(child)
        for cmd in self.shown[:120]:
            self.list.add(self._row(cmd))
        self.list.show_all()
        first = self.list.get_row_at_index(0)
        if first:
            self.list.select_row(first)

    @staticmethod
    def _row(cmd):
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("paletterow")
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label=cmd.label)
        label.set_xalign(0.0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.get_style_context().add_class("palettelabel")
        line.pack_start(label, True, True, 0)
        if cmd.source and cmd.source != "prism":
            tag = Gtk.Label(label=cmd.source.upper())
            tag.get_style_context().add_class("palettefrom")
            line.pack_end(tag, False, False, 0)
        if cmd.keys:
            keys = Gtk.Label(label=cmd.keys)
            keys.get_style_context().add_class("palettekeys")
            line.pack_end(keys, False, False, 0)
        row.add(line)
        row.command = cmd
        return row

    # -- driving it --------------------------------------------------------
    def _keys(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            row = self.list.get_selected_row()
            index = (row.get_index() if row else 0) + (1 if event.keyval == Gdk.KEY_Down else -1)
            index = max(0, min(index, len(self.list.get_children()) - 1))
            nxt = self.list.get_row_at_index(index)
            if nxt:
                self.list.select_row(nxt)
                nxt.grab_focus()
                self.entry.grab_focus_without_selecting()
            return True
        return False

    def run_selected(self):
        row = self.list.get_selected_row()
        if row is None:
            return
        command = row.command
        self.destroy()
        try:
            command.run()
        except Exception as exc:
            print("command %s failed: %s" % (command.id, exc))

    def place_over(self, parent):
        """Sit near the top of the parent window, never off the screen edge.

        CENTER_ON_PARENT cannot be trusted: where the parent has no usable
        origin yet it centres on (0, 0) and half the palette ends up off the
        left of the display. Work it out and clamp instead.
        """
        width, height = self.get_size()
        try:
            origin_x, origin_y = parent.get_position()
        except Exception:
            origin_x, origin_y = 0, 0
        alloc = parent.get_allocation()
        x = origin_x + max(0, (alloc.width - width) // 2)
        y = origin_y + max(0, int(alloc.height * 0.12))
        screen = self.get_screen()
        if screen is not None:
            x = max(0, min(x, max(0, screen.get_width() - width)))
            y = max(0, min(y, max(0, screen.get_height() - height)))
        self.move(max(0, x), max(0, y))

    def present_it(self):
        self.show_all()
        self.place_over(self.get_transient_for() or self)
        self.present()
        self.entry.grab_focus()
