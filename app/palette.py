"""palette — one box that goes anywhere in the workspace.

Ctrl+P opens it on the files in the folder, Ctrl+Shift+P on the commands. The
prefix decides, so you never have to close it and open the other one:

    (nothing)   files in this workspace, fuzzy matched
    >           every command, built in and from extensions
    :           a line number in the file you are looking at

Filtering happens on the strings, never on the disk: the file list is walked
once in the background and reused, so typing stays instant in a big repository.
"""
import os

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

MAX_ROWS = 60           # more than fits on screen, fewer than costs anything


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


class Item:
    """One row: what it says, what it says quietly, and what it does."""

    def __init__(self, label, detail="", keys="", tag="", run=None, sort="",
                 ident=""):
        self.id = ident or label
        self.label = label
        self.detail = detail
        self.keys = keys
        self.tag = tag
        self.run = run or (lambda: None)
        self.sort = sort or label


class Palette(Gtk.Window):
    def __init__(self, parent, commands, files=None, start=""):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_decorated(False)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.set_default_size(660, 440)
        self.get_style_context().add_class("palette")
        self.win = parent
        self.commands = commands
        self.files = files or []
        self.shown = []
        self._filter_timer = None

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)

        self.entry = Gtk.Entry()
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

        self.hint = Gtk.Label(label="")
        self.hint.set_xalign(0.0)
        self.hint.get_style_context().add_class("palettehint")
        box.pack_start(self.hint, False, False, 0)

        self.add(box)
        self.connect("key-press-event", self._keys)
        self.entry.set_text(start)
        self.entry.set_position(-1)
        self.refilter()

    # -- what is being asked for ----------------------------------------------
    def mode(self):
        text = self.entry.get_text()
        if text.startswith(">"):
            return "commands", text[1:].strip()
        if text.startswith(":"):
            return "line", text[1:].strip()
        return ("files" if self.files else "commands"), text.strip()

    def set_files(self, files):
        """The background walk landed; use it without disturbing the typing."""
        self.files = files
        if self.mode()[0] == "files":
            self.refilter()

    # -- the list --------------------------------------------------------------
    def refilter(self):
        which, needle = self.mode()
        if which == "commands":
            items = self._command_items(needle)
            self.entry.set_placeholder_text("Type a command")
            note = "%d commands   ·   Ctrl+P for files" % len(items)
        elif which == "line":
            items = self._line_items(needle)
            self.entry.set_placeholder_text("Line number")
            note = "go to a line in this file"
        else:
            items = self._file_items(needle)
            self.entry.set_placeholder_text("Go to file")
            note = ("%d of %d files   ·   > for commands, : for a line"
                    % (len(items), len(self.files)))
            if not self.files:
                note = "no folder open   ·   > for commands"
        self.shown = items
        self.hint.set_text(note)

        for child in self.list.get_children():
            self.list.remove(child)
        for item in items[:MAX_ROWS]:
            self.list.add(self._row(item))
        self.list.show_all()
        first = self.list.get_row_at_index(0)
        if first:
            self.list.select_row(first)

    def _command_items(self, needle):
        scored = []
        for cmd in self.commands:
            hit = score(needle, cmd.label + " " + cmd.id)
            if hit is not None:
                scored.append((hit, cmd.label, Item(
                    cmd.label, ident=cmd.id, keys=cmd.keys,
                    tag="" if cmd.source in ("prism", None) else cmd.source.upper(),
                    run=cmd.run)))
        scored.sort(key=lambda row: (row[0], row[1]))
        return [item for _s, _l, item in scored]

    def _file_items(self, needle):
        open_now = {os.path.abspath(d.path) for d in self.win.editor.docs if d.path}
        root = self.win.root or ""
        scored = []
        for relative in self.files:
            name = os.path.basename(relative)
            hit = score(needle, relative)
            if hit is None:
                continue
            # a match on the name itself beats a match somewhere in the folders
            if score(needle, name) is not None:
                hit -= 60
            full = os.path.join(root, relative)
            if full in open_now:
                hit -= 25               # what you already have open is likelier
            folder = os.path.dirname(relative)
            scored.append((hit, relative, Item(
                name, ident=relative, detail=folder,
                tag="OPEN" if full in open_now else "",
                run=(lambda f: lambda: self.win.open_file(f))(full))))
        scored.sort(key=lambda row: (row[0], row[1]))
        return [item for _s, _r, item in scored]

    def _line_items(self, needle):
        if not needle.isdigit():
            return [Item("Type a line number", detail="the file you are looking at")]
        number = int(needle)
        return [Item("Go to line %d" % number,
                     run=(lambda n: lambda: self.win.editor.go_to(n))(number))]

    @staticmethod
    def _row(item):
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("paletterow")
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label=item.label)
        label.set_xalign(0.0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.get_style_context().add_class("palettelabel")
        line.pack_start(label, False, False, 0)
        if item.detail:
            detail = Gtk.Label(label=item.detail)
            detail.set_xalign(0.0)
            detail.set_ellipsize(Pango.EllipsizeMode.START)
            detail.get_style_context().add_class("palettedetail")
            line.pack_start(detail, True, True, 0)
        else:
            line.pack_start(Gtk.Label(label=""), True, True, 0)
        if item.tag:
            tag = Gtk.Label(label=item.tag)
            tag.get_style_context().add_class("palettefrom")
            line.pack_end(tag, False, False, 0)
        if item.keys:
            keys = Gtk.Label(label=item.keys)
            keys.get_style_context().add_class("palettekeys")
            line.pack_end(keys, False, False, 0)
        row.add(line)
        row.item = item
        return row

    # -- driving it ------------------------------------------------------------
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
                self.entry.set_position(-1)
            return True
        return False

    def run_selected(self):
        row = self.list.get_selected_row()
        if row is None:
            return
        item = row.item
        self.destroy()
        try:
            item.run()
        except Exception as exc:
            print("palette: %s failed: %s" % (item.label, exc))

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
        y = origin_y + max(0, int(alloc.height * 0.10))
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
        self.entry.set_position(-1)
        GLib.idle_add(self.refilter)
