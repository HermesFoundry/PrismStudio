"""editor — the middle of the code view: open files, edit them, find in them.

Several files open at once, each with its own buffer, undo history and cursor.
Find and replace, go to line, a status bar, and colours generated from the
active skin so it belongs to the rest of the window.
"""
import os

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import Gdk, Gio, GLib, GtkSource, Gtk, Pango  # noqa: E402

import assist  # noqa: E402
import core  # noqa: E402
import inline  # noqa: E402
import lsp  # noqa: E402
import sourcestyle  # noqa: E402

MAX_BYTES = 4 * 1024 * 1024
LOCAL_DELAY = 80            # ms of quiet before the offline suggestion appears
AUTOSAVE_DELAY = 1400       # ms of quiet before an open file is written back


def _rgba(colour):
    got = Gdk.RGBA()
    got.parse(colour)
    return got


def _changed_span(was, now):
    """The stretch of `now` that differs from `was`, trimming equal ends.

    Enough to point at what somebody else just did to the file without
    pulling in a whole diff library for a highlight that lasts four seconds.
    """
    head = 0
    limit = min(len(was), len(now))
    while head < limit and was[head] == now[head]:
        head += 1
    tail = 0
    while tail < limit - head and was[len(was) - 1 - tail] == now[len(now) - 1 - tail]:
        tail += 1
    return head, len(now) - tail


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


class Document:
    """One open file: its buffer, where it came from, and whether it moved."""

    counter = 0

    def __init__(self, path=None, theme=None):
        self.path = path
        if path is None:
            Document.counter += 1
            self.key = "untitled:%d" % Document.counter
            self.name = "untitled %d" % Document.counter if Document.counter > 1 else "untitled"
        else:
            self.key = path
            self.name = os.path.basename(path)
        self.buffer = GtkSource.Buffer()
        self.buffer.set_highlight_matching_brackets(True)
        self.monitor = None
        self.mtime = None
        self.search = None
        self.revision = 0           # bumped on every edit, keys the word index
        self.saving = False         # our own write, not somebody else's

    def load(self):
        with open(self.path, "r", errors="replace") as fh:
            text = fh.read()
        self.buffer.begin_not_undoable_action()
        self.buffer.set_text(text)
        self.buffer.end_not_undoable_action()
        self.buffer.set_modified(False)
        self.buffer.place_cursor(self.buffer.get_start_iter())
        self.remember_mtime()

    def remember_mtime(self):
        try:
            self.mtime = os.path.getmtime(self.path) if self.path else None
        except OSError:
            self.mtime = None

    def changed_on_disk(self):
        if not self.path or self.mtime is None:
            return False
        try:
            return os.path.getmtime(self.path) > self.mtime + 0.01
        except OSError:
            return False

    def text(self):
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, True)


