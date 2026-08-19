"""main — the PrismStudio window and application.

The layout is the one every editor has settled on, for good reasons:

    ┌──┬──────────┬───────────────────────────┬──────────┐
    │a │ side bar │ editor                    │ Claude   │
    │c │          ├───────────────────────────┤          │
    │t │          │ panel: terminals, output  │          │
    ├──┴──────────┴───────────────────────────┴──────────┤
    │ status bar                                          │
    └─────────────────────────────────────────────────────┘

The activity bar down the left switches what the side bar shows. Everything
except the editor can be hidden, and what you had open comes back next time.
"""
import os
import sys
import threading
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")
gi.require_version("GtkSource", "4")
from gi.repository import Gdk, Gio, GLib, Gtk, Vte  # noqa: E402

import core  # noqa: E402
import extensions  # noqa: E402
import keymap  # noqa: E402
import lsp  # noqa: E402
import copilot  # noqa: E402
import github  # noqa: E402
import styling  # noqa: E402
import updates  # noqa: E402
import workspace  # noqa: E402
import assistant as assistant_mod  # noqa: E402
from assistant import Assistant  # noqa: E402
from editor import Editor  # noqa: E402
from explorer import Explorer, choose_file, choose_folder, icon_button  # noqa: E402
from panel import Panel  # noqa: E402
from runbar import RunBar  # noqa: E402
from search import SearchPanel  # noqa: E402
from selection import SelectionBar  # noqa: E402
from sourcecontrol import SourceControl  # noqa: E402

ACTIVITIES = [
    ("explorer", "folder-symbolic", "E", "Explorer   Ctrl+Shift+E"),
    ("search", "system-search-symbolic", "S", "Search   Ctrl+Shift+F"),
    ("git", "media-playlist-shuffle-symbolic", "G", "Source control   Ctrl+Shift+G"),
    ("run", "media-playback-start-symbolic", "R", "Run   Ctrl+Shift+D"),
    ("extensions", "application-x-addon-symbolic", "X", "Extensions   Ctrl+Shift+X"),
]


