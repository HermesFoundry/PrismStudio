"""prefs — the settings window. Everything applies straight away.

Five pages: how it looks, how the editor behaves, what the assistant does,
which extensions are loaded, and the keyboard.
"""
import os
import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import core  # noqa: E402
import extensions  # noqa: E402
import keymap  # noqa: E402


class PrefsDialog(Gtk.Dialog):
    def __init__(self, window, page=0):
        super().__init__(title="%s settings" % core.APP_NAME,
                         transient_for=window, modal=False)
        self.win = window
        self.set_default_size(620, 660)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.get_style_context().add_class("prefs")
        self.add_button("Done", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda *_: self.destroy())

        book = Gtk.Notebook()
        book.set_border_width(8)
        book.append_page(self._look_page(), Gtk.Label(label="Look"))
        book.append_page(self._editor_page(), Gtk.Label(label="Editor"))
        book.append_page(self._assistant_page(), Gtk.Label(label="Claude"))
        book.append_page(self._extensions_page(), Gtk.Label(label="Extensions"))
        book.append_page(self._keys_page(), Gtk.Label(label="Keys"))
        book.append_page(self._github_page(), Gtk.Label(label="GitHub"))
        book.append_page(self._updates_page(), Gtk.Label(label="Updates"))
        area = self.get_content_area()
        area.set_spacing(0)
        area.pack_start(book, True, True, 0)
        self.show_all()
        book.set_current_page(page)

    # -- helpers ---------------------------------------------------------------
    def _page(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        column.set_border_width(14)
        scroll.add(column)
        return scroll, column

    def _heading(self, column, text, hint=None):
        label = Gtk.Label(label=text)
        label.get_style_context().add_class("heading")
        label.set_xalign(0.0)
        column.pack_start(label, False, False, 0)
        if hint:
            note = Gtk.Label(label=hint)
            note.get_style_context().add_class("hint")
            note.set_xalign(0.0)
            note.set_line_wrap(True)
            column.pack_start(note, False, False, 0)

    def _row(self, column, label, widget):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        text = Gtk.Label(label=label)
        text.set_xalign(0.0)
        text.set_size_request(190, -1)
        row.pack_start(text, False, False, 0)
        row.pack_end(widget, False, False, 0)
        column.pack_start(row, False, False, 0)
        return row

    def _switch(self, key, default="0"):
        widget = Gtk.Switch()
        widget.set_active(self.win.cfg.get(key, default) == "1")
        widget.set_halign(Gtk.Align.END)
        widget.connect("notify::active",
                       lambda s, _p: self._set(key, "1" if s.get_active() else "0"))
        return widget

    def _set(self, key, value):
        self.win.cfg[key] = str(value)
        core.save_settings({key: str(value)})
        self._apply(key, str(value))

    def _apply(self, key, value):
        editor = self.win.editor
        if key in ("THEME", "FONT"):
            self.win.restyle()
        elif key == "SUGGEST":
            editor.suggest_mode = value
            editor._sync_assist_button()
            editor.ghost.clear()
        elif key == "SUGGEST_MODEL":
            editor.claude.model = value
        elif key == "SUGGEST_DELAY":
            editor.claude_delay = max(400, int(value))
        elif key == "AUTOSAVE":
            editor.autosave = value == "1"
        elif key == "FLUSH_FOR_CLAUDE":
            editor.flush_for_claude = value == "1"
        elif key == "CLAUDE_PLACE":
            # only move it if it is actually on screen; choosing a place is not
            # a request to summon Claude
            if self.win.claude_showing():
                self.win.place_claude(value, remember=False)
        elif key == "LINE_NUMBERS":
            editor.view.set_show_line_numbers(value == "1")
        elif key == "CURRENT_LINE":
            editor.view.set_highlight_current_line(value == "1")
        elif key == "WRAP":
            editor.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if value == "1"
                                      else Gtk.WrapMode.NONE)
        elif key == "TAB_SIZE":
            editor.view.set_tab_width(int(value))
            editor.view.set_indent_width(int(value))
        elif key == "SPACES":
            editor.view.set_insert_spaces_instead_of_tabs(value == "1")
        elif key == "UPDATE_URL":
            # a new address means the old server's answer no longer applies
            import updates as updates_module
            state = updates_module.read_state()
            state.pop("latest", None)
            state.pop("last_check", None)
            updates_module.write_state(state)
        elif key == "RIGHT_MARGIN":
            editor.view.set_show_right_margin(int(value) > 0)
            if int(value) > 0:
                editor.view.set_right_margin_position(int(value))

    # -- pages -----------------------------------------------------------------
    def _look_page(self):
        scroll, column = self._page()
        self._heading(column, "Skin",
                      "The same format Iris Terminal uses. Drop more in "
                      "~/.config/prismstudio/themes.")
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(2)
        flow.set_row_spacing(6)
        flow.set_column_spacing(6)
        self.cards = {}
        for name in core.theme_names():
            theme = core.load_theme(name)
            card = self._theme_card(name, theme)
            self.cards[name] = card
            flow.add(card)
        column.pack_start(flow, False, False, 0)

        self._heading(column, "Type")
        font = Gtk.FontButton()
        font.set_font(self.win.cfg.get("FONT", "Ubuntu Sans Mono 11"))
        font.connect("font-set", lambda b: self._set("FONT", b.get_font()))
        self._row(column, "Editor and terminal", font)

        ui_font = Gtk.Entry()
        ui_font.set_text(self.win.cfg.get("UI_FONT", ""))
        ui_font.set_placeholder_text("the desktop default")
        ui_font.connect("changed", lambda e: self._set("UI_FONT", e.get_text()))
        self._row(column, "Interface font", ui_font)
        return scroll

    def _theme_card(self, name, theme):
        button = Gtk.Button()
        button.get_style_context().add_class("sidebtn")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label(label=theme.get("NAME", name))
        title.set_xalign(0.0)
        blurb = Gtk.Label(label=theme.get("BLURB", ""))
        blurb.set_xalign(0.0)
        blurb.get_style_context().add_class("hint")
        chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        for key in ("BG", "PANEL", "FG", "ACCENT", "ACCENT2", "OK", "URGENT"):
            chip = Gtk.DrawingArea()
            chip.set_size_request(16, 12)
            chip.connect("draw", self._draw_chip, theme[key])
            chips.pack_start(chip, False, False, 0)
        box.pack_start(title, False, False, 0)
        box.pack_start(blurb, False, False, 0)
        box.pack_start(chips, False, False, 0)
        button.add(box)
        button.connect("clicked", lambda *_: self._set("THEME", name))
        if name == self.win.cfg.get("THEME"):
            button.get_style_context().add_class("suggested-action")
        return button

    @staticmethod
    def _draw_chip(widget, cr, colour):
        r, g, b = core.rgb(colour)
        cr.set_source_rgb(r / 255.0, g / 255.0, b / 255.0)
        cr.rectangle(0, 0, widget.get_allocated_width(), widget.get_allocated_height())
        cr.fill()
        return False

    def _editor_page(self):
        scroll, column = self._page()
        self._heading(column, "The text")
        size = Gtk.SpinButton.new_with_range(1, 12, 1)
        size.set_value(float(self.win.cfg.get("TAB_SIZE", "4")))
        size.connect("value-changed", lambda s: self._set("TAB_SIZE", int(s.get_value())))
        self._row(column, "Tab size", size)
        self._row(column, "Insert spaces", self._switch("SPACES", "1"))
        self._row(column, "Line numbers", self._switch("LINE_NUMBERS", "1"))
        self._row(column, "Highlight the current line", self._switch("CURRENT_LINE", "1"))
        self._row(column, "Wrap long lines", self._switch("WRAP", "0"))

        margin = Gtk.SpinButton.new_with_range(0, 200, 1)
        margin.set_value(float(self.win.cfg.get("RIGHT_MARGIN", "0")))
        margin.set_tooltip_text("0 for no guide")
        margin.connect("value-changed",
                       lambda s: self._set("RIGHT_MARGIN", int(s.get_value())))
        self._row(column, "Margin guide at column", margin)

        self._heading(column, "Files")
        self._row(column, "Save constantly while typing", self._switch("AUTOSAVE", "0"))
        self._row(column, "Trim trailing space on save", self._switch("TRIM_ON_SAVE", "0"))
        self._row(column, "Remember files within a folder",
                  self._switch("RESTORE_SESSION", "1"))
        self._row(column, "Reopen last folder on start",
                  self._switch("REOPEN_LAST", "0"))
        note = Gtk.Label()
        note.set_markup("<small>Off, PrismStudio starts empty and lists nothing "
                        "on your machine until you open something. On, a bare "
                        "<tt>prism</tt> reopens the folder you had last.</small>")
        note.set_line_wrap(True)
        note.set_xalign(0.0)
        note.get_style_context().add_class("hint")
        column.pack_start(note, False, False, 0)
        self._row(column, "Ask before closing unsaved work",
                  self._switch("CONFIRM_CLOSE", "1"))
        return scroll

    def _assistant_page(self):
        scroll, column = self._page()
        self._heading(column, "Inline suggestions",
                      "Ghost text at the cursor. Tab takes it, Escape drops it.")
        modes = Gtk.ComboBoxText()
        for value, label in (("off", "Off"),
                             ("local", "From this file — instant"),
                             ("claude", "Ask Claude too — a few seconds")):
            modes.append(value, label)
        modes.set_active_id(self.win.cfg.get("SUGGEST", "local"))
        modes.connect("changed", lambda c: self._set("SUGGEST", c.get_active_id()))
        self._row(column, "Suggestions", modes)

        model = Gtk.ComboBoxText()
        for value, label in (("haiku", "Haiku — quickest"), ("sonnet", "Sonnet"),
                             ("opus", "Opus — slowest, most careful")):
            model.append(value, label)
        model.set_active_id(self.win.cfg.get("SUGGEST_MODEL", "haiku"))
        model.connect("changed", lambda c: self._set("SUGGEST_MODEL", c.get_active_id()))
        self._row(column, "Claude model", model)

        delay = Gtk.SpinButton.new_with_range(400, 5000, 100)
        delay.set_value(float(self.win.cfg.get("SUGGEST_DELAY", "1200")))
        delay.connect("value-changed",
                      lambda s: self._set("SUGGEST_DELAY", int(s.get_value())))
        self._row(column, "Ask Claude after (ms)", delay)

        note = Gtk.Label()
        note.set_markup("<small>Asking Claude takes several seconds per answer, so it "
                        "runs after you pause rather than on every keystroke. The file "
                        "tier is instant and always runs.</small>")
        note.set_line_wrap(True)
        note.set_xalign(0.0)
        note.get_style_context().add_class("hint")
        column.pack_start(note, False, False, 0)

        self._heading(column, "Where Claude opens",
                      "Claude is summoned, never resident: nothing is on "
                      "screen and no session runs until you press "
                      "Ctrl+Shift+C. This is where it appears when you do, "
                      "and moving it keeps the session running.")
        import assistant as assistant_mod
        place = Gtk.ComboBoxText()
        for ident, label in assistant_mod.PLACES:
            place.append(ident, label)
        place.set_active_id(self.win.cfg.get("CLAUDE_PLACE", "panel"))
        place.connect("changed",
                      lambda c: c.get_active_id() and self._set("CLAUDE_PLACE",
                                                                c.get_active_id()))
        self._row(column, "Opens", place)

        self._heading(column, "The Claude session")
        command = Gtk.Entry()
        command.set_text(self.win.cfg.get("CLAUDE_CMD", "claude"))
        command.set_tooltip_text('for example "claude --resume"')
        command.connect("changed", lambda e: self._set("CLAUDE_CMD", e.get_text()))
        self._row(column, "Command", command)
        self._row(column, "Save before Claude reads a file",
                  self._switch("FLUSH_FOR_CLAUDE", "1"))
        return scroll

    # -- github ----------------------------------------------------------------
    def _github_page(self):
        scroll, column = self._page()
        self._heading(column, "GitHub",
                      "Signing in, cloning and publishing go through the "
                      "GitHub CLI (gh), which keeps your token in the system "
                      "keyring. PrismStudio never reads it.")

        import clone as clone_mod
        self.account_bar = clone_mod.AccountBar(self.win,
                                                on_change=lambda _a: self._keys())
        column.pack_start(self.account_bar, False, False, 0)

        protocol = Gtk.ComboBoxText()
        for value, label in (("ssh", "SSH — git@github.com:owner/name.git"),
                             ("https", "HTTPS — https://github.com/owner/name")):
            protocol.append(value, label)
        protocol.set_active_id(self.win.cfg.get("GIT_PROTOCOL", "ssh"))
        protocol.connect("changed",
                         lambda c: self._set("GIT_PROTOCOL", c.get_active_id()))
        self._row(column, "Clone over", protocol)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, handler in (("Clone a repository…", self._do_clone),
                               ("Publish this folder…", self._do_publish)):
            button = Gtk.Button(label=label)
            button.connect("clicked", handler)
            buttons.pack_start(button, False, False, 0)
        column.pack_start(buttons, False, False, 2)

        self._heading(column, "Copilot",
                      "GitHub Copilot as a suggestion source. It needs its "
                      "language server installed and a Copilot subscription — "
                      "being signed in to gh is not the same thing.")
        self.copilot_status = Gtk.Label(xalign=0)
        self.copilot_status.set_line_wrap(True)
        self.copilot_status.get_style_context().add_class("hint")
        column.pack_start(self.copilot_status, False, False, 0)

        command = Gtk.Entry()
        command.set_text(self.win.cfg.get("COPILOT_CMD", "copilot-language-server"))
        command.connect("changed", lambda e: self._set("COPILOT_CMD", e.get_text()))
        self._row(column, "Language server", command)

        copilot_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, handler in (("Sign in to Copilot", self._copilot_in),
                               ("Sign out", self._copilot_out),
                               ("Check", lambda *_: self._copilot_state())):
            button = Gtk.Button(label=label)
            button.connect("clicked", handler)
            copilot_buttons.pack_start(button, False, False, 0)
        column.pack_start(copilot_buttons, False, False, 2)
        self._copilot_state()

        self._heading(column, "SSH keys",
                      "Cloning over SSH needs a key GitHub knows about. "
                      "Test the connection to find out whether it does.")
        self.key_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        column.pack_start(self.key_box, False, False, 0)

        key_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, handler in (("Test the connection", self._test_ssh),
                               ("Upload a key…", self._upload_key),
                               ("Make a new key…", self._make_key)):
            button = Gtk.Button(label=label)
            button.connect("clicked", handler)
            key_buttons.pack_start(button, False, False, 0)
        column.pack_start(key_buttons, False, False, 2)

        self.key_status = Gtk.Label(xalign=0)
        self.key_status.set_line_wrap(True)
        self.key_status.get_style_context().add_class("hint")
        column.pack_start(self.key_status, False, False, 0)
        self._keys()
        return scroll

    def _copilot_state(self):
        client = getattr(self.win, "copilot", None)
        if client is None:
            self.copilot_status.set_text("not available in this window")
            return
        if not client.available():
            self.copilot_status.set_markup(
                "Not installed. <tt>npm install -g "
                "@github/copilot-language-server</tt>")
            return
        kind, message = client.status()
        words = {"off": "installed, not started yet",
                 "starting": "starting…",
                 "ready": "signed in and answering",
                 "signed-out": "installed, but not signed in",
                 "no-subscription": "signed in, but this account has no Copilot",
                 "inactive": "not offering suggestions for this file",
                 "warning": "having trouble",
                 "missing": "not installed",
                 "error": "not working"}
        self.copilot_status.set_text(
            words.get(kind, kind) + (" — " + message if message else ""))

    def _copilot_in(self, *_):
        self.win.copilot_sign_in()
        GLib.timeout_add_seconds(3, lambda: (self._copilot_state(), False)[1])

    def _copilot_out(self, *_):
        self.win.copilot_sign_out()
        GLib.timeout_add_seconds(2, lambda: (self._copilot_state(), False)[1])

    def _keys(self):
        import github
        for child in self.key_box.get_children():
            self.key_box.remove(child)
        local = github.local_ssh_keys()
        remote = github.ssh_keys() if github.account().signed_in else []
        if remote:
            titles = ", ".join(title for title, _ in remote[:6])
            text = "On your account: %s" % titles
        elif github.account().signed_in:
            text = "No keys on your account yet."
        else:
            text = "Sign in to see the keys on your account."
        label = Gtk.Label(label=text, xalign=0)
        label.set_line_wrap(True)
        label.get_style_context().add_class("hint")
        self.key_box.pack_start(label, False, False, 0)
        if local:
            names = ", ".join(name for _, name, _ in local)
            here = Gtk.Label(label="On this machine: " + names, xalign=0)
            here.set_line_wrap(True)
            here.get_style_context().add_class("ghkey")
            self.key_box.pack_start(here, False, False, 0)
        self.key_box.show_all()

    def _do_clone(self, *_):
        self.win.show_clone()

    def _do_publish(self, *_):
        self.win.show_publish()

    def _test_ssh(self, *_):
        import github
        self.key_status.set_text("asking github.com…")

        def work():
            ok, message = github.test_ssh()
            GLib.idle_add(self.key_status.set_text,
                          ("✓ " if ok else "✗ ") + message)

        threading.Thread(target=work, daemon=True).start()

    def _upload_key(self, *_):
        import github
        local = github.local_ssh_keys()
        if not local:
            self.key_status.set_text("no public keys in ~/.ssh to upload")
            return
        dialog = Gtk.Dialog(title="Upload a public key", transient_for=self,
                            modal=True)
        dialog.get_style_context().add_class("prefs")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Upload", Gtk.ResponseType.OK)
        picker = Gtk.ComboBoxText()
        for full, name, comment in local:
            picker.append(full, "%s   %s" % (name, comment))
        picker.set_active(0)
        area = dialog.get_content_area()
        area.set_border_width(14)
        area.set_spacing(8)
        note = Gtk.Label(xalign=0)
        note.set_markup("<small>Only the <tt>.pub</tt> half is sent. The "
                        "private key never leaves this machine.</small>")
        note.set_line_wrap(True)
        area.pack_start(picker, False, False, 0)
        area.pack_start(note, False, False, 0)
        dialog.show_all()
        answer = dialog.run()
        chosen = picker.get_active_id()
        dialog.destroy()
        if answer == Gtk.ResponseType.OK and chosen:
            title = "%s (%s)" % (core.APP_NAME, os.uname().nodename)
            self.win.run_in_panel(github.add_key_argv(chosen, title))
            GLib.timeout_add_seconds(6, lambda: (self._keys(), False)[1])

    def _make_key(self, *_):
        import github
        target = os.path.expanduser("~/.ssh/github_prismstudio")
        if os.path.exists(target):
            self.key_status.set_text("%s already exists — upload it instead"
                                     % target)
            return
        comment = "%s@%s" % (os.environ.get("USER", "user"), os.uname().nodename)
        self.win.run_in_panel("mkdir -p ~/.ssh && chmod 700 ~/.ssh && " +
                              github.generate_key_argv(target, comment))
        self.key_status.set_text("making %s in the terminal, then upload it"
                                 % target)
        GLib.timeout_add_seconds(6, lambda: (self._keys(), False)[1])

    # -- updates ---------------------------------------------------------------
    def _updates_page(self):
        scroll, column = self._page()
        self._heading(column, "Updates",
                      "PrismStudio asks one address whether there is a newer "
                      "version and shows you what changed. It never installs "
                      "anything on its own.")

        version = Gtk.Label(label="PrismStudio %s" % core.VERSION)
        version.set_xalign(0.0)
        self._row(column, "You are running", version)
        self._row(column, "Check when the app starts", self._switch("UPDATE_CHECK", "1"))

        hours = Gtk.SpinButton.new_with_range(1, 336, 1)
        hours.set_value(float(self.win.cfg.get("UPDATE_INTERVAL", "20") or 20))
        hours.connect("value-changed",
                      lambda s: self._set("UPDATE_INTERVAL", int(s.get_value())))
        self._row(column, "Hours between checks", hours)

        address = Gtk.Entry()
        address.set_text(self.win.cfg.get("UPDATE_URL", core.DEFAULTS["UPDATE_URL"]))
        address.set_width_chars(34)
        address.connect("changed", lambda e: self._set("UPDATE_URL", e.get_text()))
        self._row(column, "Where to check", address)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        now = Gtk.Button(label="Check now")
        now.connect("clicked", lambda *_: self.win.updates.check(manual=True))
        buttons.pack_start(now, False, False, 0)
        again = Gtk.Button(label="Un-skip versions")
        again.set_tooltip_text("Show the card again for a version you skipped")
        again.connect("clicked", self._unskip)
        buttons.pack_start(again, False, False, 0)
        column.pack_start(buttons, False, False, 4)

        note = Gtk.Label()
        note.set_markup(
            "<small>The request is a plain GET carrying "
            "<tt>User-Agent: PrismStudio/%s</tt> and nothing else: no identifier, "
            "no machine details, nothing about what you have open. Turned off, it "
            "never opens a socket. The only things kept on disk are the time of "
            "the last check and the version you last skipped, in "
            "<tt>~/.cache/prismstudio/updates.json</tt>.</small>" % core.VERSION)
        note.set_line_wrap(True)
        note.set_xalign(0.0)
        note.get_style_context().add_class("hint")
        column.pack_start(note, False, False, 0)
        return scroll

    def _unskip(self, *_):
        import updates as updates_module
        state = updates_module.read_state()
        state.pop("dismissed", None)
        updates_module.write_state(state)
        self.win.updates.check(manual=True)

    # -- extensions ------------------------------------------------------------
    def _extensions_page(self):
        scroll, column = self._page()
        self._heading(column, "Extensions",
                      "Python files in ~/.config/prismstudio/extensions. They run in "
                      "this process with your permissions, so install ones you have read.")
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, handler in (("Install file…", self._install_file),
                               ("Install folder…", self._install_folder),
                               ("From git…", self._install_git),
                               ("Open folder", self._open_folder),
                               ("Reload", lambda *_: self._reload())):
            button = Gtk.Button(label=label)
            button.connect("clicked", handler)
            buttons.pack_start(button, False, False, 0)
        column.pack_start(buttons, False, False, 0)
        self.ext_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        column.pack_start(self.ext_list, False, False, 0)
        self._render_extensions()
        return scroll

    @property
    def _registry(self):
        return self.win.app.extensions

    def _render_extensions(self):
        for child in self.ext_list.get_children():
            self.ext_list.remove(child)
        found = self._registry.extensions or self._registry.found()
        if not found:
            empty = Gtk.Label(label="Nothing installed yet.")
            empty.set_xalign(0.0)
            empty.get_style_context().add_class("hint")
            self.ext_list.pack_start(empty, False, False, 0)
            self.ext_list.show_all()
            return
        off = self._registry.disabled_names()
        for ext in found:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.get_style_context().add_class("extrow")
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name = Gtk.Label(label=ext.name + ("  " + ext.version if ext.version else ""))
            name.set_xalign(0.0)
            name.get_style_context().add_class("extname")
            blurb = Gtk.Label(label=ext.error or ext.blurb)
            blurb.set_xalign(0.0)
            blurb.set_line_wrap(True)
            blurb.get_style_context().add_class("extbad" if ext.error else "extblurb")
            text.pack_start(name, False, False, 0)
            text.pack_start(blurb, False, False, 0)
            row.pack_start(text, True, True, 0)

            toggle = Gtk.Switch()
            toggle.set_active(ext.name not in off)
            toggle.set_valign(Gtk.Align.CENTER)
            toggle.connect("notify::active",
                           (lambda n: lambda s, _p: self._toggle(n, s.get_active()))(ext.name))
            row.pack_end(toggle, False, False, 0)
            remove = Gtk.Button(label="Remove")
            remove.set_valign(Gtk.Align.CENTER)
            remove.connect("clicked", (lambda n: lambda *_: self._remove(n))(ext.name))
            row.pack_end(remove, False, False, 0)
            self.ext_list.pack_start(row, False, False, 0)
        self.ext_list.show_all()

    def _toggle(self, name, on):
        off = self._registry.disabled_names()
        off.discard(name) if on else off.add(name)
        self._registry.set_disabled(off)
        self._reload()

    def _remove(self, name):
        ok, message = self._registry.remove(name)
        self.win.say(message, bad=not ok)
        if ok:
            self._reload()

    def _reload(self):
        self._registry.load_all()
        self.win.editor.local.extra = self._registry.completer_functions()
        self._render_extensions()
        self.win.say("extensions reloaded")

    def _open_folder(self, *_):
        folder = extensions.Registry.ensure_folder()
        try:
            Gtk.show_uri_on_window(self, "file://" + folder, Gdk.CURRENT_TIME)
        except Exception:
            self.win.say(folder)

    def _install_file(self, *_):
        self._install(Gtk.FileChooserAction.OPEN, "Choose an extension .py file")

    def _install_folder(self, *_):
        self._install(Gtk.FileChooserAction.SELECT_FOLDER, "Choose an extension folder")

    def _install(self, action, title):
        dialog = Gtk.FileChooserDialog(title=title, transient_for=self, modal=True,
                                       action=action)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Install", Gtk.ResponseType.OK)
        shipped = os.path.join(core.ROOT, "extensions")
        dialog.set_current_folder(shipped if os.path.isdir(shipped)
                                  else os.path.expanduser("~"))
        path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not path:
            return
        ok, message = extensions.Registry.install_path(path)
        self.win.say(message, bad=not ok)
        if ok:
            self._reload()

    def _install_git(self, *_):
        dialog = Gtk.Dialog(title="Install from git", transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Clone", Gtk.ResponseType.OK)
        entry = Gtk.Entry()
        entry.set_placeholder_text("https://github.com/someone/a-prism-extension")
        entry.set_width_chars(46)
        entry.set_activates_default(True)
        area = dialog.get_content_area()
        area.set_border_width(12)
        area.pack_start(entry, False, False, 0)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        url = entry.get_text().strip() if dialog.run() == Gtk.ResponseType.OK else ""
        dialog.destroy()
        if not url:
            return
        ok, message = extensions.Registry.install_git(url)
        self.win.say(message, bad=not ok)
        if ok:
            self._reload()

    # -- keys ------------------------------------------------------------------
    def _keys_page(self):
        scroll, column = self._page()
        self.keys_column = column
        self._render_keys()
        return scroll

    def _render_keys(self):
        for child in self.keys_column.get_children():
            self.keys_column.remove(child)
        self._heading(self.keys_column, "Shortcuts",
                      "Click a shortcut and press the keys you want. "
                      "Saved in ~/.config/prismstudio/keys.conf.")

        preset = Gtk.ComboBoxText()
        preset.append("standard", "Standard — Ctrl+S, Ctrl+P, Ctrl+F")
        preset.append("reach", "Reach — moved off the plain control keys")
        preset.set_active_id(self.win.km.preset)
        preset.connect("changed", lambda c: self._set_preset(c.get_active_id()))
        self._row(self.keys_column, "Preset", preset)

        clashes = self.win.km.conflicts()
        if clashes:
            warn = Gtk.Label(label="Bound twice: " + ", ".join(
                "%s (%s)" % (a, ", ".join(b)) for a, b in clashes.items()))
            warn.set_xalign(0.0)
            warn.set_line_wrap(True)
            warn.get_style_context().add_class("extbad")
            self.keys_column.pack_start(warn, False, False, 0)

        for group in keymap.GROUPS:
            rows = [a for a in keymap.ACTIONS if a[2] == group]
            if not rows:
                continue
            self._heading(self.keys_column, group)
            for action, label, _group, _standard, _reach in rows:
                self._key_row(action, label)

        reset = Gtk.Button(label="Reset every shortcut")
        reset.connect("clicked", lambda *_: self._reset_keys())
        self.keys_column.pack_start(reset, False, False, 8)
        self.keys_column.show_all()

    def _key_row(self, action, label):
        button = Gtk.Button(label=self.win.km.accel_for(action) or "unbound")
        button.set_size_request(190, -1)
        button.connect("clicked", lambda b: self._record(action, b))
        self._row(self.keys_column, label, button)

    def _record(self, action, button):
        button.set_label("press the keys…")
        dialog = Gtk.Window(type=Gtk.WindowType.POPUP)
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_default_size(1, 1)

        def on_key(_widget, event):
            if event.keyval in (Gdk.KEY_Escape,):
                dialog.destroy()
                button.set_label(self.win.km.accel_for(action) or "unbound")
                return True
            keyval, mask = keymap.normalise_event(event)
            if keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Shift_L,
                          Gdk.KEY_Shift_R, Gdk.KEY_Alt_L, Gdk.KEY_Alt_R):
                return True                  # still holding modifiers down
            accel = keymap.format_accel(keyval, mask)
            if not accel:
                return True
            binds = dict(self.win.km.binds)
            binds[action] = accel
            keymap.save(self.win.km.preset, binds)
            self.win.km.reload()
            dialog.destroy()
            self._render_keys()
            self.win.say("%s is now %s" % (action, accel))
            return True

        dialog.connect("key-press-event", on_key)
        dialog.show_all()
        dialog.grab_focus()

    def _set_preset(self, preset):
        keymap.save(preset, keymap.defaults(preset))
        self.win.km.reload()
        self._render_keys()

    def _reset_keys(self):
        keymap.save(self.win.km.preset, keymap.defaults(self.win.km.preset))
        self.win.km.reload()
        self._render_keys()
        self.win.say("shortcuts reset")
