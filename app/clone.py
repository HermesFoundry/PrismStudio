"""clone — getting a repository onto the machine, and putting one on GitHub.

Two dialogs and one shared strip. The strip says who you are signed in as and
offers to fix it; the dialogs are Clone and Publish. Everything slow happens
in the terminal panel rather than behind a spinner, because `git clone` on a
large repository is the sort of thing you want to watch, and signing in is a
device flow that prints a code you have to read.

Nothing here handles a credential. `gh` owns the token and keeps it in the
system keyring; this asks it who you are and never for what it holds.
"""
import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import core  # noqa: E402
import github  # noqa: E402
from explorer import choose_folder  # noqa: E402


# --------------------------------------------------------------------------- #
# the account strip, shared by the dialogs and the settings page
# --------------------------------------------------------------------------- #
class AccountBar(Gtk.Box):
    """Who you are on GitHub, and the one button that changes it."""

    def __init__(self, window, on_change=None):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.parent = window
        self.on_change = on_change
        self.get_style_context().add_class("ghbar")

        self.label = Gtk.Label(xalign=0)
        self.label.set_line_wrap(True)
        self.pack_start(self.label, True, True, 0)

        self.action = Gtk.Button()
        self.action.get_style_context().add_class("sidebtn")
        self.action.connect("clicked", self._act)
        self.pack_end(self.action, False, False, 0)
        self.refresh()

    def refresh(self):
        self.account = github.account()
        if not github.available():
            self.label.set_markup(
                "<b>The GitHub CLI is not installed.</b>\n"
                "<small>Cloning by URL still works. For signing in, your "
                "repository list and publishing, install <tt>gh</tt>.</small>")
            self.action.set_label("How")
        elif self.account.signed_in:
            self.label.set_markup(
                "<b>%s</b>\n<small>on %s%s</small>"
                % (GLib.markup_escape_text(self.account.user),
                   GLib.markup_escape_text(self.account.host),
                   ", git over " + self.account.protocol
                   if self.account.protocol else ""))
            self.action.set_label("Sign out")
        else:
            self.label.set_markup(
                "<b>Not signed in to GitHub.</b>\n"
                "<small>Sign in to list your repositories and publish folders. "
                "Cloning a URL you already have does not need it.</small>")
            self.action.set_label("Sign in")
        self.show_all()

    def _act(self, *_):
        if not github.available():
            Gtk.show_uri_on_window(self.parent, "https://cli.github.com/", 0)
            return
        protocol = self.parent.cfg.get("GIT_PROTOCOL", "ssh")
        if self.account.signed_in:
            self.parent.run_in_panel(github.logout_argv())
            message = "signing out in the terminal"
        else:
            self.parent.run_in_panel(github.login_argv(protocol))
            message = "sign in is running in the terminal — it prints a code"
        self.parent.say(message)
        # gh takes a browser round trip; look again shortly rather than guess
        GLib.timeout_add_seconds(6, self._recheck)
        GLib.timeout_add_seconds(20, self._recheck)

    def _recheck(self):
        self.refresh()
        if self.on_change:
            self.on_change(self.account)
        return False