class PrismWindow(Gtk.ApplicationWindow):
    def __init__(self, app, root=None):
        super().__init__(application=app, title=core.APP_NAME)
        self.app = app
        self.cfg = core.load_settings()
        self.theme = core.load_theme(self.cfg["THEME"])
        self.km = keymap.Keymap()
        self.root = None
        self._status_timer = None
        self._files = []                # the go-to-file list for this folder
        self._file_root = None
        self._file_at = 0.0
        self._file_walking = False
        self._file_watchers = []
        self.get_style_context().add_class("prism")

        self.set_default_size(1360, 860)
        self._wear_icon()

        # ---- title bar -------------------------------------------------------
        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.get_style_context().add_class("prismhead")
        self.set_titlebar(self.header)
        self._build_menu()
        self._build_header_buttons()

        # ---- activity bar ----------------------------------------------------
        self.activity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.activity.get_style_context().add_class("activitybar")
        self.activity_buttons = {}
        group = None
        for name, icon, fallback, tip in ACTIVITIES:
            button = Gtk.RadioButton.new_from_widget(group)
            group = group or button
            button.set_mode(False)
            button.set_tooltip_text(tip)
            button.get_style_context().add_class("activitybtn")
            if Gtk.IconTheme.get_default().has_icon(icon):
                button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR))
            else:
                button.set_label(fallback)
            button.connect("toggled",
                           (lambda n: lambda b: b.get_active() and self.show_side(n))(name))
            self.activity_buttons[name] = button
            self.activity.pack_start(button, False, False, 0)

        # ---- side bar --------------------------------------------------------
        self.explorer = Explorer(self)
        self.search = SearchPanel(self)
        self.git = SourceControl(self)
        self.run_side = self._build_run_side()
        self.extensions_side = self._build_extensions_side()

        self.side_title = Gtk.Label(label="EXPLORER")
        self.side_title.set_xalign(0.0)
        self.side_title.get_style_context().add_class("sidetitle")
        side_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        side_head.get_style_context().add_class("sidehead")
        side_head.pack_start(self.side_title, True, True, 0)
        self.side_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        side_head.pack_end(self.side_actions, False, False, 0)

        self.side_stack = Gtk.Stack()
        self.side_stack.add_named(self.explorer, "explorer")
        self.side_stack.add_named(self.search, "search")
        self.side_stack.add_named(self.git, "git")
        self.side_stack.add_named(self.run_side, "run")
        self.side_stack.add_named(self.extensions_side, "extensions")

        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.sidebar.get_style_context().add_class("sidebar")
        self.sidebar.pack_start(side_head, False, False, 0)
        self.sidebar.pack_start(self.side_stack, True, True, 0)

        # ---- editor and panel ------------------------------------------------
        self.copilot = copilot.Client(self)
        self.lsp = lsp.Client(None, on_diagnostics=self._diagnostics,
                              on_log=lambda text: self.panel.write(text)
                              if getattr(self, "panel", None) else None)
        self.lsp.enabled = self.cfg.get("LSP", "1") == "1"
        self.editor = Editor(self, None, self.say_from_editor)
        self.editor.on_saved = self.file_saved
        self.editor.on_ask = self.point_claude_at
        self.selection = (SelectionBar(self, self.editor)
                          if self.cfg.get("SELECTION_BAR", "1") == "1" else None)
        self.runbar = RunBar(self)
        self.panel = Panel(self)

        # The run controls sit at the end of the tab strip rather than in a bar
        # of their own. A folder with nothing to run then costs no height at all.
        self.editor.attach_run(self.runbar)

        self.vertical = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.vertical.pack1(self.editor, True, True)
        self.vertical.pack2(self.panel, False, True)

        # ---- Claude ----------------------------------------------------------
        # Built, but deliberately not placed: it goes on screen when you ask
        # for it, in whichever of the three places you last chose.
        self.assistant = Assistant(self)
        self.claude_window = None
        self._claude_where = None

        self.middle = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.middle.pack1(self.vertical, True, True)

        self.outer = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.outer.pack1(self.sidebar, False, True)
        self.outer.pack2(self.middle, True, True)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.pack_start(self.activity, False, False, 0)
        body.pack_start(self.outer, True, True, 0)

        # ---- status bar ------------------------------------------------------
        self.status = self._build_status()

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root_box.pack_start(body, True, True, 0)
        root_box.pack_start(self.status, False, False, 0)
        self.add(root_box)

        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", self.on_close)
        self.app.load_css(self.theme, self.cfg)

        self.show_all()
        self._apply_layout()
        self.updates = updates.Updates(self)
        self.updates.start()
        if root:
            self.open_folder(root, restore=True)
        else:
            self._sync_title()
            self.editor.show_welcome_if_empty()

    def _wear_icon(self):
        """Use the shipped icon whether or not install.sh has been run."""
        self.set_icon_name(core.APP_ID)
        shipped = os.path.join(core.ROOT, "packaging", "icons", "256.png")
        if os.path.exists(shipped):
            try:
                from gi.repository import GdkPixbuf
                sizes = [os.path.join(core.ROOT, "packaging", "icons", "%d.png" % s)
                         for s in (48, 128, 256, 512)]
                icons = [GdkPixbuf.Pixbuf.new_from_file(p)
                         for p in sizes if os.path.exists(p)]
                if icons:
                    self.set_icon_list(icons)
            except Exception:
                pass

    @property
    def assistant_enabled(self):
        """Whether any Claude feature is offered at all.

        Off means off: no pane, no menu, no palette entries, no Claude tier in
        the suggestions, and nothing on the selection bar that would need it.
        """
        return self.cfg.get("CLAUDE", "1") == "1"

    # ---------------------------------------------------------------------- #
    # chrome
    # ---------------------------------------------------------------------- #
    def _build_menu(self):
        """Every command, behind one button.

        A menu bar across the top is seven click targets you use twice a week
        and a row of chrome you look at all day. The same groups live in here,
        and the palette reaches all of them without the mouse: Ctrl+P for a
        file, Ctrl+Shift+P for a command.
        """
        bar = Gtk.Menu()
        bar.get_style_context().add_class("prismmenu")

        def menu(label, items):
            root_item = Gtk.MenuItem(label=label)
            sub = Gtk.Menu()
            for entry in items:
                if entry is None:
                    sub.append(Gtk.SeparatorMenuItem())
                    continue
                text, action = entry
                item = Gtk.MenuItem(label=text)
                item.connect("activate", lambda _i, a=action: self.do_action(a))
                sub.append(item)
            root_item.set_submenu(sub)
            bar.append(root_item)

        menu("File", [("New file", "new-file"), ("Open file…", "open-file"),
                      ("Open folder…", "open-folder"), None,
                      ("Save", "save"), ("Save as…", "save-as"), None,
                      ("Close file", "close-file"), ("Close folder", "close-folder"), None,
                      ("Preferences…", "preferences"), ("Quit", "quit")])
        menu("Edit", [("Undo", "undo"), ("Redo", "redo"), None,
                      ("Find…", "find"), ("Replace…", "replace"),
                      ("Search the workspace…", "search"), None,
                      ("Go to line…", "go-to-line"),
                      ("Go to definition", "go-to-definition")])
        menu("View", [("Explorer", "side-explorer"), ("Search", "side-search"),
                      ("Source control", "side-git"), ("Run", "side-run"),
                      ("Extensions", "side-extensions"), None,
                      ("Toggle side bar", "toggle-sidebar"),
                      ("Toggle panel", "toggle-panel"), None,
                      ("Go to file…", "quick-open"),
                      ("Command palette…", "palette"),
                      ("Keyboard shortcuts", "keymap"), None,
                      ("Bigger text", "zoom-in"), ("Smaller text", "zoom-out"),
                      ("Reset text size", "zoom-reset"), ("Full screen", "fullscreen")])
        menu("Git", [("Commit", "git-commit"), ("Sync", "git-sync"), None,
                     ("Clone a repository…", "git-clone"),
                     ("Publish to GitHub…", "git-publish"), None,
                     ("Refresh", "git-refresh")])
        menu("Run", [("Run the app", "run-app"), ("Stop", "stop-app"),
                     ("Open in the browser", "open-app"), None,
                     ("Run this file", "run-file"),
                     ("Look at the folder again", "rescan"), None,
                     ("New terminal", "new-terminal")])
        if self.assistant_enabled:
            menu("Claude", [("Open Claude", "toggle-assistant"), None,
                            ("Open it in the bottom panel", "claude-place-panel"),
                            ("Open it beside the editor", "claude-place-side"),
                            ("Open it in its own window", "claude-place-window"), None,
                            ("Suggest here", "suggest"),
                            ("Change suggestion source", "suggest-mode"), None,
                            ("Have Claude change this…", "claude-edit"),
                            ("Point Claude at this file", "ask-claude"), None,
                            ("Restart Claude", "restart-claude")])
        else:
            menu("Assist", [("Suggest here", "suggest"),
                            ("Change suggestion source", "suggest-mode")])
        menu("Help", [("Keyboard shortcuts", "keymap"), None,
                      ("Check for updates", "check-updates"),
                      ("About", "about")])
        bar.show_all()
        self.app_menu = bar

        button = Gtk.MenuButton()
        button.set_popup(bar)
        button.set_tooltip_text("Menu")
        button.get_style_context().add_class("toolbtn")
        button.get_style_context().add_class("appmenu")
        if Gtk.IconTheme.get_default().has_icon("open-menu-symbolic"):
            button.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic",
                                                          Gtk.IconSize.MENU))
        else:
            button.set_label("☰")
        self.header.pack_start(button)

    def _build_header_buttons(self):
        self.title_label = Gtk.Label(label=core.APP_NAME)
        self.title_label.get_style_context().add_class("prismtitle")
        self.subtitle_label = Gtk.Label(label="")
        self.subtitle_label.get_style_context().add_class("prismsubtitle")
        # One line, side by side. Stacking the two costs every window a dozen
        # pixels of title bar to say something the tab strip already says.
        titles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        titles.pack_start(self.title_label, False, False, 0)
        titles.pack_start(self.subtitle_label, False, False, 0)
        self.header.set_custom_title(titles)

        self.assist_toggle = Gtk.ToggleButton()
        self.assist_toggle.set_tooltip_text("Claude   Ctrl+Shift+C")
        self.assist_toggle.get_style_context().add_class("toolbtn")
        self.assist_toggle.set_label("Claude")
        self.assist_toggle.connect("toggled", self._claude_button_toggled)
        self.header.pack_end(self.assist_toggle)

        self.panel_toggle = Gtk.ToggleButton()
        self.panel_toggle.set_tooltip_text("Terminal panel   Ctrl+J")
        self.panel_toggle.get_style_context().add_class("toolbtn")
        if Gtk.IconTheme.get_default().has_icon("utilities-terminal-symbolic"):
            self.panel_toggle.set_image(
                Gtk.Image.new_from_icon_name("utilities-terminal-symbolic", Gtk.IconSize.MENU))
        else:
            self.panel_toggle.set_label("Terminal")
        self.panel_toggle.connect("toggled",
                                  lambda b: self.toggle_panel(b.get_active(), False))
        self.header.pack_end(self.panel_toggle)

        self.header.pack_end(icon_button("edit-find-symbolic", "find",
                                         "Go to file   Ctrl+P",
                                         lambda *_: self.do_action("quick-open"), "toolbtn"))

    def _build_status(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.get_style_context().add_class("statusbar")

        self.branch_label = Gtk.Label(label="")
        self.branch_label.get_style_context().add_class("statusitem")
        self.message_label = Gtk.Label(label="")
        self.message_label.set_ellipsize(3)
        self.message_label.get_style_context().add_class("statusitem")

        bar.pack_start(self.branch_label, False, False, 0)
        bar.pack_start(self.message_label, True, True, 0)
        # these widgets are owned by the editor and borrowed here
        bar.pack_start(self.editor.diag_label, False, False, 0)
        for widget in (self.editor.hint_label, self.editor.pos_label,
                       self.editor.lang_label, self.editor.info_label,
                       self.editor.assist_btn, self.editor.wrap_btn):
            bar.pack_end(widget, False, False, 0)
        return bar

    def _build_run_side(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        self.run_summary = Gtk.Label(label="Open a folder to see what it is.")
        self.run_summary.set_xalign(0.0)
        self.run_summary.set_line_wrap(True)
        self.run_summary.get_style_context().add_class("hint")
        box.pack_start(self.run_summary, False, False, 0)
        self.run_targets = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(self.run_targets, False, False, 0)
        return box

    def _build_extensions_side(self):
        outer = Gtk.ScrolledWindow()
        outer.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(12)
        note = Gtk.Label(label="Python add-ons loaded from your config folder.")
        note.set_xalign(0.0)
        note.set_line_wrap(True)
        note.get_style_context().add_class("hint")
        box.pack_start(note, False, False, 0)
        self.extensions_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(self.extensions_list, False, False, 0)
        manage = Gtk.Button(label="Manage extensions…")
        manage.get_style_context().add_class("sidebtn")
        manage.connect("clicked", lambda *_: self.do_action("preferences-extensions"))
        box.pack_start(manage, False, False, 6)
        outer.add(box)
        return outer

    def _sync_extensions_side(self):
        for child in self.extensions_list.get_children():
            self.extensions_list.remove(child)
        found = self.app.extensions.extensions or self.app.extensions.found()
        if not found:
            empty = Gtk.Label(label="None installed.")
            empty.set_xalign(0.0)
            empty.get_style_context().add_class("sideempty")
            self.extensions_list.pack_start(empty, False, False, 0)
        for ext in found:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            row.get_style_context().add_class("extrow")
            name = Gtk.Label(label=ext.name)
            name.set_xalign(0.0)
            name.get_style_context().add_class("extname")
            blurb = Gtk.Label(label=ext.error or ext.blurb)
            blurb.set_xalign(0.0)
            blurb.set_line_wrap(True)
            blurb.get_style_context().add_class("extbad" if ext.error else "extblurb")
            row.pack_start(name, False, False, 0)
            row.pack_start(blurb, False, False, 0)
            self.extensions_list.pack_start(row, False, False, 0)
        self.extensions_list.show_all()

    # ---------------------------------------------------------------------- #
    # layout
    # ---------------------------------------------------------------------- #
    def _apply_layout(self):
        try:
            self.outer.set_position(int(self.cfg.get("SIDEBAR_WIDTH", "240")))
        except ValueError:
            self.outer.set_position(240)
        side = self.cfg.get("SIDEBAR", "explorer")
        if side in self.activity_buttons:
            self.activity_buttons[side].set_active(True)
            self.show_side(side)
        else:
            self.sidebar.hide()
        # sizing needs real allocations, which do not exist until GTK has laid
        # the window out once, so let it settle first
        GLib.idle_add(self._apply_sizes)

    def _apply_sizes(self):
        self.toggle_panel(self.cfg.get("PANEL", "0") == "1", False)
        if self.assistant_enabled and self.cfg.get("ASSISTANT", "0") == "1":
            self.show_claude(focus=False, remember=False)
        self.assist_toggle.set_visible(self.assistant_enabled)
        return False

    def show_side(self, name):
        self.side_stack.set_visible_child_name(name)
        self._sync_side_title(name)
        self.sidebar.show()
        if name == "search":
            self.search.focus()
        elif name == "extensions":
            self._sync_extensions_side()
        elif name == "git":
            self.git.refresh()
        elif name == "run":
            self._sync_run_side()
        self.cfg["SIDEBAR"] = name
        return True

    def toggle_sidebar(self, on=None):
        want = (not self.sidebar.get_visible()) if on is None else on
        self.sidebar.set_visible(want)
        return True

    def toggle_panel(self, on=None, remember=True):
        want = (not self.panel.get_visible()) if on is None else on
        if want and not self.panel.terminals:
            self.panel.new_terminal(select=False)
        self.panel.set_visible(want)
        if want:
            self.panel.show_all()
            # measure the paned itself, not the window: the header, run bar and
            # status bar are not inside it, so window height overshoots badly
            height = self.vertical.get_allocated_height() or self.get_allocated_height() or 800
            try:
                wanted = int(self.cfg.get("PANEL_HEIGHT", "220"))
            except ValueError:
                wanted = 220
            self.vertical.set_position(max(140, height - wanted))
            terminal = self.panel.current_terminal()
            if terminal:
                terminal.term.grab_focus()
        if self.panel_toggle.get_active() != want:
            self.panel_toggle.set_active(want)
        if remember:
            self.cfg["PANEL"] = "1" if want else "0"
        return True

    # ---------------------------------------------------------------------- #
    # Claude: summoned, placed, and put away again
    # ---------------------------------------------------------------------- #
    def claude_place(self):
        place = self.cfg.get("CLAUDE_PLACE", "panel")
        return place if place in ("panel", "side", "window") else "panel"

    def claude_showing(self):
        return self.assistant.get_parent() is not None

    def _park_claude(self):
        """Take the widget out of wherever it is, session still running.

        Unparenting keeps the Python reference, which keeps the terminal, which
        keeps the shell and whatever Claude is in the middle of. Moving it is a
        re-parent, never a restart.
        """
        if self.panel.claude_here():
            self.panel.unmount_claude()
        parent = self.assistant.get_parent()
        if parent is not None:
            parent.remove(self.assistant)
        if self.claude_window is not None:
            window, self.claude_window = self.claude_window, None
            window.destroy()

    def show_claude(self, focus=True, remember=True):
        """Put Claude where it belongs and start it if it is not running."""
        if not self.assistant_enabled:
            self.say("Claude is switched off in settings")
            return False
        place = self.claude_place()
        if not self.claude_showing() or place != self._claude_where:
            self._park_claude()
            if place == "side":
                self.middle.pack2(self.assistant, False, True)
                self.assistant.show_head(True)
                self.assistant.show_all()
                width = (self.middle.get_allocated_width()
                         or self.get_allocated_width() or 1300)
                try:
                    wanted = int(self.cfg.get("ASSISTANT_WIDTH", "420"))
                except ValueError:
                    wanted = 420
                self.middle.set_position(max(320, width - wanted))
            elif place == "window":
                self.claude_window = assistant_mod.ClaudeWindow(self, self.assistant)
                self.assistant.show_head(True)
                self.claude_window.show_all()
                self.claude_window.present()
            else:
                self.toggle_panel(True, remember=False)
                self.panel.mount_claude(self.assistant)
            self._claude_where = place
        elif place == "panel":
            self.toggle_panel(True, remember=False)
            self.panel.show("claude")
        elif place == "window" and self.claude_window is not None:
            self.claude_window.present()
        self.assistant.start()
        if focus:
            self.assistant.focus()
        self._sync_claude_button(True)
        if remember:
            self.cfg["ASSISTANT"] = "1"
        return True

    def hide_claude(self, remember=True):
        """Off the screen, still alive: summoning it again is instant."""
        self._park_claude()
        self._sync_claude_button(False)
        if remember:
            self.cfg["ASSISTANT"] = "0"
        self.editor.view.grab_focus()
        return True

    def toggle_assistant(self, on=None, remember=True):
        """The one entry point everything else uses, old name kept."""
        if not self.assistant_enabled:
            self._park_claude()
            return False
        want = (not self.claude_showing()) if on is None else on
        return self.show_claude(remember=remember) if want \
            else self.hide_claude(remember=remember)

    def place_claude(self, where, remember=True):
        """Move it, and open it there if it was not open."""
        if where not in ("panel", "side", "window"):
            return False
        self.cfg["CLAUDE_PLACE"] = where
        if remember:
            core.save_settings(self.cfg)
        self.show_claude()
        self.say("Claude opens %s" % assistant_mod.PLACE_NAMES[where].lower())
        return True

    def claude_place_menu(self, button):
        """The little chooser on Claude's own header."""
        menu = Gtk.Menu()
        here = self.claude_place()
        group = None
        for where, label in assistant_mod.PLACES:
            item = Gtk.RadioMenuItem(label=label, group=group)
            group = group or item
            item.set_active(where == here)
            item.connect("toggled", (lambda w: lambda i: i.get_active()
                                     and w != self.claude_place()
                                     and self.place_claude(w))(where))
            menu.append(item)
        menu.show_all()
        menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST,
                             Gdk.Gravity.NORTH_WEST, None)
        return True

    def _sync_claude_button(self, on):
        if self.assist_toggle.get_active() != on:
            self.assist_toggle.handler_block_by_func(self._claude_button_toggled)
            self.assist_toggle.set_active(on)
            self.assist_toggle.handler_unblock_by_func(self._claude_button_toggled)

    def _claude_button_toggled(self, button):
        self.toggle_assistant(button.get_active())

    # ---------------------------------------------------------------------- #
    # the workspace
    # ---------------------------------------------------------------------- #
    def open_folder(self, path, restore=False):
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(path):
            self.say("no such folder: %s" % path, bad=True)
            return False
        if self.root:
            self._save_session()
        self.root = path
        self.editor.root = path
        self.explorer.set_root(path)
        self.search.set_folder(path)
        self.git.set_root(path)
        self.lsp.set_root(path)
        workspace.remember_folder(path)
        self.runbar.rescan()
        self._sync_run_side()
        self._sync_title()
        self._sync_side_title()
        self.file_index(refresh=True)       # start the walk while you read
        if restore and self.cfg.get("RESTORE_SESSION", "1") == "1":
            self._restore_session()
        self.editor.show_welcome_if_empty()
        found = self.runbar.project
        if found.targets:
            self.say("%s — %s" % (found.summary,
                                  "press Run" if not found.pending
                                  else "install the dependencies first"))
        else:
            self.say("opened %s" % core.short_path(path))
        return True

    def close_folder(self):
        self._save_session()
        self.root = None
        self.editor.root = None
        self.explorer.set_root(None)
        self.search.set_folder(None)
        self.git.set_root(None)
        self.lsp.set_root(None)
        self.runbar.rescan()
        self._sync_title()
        self.say("closed the folder")
        return True

    def open_file(self, path, line=None, split=False):
        if not self.editor.open(path):
            return False
        if line:
            self.editor.go_to(line)
        self.editor.view.grab_focus()
        self._sync_title()
        return True

    def file_saved(self, path):
        self.explorer.reveal(path)
        if self.side_stack.get_visible_child_name() == "git":
            self.git.refresh()
        if os.path.basename(path) in ("package.json", "requirements.txt",
                                      "pyproject.toml", "Cargo.toml", "go.mod",
                                      "composer.json", "Gemfile", "Makefile"):
            self.runbar.rescan()
            self._sync_run_side()
        self._sync_title()

    def renamed(self, old, new):
        for doc in list(self.editor.docs):
            if doc.path == old:
                doc.path, doc.key, doc.name = new, new, os.path.basename(new)
                self.editor._sync_tabs()

    def deleted(self, path):
        for doc in list(self.editor.docs):
            if doc.path == path:
                doc.buffer.set_modified(False)
                self.editor.close_doc(doc)

    def _sync_title(self):
        name = workspace.name_for(self.root)
        open_file = self.editor.path
        if open_file:
            self.title_label.set_text(os.path.basename(open_file))
            self.subtitle_label.set_text(name if self.root else "")
        else:
            self.title_label.set_text(name if self.root else core.APP_NAME)
            self.subtitle_label.set_text(core.short_path(self.root) if self.root else "")
        self.set_title("%s — %s" % (name, core.APP_NAME) if self.root else core.APP_NAME)
        branch = core.git_branch(self.root)
        self.branch_label.set_text(("⎇ " + branch) if branch else "")

    def _sync_side_title(self, name=None):
        """Name the region — except the explorer, which names the folder."""
        name = name or self.side_stack.get_visible_child_name() or "explorer"
        if name == "explorer" and self.root:
            self.side_title.set_text(workspace.name_for(self.root).upper())
        elif name == "git":
            self.side_title.set_text("SOURCE CONTROL")
        else:
            self.side_title.set_text(name.upper())

    def _sync_run_side(self):
        for child in self.run_targets.get_children():
            self.run_targets.remove(child)
        found = self.runbar.project
        self.run_summary.set_text(
            found.summary if self.root else "Open a folder to see what it is.")
        for step in found.pending:
            button = Gtk.Button(label="Install: %s" % step.label)
            button.get_style_context().add_class("sidebtn")
            button.connect("clicked", lambda *_: self.runbar.install())
            self.run_targets.pack_start(button, False, False, 0)
        for step in found.blocked:
            note = Gtk.Label(label="cannot: %s" % step.blocked)
            note.set_xalign(0.0)
            note.set_line_wrap(True)
            note.get_style_context().add_class("extbad")
            self.run_targets.pack_start(note, False, False, 0)
        for index, target in enumerate(getattr(self.runbar, "choices", [])):
            button = Gtk.Button(label=("▶  " if target.web else "   ") + target.label)
            button.get_style_context().add_class("sidebtn")
            button.set_tooltip_text(target.detail or target.command)
            button.connect("clicked",
                           (lambda i: lambda *_: self._run_index(i))(index))
            self.run_targets.pack_start(button, False, False, 0)
        self.run_targets.show_all()

    def _run_index(self, index):
        self.runbar.targets.set_active(index)
        self.runbar.run()

    # ---------------------------------------------------------------------- #
    # sessions
    # ---------------------------------------------------------------------- #
    def _save_session(self):
        if self.cfg.get("RESTORE_SESSION", "1") != "1":
            return
        files = []
        for doc in self.editor.docs:
            if doc.path:
                it = doc.buffer.get_iter_at_mark(doc.buffer.get_insert())
                files.append({"path": doc.path, "line": it.get_line() + 1})
        workspace.save_session(self.root, files, self.editor.path,
                               {"panel": self.panel.get_visible(),
                                "assistant": self.claude_showing(),
                                "claude_place": self.claude_place(),
                                "sidebar": self.cfg.get("SIDEBAR", "explorer")})

    def _restore_session(self):
        session = workspace.load_session(self.root)
        for entry in session["files"]:
            if self.editor.open(entry["path"], focus=False):
                self.editor.go_to(entry.get("line") or 1)
        active = session.get("active")
        if active:
            for doc in self.editor.docs:
                if doc.path == active:
                    self.editor.switch(doc)
                    break
        if session["files"]:
            self.say("reopened %d file%s" % (len(session["files"]),
                                             "" if len(session["files"]) == 1 else "s"))

    # ---------------------------------------------------------------------- #
    # messages
    # ---------------------------------------------------------------------- #
    def say(self, text, bad=False):
        self.message_label.set_text(text)
        context = self.message_label.get_style_context()
        context.remove_class("statusbad")
        if bad:
            context.add_class("statusbad")
        if self._status_timer:
            GLib.source_remove(self._status_timer)
        self._status_timer = GLib.timeout_add_seconds(9, self._clear_message)

    def _clear_message(self):
        self.message_label.set_text("")
        self._status_timer = None
        return False

    def say_from_editor(self, text, bad=False):
        self.say(text, bad)

    def _diagnostics(self, path, items):
        self.editor.show_diagnostics(path, items)

    def editor_status_changed(self, _editor):
        self._sync_title()

    def terminal_changed(self, _terminal):
        if self.panel.get_visible():
            self.panel._sync_picker()

    def terminal_bell(self, _terminal):
        pass

    # ---------------------------------------------------------------------- #
    # things the panes ask for
    # ---------------------------------------------------------------------- #
    def show_shell(self):
        self.toggle_panel(True)

    def status_message(self, text, bad=False):
        self.say(text, bad)

    @property
    def win(self):
        """The run bar was written against a view that had a window; here the
        window is the view, so it points at itself."""
        return self

    @property
    def shell(self):
        """The run bar talks to whichever terminal is in front."""
        if not self.panel.terminals:
            self.panel.new_terminal(select=False)
        return self.panel.current_terminal()

    def terminal_in(self, folder):
        self.toggle_panel(True)
        self.panel.new_terminal(cwd=folder)

    def search_in(self, folder):
        self.activity_buttons["search"].set_active(True)
        self.show_side("search")
        self.search.set_folder(folder)

    def point_claude_at(self, path, first, last=None):
        self.show_claude(focus=False)
        return self.assistant.point_at(path, first, last)

    def point_claude_at_current(self):
        return self.editor.ask_claude()

    # ---------------------------------------------------------------------- #
    # keys and actions
    # ---------------------------------------------------------------------- #
    def on_key(self, _widget, event):
        focus = self.get_focus()
        if (hasattr(self.editor, "view") and focus is self.editor.view
                and self.editor.handle_key(event)):
            return True
        in_text = isinstance(focus, (Gtk.Entry, Gtk.TextView))
        action = self.km.match(event)
        if action:
            if in_text and action in ("copy", "paste", "select-all", "find",
                                      "undo", "redo", "save"):
                if action not in ("find", "save"):
                    return False
            return bool(self.do_action(action))
        return False

    def do_action(self, name):
        handler = self.actions().get(name)
        if handler is None:
            return False
        return handler()

    def actions(self):
        if getattr(self, "_actions", None):
            return self._actions
        editor = self.editor
        self._actions = {
            "new-file": lambda: (editor.new_file(), True)[1],
            "open-file": self.pick_file,
            "open-folder": self.pick_folder,
            "close-folder": self.close_folder,
            "save": lambda: (editor.save(), True)[1],
            "save-as": lambda: (editor.save(ask=True), True)[1],
            "close-file": lambda: (editor.close_doc(), True)[1],
            "next-file": lambda: (editor.cycle(1), True)[1],
            "prev-file": lambda: (editor.cycle(-1), True)[1],
            "undo": lambda: (editor.undo(), True)[1],
            "redo": lambda: (editor.redo(), True)[1],
            "find": lambda: (editor.findbar.open(), True)[1],
            "replace": lambda: (editor.findbar.open(with_replace=True), True)[1],
            "go-to-line": lambda: (editor.go_to_line(), True)[1],
            "go-to-definition": lambda: (editor.go_to_definition(), True)[1],
            "search": self.focus_search,
            "side-explorer": lambda: self._side("explorer"),
            "side-search": lambda: self._side("search"),
            "side-git": lambda: self._side("git"),
            "side-run": lambda: self._side("run"),
            "side-extensions": lambda: self._side("extensions"),
            "toggle-sidebar": self.toggle_sidebar,
            "toggle-panel": lambda: self.toggle_panel(),
            "toggle-assistant": lambda: self.toggle_assistant(),
            "git-commit": lambda: (self._side("git"), self.git.commit(), True)[2],
            "git-sync": lambda: (self._side("git"), self.git.sync(), True)[2],
            "git-refresh": lambda: (self.git.refresh(), True)[1],
            "new-terminal": lambda: (self.toggle_panel(True),
                                     self.panel.new_terminal(), True)[2],
            "palette": self.show_palette,
            "preferences": lambda: self.open_prefs(0),
            "preferences-extensions": lambda: self.open_prefs(3),
            "keymap": self.show_keymap,
            "about": self.show_about,
            "check-updates": self.check_updates,
            "git-clone": self.show_clone,
            "git-publish": self.show_publish,
            "quit": self.quit_app,
            "fullscreen": self.toggle_fullscreen,
            "zoom-in": lambda: self.zoom(1),
            "zoom-out": lambda: self.zoom(-1),
            "zoom-reset": lambda: self.zoom(0),
            "run-app": self.run_app,
            "stop-app": lambda: self.runbar.stop() if self.runbar.running else False,
            "open-app": lambda: self.runbar.open_browser(),
            "run-file": self.run_file,
            "rescan": self.rescan_project,
            "suggest": lambda: (editor.request_claude(True), True)[1],
            "suggest-mode": lambda: (editor.cycle_suggest_mode(), True)[1],
            "claude-edit": self.claude_edit,
            "ask-claude": lambda: (editor.ask_claude(), True)[1],
            "restart-claude": lambda: (self.show_claude(), self.assistant.restart(),
                                       True)[2],
            "claude-place-panel": lambda: self.place_claude("panel"),
            "claude-place-side": lambda: self.place_claude("side"),
            "claude-place-window": lambda: self.place_claude("window"),
            "quick-open": self.quick_open,
            "new-window": self.new_window,
        }
        return self._actions

    def claude_edit(self):
        if not self.assistant_enabled:
            self.say("Claude is switched off in settings")
            return True
        if self.selection:
            self.selection.suppress(True)
        self.editor.editbar.open()
        return True

    def _side(self, name):
        self.sidebar.show()
        self.activity_buttons[name].set_active(True)
        self.show_side(name)
        return True

    def focus_search(self):
        selection = self.editor.selected_text()
        self._side("search")
        self.search.focus(selection or None)
        return True

    def pick_file(self):
        path = choose_file(self, self.root or os.path.expanduser("~"))
        if path:
            self.open_file(path)
        return True

    def pick_folder(self):
        path = choose_folder(self, self.root or os.path.expanduser("~"))
        if path:
            self.open_folder(path, restore=True)
        return True

    def run_app(self):
        if not self.runbar.choices:
            self.runbar.rescan()
        if self.runbar.choices:
            return self.runbar.toggle()
        return self.run_file()

    def rescan_project(self):
        """Look at the folder again after you have changed what is in it."""
        found = self.runbar.rescan()
        self._sync_run_side()
        self.say(found.summary if self.root else "no folder open")
        return True

    def run_file(self):
        import runner
        label, command = runner.command_for(self.editor.path)
        if label is None:
            self.say(command, bad=True)
            return True
        self.editor.flush()
        self.toggle_panel(True)
        self.panel.run(command, os.path.dirname(self.editor.path))
        return True

    def zoom(self, delta):
        size = self.cfg.get("FONT", "Ubuntu Sans Mono 11").rsplit(" ", 1)
        try:
            points = int(size[-1])
        except ValueError:
            points = 11
        points = 11 if delta == 0 else max(6, min(38, points + delta))
        self.cfg["FONT"] = "%s %d" % (size[0], points)
        core.save_settings({"FONT": self.cfg["FONT"]})
        self.restyle()
        return True

    def toggle_fullscreen(self):
        window = self.get_window()
        if window and window.get_state() & Gdk.WindowState.FULLSCREEN:
            self.unfullscreen()
        else:
            self.fullscreen()
        return True

    # ---------------------------------------------------------------------- #
    # going places
    # ---------------------------------------------------------------------- #
    def show_palette(self):
        """Ctrl+Shift+P — the commands, with the files a backspace away."""
        return self._palette(start=">")

    def quick_open(self):
        """Ctrl+P — the files, with the commands a keystroke away."""
        return self._palette(start="")

    def _palette(self, start=""):
        import palette
        window = palette.Palette(self, self.all_commands(),
                                 files=self.file_index(), start=start)
        # If the walk is still going, hand the list over when it lands rather
        # than making the box wait for it.
        self._file_watchers.append(window.set_files)
        window.connect("destroy", lambda *_: self._file_watchers.remove(window.set_files)
                       if window.set_files in self._file_watchers else None)
        window.present_it()
        return True

    def file_index(self, refresh=False):
        """The workspace's files, walked in a thread and kept until they change.

        Always returns immediately, with whatever is known. A folder that has
        not been walked yet answers empty and fills itself in a moment later,
        which is the difference between a box that opens now and a box that
        opens when a repository has finished being counted.
        """
        root = self.root
        if not root:
            return []
        stale = (self._file_root != root
                 or refresh
                 or (time.monotonic() - self._file_at) > 30)
        if stale and not self._file_walking:
            self._file_walking = True
            if self._file_root != root:
                self._files = []
            self._file_root = root

            def walk():
                found = workspace.walk_files(root)
                GLib.idle_add(self._files_landed, root, found)

            threading.Thread(target=walk, daemon=True).start()
        return self._files

    def _files_landed(self, root, found):
        self._file_walking = False
        if root != self.root:
            return False
        self._files, self._file_at = found, time.monotonic()
        for watcher in list(self._file_watchers):
            try:
                watcher(found)
            except Exception:
                pass
        return False

    def all_commands(self):
        out = []
        actions = self.actions()
        claude_only = {"claude-edit", "ask-claude", "restart-claude",
                       "toggle-assistant", "claude-place-panel",
                       "claude-place-side", "claude-place-window"}
        for ident, label, group, _default, _alt in keymap.ACTIONS:
            handler = actions.get(ident)
            if handler is None:
                continue
            if ident in claude_only and not self.assistant_enabled:
                continue
            out.append(extensions.Command(ident, "%s: %s" % (group, label),
                                          handler, "prism", self.km.accel_for(ident)))
        out.extend(self.app.extensions.commands)
        return out

    def show_keymap(self):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.INFO,
                                   buttons=Gtk.ButtonsType.CLOSE,
                                   text="Keyboard shortcuts")
        dialog.format_secondary_markup(keymap.as_markdown(self.km))
        dialog.get_style_context().add_class("prefs")
        dialog.run()
        dialog.destroy()
        return True

    # ---------------------------------------------------------------------- #
    # github
    # ---------------------------------------------------------------------- #
    def run_in_panel(self, command, cwd=None):
        """Show the panel and run something in it, where it can be watched."""
        self.toggle_panel(True)
        return self.panel.run(command, cwd=cwd or self.root)

    def show_clone(self):
        import clone
        clone.CloneDialog(self).show_all()
        return True

    def show_publish(self):
        import clone
        if not self.root:
            self.say("open the folder you want to publish first", bad=True)
            return True
        clone.PublishDialog(self).show_all()
        return True

    def clone_into(self, url, target):
        """git clone, in the terminal, then offer to open what arrived.

        The clone runs where you can see it because a big repository takes a
        while and a silent spinner tells you nothing. Finishing is detected by
        a marker echoed after it, rather than by guessing from the clock.
        """
        marker = "PRISM_CLONE_DONE"
        parent = os.path.dirname(target)
        self.say("cloning into %s" % target)
        self.run_in_panel("git clone %s %s && echo %s"
                          % (GLib.shell_quote(url), GLib.shell_quote(target), marker),
                          cwd=parent)
        self._await_clone(target, marker, tries=[0])

    def _await_clone(self, target, marker, tries):
        def look():
            tries[0] += 1
            done = os.path.isdir(os.path.join(target, ".git")) and \
                marker in self._panel_text()
            if done:
                self._clone_arrived(target)
                return False
            if tries[0] > 600:                 # ten minutes is long enough
                return False
            return True
        GLib.timeout_add_seconds(1, look)

    def _panel_text(self):
        """Whatever the visible terminal is showing. Empty on any trouble."""
        terminal = self.panel.current_terminal()
        if terminal is None:
            return ""
        for attempt in (
                lambda: terminal.term.get_text_format(Vte.Format.TEXT),):
            try:
                got = attempt()
            except Exception:
                continue
            while isinstance(got, tuple) and got:
                got = got[0]
            if isinstance(got, str):
                return got
        return ""

    def _clone_arrived(self, target):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO,
                                   text="Cloned %s" % os.path.basename(target))
        dialog.format_secondary_text("Open it now?")
        dialog.get_style_context().add_class("prefs")
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.YES:
            self.open_folder(target)
        else:
            self.say("cloned into %s" % target)

    def publish_folder(self, name, private, description):
        """gh repo create, from the open folder, pushing what is committed."""
        if not github.available():
            self.say("publishing needs the GitHub CLI (gh)", bad=True)
            return
        if not self.git.repo.is_repo():
            self.say("this folder is not a git repository yet", bad=True)
            return
        self.say("publishing %s" % name)
        self.run_in_panel(github.create_argv(name, private, description,
                                             self.root, push=True))
        GLib.timeout_add_seconds(8, lambda: (self.git.refresh(), False)[1])

    def copilot_status_changed(self, kind, message):
        """The Copilot server volunteers its state; pass on the useful ones."""
        if kind in ("signed-out", "no-subscription", "error"):
            self.say("Copilot: " + (message or kind), bad=True)
        elif kind == "ready" and self.editor.suggest_mode == "copilot":
            self.say("Copilot is ready")
        return False

    def copilot_sign_in(self):
        """Device flow: show the code, open the page, wait for the server."""
        server = self.copilot.ensure()
        if server is None:
            kind, message = self.copilot.status()
            self.say("Copilot: " + (message or kind), bad=True)
            return True

        def coded(code, url, error):
            if error:
                self.say("Copilot sign-in failed: " + error, bad=True)
                return
            if not code:
                self.say("already signed in to Copilot")
                return
            self._show_device_code(code, url)
        server.sign_in(coded)
        self.say("asking Copilot to start a sign-in…")
        return True

    def _show_device_code(self, code, url):
        dialog = Gtk.Dialog(title="Sign in to Copilot", transient_for=self,
                            modal=False)
        dialog.get_style_context().add_class("prefs")
        dialog.get_style_context().add_class("whatsnew")
        area = dialog.get_content_area()
        area.set_border_width(20)
        area.set_spacing(12)

        lead = Gtk.Label(xalign=0)
        lead.set_markup("Enter this code at <b>%s</b>:"
                        % GLib.markup_escape_text(url))
        lead.set_line_wrap(True)
        area.pack_start(lead, False, False, 0)

        shown = Gtk.Label(label=code)
        shown.get_style_context().add_class("devicecode")
        shown.set_selectable(True)
        area.pack_start(shown, False, False, 0)

        note = Gtk.Label(xalign=0)
        note.set_markup("<small>The code is on the clipboard. This window can "
                        "be closed once GitHub says you are done — the editor "
                        "notices on its own.</small>")
        note.set_line_wrap(True)
        note.get_style_context().add_class("hint")
        area.pack_start(note, False, False, 0)

        Gtk.Clipboard.get_default(Gdk.Display.get_default()).set_text(code, -1)
        dialog.add_button("Copy again", 1)
        dialog.add_button("Open the page", 2)
        dialog.add_button("Done", Gtk.ResponseType.CLOSE)
        dialog.get_action_area().get_style_context().add_class("wnactions")
        for button in dialog.get_action_area().get_children():
            button.get_style_context().add_class("wnbtn")
        dialog.get_action_area().get_children()[-1] \
            .get_style_context().add_class("wnprimary")

        def respond(_d, response):
            if response == 1:
                Gtk.Clipboard.get_default(Gdk.Display.get_default()).set_text(code, -1)
                self.say("code copied")
            elif response == 2:
                Gtk.show_uri_on_window(self, url, 0)
            else:
                dialog.destroy()
        dialog.connect("response", respond)
        dialog.show_all()

    def copilot_sign_out(self):
        if self.copilot.server is None:
            self.say("Copilot is not running")
            return True
        self.copilot.server.sign_out(
            lambda error: self.say("signed out of Copilot" if not error
                                   else str(error), bad=bool(error)))
        return True

    def check_updates(self):
        """Help -> Check for updates. Says so either way, unlike the quiet
        check at startup."""
        self.updates.check(manual=True)
        return True

    def show_about(self):
        dialog = Gtk.AboutDialog(transient_for=self, modal=True)
        dialog.set_program_name(core.APP_NAME)
        dialog.set_version(core.VERSION)
        dialog.set_comments("An editor with Claude beside it.\n"
                            "Skins, suggestions, projects and extensions.")
        dialog.set_copyright(core.COPYRIGHT)
        dialog.set_license_type(Gtk.License.MIT_X11)
        dialog.set_website(core.HOMEPAGE)
        dialog.set_website_label("github.com/HermesFoundry/PrismStudio")
        # What it is standing on. People reporting a bug need these versions,
        # and this is the one place they can find them without a terminal.
        dialog.add_credit_section("Built on", [
            "GTK %d.%d.%d" % (Gtk.get_major_version(), Gtk.get_minor_version(),
                              Gtk.get_micro_version()),
            "Python %d.%d.%d" % sys.version_info[:3],
            "VTE %d.%d" % (Vte.MAJOR_VERSION, Vte.MINOR_VERSION),
        ])
        shipped = os.path.join(core.ROOT, "packaging", "icons", "128.png")
        if os.path.exists(shipped):
            from gi.repository import GdkPixbuf
            dialog.set_logo(GdkPixbuf.Pixbuf.new_from_file(shipped))
        dialog.get_style_context().add_class("prefs")
        dialog.run()
        dialog.destroy()
        return True

    def open_prefs(self, page=0):
        import prefs
        prefs.PrefsDialog(self, page).show_all()
        return True

    def new_window(self):
        PrismWindow(self.app, self.root)
        return True

    def restyle(self):
        self.theme = core.load_theme(self.cfg["THEME"])
        self.app.load_css(self.theme, self.cfg)
        self.editor.restyle(self.theme, self.cfg)
        self.panel.restyle(self.theme, self.cfg)
        self.assistant.restyle(self.theme, self.cfg)
        self.explorer.restyle()

    def quit_app(self):
        self.close()
        return True

    def on_close(self, *_):
        if self.cfg.get("CONFIRM_CLOSE", "1") == "1":
            unsaved = [d for d in self.editor.docs if d.buffer.get_modified()]
            if unsaved and not self._confirm_unsaved(unsaved):
                return True
        self._save_session()
        self.updates.stop()
        self.copilot.shutdown()
        self.lsp.shutdown()
        core.save_settings({"SIDEBAR": self.cfg.get("SIDEBAR", "explorer"),
                            "PANEL": self.cfg.get("PANEL", "0"),
                            "ASSISTANT": self.cfg.get("ASSISTANT", "1")})
        return False

    def _confirm_unsaved(self, unsaved):
        names = ", ".join(d.name for d in unsaved[:4])
        more = " and %d more" % (len(unsaved) - 4) if len(unsaved) > 4 else ""
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text="%s ha%s unsaved changes"
                                        % (names + more, "s" if len(unsaved) == 1 else "ve"))
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Close without saving", Gtk.ResponseType.OK,
                           "Save all", Gtk.ResponseType.ACCEPT)
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.ACCEPT:
            keep = self.editor.current
            for doc in unsaved:
                self.editor.current = doc
                self.editor.save(quiet=True)
            self.editor.current = keep
            return True
        return answer == Gtk.ResponseType.OK


