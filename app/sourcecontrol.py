"""sourcecontrol — the git panel: what changed, stage it, commit it, look back.

Laid out the way every editor lays this out, because the arrangement is not the
interesting part: a message box at the top, the changes grouped by whether they
are staged, and the history underneath. Clicking a file opens its diff in the
editor area as a read-only tab, so diffs get the same syntax colours and the
same find bar as anything else.

Nothing here destroys work without asking. Discard is the only irreversible
action and it always confirms, naming the files.
"""
import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

import gitrepo  # noqa: E402
from explorer import ask_text, icon_button  # noqa: E402

LETTER_CLASS = {"M": "gitmod", "A": "gitadd", "D": "gitdel", "R": "gitmod",
                "?": "gitnew", "U": "gitconflict", "C": "gitmod", "T": "gitmod"}


class SourceControl(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.window = window
        self.repo = gitrepo.Repo(None)
        self.busy = False
        self.set_border_width(10)

        # ---- branch and the network -----------------------------------------
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.branch_btn = Gtk.Button(label="—")
        self.branch_btn.get_style_context().add_class("gitbranch")
        self.branch_btn.set_tooltip_text("Switch branch")
        self.branch_btn.connect("clicked", lambda *_: self.branch_menu())
        top.pack_start(self.branch_btn, True, True, 0)

        self.sync_btn = Gtk.Button(label="")
        self.sync_btn.get_style_context().add_class("gitsync")
        self.sync_btn.set_tooltip_text("Pull, then push")
        self.sync_btn.connect("clicked", lambda *_: self.sync())
        top.pack_end(self.sync_btn, False, False, 0)
        top.pack_end(icon_button("view-refresh-symbolic", "⟳", "Refresh",
                                 lambda *_: self.refresh()), False, False, 0)
        self.pack_start(top, False, False, 0)

        # ---- the message ----------------------------------------------------
        self.message = Gtk.TextView()
        self.message.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.message.set_accepts_tab(False)
        self.message.get_style_context().add_class("gitmessage")
        self.message.connect("key-press-event", self._message_keys)
        frame = Gtk.ScrolledWindow()
        frame.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        frame.set_size_request(-1, 68)
        frame.add(self.message)
        self.pack_start(frame, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.commit_btn = Gtk.Button(label="Commit")
        self.commit_btn.get_style_context().add_class("gitcommit")
        self.commit_btn.connect("clicked", lambda *_: self.commit())
        row.pack_start(self.commit_btn, True, True, 0)
        more = Gtk.Button(label="⋯")
        more.set_tooltip_text("More git actions")
        more.get_style_context().add_class("iconbtn")
        more.connect("clicked", lambda b: self.more_menu(b))
        row.pack_end(more, False, False, 0)
        self.pack_start(row, False, False, 0)

        # ---- the lists ------------------------------------------------------
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.body)
        self.pack_start(scroll, True, True, 0)

        self.note = Gtk.Label(label="")
        self.note.set_xalign(0.0)
        self.note.set_line_wrap(True)
        self.note.get_style_context().add_class("hint")
        self.pack_start(self.note, False, False, 0)

    # ---------------------------------------------------------------------- #
    # reading the repository
    # ---------------------------------------------------------------------- #
    def set_root(self, root):
        self.repo = gitrepo.Repo(root)
        self.refresh()

    def refresh(self):
        for child in self.body.get_children():
            self.body.remove(child)
        if not self.repo.root:
            self._empty("Open a folder to see its history.")
            return
        if not self.repo.is_repo():
            self._not_a_repo()
            return

        branch = self.repo.branch()
        ahead, behind = self.repo.ahead_behind()
        self.branch_btn.set_label("⎇  " + branch)
        upstream = self.repo.upstream()
        if not upstream:
            self.sync_btn.set_label("Publish")
            self.sync_btn.set_tooltip_text("Push this branch and set its upstream")
        else:
            bits = []
            if behind:
                bits.append("↓%d" % behind)
            if ahead:
                bits.append("↑%d" % ahead)
            self.sync_btn.set_label(" ".join(bits) if bits else "Sync")
            self.sync_btn.set_tooltip_text("Pull then push, against %s" % upstream)

        if not self.repo.remotes():
            self._offer_publish()

        changes = self.repo.status()
        staged = [c for c in changes if c.staged]
        unstaged = [c for c in changes if c.unstaged and not c.untracked]
        untracked = [c for c in changes if c.untracked]
        conflicts = [c for c in changes if c.conflicted]

        if conflicts:
            self._section("Conflicts", conflicts, kind="conflict")
        if staged:
            self._section("Staged changes", staged, kind="staged")
        if unstaged:
            self._section("Changes", unstaged, kind="unstaged")
        if untracked:
            self._section("Untracked", untracked, kind="unstaged")
        if not changes:
            self._empty("Nothing to commit — the working tree is clean.")

        self.commit_btn.set_sensitive(bool(staged) or bool(unstaged) or bool(untracked))
        self.commit_btn.set_label("Commit %d file%s" % (len(staged),
                                                        "" if len(staged) == 1 else "s")
                                  if staged else "Commit all")
        self._history()
        self.body.show_all()

    def _offer_publish(self):
        """A repository with no remote at all has nowhere to push to. The
        Publish on the sync button means "push this branch"; this means "put
        this repository somewhere"."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_bottom(8)
        label = Gtk.Label(label="No remote. Nothing here is anywhere else yet.")
        label.set_xalign(0.0)
        label.set_line_wrap(True)
        label.get_style_context().add_class("sideempty")
        box.pack_start(label, False, False, 0)
        button = Gtk.Button(label="Publish to GitHub…")
        button.get_style_context().add_class("sidebtn")
        button.connect("clicked", lambda *_: self.window.show_publish())
        box.pack_start(button, False, False, 0)
        self.body.pack_start(box, False, False, 0)

    def _empty(self, text):
        label = Gtk.Label(label=text)
        label.set_xalign(0.0)
        label.set_line_wrap(True)
        label.get_style_context().add_class("sideempty")
        self.body.pack_start(label, False, False, 0)
        self.branch_btn.set_label("—")
        self.sync_btn.set_label("")
        self.commit_btn.set_sensitive(False)
        self.body.show_all()

    def _not_a_repo(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        label = Gtk.Label(label="This folder is not a git repository.")
        label.set_xalign(0.0)
        label.set_line_wrap(True)
        label.get_style_context().add_class("sideempty")
        box.pack_start(label, False, False, 0)
        for text, handler in (
                ("Initialise a repository here", lambda *_: self._init()),
                ("Clone a repository…", lambda *_: self.window.show_clone())):
            button = Gtk.Button(label=text)
            button.get_style_context().add_class("sidebtn")
            button.connect("clicked", handler)
            box.pack_start(button, False, False, 0)
        self.body.pack_start(box, False, False, 0)
        self.branch_btn.set_label("—")
        self.sync_btn.set_label("")
        self.commit_btn.set_sensitive(False)
        self.body.show_all()

    def _init(self):
        ok, _, err = self.repo.init()
        self.window.say("initialised a repository" if ok else err, bad=not ok)
        self.refresh()

    # -- one group of files ----------------------------------------------------
    def _section(self, title, changes, kind):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        label = Gtk.Label(label="%s  %d" % (title.upper(), len(changes)))
        label.set_xalign(0.0)
        label.get_style_context().add_class("sidetitle")
        header.pack_start(label, True, True, 0)
        if kind == "staged":
            header.pack_end(icon_button("list-remove-symbolic", "−", "Unstage everything",
                                        lambda *_: self._unstage([c.path for c in changes])),
                            False, False, 0)
        elif kind == "unstaged":
            header.pack_end(icon_button("list-add-symbolic", "+", "Stage everything",
                                        lambda *_: self._stage([c.path for c in changes])),
                            False, False, 0)
        self.body.pack_start(header, False, False, 0)

        for change in changes:
            self.body.pack_start(self._row(change, kind), False, False, 0)

    def _row(self, change, kind):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.get_style_context().add_class("gitrow")

        letter = Gtk.Label(label=change.letter)
        letter.get_style_context().add_class(LETTER_CLASS.get(change.letter, "gitmod"))
        letter.set_width_chars(1)

        name = Gtk.Label(label=change.name)
        name.set_xalign(0.0)
        name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        name.get_style_context().add_class("gitname")
        folder = Gtk.Label(label=change.folder)
        folder.set_xalign(0.0)
        folder.set_ellipsize(Pango.EllipsizeMode.START)
        folder.get_style_context().add_class("gitfolder")

        text = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        text.pack_start(name, False, False, 0)
        text.pack_start(folder, True, True, 0)

        click = Gtk.EventBox()
        click.set_visible_window(False)
        click.add(text)
        click.set_tooltip_text("%s — click to see the diff" % change.word)
        click.connect("button-press-event",
                      (lambda c, k: lambda *_: self.open_diff(c, k))(change, kind))

        row.pack_start(letter, False, False, 0)
        row.pack_start(click, True, True, 0)
        if kind == "staged":
            row.pack_end(icon_button("list-remove-symbolic", "−", "Unstage",
                                     (lambda p: lambda *_: self._unstage([p]))(change.path)),
                         False, False, 0)
        elif kind == "unstaged":
            row.pack_end(icon_button("edit-undo-symbolic", "↺", "Discard changes",
                                     (lambda c: lambda *_: self._discard([c]))(change)),
                         False, False, 0)
            row.pack_end(icon_button("list-add-symbolic", "+", "Stage",
                                     (lambda p: lambda *_: self._stage([p]))(change.path)),
                         False, False, 0)
        return row

    # -- history ---------------------------------------------------------------
    def _history(self):
        commits = self.repo.log(25)
        if not commits:
            return
        label = Gtk.Label(label="HISTORY")
        label.set_xalign(0.0)
        label.get_style_context().add_class("sidetitle")
        self.body.pack_start(label, False, False, 0)
        for commit in commits:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            row.get_style_context().add_class("gitrow")
            subject = Gtk.Label(label=commit.subject)
            subject.set_xalign(0.0)
            subject.set_ellipsize(Pango.EllipsizeMode.END)
            subject.get_style_context().add_class("gitname")
            meta = Gtk.Label(label="%s · %s · %s" % (commit.short, commit.author, commit.when))
            meta.set_xalign(0.0)
            meta.set_ellipsize(Pango.EllipsizeMode.END)
            meta.get_style_context().add_class("gitfolder")
            row.pack_start(subject, False, False, 0)
            row.pack_start(meta, False, False, 0)
            click = Gtk.EventBox()
            click.set_visible_window(False)
            click.add(row)
            click.set_tooltip_text("Show this commit")
            click.connect("button-press-event",
                          (lambda c: lambda *_: self.open_commit(c))(commit))
            self.body.pack_start(click, False, False, 0)

    # ---------------------------------------------------------------------- #
    # actions
    # ---------------------------------------------------------------------- #
    def _after(self, result, what):
        ok, _, err = result
        self.window.say(err or ("could not %s" % what) if not ok else what, bad=not ok)
        self.refresh()

    def _stage(self, paths):
        self._after(self.repo.stage(paths), "staged %d" % len(paths))

    def _unstage(self, paths):
        self._after(self.repo.unstage(paths), "unstaged %d" % len(paths))

    def _discard(self, changes):
        names = ", ".join(c.name for c in changes[:4])
        more = " and %d more" % (len(changes) - 4) if len(changes) > 4 else ""
        gone = [c for c in changes if c.untracked]
        detail = ("%s%s will go back to the last commit." % (names, more))
        if gone:
            detail += ("\n%d untracked file%s will be deleted outright."
                       % (len(gone), "" if len(gone) == 1 else "s"))
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text="Discard changes?")
        dialog.format_secondary_text(detail + "\nThis cannot be undone.")
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Discard", Gtk.ResponseType.OK)
        answer = dialog.run()
        dialog.destroy()
        if answer != Gtk.ResponseType.OK:
            return
        self._after(self.repo.discard([c.path for c in changes]),
                    "discarded %d" % len(changes))

    def commit(self, amend=False):
        buffer = self.message.get_buffer()
        message = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        changes = self.repo.status()
        if not any(c.staged for c in changes):
            # VS Code's habit: with nothing staged, commit everything tracked
            ok, _, err = self.repo.stage_all()
            if not ok:
                self.window.say(err, bad=True)
                return
        ok, out, err = self.repo.commit(message, amend=amend)
        if ok:
            buffer.set_text("")
            self.window.say((out.strip().split("\n") or ["committed"])[0])
        else:
            self.window.say(err or "commit failed", bad=True)
        self.refresh()

    def _message_keys(self, _widget, event):
        from gi.repository import Gdk
        if (event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter)
                and event.state & Gdk.ModifierType.CONTROL_MASK):
            self.commit()
            return True
        return False

    # -- the network -----------------------------------------------------------
    def _remote(self, what, extra=None, label=None):
        if self.busy:
            self.window.say("already talking to the remote")
            return
        self.busy = True
        self.sync_btn.set_sensitive(False)
        self.window.say("%s…" % (label or what))

        def done(ok, text):
            self.busy = False
            self.sync_btn.set_sensitive(True)
            first = [line for line in text.split("\n") if line.strip()]
            self.window.say(first[-1] if first else text, bad=not ok)
            self.window.panel.write("git %s\n%s" % (what, text))
            self.refresh()

        self.repo.remote_op(what, done, extra)

    def sync(self):
        if not self.repo.upstream():
            branch = self.repo.branch()
            self._remote("push", ["--set-upstream", "origin", branch], "publishing")
            return
        ahead, behind = self.repo.ahead_behind()
        if behind:
            self._remote("pull", label="pulling")
        elif ahead:
            self._remote("push", label="pushing")
        else:
            self._remote("fetch", label="fetching")

    def more_menu(self, button):
        menu = Gtk.Menu()

        def add(label, fn, enabled=True):
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(enabled)
            item.connect("activate", lambda *_: fn())
            menu.append(item)

        repo = self.repo.is_repo()
        add("Fetch", lambda: self._remote("fetch", label="fetching"), repo)
        add("Pull", lambda: self._remote("pull", label="pulling"), repo)
        add("Push", lambda: self._remote("push", label="pushing"), repo)
        menu.append(Gtk.SeparatorMenuItem())
        add("Stage everything", lambda: self._after(self.repo.stage_all(), "staged all"), repo)
        add("Amend the last commit", lambda: self.commit(amend=True), repo)
        menu.append(Gtk.SeparatorMenuItem())
        add("New branch…", self._new_branch, repo)
        add("Open the full log", lambda: self.open_log(), repo)
        menu.show_all()
        menu.popup_at_widget(button, 0, 2, None)

    def branch_menu(self):
        if not self.repo.is_repo():
            return
        menu = Gtk.Menu()
        current = self.repo.branch()
        for name in self.repo.branches():
            item = Gtk.MenuItem(label=("● " if name == current else "   ") + name)
            item.connect("activate", (lambda n: lambda *_: self._checkout(n))(name))
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        item = Gtk.MenuItem(label="New branch…")
        item.connect("activate", lambda *_: self._new_branch())
        menu.append(item)
        menu.show_all()
        menu.popup_at_widget(self.branch_btn, 0, 2, None)

    def _checkout(self, name):
        self._after(self.repo.checkout(name), "switched to %s" % name)

    def _new_branch(self):
        name = ask_text(self.window, "New branch", "Name for the new branch")
        if name:
            self._after(self.repo.create_branch(name), "created %s" % name)

    # -- showing diffs ---------------------------------------------------------
    def open_diff(self, change, kind):
        text = self.repo.diff(change.path, staged=(kind == "staged"))
        title = "%s %s" % ("staged" if kind == "staged" else "changes", change.name)
        self.window.editor.open_virtual(title, text or "no differences", "diff")

    def open_commit(self, commit):
        self.window.editor.open_virtual("%s %s" % (commit.short, commit.subject[:40]),
                                        self.repo.show(commit.sha), "diff")

    def open_log(self):
        lines = ["%s  %-18s  %s   %s" % (c.short, c.author[:18], c.when, c.subject)
                 for c in self.repo.log(400)]
        self.window.editor.open_virtual("history", "\n".join(lines) or "no commits", None)