# --------------------------------------------------------------------------- #
# clone
# --------------------------------------------------------------------------- #
class CloneDialog(Gtk.Dialog):
    """Paste a URL, or pick one of yours once you are signed in."""

    def __init__(self, window):
        Gtk.Dialog.__init__(self, title="Clone a repository",
                            transient_for=window, modal=False)
        self.parent = window
        self.set_default_size(600, -1)
        self.get_style_context().add_class("prefs")
        self.get_style_context().add_class("whatsnew")

        box = self.get_content_area()
        box.set_spacing(0)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_border_width(16)
        box.pack_start(outer, True, True, 0)

        self.bar = AccountBar(window, on_change=lambda _a: self.load())
        outer.pack_start(self.bar, False, False, 0)

        # -- by URL --------------------------------------------------------
        heading = Gtk.Label(label="Repository URL", xalign=0)
        heading.get_style_context().add_class("heading")
        outer.pack_start(heading, False, False, 0)

        self.url = Gtk.Entry()
        self.url.set_placeholder_text("git@github.com:owner/name.git  ·  "
                                      "https://github.com/owner/name")
        self.url.connect("activate", lambda *_: self.go())
        self.url.connect("changed", lambda *_: self._sync())
        outer.pack_start(self.url, False, False, 0)

        into_label = Gtk.Label(label="Clone into", xalign=0)
        into_label.get_style_context().add_class("heading")
        outer.pack_start(into_label, False, False, 0)

        where = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.folder = Gtk.Entry()
        self.folder.set_text(self._default_parent())
        self.folder.connect("changed", lambda *_: self._sync())
        where.pack_start(self.folder, True, True, 0)
        pick = Gtk.Button(label="Choose…")
        pick.get_style_context().add_class("sidebtn")
        pick.connect("clicked", self._pick)
        where.pack_end(pick, False, False, 0)
        outer.pack_start(where, False, False, 0)

        self.into = Gtk.Label(xalign=0)
        self.into.get_style_context().add_class("hint")
        outer.pack_start(self.into, False, False, 0)

        # -- or one of yours -----------------------------------------------
        heading = Gtk.Label(label="Your repositories", xalign=0)
        heading.get_style_context().add_class("heading")
        outer.pack_start(heading, False, False, 0)

        self.filter = Gtk.Entry()
        self.filter.set_placeholder_text("filter")
        self.filter.connect("changed", lambda *_: self._paint())
        outer.pack_start(self.filter, False, False, 0)

        scroll = self.scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(-1, 200)
        self.list = Gtk.ListBox()
        self.list.get_style_context().add_class("ghlist")
        self.list.connect("row-selected", self._chose)
        self.list.connect("row-activated", lambda *_: self.go())
        scroll.add(self.list)
        outer.pack_start(scroll, False, False, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("hint")
        outer.pack_start(self.status, False, False, 0)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.clone_button = self.add_button("Clone", Gtk.ResponseType.OK)
        self.get_action_area().get_style_context().add_class("wnactions")
        for button in self.get_action_area().get_children():
            button.get_style_context().add_class("wnbtn")
        self.clone_button.get_style_context().add_class("wnprimary")
        self.connect("response", self._respond)

        self.all = []
        self._sync()
        self.load()

    # -- helpers -----------------------------------------------------------
    def _default_parent(self):
        for candidate in (self.parent.root and os.path.dirname(self.parent.root),
                          os.path.expanduser("~/Projects"),
                          os.path.expanduser("~")):
            if candidate and os.path.isdir(candidate):
                return candidate
        return os.path.expanduser("~")

    def _pick(self, *_):
        chosen = choose_folder(self, self.folder.get_text(),
                               "Clone into which folder")
        if chosen:
            self.folder.set_text(chosen)

    def name_from_url(self, url):
        name = url.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return name.split(":")[-1]

    def destination(self):
        name = self.name_from_url(self.url.get_text().strip())
        parent = self.folder.get_text().strip() or os.path.expanduser("~")
        return os.path.join(parent, name) if name else ""

    def _sync(self):
        url = self.url.get_text().strip()
        target = self.destination()
        ready = bool(url) and bool(target)
        self.clone_button.set_sensitive(ready)
        if not url:
            self.into.set_text("")
        elif os.path.exists(target):
            self.into.set_markup(
                "<small>%s already exists — clone will refuse rather than "
                "merge into it.</small>" % GLib.markup_escape_text(target))
        else:
            self.into.set_markup("<small>into %s</small>"
                                 % GLib.markup_escape_text(target))

    # -- the list ----------------------------------------------------------
    def load(self):
        if not github.available() or not github.account().signed_in:
            self.all = []
            self._paint()
            return
        self.status.set_text("reading your repositories…")
        github.repos(on_done=self._loaded)

    def _loaded(self, items, problem):
        self.all = items
        self.status.set_text(problem or "")
        self._paint()
        return False

    def _paint(self):
        for row in self.list.get_children():
            self.list.remove(row)
        needle = self.filter.get_text().strip().lower()
        shown = [r for r in self.all
                 if not needle or needle in (r.full_name + " " + r.description).lower()]
        if not shown:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            label = Gtk.Label(xalign=0)
            label.get_style_context().add_class("sideempty")
            if not github.available():
                label.set_text("Install gh to list your repositories.")
            elif not self.all:
                label.set_text("Sign in above to list your repositories.")
            else:
                label.set_text("Nothing matches %r." % needle)
            label.set_justify(Gtk.Justification.CENTER)
            label.set_halign(Gtk.Align.CENTER)
            label.set_valign(Gtk.Align.CENTER)
            label.set_vexpand(True)
            label.set_margin_top(28)
            label.set_margin_bottom(28)
            row.add(label)
            self.list.add(row)
            self.list.show_all()
            return
        for repo in shown:
            row = Gtk.ListBoxRow()
            row.repo = repo
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            column.set_border_width(7)
            title = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
            name = Gtk.Label(label=repo.full_name, xalign=0)
            name.get_style_context().add_class("ghname")
            title.pack_start(name, False, False, 0)
            if repo.private:
                tag = Gtk.Label(label="private")
                tag.get_style_context().add_class("ghtag")
                title.pack_start(tag, False, False, 0)
            when = Gtk.Label(label=repo.updated, xalign=1)
            when.get_style_context().add_class("hint")
            title.pack_end(when, False, False, 0)
            column.pack_start(title, False, False, 0)
            if repo.description:
                blurb = Gtk.Label(label=repo.description, xalign=0)
                blurb.get_style_context().add_class("hint")
                blurb.set_ellipsize(3)
                column.pack_start(blurb, False, False, 0)
            row.add(column)
            self.list.add(row)
        self.list.show_all()
        self.status.set_text("%d repositories" % len(shown))

    def _chose(self, _list, row):
        if row is not None and getattr(row, "repo", None) is not None:
            protocol = self.parent.cfg.get("GIT_PROTOCOL", "ssh")
            self.url.set_text(row.repo.clone_url(protocol))

    # -- doing it ----------------------------------------------------------
    def _respond(self, _dialog, response):
        if response == Gtk.ResponseType.OK:
            self.go()
        else:
            self.destroy()

    def go(self):
        url = self.url.get_text().strip()
        target = self.destination()
        if not url or not target:
            return
        if os.path.exists(target):
            self.parent.say("%s already exists" % target, bad=True)
            return
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            self.parent.say("%s is not a folder" % parent, bad=True)
            return
        self.destroy()
        self.parent.clone_into(url, target)


# --------------------------------------------------------------------------- #
# publish
# --------------------------------------------------------------------------- #
class PublishDialog(Gtk.Dialog):
    """Put the open folder on GitHub and point origin at it."""

    def __init__(self, window):
        Gtk.Dialog.__init__(self, title="Publish to GitHub",
                            transient_for=window, modal=False)
        self.parent = window
        self.set_default_size(520, -1)
        self.get_style_context().add_class("prefs")
        self.get_style_context().add_class("whatsnew")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_border_width(16)
        self.get_content_area().pack_start(outer, True, True, 0)

        self.bar = AccountBar(window)
        outer.pack_start(self.bar, False, False, 0)

        folder = window.root or ""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.pack_start(Gtk.Label(label="Folder", xalign=0), False, False, 0)
        here = Gtk.Label(label=folder or "no folder open", xalign=0)
        here.get_style_context().add_class("hint")
        here.set_ellipsize(1)
        row.pack_start(here, True, True, 0)
        outer.pack_start(row, False, False, 0)

        self.name = Gtk.Entry()
        self.name.set_text(os.path.basename(folder.rstrip("/")) if folder else "")
        outer.pack_start(self._labelled("Repository name", self.name), False, False, 0)

        self.description = Gtk.Entry()
        self.description.set_placeholder_text("optional")
        outer.pack_start(self._labelled("Description", self.description),
                         False, False, 0)

        self.private = Gtk.CheckButton(label="Private")
        self.private.set_active(True)
        outer.pack_start(self.private, False, False, 0)

        note = Gtk.Label(xalign=0)
        note.set_markup(
            "<small>This creates the repository, sets <tt>origin</tt> and pushes "
            "the current branch, in the terminal panel so you can see what it "
            "does. The folder has to be a git repository with at least one "
            "commit already.</small>")
        note.set_line_wrap(True)
        note.get_style_context().add_class("hint")
        outer.pack_start(note, False, False, 0)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.ok = self.add_button("Publish", Gtk.ResponseType.OK)
        self.get_action_area().get_style_context().add_class("wnactions")
        for button in self.get_action_area().get_children():
            button.get_style_context().add_class("wnbtn")
        self.ok.get_style_context().add_class("wnprimary")
        self.connect("response", self._respond)

    def _labelled(self, text, widget):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        label = Gtk.Label(label=text, xalign=0)
        label.set_size_request(140, -1)
        row.pack_start(label, False, False, 0)
        row.pack_start(widget, True, True, 0)
        return row

    def _respond(self, _dialog, response):
        if response != Gtk.ResponseType.OK:
            self.destroy()
            return
        name = self.name.get_text().strip()
        if not name:
            self.parent.say("the repository needs a name", bad=True)
            return
        self.destroy()
        self.parent.publish_folder(name, self.private.get_active(),
                                   self.description.get_text().strip())
