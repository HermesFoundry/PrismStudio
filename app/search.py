"""search — find text across the whole workspace, not just the open file.

Uses ripgrep when it is installed because it is enormously faster on a real
tree, and falls back to walking the folder in Python when it is not, so the
feature never simply disappears. Either way the search runs off the main loop
and results stream in as they are found.
"""
import os
import re
import shutil
import subprocess
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

import workspace  # noqa: E402

MAX_HITS = 500
MAX_FILE_BYTES = 2 * 1024 * 1024


class Hit:
    def __init__(self, path, line, text):
        self.path = path
        self.line = line
        self.text = text


def _rg_available():
    return bool(shutil.which("rg"))


def run_ripgrep(root, needle, regex, case, on_hit, should_stop):
    argv = ["rg", "--line-number", "--no-heading", "--color", "never",
            "--max-count", "40", "--max-filesize", "2M"]
    if not regex:
        argv.append("--fixed-strings")
    argv.append("--case-sensitive" if case else "--ignore-case")
    for folder in sorted(workspace.IGNORE):
        argv += ["--glob", "!%s" % folder]
    argv += ["--", needle, root]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, errors="replace")
    except OSError:
        return False
    count = 0
    for raw in proc.stdout:
        if should_stop() or count >= MAX_HITS:
            proc.kill()
            break
        parts = raw.rstrip("\n").split(":", 2)
        if len(parts) < 3:
            continue
        path, number, text = parts
        try:
            number = int(number)
        except ValueError:
            continue
        on_hit(Hit(path, number, text.strip()[:300]))
        count += 1
    try:
        proc.stdout.close()
        proc.wait(timeout=1)
    except Exception:
        pass
    return True


def run_python(root, needle, regex, case, on_hit, should_stop):
    """The fallback. Slower, but it works on a machine without ripgrep."""
    try:
        pattern = re.compile(needle if regex else re.escape(needle),
                             0 if case else re.IGNORECASE)
    except re.error:
        return
    count = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if workspace.interesting(d)]
        for name in files:
            if should_stop() or count >= MAX_HITS:
                return
            if not workspace.interesting(name):
                continue
            full = os.path.join(base, name)
            try:
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
                with open(full, errors="replace") as fh:
                    for number, line in enumerate(fh, 1):
                        if pattern.search(line):
                            on_hit(Hit(full, number, line.strip()[:300]))
                            count += 1
                            if count >= MAX_HITS:
                                return
            except OSError:
                continue


class SearchPanel(Gtk.Box):
    """The search side bar: a box to type in, and the hits underneath."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.window = window
        self.folder = None
        self.hits = []
        self._generation = 0
        self.set_border_width(10)

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("Search the workspace")
        self.entry.connect("activate", lambda *_: self.start())
        self.pack_start(self.entry, False, False, 0)

        options = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.case = Gtk.ToggleButton(label="Aa")
        self.case.set_tooltip_text("Match case")
        self.case.get_style_context().add_class("findtoggle")
        self.regex = Gtk.ToggleButton(label=".*")
        self.regex.set_tooltip_text("Regular expression")
        self.regex.get_style_context().add_class("findtoggle")
        for toggle in (self.case, self.regex):
            toggle.connect("toggled", lambda *_: self.start())
            options.pack_start(toggle, False, False, 0)
        go = Gtk.Button(label="Search")
        go.get_style_context().add_class("sidebtn")
        go.connect("clicked", lambda *_: self.start())
        options.pack_end(go, False, False, 0)
        self.pack_start(options, False, False, 0)

        self.count = Gtk.Label(label="")
        self.count.set_xalign(0.0)
        self.count.get_style_context().add_class("searchcount")
        self.pack_start(self.count, False, False, 0)

        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", self._open)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.list)
        self.pack_start(scroll, True, True, 0)

    # -- driving it ------------------------------------------------------------
    def focus(self, preset=None):
        if preset:
            self.entry.set_text(preset)
        self.entry.grab_focus()
        if self.entry.get_text():
            self.entry.select_region(0, -1)

    def set_folder(self, folder):
        self.folder = folder

    def start(self):
        needle = self.entry.get_text()
        root = self.folder or self.window.root
        self._generation += 1
        mine = self._generation
        for child in self.list.get_children():
            self.list.remove(child)
        self.hits = []
        if not needle:
            self.count.set_text("")
            return
        if not root:
            self.count.set_text("open a folder first")
            return
        self.count.set_text("searching %s…" % workspace.name_for(root))

        found = []
        regex, case = self.regex.get_active(), self.case.get_active()

        def collect(hit):
            found.append(hit)

        def work():
            if not _rg_available() or not run_ripgrep(root, needle, regex, case,
                                                      collect, lambda: mine != self._generation):
                run_python(root, needle, regex, case, collect,
                           lambda: mine != self._generation)
            GLib.idle_add(lambda: self._done(mine, found, root))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, mine, found, root):
        if mine != self._generation:
            return False
        self.hits = found
        files = len({h.path for h in found})
        if not found:
            self.count.set_text("nothing found")
        else:
            self.count.set_text("%d %s in %d %s%s"
                                % (len(found), "hit" if len(found) == 1 else "hits",
                                   files, "file" if files == 1 else "files",
                                   " (showing the first %d)" % MAX_HITS
                                   if len(found) >= MAX_HITS else ""))
        for hit in found[:MAX_HITS]:
            self.list.add(self._row(hit, root))
        self.list.show_all()
        return False

    def _row(self, hit, root):
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("searchhit")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        where = Gtk.Label(label="%s:%d" % (os.path.relpath(hit.path, root), hit.line))
        where.set_xalign(0.0)
        where.set_ellipsize(Pango.EllipsizeMode.START)
        where.get_style_context().add_class("searchfile")
        text = Gtk.Label(label=hit.text)
        text.set_xalign(0.0)
        text.set_ellipsize(Pango.EllipsizeMode.END)
        text.get_style_context().add_class("searchtext")
        box.pack_start(where, False, False, 0)
        box.pack_start(text, False, False, 0)
        row.add(box)
        row.hit = hit
        return row

    def _open(self, _list, row):
        hit = getattr(row, "hit", None)
        if hit:
            self.window.open_file(hit.path, line=hit.line)