class FindBar(Gtk.Revealer):
    """Find and replace inside the file, not the terminal scrollback."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.set_transition_duration(120)

        self.settings = GtkSource.SearchSettings()
        self.settings.set_wrap_around(True)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.get_style_context().add_class("editorfind")

        self.find = Gtk.Entry()
        self.find.set_placeholder_text("Find")
        self.find.set_width_chars(22)
        self.find.connect("changed", lambda *_: self._changed())
        self.find.connect("activate", lambda *_: self.step(1))
        self.find.connect("key-press-event", self._keys)

        self.replace = Gtk.Entry()
        self.replace.set_placeholder_text("Replace with")
        self.replace.set_width_chars(20)
        self.replace.connect("key-press-event", self._keys)

        self.count = Gtk.Label(label="")
        self.count.get_style_context().add_class("findstatus")

        self.case = Gtk.ToggleButton(label="Aa")
        self.case.set_tooltip_text("Match case")
        self.case.get_style_context().add_class("findtoggle")
        self.case.connect("toggled", lambda b: (self.settings.set_case_sensitive(b.get_active()),
                                                self._changed()))

        box.pack_start(self.find, False, False, 0)
        box.pack_start(icon_button("go-up-symbolic", "‹", "Previous   Shift+F3",
                                   lambda *_: self.step(-1)), False, False, 0)
        box.pack_start(icon_button("go-down-symbolic", "›", "Next   F3",
                                   lambda *_: self.step(1)), False, False, 0)
        box.pack_start(self.case, False, False, 0)
        box.pack_start(self.count, False, False, 6)
        box.pack_start(self.replace, False, False, 0)
        box.pack_start(icon_button("edit-find-replace-symbolic", "replace", "Replace this one",
                                   lambda *_: self.replace_one()), False, False, 0)
        replace_all = Gtk.Button(label="All")
        replace_all.set_tooltip_text("Replace every match")
        replace_all.get_style_context().add_class("iconbtn")
        replace_all.set_relief(Gtk.ReliefStyle.NONE)
        replace_all.connect("clicked", lambda *_: self.replace_all())
        box.pack_start(replace_all, False, False, 0)
        box.pack_end(icon_button("window-close-symbolic", "✕", "Close   Esc",
                                 lambda *_: self.close()), False, False, 0)
        self.add(box)

    def _keys(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.step(-1 if event.state & Gdk.ModifierType.SHIFT_MASK else 1)
            return True
        return False

    def context(self):
        doc = self.editor.doc()
        if doc is None:
            return None
        if doc.search is None:
            doc.search = GtkSource.SearchContext.new(doc.buffer, self.settings)
            doc.search.set_highlight(True)
        return doc.search

    def _changed(self):
        self.settings.set_search_text(self.find.get_text() or None)
        GLib.timeout_add(60, self._update_count)

    def _update_count(self):
        ctx = self.context()
        if ctx is None:
            return False
        n = ctx.get_occurrences_count()
        text = self.find.get_text()
        if not text:
            self.count.set_text("")
        elif n < 0:
            self.count.set_text("searching")
        elif n == 0:
            self.count.set_text("no matches")
        else:
            self.count.set_text("%d match%s" % (n, "" if n == 1 else "es"))
        return False

    def step(self, direction):
        ctx = self.context()
        if ctx is None or not self.find.get_text():
            return
        buf = ctx.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        if direction > 0:
            found, start, end, _wrap = ctx.forward(cursor)
        else:
            found, start, end, _wrap = ctx.backward(cursor)
        if found:
            buf.select_range(start, end)
            self.editor.view.scroll_to_iter(start, 0.2, False, 0, 0)
        self._update_count()

    def replace_one(self):
        ctx = self.context()
        if ctx is None:
            return
        buf = ctx.get_buffer()
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            try:
                ctx.replace(start, end, self.replace.get_text(), -1)
            except GLib.Error:
                pass
        self.step(1)

    def replace_all(self):
        ctx = self.context()
        if ctx is None:
            return
        try:
            n = ctx.replace_all(self.replace.get_text(), -1)
            self.editor.status_message("replaced %d" % n)
        except GLib.Error as exc:
            self.editor.status_message(str(exc))
        self._update_count()

    def open(self, with_replace=False):
        doc = self.editor.doc()
        if doc and doc.buffer.get_has_selection():
            start, end = doc.buffer.get_selection_bounds()
            chunk = doc.buffer.get_text(start, end, False)
            if chunk and "\n" not in chunk:
                self.find.set_text(chunk)
        self.replace.set_visible(True)
        self.set_reveal_child(True)
        self.show_all()
        (self.replace if with_replace else self.find).grab_focus()
        self.find.select_region(0, -1)
        self._changed()

    def close(self):
        self.set_reveal_child(False)
        ctx = self.context()
        if ctx:
            ctx.set_highlight(False)
        self.editor.view.grab_focus()


class Editor(Gtk.Box):
    def __init__(self, win, root, on_status, on_run=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.win = win
        self.root = root
        self.on_status = on_status
        self.on_run = on_run or (lambda *_: None)
        self.on_ask = None              # set by the code view: hand text to Claude
        self.on_saved = None
        self.docs = []
        self.current = None

        # ---- the strip of open files ---------------------------------------
        self.tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.tabs.get_style_context().add_class("edtabs")
        tabscroll = Gtk.ScrolledWindow()
        tabscroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        tabscroll.add(self.tabs)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        head.get_style_context().add_class("editorhead")
        head.pack_start(tabscroll, True, True, 0)
        self.save_btn = icon_button("document-save-symbolic", "save", "Save   Ctrl+S",
                                    lambda *_: self.save())
        head.pack_end(self.save_btn, False, False, 0)
        head.pack_end(icon_button("user-idle-symbolic", "ask",
                                  "Point Claude at this file   Ctrl+Shift+A",
                                  lambda *_: self.ask_claude()), False, False, 0)
        self.head = head
        head.pack_end(icon_button("document-edit-symbolic", "edit",
                                  "Have Claude change this   Ctrl+I",
                                  lambda *_: self.editbar.open()), False, False, 0)
        head.pack_end(icon_button("document-new-symbolic", "new", "New file   Ctrl+N",
                                  lambda *_: self.new_file()), False, False, 0)
        self.pack_start(head, False, False, 0)

        # ---- the view -------------------------------------------------------
        self.view = GtkSource.View()
        self.view.set_show_line_numbers(True)
        self.view.set_highlight_current_line(True)
        self.view.set_auto_indent(True)
        self.view.set_indent_width(4)
        self.view.set_tab_width(4)
        self.view.set_insert_spaces_instead_of_tabs(True)
        self.view.set_monospace(True)
        self.view.set_smart_backspace(True)
        self.view.set_show_line_marks(False)
        self.view.get_style_context().add_class("codeeditor")

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.view)

        self.findbar = FindBar(self)

        # ---- the assistant ---------------------------------------------------
        cfg = win.cfg
        self.local = assist.LocalEngine()
        registry = getattr(getattr(win, "app", None), "extensions", None)
        self.registry = registry
        if registry is not None:
            self.local.extra = registry.completer_functions()
        self.claude = assist.ClaudeEngine(
            command=(cfg.get("CLAUDE_CMD") or "claude").split()[0],
            model=cfg.get("SUGGEST_MODEL", "haiku"))
        self.ghost = inline.Ghost(self.view)
        self.editbar = inline.EditBar(self)
        self.suggest_mode = cfg.get("SUGGEST", "local")     # off | local | claude
        # Background saving is off unless asked for: a file you merely opened
        # should not be rewritten because you leaned on the keyboard. Claude
        # still never reads a stale file, because flush() runs before it looks.
        self.autosave = cfg.get("AUTOSAVE", "0") == "1"
        self.flush_for_claude = cfg.get("FLUSH_FOR_CLAUDE", "1") == "1"
        try:
            self.claude_delay = max(400, int(cfg.get("SUGGEST_DELAY", "1200")))
        except ValueError:
            self.claude_delay = 1200
        self.lsp = getattr(win, "lsp", None)
        self._lsp_timer = None
        self._local_timer = None
        self._claude_timer = None
        self._copilot_timer = None
        self._copilot_item = None       # the item Copilot last offered
        self._copilot_note = ""         # why it had nothing, when it had nothing
        self._autosave_timer = None
        self._touched = None            # range Claude last changed, for the flash

        # ---- nothing open ---------------------------------------------------
        self.welcome = self._build_welcome()

        self.stack = Gtk.Stack()
        self.stack.add_named(self.welcome, "welcome")
        self.editing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.editing.pack_start(self.editbar, False, False, 0)
        self.editing.pack_start(self.findbar, False, False, 0)
        self.editing.pack_start(scroll, True, True, 0)
        self.stack.add_named(self.editing, "editing")
        self.pack_start(self.stack, True, True, 0)

        # ---- status ---------------------------------------------------------
        # The status bar belongs to the window in this app, not to the editor.
        # These stay as plain objects so the same code can fill them in, and the
        # window borrows them for its own bar.
        self.pos_label = Gtk.Label(label="")
        self.pos_label.get_style_context().add_class("statusitem")
        self.lang_label = Gtk.Label(label="")
        self.lang_label.get_style_context().add_class("statusitem")
        self.info_label = Gtk.Label(label="")
        self.info_label.get_style_context().add_class("statusitem")
        self.hint_label = Gtk.Label(label="")
        self.hint_label.get_style_context().add_class("assisthint")
        self.diag_label = Gtk.Label(label="")
        self.diag_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.diag_label.set_max_width_chars(56)
        self.diag_label.get_style_context().add_class("statusitem")
        self.wrap_btn = Gtk.Button(label="wrap: off")
        self.wrap_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.wrap_btn.get_style_context().add_class("statusbtn")
        self.wrap_btn.connect("clicked", lambda *_: self.toggle_wrap())
        self.assist_btn = Gtk.Button(label="")
        self.assist_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.assist_btn.get_style_context().add_class("statusbtn")
        self.assist_btn.set_tooltip_text("Suggestions: off, from this file, or ask Claude")
        self.assist_btn.connect("clicked", lambda *_: self.cycle_suggest_mode())
        self._sync_assist_button()

        self.restyle(win.theme, win.cfg)
        self._show_welcome()

    # -- welcome --------------------------------------------------------------
    def _build_welcome(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label()
        title.set_markup("<span size='xx-large' weight='bold'>PrismStudio</span>")
        title.get_style_context().add_class("welcometitle")
        box.pack_start(title, False, False, 0)

        invite = Gtk.Label(label="double-click anywhere to start writing")
        invite.get_style_context().add_class("welcomeinvite")
        box.pack_start(invite, False, False, 4)

        for keys, what in (("Ctrl+K", "open a folder"), ("Ctrl+O", "open a file"),
                           ("Ctrl+N", "new file"), ("Ctrl+Shift+P", "command palette"),
                           ("Ctrl+Shift+F", "search the workspace"),
                           ("Ctrl+Shift+B", "run the app"), ("Ctrl+J", "terminal"),
                           ("Ctrl+I", "have Claude change something")):
            row = Gtk.Label()
            row.set_markup("<span font_family='monospace'>%s</span>   %s" % (keys, what))
            row.set_xalign(0.0)
            row.get_style_context().add_class("welcomerow")
            box.pack_start(row, False, False, 0)

        # A Gtk.Box has no window of its own and never sees a click, so the
        # whole welcome sits in an event box. It fills the stack rather than
        # hugging the text, so double-clicking the empty space works too —
        # which is where people actually click.
        catcher = Gtk.EventBox()
        catcher.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        catcher.set_above_child(False)
        catcher.add(box)
        catcher.connect("button-press-event", self._welcome_clicked)
        catcher.connect("realize", lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "text")))
        self.welcome_box = box
        return catcher

    def _welcome_clicked(self, _widget, event):
        """Double-click the empty state to get straight into a new file."""
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.new_file()
            return True
        return False

    def _show_welcome(self):
        self.welcome.show_all()
        self.stack.set_visible_child(self.welcome)
        self.save_btn.set_sensitive(False)

    # -- documents ------------------------------------------------------------
    def doc(self):
        return self.current

    @property
    def path(self):
        return self.current.path if self.current else None

    def open(self, path, focus=True):
        path = os.path.abspath(path)
        for doc in self.docs:
            if doc.path == path:
                self.switch(doc, focus)
                return True
        try:
            if os.path.getsize(path) > MAX_BYTES:
                self.status_message("%s is too big to open here" % os.path.basename(path))
                return False
        except OSError as exc:
            self.status_message(str(exc))
            return False
        doc = Document(path)
        try:
            doc.load()
        except (OSError, UnicodeDecodeError) as exc:
            self.status_message("cannot open: %s" % exc)
            return False
        doc.buffer.set_language(self._language_for(path))
        doc.buffer.set_style_scheme(self._scheme)
        self._watch(doc)
        self._add(doc, focus)
        if self.registry is not None:
            self.registry.fire("on_open", path)
        self.lsp_open(doc)
        return True

    @staticmethod
    def _language_for(path):
        manager = GtkSource.LanguageManager.get_default()
        lang = manager.guess_language(path, None)
        if lang is not None and lang.get_id() == "python":
            return manager.get_language("python3") or lang
        return lang

    def open_virtual(self, title, text, language=None):
        """Show generated text (a diff, a log) as a read-only tab.

        It is a Document like any other so it gets the skin's syntax colours,
        the find bar and go-to-line, but it has no path, cannot be saved, and
        is replaced rather than duplicated if you open the same view twice.
        """
        key = "view:" + title
        for doc in self.docs:
            if doc.key == key:
                doc.buffer.begin_not_undoable_action()
                doc.buffer.set_text(text)
                doc.buffer.end_not_undoable_action()
                doc.buffer.set_modified(False)
                self.switch(doc)
                return doc
        doc = Document(None)
        doc.key, doc.name, doc.virtual = key, title, True
        doc.buffer.begin_not_undoable_action()
        doc.buffer.set_text(text)
        doc.buffer.end_not_undoable_action()
        doc.buffer.set_modified(False)
        if language:
            doc.buffer.set_language(
                GtkSource.LanguageManager.get_default().get_language(language))
        doc.buffer.set_style_scheme(self._scheme)
        self._add(doc, True)
        self.view.set_editable(False)
        return doc

    def new_file(self):
        doc = Document(None)
        doc.buffer.set_style_scheme(self._scheme)
        self._add(doc, True)
        self.status_message("new file, Ctrl+S to name and save it")

    def _add(self, doc, focus):
        doc.buffer.connect("modified-changed", lambda *_: self._sync_tabs())
        doc.buffer.connect("changed", lambda *_: self._typed(doc))
        doc.buffer.connect("mark-set", lambda *a: self._cursor_moved())
        self.docs.append(doc)
        self.switch(doc, focus)

    def _watch(self, doc):
        if not doc.path:
            return
        try:
            gfile = Gio.File.new_for_path(doc.path)
            doc.monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            doc.monitor.connect("changed", self._file_changed, doc)
        except GLib.Error:
            doc.monitor = None

    def _file_changed(self, _monitor, _f, _other, event, doc):
        if event not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            return
        if not doc.changed_on_disk():
            return
        if doc.buffer.get_modified():
            self.status_message("%s changed on disk, and you have unsaved edits"
                                % os.path.basename(doc.path))
            return
        offset = doc.buffer.get_iter_at_mark(doc.buffer.get_insert()).get_offset()
        was = doc.text()
        try:
            doc.load()
        except OSError:
            return
        now = doc.text()
        it = doc.buffer.get_iter_at_offset(min(offset, doc.buffer.get_char_count()))
        doc.buffer.place_cursor(it)
        first, last = _changed_span(was, now)
        if last > first:
            self.flash(doc, first, last, seconds=4)
            self.view.scroll_to_iter(doc.buffer.get_iter_at_offset(first), 0.3, False, 0, 0)
        self.status_message("%s changed on disk and was reloaded" % os.path.basename(doc.path))

    def switch(self, doc, focus=True):
        self.view.set_editable(not getattr(doc, "virtual", False))
        self.ghost.clear()
        self._drop_timers()
        self.current = doc
        self.view.set_buffer(doc.buffer)
        self.editing.show_all()
        self.findbar.set_reveal_child(False)
        self.editbar.set_reveal_child(False)
        self.stack.set_visible_child(self.editing)
        self._sync_tabs()
        self._sync_status()
        if focus:
            self.view.grab_focus()

    def close_doc(self, doc=None):
        doc = doc or self.current
        if doc is None:
            return
        if doc.buffer.get_modified() and not self._confirm_discard(doc):
            return
        if doc.monitor:
            doc.monitor.cancel()
        self.local.forget(doc.key)
        self.lsp_close(doc)
        index = self.docs.index(doc)
        self.docs.remove(doc)
        if self.docs:
            self.switch(self.docs[min(index, len(self.docs) - 1)])
        else:
            self.current = None
            self.view.set_buffer(GtkSource.Buffer())
            self._show_welcome()
        self._sync_tabs()

    def _confirm_discard(self, doc):
        dialog = Gtk.MessageDialog(transient_for=self.win, modal=True,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text="%s has unsaved changes" % doc.name)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Discard", Gtk.ResponseType.OK,
                           "Save", Gtk.ResponseType.ACCEPT)
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.ACCEPT:
            keep = self.current
            self.current = doc
            saved = self.save()
            self.current = keep
            return saved
        return answer == Gtk.ResponseType.OK

    # -- saving ---------------------------------------------------------------
    def save(self, ask=False, quiet=False):
        doc = self.current
        if doc is None:
            return False
        if getattr(doc, "virtual", False):
            self.status_message("this is a generated view, there is nothing to save")
            return False
        path = doc.path if (doc.path and not ask) else self._ask_where(doc)
        if not path:
            return False
        try:
            with open(path, "w") as fh:
                fh.write(doc.text())
        except OSError as exc:
            self.status_message("could not save: %s" % exc)
            return False
        first = doc.path != path
        doc.path, doc.key, doc.name = path, path, os.path.basename(path)
        doc.buffer.set_modified(False)
        doc.remember_mtime()
        # an untitled file only learns what it is once it has a name
        if first or doc.buffer.get_language() is None:
            doc.buffer.set_language(self._language_for(path))
        if first:
            self._watch(doc)
        self._sync_tabs()
        self._sync_status()
        if not quiet:
            self.status_message("saved %s" % doc.name)
        if self.on_saved:
            self.on_saved(path)
        if self.registry is not None:
            self.registry.fire("on_save", path)
        if first:
            self.lsp_open(doc)
        else:
            self.lsp_saved(doc)
        return True

    def _ask_where(self, doc):
        dialog = Gtk.FileChooserDialog(title="Save as", transient_for=self.win, modal=True,
                                       action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dialog.get_style_context().add_class("prefs")
        dialog.set_current_folder(os.path.dirname(doc.path) if doc.path else self.root)
        dialog.set_current_name(doc.name if doc.path else "untitled.txt")
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_default_size(760, 520)
        path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        return path

    # -- tabs -----------------------------------------------------------------
    def _sync_tabs(self):
        for child in self.tabs.get_children():
            self.tabs.remove(child)
        for doc in self.docs:
            tab = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            tab.get_style_context().add_class("edtab")
            if doc is self.current:
                tab.get_style_context().add_class("active")
            label = Gtk.Label(label=doc.name + (" ●" if doc.buffer.get_modified() else ""))
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.set_max_width_chars(20)
            close = icon_button("window-close-symbolic", "✕", "Close   Ctrl+W",
                                (lambda d: lambda *_: self.close_doc(d))(doc), "edtabclose")
            evt = Gtk.EventBox()
            evt.set_visible_window(False)
            evt.add(label)
            evt.connect("button-press-event",
                        (lambda d: lambda _w, e: self._tab_clicked(d, e))(doc))
            tab.pack_start(evt, True, True, 0)
            tab.pack_start(close, False, False, 0)
            self.tabs.pack_start(tab, False, False, 0)
        self.tabs.show_all()
        self.save_btn.set_sensitive(bool(self.current and (self.current.buffer.get_modified()
                                                           or not self.current.path)))

    def _tab_clicked(self, doc, event):
        if event.button == 2:
            self.close_doc(doc)
        else:
            self.switch(doc)
        return True

    # -- status ---------------------------------------------------------------
    def _sync_status(self):
        doc = self.current
        if doc is None:
            return
        it = doc.buffer.get_iter_at_mark(doc.buffer.get_insert())
        line, col = it.get_line() + 1, it.get_line_offset() + 1
        selected = ""
        if doc.buffer.get_has_selection():
            start, end = doc.buffer.get_selection_bounds()
            selected = ", %d selected" % (end.get_offset() - start.get_offset())
        self.pos_label.set_text("line %d, column %d%s" % (line, col, selected))
        lang = doc.buffer.get_language()
        self.lang_label.set_text(lang.get_name() if lang else "plain text")
        self.info_label.set_text("%d lines" % doc.buffer.get_line_count())
        if self.lsp is not None and doc.path:
            errors, warnings = self.lsp.counts(doc.path)
            bits = []
            if errors:
                bits.append("%d error%s" % (errors, "" if errors == 1 else "s"))
            if warnings:
                bits.append("%d warning%s" % (warnings, "" if warnings == 1 else "s"))
            here = self.diagnostic_at_cursor()
            self.diag_label.set_text(here or ("  ".join(bits) if bits else ""))
            context = self.diag_label.get_style_context()
            context.remove_class("statusbad")
            if errors or here.startswith("error"):
                context.add_class("statusbad")
        self.notify_window()

    def status_message(self, text):
        self.on_status(text, text.startswith(("could not", "cannot")))

    def notify_window(self):
        """Nudge the window to re-read the status fields we just changed."""
        hook = getattr(self.win, "editor_status_changed", None)
        if hook:
            hook(self)

    def toggle_wrap(self):
        on = self.view.get_wrap_mode() == Gtk.WrapMode.NONE
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if on else Gtk.WrapMode.NONE)
        self.wrap_btn.set_label("wrap: on" if on else "wrap: off")

    def go_to_line(self):
        doc = self.current
        if doc is None:
            return
        popover = Gtk.Popover.new(self.pos_label)
        entry = Gtk.Entry()
        entry.set_placeholder_text("line number")
        entry.set_width_chars(10)
        entry.set_margin_top(6)
        entry.set_margin_bottom(6)
        entry.set_margin_start(6)
        entry.set_margin_end(6)

        def go(*_):
            try:
                number = max(1, int(entry.get_text().strip()))
            except ValueError:
                popover.popdown()
                return
            it = doc.buffer.get_iter_at_line(min(number - 1, doc.buffer.get_line_count() - 1))
            doc.buffer.place_cursor(it)
            self.view.scroll_to_iter(it, 0.3, False, 0, 0)
            popover.popdown()
            self.view.grab_focus()

        entry.connect("activate", go)
        popover.add(entry)
        popover.show_all()
        entry.grab_focus()

    # -- the language server ---------------------------------------------------
    def _language_id(self, doc):
        language = doc.buffer.get_language()
        ident = language.get_id() if language else None
        return ident, lsp.LSP_ID.get(ident, ident)

    def lsp_open(self, doc):
        if self.lsp is None or not doc.path:
            return
        ident, wire = self._language_id(doc)
        server = self.lsp.server_for(ident)
        if server:
            server.did_open(doc.path, wire, doc.text())

    def lsp_close(self, doc):
        if self.lsp is None or not doc.path:
            return
        server = self.lsp.server_for(self._language_id(doc)[0], start=False)
        if server:
            server.did_close(doc.path)

    def lsp_changed(self, doc):
        """Tell the server what the file says now, but not on every keystroke."""
        if self.lsp is None or not doc.path:
            return
        if self._lsp_timer:
            GLib.source_remove(self._lsp_timer)

        def send():
            self._lsp_timer = None
            server = self.lsp.server_for(self._language_id(doc)[0], start=False)
            if server:
                server.did_change(doc.path, doc.text())
            return False

        self._lsp_timer = GLib.timeout_add(420, send)

    def lsp_saved(self, doc):
        if self.lsp is None or not doc.path:
            return
        server = self.lsp.server_for(self._language_id(doc)[0], start=False)
        if server:
            server.did_save(doc.path, doc.text())

    def show_diagnostics(self, path, items):
        """Underline what the server complained about, in the right document."""
        doc = next((d for d in self.docs if d.path == path), None)
        if doc is None:
            return
        buffer = doc.buffer
        table = buffer.get_tag_table()
        for name, colour in (("lsp-error", self._diag_error),
                             ("lsp-warning", self._diag_warning)):
            tag = table.lookup(name)
            if tag is None:
                tag = buffer.create_tag(name)
                tag.set_property("underline", Pango.Underline.ERROR)
            tag.set_property("underline-rgba", colour)
            buffer.remove_tag(tag, buffer.get_start_iter(), buffer.get_end_iter())
        for item in items:
            severity = item.get("severity", 1)
            if severity > 2:
                continue
            tag = table.lookup("lsp-error" if severity == 1 else "lsp-warning")
            start = self._iter_at(buffer, item["range"]["start"])
            end = self._iter_at(buffer, item["range"]["end"])
            if end.compare(start) <= 0:
                end = start.copy()
                if not end.ends_line():
                    end.forward_char()
            buffer.apply_tag(tag, start, end)
        if doc is self.current:
            self._sync_status()

    @staticmethod
    def _iter_at(buffer, position):
        line = max(0, min(position.get("line", 0), buffer.get_line_count() - 1))
        it = buffer.get_iter_at_line(line)
        column = position.get("character", 0)
        for _ in range(column):
            if it.ends_line():
                break
            it.forward_char()
        return it

    def diagnostic_at_cursor(self):
        """The message for whatever the cursor is sitting inside, if anything."""
        doc = self.current
        if doc is None or self.lsp is None or not doc.path:
            return ""
        items = self.lsp.diagnostics.get(doc.path) or []
        it = doc.buffer.get_iter_at_mark(doc.buffer.get_insert())
        line, column = it.get_line(), it.get_line_offset()
        for item in items:
            start, end = item["range"]["start"], item["range"]["end"]
            if start["line"] <= line <= end["line"]:
                if line == start["line"] and column < start["character"]:
                    continue
                if line == end["line"] and column > end["character"]:
                    continue
                return "%s: %s" % (lsp.SEVERITY.get(item.get("severity", 1)),
                                   item.get("message", "").split("\n")[0])
        return ""

    def go_to_definition(self):
        doc = self.current
        if doc is None or self.lsp is None or not doc.path:
            return False
        server = self.lsp.server_for(self._language_id(doc)[0])
        if server is None:
            self.status_message("no language server for this file")
            return False
        it = doc.buffer.get_iter_at_mark(doc.buffer.get_insert())

        def landed(result, error):
            if error or not result:
                self.status_message("no definition found")
                return
            first = result[0] if isinstance(result, list) else result
            target = first.get("uri") or first.get("targetUri")
            span = first.get("range") or first.get("targetSelectionRange") or {}
            path = lsp.path_for(target or "")
            line = span.get("start", {}).get("line", 0) + 1
            if path and os.path.isfile(path):
                self.open(path)
                self.go_to(line)
                self.status_message("%s:%d" % (os.path.basename(path), line))
            else:
                self.status_message("definition is outside this workspace")

        server.definition(doc.path, it.get_line(), it.get_line_offset(), landed)
        self.status_message("looking…")
        return True

    def lsp_suggest(self):
        """Ask the server what could come next, and fold it into the ghost text."""
        doc = self.current
        if doc is None or self.lsp is None or not doc.path:
            return
        server = self.lsp.server_for(self._language_id(doc)[0])
        if server is None or not server.ready:
            return
        it = doc.buffer.get_iter_at_mark(doc.buffer.get_insert())
        line, column = it.get_line(), it.get_line_offset()
        at = doc.revision

        def landed(result, error):
            if error or doc.revision != at or doc is not self.current:
                return
            items = (result or {}).get("items") if isinstance(result, dict) else result
            prefix = assist.IDENT_TAIL.search(
                doc.buffer.get_text(doc.buffer.get_start_iter(), it, True))
            prefix = prefix.group(1) if prefix else ""
            best = None
            for item in (items or [])[:60]:
                label = (item.get("insertText") or item.get("label") or "").strip()
                if not label or label in ("(", ")"):
                    continue
                if prefix and not label.startswith(prefix):
                    continue
                rest = label[len(prefix):]
                if rest:
                    best = rest
                    break
            if best:
                self.ghost.add(assist.Suggestion(best, "lsp", server.name))
                self._sync_hint()

        server.completion(doc.path, line, column, landed)

    # -- copilot --------------------------------------------------------------
    def request_copilot(self, automatic=True):
        """Ask Copilot for ghost text at the cursor.

        Answers that arrive after the buffer moved on are dropped, the same as
        every other source: a suggestion for text you have already changed is
        worse than none.
        """
        self._copilot_timer = None
        doc = self.current
        client = getattr(self.win, "copilot", None)
        if doc is None or client is None or not doc.path:
            return False
        server = client.ensure()
        if server is None:
            kind, message = client.status()
            if not automatic:
                self.win.say(message or "Copilot is not available", bad=True)
            return False
        text = doc.buffer.get_text(doc.buffer.get_start_iter(),
                                   doc.buffer.get_end_iter(), True)
        language = self._language_id(doc)[0]

        def sync():
            if doc.path not in server.open_files:
                server.open_document(doc.path, language, text)
            else:
                server.change_document(doc.path, text)

        if server.ready:
            sync()
        else:
            # didOpen before initialize lands is dropped on the floor
            GLib.timeout_add(600, lambda: (sync(), False)[1])
        it = doc.buffer.get_iter_at_mark(doc.buffer.get_insert())
        line, column = it.get_line(), it.get_line_offset()
        at = doc.revision

        def landed(items, error):
            if doc.revision != at or doc is not self.current:
                return
            if error:
                if not automatic:
                    self.win.say("Copilot: " + error, bad=True)
                self._copilot_note = error
                self._sync_hint()
                return
            self._copilot_note = ""
            for item in items[:4]:
                body = (item.get("insertText") or "").rstrip()
                if not body:
                    continue
                self.ghost.add(assist.Suggestion(body, "copilot", "Copilot"))
                server.shown(item)
                self._copilot_item = item
                break
            self._sync_hint()

        server.complete(doc.path, line, column, landed,
                        tab_size=self.view.get_tab_width(),
                        spaces=self.view.get_insert_spaces_instead_of_tabs(),
                        automatic=automatic)
        return False

    def copilot_accepted(self):
        """Copilot counts acceptances; staying silent skews its own model."""
        item = getattr(self, "_copilot_item", None)
        client = getattr(self.win, "copilot", None)
        if item and client and client.server is not None:
            client.server.accepted(item)
        self._copilot_item = None

    # -- suggestions ----------------------------------------------------------
    def _typed(self, doc):
        """Something changed in the buffer: re-suggest, and maybe save."""
        doc.revision += 1
        self._sync_status()
        self._drop_timers()
        self.ghost.clear()
        if self.suggest_mode != "off":
            self._local_timer = GLib.timeout_add(LOCAL_DELAY, self._suggest_local)
        if self.suggest_mode == "claude":
            self._claude_timer = GLib.timeout_add(self.claude_delay,
                                                  lambda: self.request_claude(False))
        elif self.suggest_mode == "copilot":
            # Copilot answers in well under a second, so it can be asked much
            # sooner than Claude without turning into a request per keystroke.
            self._copilot_timer = GLib.timeout_add(
                max(200, min(self.claude_delay, 500)), self.request_copilot)
        self.lsp_changed(doc)
        if self.autosave and doc.path:
            self._autosave_timer = GLib.timeout_add(AUTOSAVE_DELAY, self._autosave)
        self._sync_hint()

    def _cursor_moved(self):
        if self.ghost.stale():
            self.ghost.clear()
            self._sync_hint()
        self._sync_status()

    def _drop_timers(self):
        for name in ("_local_timer", "_claude_timer", "_copilot_timer"):
            timer = getattr(self, name, None)
            if timer:
                GLib.source_remove(timer)
                setattr(self, name, None)

    def _context(self):
        """Everything the engines need to know about where the cursor is."""
        doc = self.current
        if doc is None:
            return None
        buf = doc.buffer
        it = buf.get_iter_at_mark(buf.get_insert())
        start, end = buf.get_bounds()
        before = buf.get_text(start, it, True)
        after = buf.get_text(it, end, True)
        lang = buf.get_language()
        return doc, before, after, (lang.get_id() if lang else None)

    def _suggest_local(self):
        self._local_timer = None
        got = self._context()
        if got is None or not self.view.has_focus():
            return False
        doc, before, after, language = got
        if before.endswith(("\n", " ", "\t")) and not before.rstrip(" \t").endswith("\n"):
            pass                        # mid-indent is fine, keep going
        counts = self.local.words(doc.key, before + after, doc.revision)
        items = self.local.suggest(before, after, counts, language)
        if items:
            self.ghost.show(items)
        self.lsp_suggest()          # arrives a moment later and jumps the queue
        self._sync_hint()
        return False

    def request_claude(self, force=True):
        """Ask the CLI to fill in at the cursor. Slow on purpose, off the loop."""
        self._claude_timer = None
        got = self._context()
        if got is None:
            return False
        doc, before, after, language = got
        if not force and not self.view.has_focus():
            return False
        if not before.strip():
            return False
        if not self.claude.available():
            if force:
                self.status_message("cannot find the claude command")
            return False
        self.hint_label.set_text("Claude is thinking…")
        prompt = assist.ClaudeEngine.fill_prompt(doc.path, language, before, after)
        at = doc.revision

        def landed(text, error):
            if doc.revision != at:
                self._sync_hint()
                return
            if error:
                self.hint_label.set_text("")
                if force:
                    self.status_message("Claude could not answer: %s" % error)
                return
            if text and text.strip():
                self.ghost.add(assist.Suggestion(text, "claude", "from Claude"))
            self._sync_hint()

        self.claude.ask(prompt, assist.FILL_SYSTEM,
                        os.path.dirname(doc.path) if doc.path else self.root, landed)
        return False

    def suggest_order(self):
        """The sources you can cycle through here, in a sensible order.

        Claude is only offered when it is switched on, and Copilot only when
        its language server is actually installed — cycling onto a source that
        cannot answer is a dead stop with no explanation.
        """
        order = ["off", "local"]
        if getattr(self.win, "assistant_enabled", True):
            order.append("claude")
        client = getattr(self.win, "copilot", None)
        if client is not None and client.available():
            order.append("copilot")
        elif self.suggest_mode == "copilot":
            order.append("copilot")          # already chosen; do not strand it
        return order

    def cycle_suggest_mode(self):
        order = self.suggest_order()
        here = order.index(self.suggest_mode) if self.suggest_mode in order else -1
        self.suggest_mode = order[(here + 1) % len(order)]
        self.ghost.clear()
        self._sync_assist_button()
        self.status_message({
            "off": "suggestions off",
            "local": "suggestions from this file only, instant",
            "claude": "Claude suggests after you pause — it takes a few seconds",
            "copilot": "Copilot suggests as you type",
        }.get(self.suggest_mode, ""))
        if self.suggest_mode == "copilot":
            self._warm_copilot()
        return self.suggest_mode

    def _warm_copilot(self):
        """Start the server now rather than on the next keystroke, and say
        plainly if it cannot be started or is not signed in."""
        client = getattr(self.win, "copilot", None)
        if client is None:
            return
        if client.ensure() is None:
            kind, message = client.status()
            self.win.say("Copilot: " + (message or kind), bad=True)

    def _sync_assist_button(self):
        self.assist_btn.set_label({"off": "assist: off",
                                   "local": "assist: file",
                                   "claude": "assist: Claude",
                                   "copilot": "assist: Copilot"}.get(self.suggest_mode,
                                                                     "assist: file"))

    def _sync_hint(self):
        item = self.ghost.item
        if item is None:
            self.hint_label.set_text("")
            return
        extra = "  ·  Alt+] for %d more" % (len(self.ghost.items) - 1) \
            if len(self.ghost.items) > 1 else ""
        self.hint_label.set_text("Tab to accept (%s)%s" % (item.detail or item.source, extra))

    # -- autosave -------------------------------------------------------------
    def _autosave(self):
        self._autosave_timer = None
        doc = self.current
        if doc and doc.path and doc.buffer.get_modified():
            self.save(quiet=True)
        return False

    def flush(self):
        """Write pending edits now, so Claude reads what you can see.

        Called just before anything is handed to Claude. This is what makes
        background autosave unnecessary: the file on disk is only guaranteed
        current at the moment somebody is about to read it.
        """
        doc = self.current
        if not doc or not doc.path:
            return False
        if self.flush_for_claude and doc.buffer.get_modified():
            return self.save(quiet=True)
        return True

    def ask_claude(self):
        """Hand the Claude pane a reference to what you are looking at."""
        doc = self.current
        if doc is None:
            self.status_message("open a file first")
            return False
        if not doc.path:
            self.status_message("save the file first so Claude can find it")
            return False
        self.flush()
        buf = doc.buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            where = (doc.path, start.get_line() + 1, end.get_line() + 1)
        else:
            it = buf.get_iter_at_mark(buf.get_insert())
            where = (doc.path, it.get_line() + 1, None)
        if self.on_ask:
            self.on_ask(*where)
            return True
        self.status_message("no Claude pane in this tab")
        return False

    # -- Claude editing the open file -----------------------------------------
    def claude_edit(self, instruction, done):
        """Rewrite the selection (or the current line) to match an instruction."""
        doc = self.current
        if doc is None:
            done(False, "nothing open")
            return
        if not self.claude.available():
            done(False, "cannot find the claude command")
            return
        buf = doc.buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
        else:
            it = buf.get_iter_at_mark(buf.get_insert())
            start = buf.get_iter_at_line(it.get_line())
            end = start.copy()
            if not end.ends_line():
                end.forward_to_line_end()
        fragment = buf.get_text(start, end, True)
        if not fragment.strip():
            done(False, "nothing selected to change")
            return
        head, tail = buf.get_bounds()
        before = buf.get_text(head, start, True)
        after = buf.get_text(end, tail, True)
        lang = buf.get_language()
        prompt = assist.ClaudeEngine.edit_prompt(
            doc.path, lang.get_id() if lang else None, instruction, fragment, before, after)
        at = doc.revision
        first, last = start.get_offset(), end.get_offset()

        def landed(text, error):
            if error:
                done(False, error)
                return
            if doc.revision != at:
                done(False, "the file changed while Claude was working")
                return
            if text is None or not text.strip():
                done(False, "Claude sent nothing back")
                return
            if text == fragment:
                done(True, "no change needed")
                return
            self._replace_range(doc, first, last, text)
            done(True, "applied — Ctrl+Z to undo")

        self.claude.ask(prompt, assist.EDIT_SYSTEM,
                        os.path.dirname(doc.path) if doc.path else self.root, landed)

    def _replace_range(self, doc, first, last, text):
        """One undoable swap, then colour it so you can see what moved."""
        buf = doc.buffer
        buf.begin_user_action()
        start = buf.get_iter_at_offset(first)
        end = buf.get_iter_at_offset(last)
        buf.delete(start, end)
        start = buf.get_iter_at_offset(first)
        buf.insert(start, text)
        buf.end_user_action()
        end = buf.get_iter_at_offset(first + len(text))
        buf.place_cursor(end)
        self.view.scroll_to_iter(buf.get_iter_at_offset(first), 0.25, False, 0, 0)
        self.flash(doc, first, first + len(text))

    def flash(self, doc, first, last, seconds=3):
        """Tint a range so an edit you did not type is impossible to miss."""
        buf = doc.buffer
        table = buf.get_tag_table()
        tag = table.lookup("prism-touched")
        if tag is None:
            tag = buf.create_tag("prism-touched")
        tag.set_property("background", self._touch_colour)
        buf.apply_tag(tag, buf.get_iter_at_offset(first), buf.get_iter_at_offset(last))

        def fade():
            try:
                buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())
            except Exception:
                pass
            return False

        GLib.timeout_add(seconds * 1000, fade)

    # -- what the window asks for ---------------------------------------------
    def show_welcome_if_empty(self):
        if not self.docs:
            self._show_welcome()

    def go_to(self, line):
        """Put the cursor on a 1-based line and scroll it into view."""
        doc = self.current
        if doc is None:
            return False
        line = max(1, min(int(line), doc.buffer.get_line_count()))
        it = doc.buffer.get_iter_at_line(line - 1)
        doc.buffer.place_cursor(it)
        self.view.scroll_to_iter(it, 0.3, False, 0, 0)
        return True

    def cycle(self, step):
        if len(self.docs) < 2:
            return False
        index = self.docs.index(self.current) if self.current in self.docs else 0
        self.switch(self.docs[(index + step) % len(self.docs)])
        return True

    def undo(self):
        doc = self.current
        if doc is not None and doc.buffer.can_undo():
            doc.buffer.undo()
            return True
        return False

    def redo(self):
        doc = self.current
        if doc is not None and doc.buffer.can_redo():
            doc.buffer.redo()
            return True
        return False

    def selected_text(self):
        """What is selected right now, for seeding a workspace search."""
        doc = self.current
        if doc is None or not doc.buffer.get_has_selection():
            return ""
        start, end = doc.buffer.get_selection_bounds()
        text = doc.buffer.get_text(start, end, True)
        return text if (chr(10) not in text and len(text) < 120) else ""

    # -- keys -----------------------------------------------------------------
    def handle_key(self, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        shift = event.state & Gdk.ModifierType.SHIFT_MASK
        alt = event.state & Gdk.ModifierType.MOD1_MASK
        key = event.keyval

        # the suggestion gets first refusal, the way Copilot does it
        if self.ghost.item is not None:
            if key == Gdk.KEY_Tab and not ctrl and not shift:
                from_copilot = (self.ghost.item is not None
                                and self.ghost.item.source == "copilot")
                if self.ghost.accept():
                    if from_copilot:
                        self.copilot_accepted()
                    self._sync_hint()
                    return True
            if key == Gdk.KEY_Escape:
                self.ghost.clear()
                self._sync_hint()
                return True
            if alt and key in (Gdk.KEY_bracketright, Gdk.KEY_bracketleft):
                self.ghost.cycle(1 if key == Gdk.KEY_bracketright else -1)
                self._sync_hint()
                return True
            if ctrl and key == Gdk.KEY_Right:
                self.ghost.accept("word")
                self._sync_hint()
                return True

        if key == Gdk.KEY_F12:
            self.go_to_definition()
            return True
        if key == Gdk.KEY_F3:
            self.findbar.step(-1 if shift else 1)
            return True
        if key == Gdk.KEY_Escape and self.findbar.get_reveal_child():
            self.findbar.close()
            return True
        if key == Gdk.KEY_Escape and self.editbar.get_reveal_child():
            self.editbar.close()
            return True
        if not ctrl:
            return False
        if key == Gdk.KEY_space:
            self.request_claude(True)
            return True
        if key in (Gdk.KEY_i, Gdk.KEY_I):
            self.editbar.open()
            return True
        if shift and key in (Gdk.KEY_a, Gdk.KEY_A):
            self.ask_claude()
            return True
        if key in (Gdk.KEY_s, Gdk.KEY_S):
            self.save(ask=bool(shift))
            return True
        if key in (Gdk.KEY_n, Gdk.KEY_N):
            self.new_file()
            return True
        if key in (Gdk.KEY_w, Gdk.KEY_W):
            self.close_doc()
            return True
        if key in (Gdk.KEY_f, Gdk.KEY_F):
            self.findbar.open()
            return True
        if key in (Gdk.KEY_h, Gdk.KEY_H):
            self.findbar.open(with_replace=True)
            return True
        if key in (Gdk.KEY_g, Gdk.KEY_G):
            self.go_to_line()
            return True
        return False

    # -- looks ----------------------------------------------------------------
    def restyle(self, theme, cfg):
        self._scheme = sourcestyle.scheme_for(theme)
        for doc in self.docs:
            doc.buffer.set_style_scheme(self._scheme)
        self.view.override_font(Pango.FontDescription.from_string(
            cfg.get("FONT", "Ubuntu Sans Mono 11")))
        self._touch_colour = core.mix(theme["BG"], theme["ACCENT"], 0.28)
        self._diag_error = _rgba(theme["URGENT"])
        self._diag_warning = _rgba(theme["ACCENT2"])
        self.ghost.restyle(theme)
