"""explorer — the file tree down the left, and the file operations on it.

Nothing on the machine is listed until a folder is opened. Before that the
panel offers the ways in: open a folder, open a file, or pick something recent.
"""
import os
import shutil

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

import core  # noqa: E402
import workspace  # noqa: E402

FOLDER_ICON = "folder-symbolic"
FILE_ICON = "text-x-generic-symbolic"

# A file list where every row carries the same white page is a list you read
# by name alone. No icon theme ships a symbol per language, but symbolic icons
# take whatever colour they are handed, so the shape says what kind of thing it
# is and the colour says which language — both out of the skin, so a new skin
# recolours the tree with everything else.
KINDS = {
    "code": ("ACCENT", """py pyw js jsx mjs cjs ts tsx go rs c h cc cpp hpp java rb php
                          lua swift kt cs vue svelte dart scala ex exs erl hs ml r pl"""),
    "shell": ("OK", "sh bash zsh fish bat cmd ps1 mk makefile dockerfile"),
    "data": ("ACCENT2", """json yaml yml toml ini cfg conf env xml sql csv tsv plist
                           lock properties"""),
    "markup": ("MARKUP", "html htm css scss sass less styl jinja j2 twig"),
    "docs": ("QUIET", "md markdown rst txt text adoc org pdf doc docx tex"),
    "media": ("MEDIA", """png jpg jpeg gif svg ico webp bmp tiff mp3 wav ogg mp4 mov
                          webm ttf otf woff woff2"""),
}
EXTENSION_KIND = {ext: kind
                  for kind, (_tint, exts) in KINDS.items()
                  for ext in exts.split()}
# where a different shape is available and says more than the generic page
KIND_ICONS = {
    "shell": "utilities-terminal-symbolic",
    "media": "image-x-generic-symbolic",
    "docs": "emblem-documents-symbolic",
}
_symbolic_cache = {}


def symbolic_icon(name, colour, size=16):
    """A symbolic icon rendered in one colour, kept so it is drawn once."""
    key = (name, colour, size)
    if key in _symbolic_cache:
        return _symbolic_cache[key]
    theme = Gtk.IconTheme.get_default()
    info = theme.lookup_icon(name, size, 0) or theme.lookup_icon(FILE_ICON, size, 0)
    pixbuf = None
    if info is not None:
        tint = Gdk.RGBA()
        tint.parse(colour)
        try:
            pixbuf = info.load_symbolic(tint, None, None, None)[0]
        except Exception:
            try:
                pixbuf = info.load_icon()
            except Exception:
                pixbuf = None
    _symbolic_cache[key] = pixbuf
    return pixbuf


def file_kind(name):
    """Which family a file name belongs to, by extension or by being famous."""
    lowered = name.lower()
    if lowered in ("makefile", "dockerfile", "justfile", "procfile"):
        return "shell"
    if lowered.startswith(".") and "." not in lowered[1:]:
        return "data"                       # .gitignore, .env, .editorconfig
    ext = lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    return EXTENSION_KIND.get(ext, "plain")


def icon_button(icon, fallback, tip, cb, css="iconbtn"):
    button = Gtk.Button()
    if Gtk.IconTheme.get_default().has_icon(icon):
        button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
    else:
        button.set_label(fallback)
    button.set_tooltip_text(tip)
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.get_style_context().add_class(css)
    button.connect("clicked", cb)
    return button


def ask_text(parent, title, prompt, value=""):
    dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.get_style_context().add_class("prefs")
    area = dialog.get_content_area()
    area.set_border_width(12)
    area.set_spacing(8)
    label = Gtk.Label(label=prompt)
    label.set_xalign(0.0)
    entry = Gtk.Entry()
    entry.set_text(value)
    entry.set_width_chars(34)
    entry.set_activates_default(True)
    area.pack_start(label, False, False, 0)
    area.pack_start(entry, False, False, 0)
    dialog.show_all()
    answer = entry.get_text().strip() if dialog.run() == Gtk.ResponseType.OK else None
    dialog.destroy()
    return answer


def choose_folder(parent, start=None, title="Open folder"):
    return _chooser(parent, Gtk.FileChooserAction.SELECT_FOLDER, title, start)