# --------------------------------------------------------------------------- #
class PrismApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=core.APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.provider = None
        self.extensions = extensions.Registry()
        self.connect("command-line", self.on_command_line)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if core.load_settings().get("EXTENSIONS", "1") == "1":
            self.extensions.load_all()
            for line in self.extensions.messages:
                print("prism: extension %s" % line, file=sys.stderr)

    def load_css(self, theme, cfg):
        try:
            self.provider.load_from_data(styling.build_css(theme, cfg).encode())
        except GLib.Error as exc:
            print("prism: stylesheet error: %s" % exc.message, file=sys.stderr)

    def on_command_line(self, _app, command_line):
        args = command_line.get_arguments()[1:]
        folder, files = None, []
        for arg in args:
            if arg.startswith("-"):
                continue
            full = os.path.abspath(arg)
            if os.path.isdir(full):
                folder = folder or full
            elif os.path.exists(full):
                files.append(full)
                folder = folder or os.path.dirname(full)
        if folder is None and not files:
            # Started with no arguments. By default that means an empty
            # window: nothing on the machine is listed until you ask for it.
            # REOPEN_LAST=1 brings back the folder you had last time instead.
            cfg = core.load_settings()
            if cfg.get("REOPEN_LAST", "0") == "1":
                folder = workspace.last_folder()
        window = PrismWindow(self, folder)
        for path in files:
            window.open_file(path)
        window.present()
        self.extensions.window = window
        return 0