def choose_file(parent, start=None, title="Open file"):
    return _chooser(parent, Gtk.FileChooserAction.OPEN, title, start)


def _chooser(parent, action, title, start, name=None):
    dialog = Gtk.FileChooserDialog(title=title, transient_for=parent, modal=True,
                                   action=action)
    dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
    dialog.get_style_context().add_class("prefs")
    dialog.set_current_folder(start or os.path.expanduser("~"))
    if name:
        dialog.set_current_name(name)
    dialog.set_default_size(820, 560)
    path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
    dialog.destroy()
    return path


class Explorer(Gtk.Box):
    """The tree, plus what you can do to the things in it."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self.root = None
        self._tint_cache = None

        self.store = Gtk.TreeStore(str, str, str)      # name, full path, kind
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_headers_visible(False)
        self.view.set_enable_search(True)
        self.view.set_search_column(0)
        self.view.set_activate_on_single_click(True)

        column = Gtk.TreeViewColumn()
        cell_icon = Gtk.CellRendererPixbuf()
        column.pack_start(cell_icon, False)
        column.set_cell_data_func(cell_icon, self._icon_for)
        cell_text = Gtk.CellRendererText()
        cell_text.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        cell_text.set_property("ypad", 1)          # GTK's default row is roomier
        cell_icon.set_property("xpad", 2)          #   than a file list needs
        column.pack_start(cell_text, True)
        column.add_attribute(cell_text, "text", 0)
        self.view.append_column(column)
        self.view.connect("row-activated", self._activated)
        self.view.connect("row-expanded", self._expanded)
        self.view.connect("button-press-event", self._clicked)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroll.add(self.view)

        self.stack = Gtk.Stack()
        self.stack.add_named(self._build_empty(), "empty")
        self.stack.add_named(self.scroll, "tree")
        self.pack_start(self.stack, True, True, 0)
        self.stack.set_visible_child_name("empty")

    # -- nothing open yet ------------------------------------------------------
    def _build_empty(self):
        outer = Gtk.ScrolledWindow()
        outer.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(14)

        note = Gtk.Label(label="No folder open.")
        note.set_xalign(0.0)
        note.get_style_context().add_class("sideempty")
        box.pack_start(note, False, False, 0)

        why = Gtk.Label(label="Nothing on this machine is listed until you choose it.")
        why.set_xalign(0.0)
        why.set_line_wrap(True)
        why.get_style_context().add_class("hint")
        box.pack_start(why, False, False, 0)

        for label, action in (("Open folder…", self.pick_folder),
                              ("Open file…", self.pick_file),
                              ("Clone a repository…", self.window.show_clone)):
            button = Gtk.Button(label=label)
            button.get_style_context().add_class("sidebtn")
            button.connect("clicked", lambda _b, fn=action: fn())
            box.pack_start(button, False, False, 0)

        self.recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.pack_start(self.recent_box, False, False, 6)
        self._fill_recent()
        outer.add(box)
        return outer

    def _fill_recent(self):
        for child in self.recent_box.get_children():
            self.recent_box.remove(child)
        folders = workspace.recent_folders()
        if not folders:
            return
        title = Gtk.Label(label="RECENT")
        title.set_xalign(0.0)
        title.get_style_context().add_class("sidetitle")
        self.recent_box.pack_start(title, False, False, 4)
        for folder in folders[:8]:
            button = Gtk.Button(label=workspace.name_for(folder))
            button.set_tooltip_text(folder)
            button.get_style_context().add_class("recentlink")
            button.set_halign(Gtk.Align.START)
            button.connect("clicked", lambda _b, f=folder: self.window.open_folder(f))
            self.recent_box.pack_start(button, False, False, 0)
        self.recent_box.show_all()

    def _tints(self):
        """The colour per family, mixed out of the active skin, once."""
        if self._tint_cache is not None:
            return self._tint_cache
        t = self.window.theme
        panel = t["PANEL"]

        def calm(colour):
            # A column of these runs the height of the window, so every tint is
            # pulled a third of the way back towards the panel. Enough to tell
            # the kinds apart at a glance, not enough to shout over the names.
            return core.mix(panel, colour, 0.66)

        self._tint_cache = {
            "ACCENT": calm(t["ACCENT"]),
            "ACCENT2": calm(t["ACCENT2"]),
            "OK": calm(t["OK"]),
            "MARKUP": calm(core.mix(t["ACCENT2"], t["ACCENT"], 0.5)),
            "MEDIA": calm(core.mix(t["ACCENT"], t["URGENT"], 0.5)),
            "QUIET": core.mix(panel, t["FG"], 0.55),
            "PLAIN": core.mix(panel, t["FG"], 0.40),
            "FOLDER": core.mix(panel, t["FG"], 0.62),
        }
        return self._tint_cache

    def _icon_for(self, _column, cell, model, it, _data):
        """Runs for every visible row on every draw, so it only does lookups.

        The kind was worked out once when the row was made and the tints are
        worked out once per skin: what is left here is two dictionary hits and
        a cached pixbuf.
        """
        kind = model[it][2] or "plain"
        tints = self._tints()
        if kind == "folder":
            icon, colour = FOLDER_ICON, tints["FOLDER"]
        elif kind == "exec":
            icon, colour = "application-x-executable-symbolic", tints["OK"]
        else:
            icon = KIND_ICONS.get(kind, FILE_ICON)
            colour = tints.get(KINDS.get(kind, (None,))[0], tints["PLAIN"])
        pixbuf = symbolic_icon(icon, colour)
        if pixbuf is not None:
            cell.set_property("pixbuf", pixbuf)
        else:
            cell.set_property("icon-name", icon)

    def restyle(self):
        """New skin, new tints — the cached pixbufs are keyed by colour."""
        self._tint_cache = None
        self.view.queue_draw()

    # -- filling it ------------------------------------------------------------
    def set_root(self, path):
        self.root = path
        self.reload()

    def reload(self):
        self.store.clear()
        if not self.root or not os.path.isdir(self.root):
            self._fill_recent()
            self.stack.set_visible_child_name("empty")
            return
        self.stack.set_visible_child_name("tree")
        self.fill(None, self.root)

    def fill(self, parent, path):
        try:
            entries = sorted(os.listdir(path), key=lambda n: (not os.path.isdir(
                os.path.join(path, n)), n.lower()))
        except OSError:
            return
        for name in entries:
            if not workspace.interesting(name):
                continue
            full = os.path.join(path, name)
            if os.path.isdir(full):
                node = self.store.append(parent, [name, full, "folder"])
                self.store.append(node, ["", "", ""])     # a stub so it expands
            else:
                kind = file_kind(name)
                if kind == "plain" and os.access(full, os.X_OK):
                    kind = "exec"       # asked once here, never again on draw
                self.store.append(parent, [name, full, kind])

    def _expanded(self, _view, it, _path):
        child = self.store.iter_children(it)
        if child and self.store[child][1] == "":
            self.store.remove(child)
            self.fill(it, self.store[it][1])

    def _activated(self, view, path, _column):
        it = self.store.get_iter(path)
        full = self.store[it][1]
        if not full:
            return
        if os.path.isdir(full):
            if view.row_expanded(path):
                view.collapse_row(path)
            else:
                view.expand_row(path, False)
        else:
            self.window.open_file(full)

    # -- the right-click menu --------------------------------------------------
    def _clicked(self, view, event):
        if event.button != 3:
            return False
        got = view.get_path_at_pos(int(event.x), int(event.y))
        if got:
            view.set_cursor(got[0])
        self._menu(event, self.store[self.store.get_iter(got[0])][1] if got else None)
        return True

    def _menu(self, event, path):
        menu = Gtk.Menu()
        folder = path if (path and os.path.isdir(path)) else (
            os.path.dirname(path) if path else self.root)

        def add(label, fn, enabled=True):
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(enabled)
            item.connect("activate", lambda *_: fn())
            menu.append(item)

        if path and os.path.isfile(path):
            add("Open", lambda: self.window.open_file(path))
            add("Open to the side", lambda: self.window.open_file(path, split=True))
            menu.append(Gtk.SeparatorMenuItem())
        add("New file…", lambda: self.new_file(folder))
        add("New folder…", lambda: self.new_folder(folder))
        menu.append(Gtk.SeparatorMenuItem())
        add("Rename…", lambda: self.rename(path), bool(path))
        add("Duplicate", lambda: self.duplicate(path), bool(path))
        add("Delete…", lambda: self.delete(path), bool(path))
        menu.append(Gtk.SeparatorMenuItem())
        add("Copy path", lambda: self.copy_path(path), bool(path))
        add("Terminal here", lambda: self.window.terminal_in(folder), bool(folder))
        add("Search in this folder", lambda: self.window.search_in(folder), bool(folder))
        menu.show_all()
        menu.popup_at_pointer(event)

    # -- operations ------------------------------------------------------------
    def new_file(self, folder=None):
        folder = folder or self.root
        if not folder:
            return
        name = ask_text(self.window, "New file", "Name for the new file in %s"
                        % workspace.name_for(folder))
        if not name:
            return
        full = os.path.join(folder, name)
        if os.path.exists(full):
            self.window.say("%s already exists" % name, bad=True)
            return
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, "a").close()
        except OSError as exc:
            self.window.say(str(exc), bad=True)
            return
        self.reload()
        self.window.open_file(full)

    def new_folder(self, folder=None):
        folder = folder or self.root
        if not folder:
            return
        name = ask_text(self.window, "New folder", "Name for the new folder in %s"
                        % workspace.name_for(folder))
        if not name:
            return
        try:
            os.makedirs(os.path.join(folder, name))
        except OSError as exc:
            self.window.say(str(exc), bad=True)
            return
        self.reload()

    def rename(self, path):
        if not path:
            return
        name = ask_text(self.window, "Rename", "New name", os.path.basename(path))
        if not name or name == os.path.basename(path):
            return
        target = os.path.join(os.path.dirname(path), name)
        if os.path.exists(target):
            self.window.say("%s already exists" % name, bad=True)
            return
        try:
            os.rename(path, target)
        except OSError as exc:
            self.window.say(str(exc), bad=True)
            return
        self.window.renamed(path, target)
        self.reload()

    def duplicate(self, path):
        if not path:
            return
        base, ext = os.path.splitext(path)
        target = "%s copy%s" % (base, ext)
        n = 2
        while os.path.exists(target):
            target = "%s copy %d%s" % (base, n, ext)
            n += 1
        try:
            if os.path.isdir(path):
                shutil.copytree(path, target)
            else:
                shutil.copy2(path, target)
        except OSError as exc:
            self.window.say(str(exc), bad=True)
            return
        self.reload()
        self.window.say("copied to %s" % os.path.basename(target))

    def delete(self, path):
        if not path:
            return
        what = "folder and everything in it" if os.path.isdir(path) else "file"
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text="Delete this %s?" % what)
        dialog.format_secondary_text(path)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Delete", Gtk.ResponseType.OK)
        answer = dialog.run()
        dialog.destroy()
        if answer != Gtk.ResponseType.OK:
            return
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as exc:
            self.window.say(str(exc), bad=True)
            return
        self.window.deleted(path)
        self.reload()

    def copy_path(self, path):
        if not path:
            return
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(path, -1)
        self.window.say("copied %s" % path)

    # -- keeping up with the outside world ------------------------------------
    def reveal(self, path):
        """Make sure a newly saved file shows up without a full reload."""
        if not self.root or not path:
            return
        if not path.startswith(self.root):
            return
        if not self._find(path):
            self.reload()

    def _find(self, path, parent=None):
        it = self.store.iter_children(parent)
        while it:
            if self.store[it][1] == path:
                return it
            found = self._find(path, it)
            if found:
                return found
            it = self.store.iter_next(it)
        return None

    def pick_folder(self):
        path = choose_folder(self.window, self.root or os.path.expanduser("~"))
        if path:
            self.window.open_folder(path)

    def pick_file(self):
        path = choose_file(self.window, self.root or os.path.expanduser("~"))
        if path:
            self.window.open_file(path)
