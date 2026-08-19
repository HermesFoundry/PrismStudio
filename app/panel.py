"""panel — the drawer along the bottom: terminals and output.

Terminals are plural here, the way they are in any editor: a picker in the
header, a + to add one, and each keeps its own working directory. Output is
where the app talks to you at length instead of in the one-line status bar.
"""
import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import core  # noqa: E402
from terminal import PrismTerminal  # noqa: E402


def tab_button(label, group=None):
    button = Gtk.RadioButton.new_with_label_from_widget(group, label)
    button.set_mode(False)
    button.get_style_context().add_class("paneltab")
    button.set_relief(Gtk.ReliefStyle.NONE)
    return button


class Panel(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self.terminals = []

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        head.get_style_context().add_class("panelhead")

        self.tab_terminal = tab_button("TERMINAL")
        self.tab_output = tab_button("OUTPUT", self.tab_terminal)
        # Claude gets a tab here only while it is living in the panel, so the
        # drawer says TERMINAL OUTPUT until you summon it and TERMINAL OUTPUT
        # CLAUDE afterwards.
        self.tab_claude = tab_button("CLAUDE", self.tab_terminal)
        self.tab_claude.set_no_show_all(True)
        self.tab_terminal.connect("toggled", lambda b: b.get_active() and self.show("terminal"))
        self.tab_output.connect("toggled", lambda b: b.get_active() and self.show("output"))
        self.tab_claude.connect("toggled", lambda b: b.get_active() and self.show("claude"))
        head.pack_start(self.tab_terminal, False, False, 0)
        head.pack_start(self.tab_output, False, False, 0)
        head.pack_start(self.tab_claude, False, False, 0)

        self.picker = Gtk.ComboBoxText()
        self.picker.get_style_context().add_class("termpick")
        self.picker.set_tooltip_text("Which terminal")
        self.picker.connect("changed", self._picked)
        head.pack_start(self.picker, False, False, 8)

        from explorer import icon_button
        head.pack_end(icon_button("window-close-symbolic", "✕", "Hide the panel   Ctrl+J",
                                  lambda *_: self.window.toggle_panel()), False, False, 0)
        self.terminal_actions = []
        for icon, fallback, tip, cb in (
                ("edit-delete-symbolic", "kill", "Close this terminal",
                 lambda *_: self.close_terminal()),
                ("list-add-symbolic", "+", "New terminal",
                 lambda *_: self.new_terminal())):
            button = icon_button(icon, fallback, tip, cb)
            button.set_no_show_all(True)
            button.set_visible(True)
            self.terminal_actions.append(button)
            head.pack_end(button, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.terminal_stack = Gtk.Stack()
        self.output = Gtk.TextView()
        self.output.set_editable(False)
        self.output.set_monospace(True)
        self.output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.output.get_style_context().add_class("outputview")
        output_scroll = Gtk.ScrolledWindow()
        output_scroll.add(self.output)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.terminal_stack, "terminal")
        self.stack.add_named(output_scroll, "output")
        self.pack_start(self.stack, True, True, 0)

    # -- terminals -------------------------------------------------------------
    def new_terminal(self, cwd=None, select=True):
        shell = self.window.cfg.get("SHELL") or os.environ.get("SHELL", "/bin/bash")
        where = cwd or self.window.root or os.path.expanduser("~")
        terminal = PrismTerminal(self.window, [shell, "-l"], cwd=where,
                                 name="terminal %d" % (len(self.terminals) + 1))
        self.terminals.append(terminal)
        self.terminal_stack.add_named(terminal, str(id(terminal)))
        terminal.show_all()
        terminal.restyle(self.window.theme, self.window.cfg)
        terminal.spawn()            # without this it is a widget with no shell
        self._sync_picker()
        if select:
            self.select(terminal)
        return terminal

    def current_terminal(self):
        if not self.terminals:
            return None
        name = self.terminal_stack.get_visible_child_name()
        for terminal in self.terminals:
            if str(id(terminal)) == name:
                return terminal
        return self.terminals[0]

    def select(self, terminal):
        self.terminal_stack.set_visible_child_name(str(id(terminal)))
        self._sync_picker()
        self.show("terminal")
        terminal.term.grab_focus()

    def close_terminal(self, terminal=None):
        terminal = terminal or self.current_terminal()
        if terminal is None:
            return
        self.terminals.remove(terminal)
        self.terminal_stack.remove(terminal)
        terminal.destroy()
        if self.terminals:
            self.select(self.terminals[-1])
        else:
            self.window.toggle_panel(False)
        self._sync_picker()

    def _sync_picker(self):
        self.picker.handler_block_by_func(self._picked)
        self.picker.remove_all()
        for terminal in self.terminals:
            self.picker.append(str(id(terminal)), terminal.label)
        current = self.terminal_stack.get_visible_child_name()
        if current:
            self.picker.set_active_id(current)
        self.picker.handler_unblock_by_func(self._picked)
        self.picker.set_visible(len(self.terminals) > 1
                                and self.stack.get_visible_child_name() == "terminal")

    def _picked(self, combo):
        chosen = combo.get_active_id()
        if chosen and chosen != self.terminal_stack.get_visible_child_name():
            self.terminal_stack.set_visible_child_name(chosen)

    def run(self, command, cwd=None):
        """Type a command into the visible terminal and press return for you."""
        terminal = self.current_terminal() or self.new_terminal(cwd)
        self.show("terminal")
        where = cwd or self.window.root
        line = ("cd %s && %s\n" % (GLib.shell_quote(where), command)) if where \
            else command + "\n"
        # wait for the shell to be listening, or the very first command after
        # opening the panel disappears into a pty nobody is reading yet
        terminal.when_ready(lambda: terminal.term.feed_child(line.encode()))
        terminal.term.grab_focus()
        return terminal

    def interrupt(self):
        terminal = self.current_terminal()
        if terminal:
            terminal.term.feed_child(b"\x03")

    # -- output ----------------------------------------------------------------
    def write(self, text):
        buffer = self.output.get_buffer()
        buffer.insert(buffer.get_end_iter(), text.rstrip("\n") + "\n")
        self.output.scroll_to_iter(buffer.get_end_iter(), 0, False, 0, 0)

    # -- Claude, while it is living here ---------------------------------------
    def mount_claude(self, assistant):
        """Take the assistant widget in as a third tab."""
        if self.stack.get_child_by_name("claude") is None:
            self.stack.add_named(assistant, "claude")
        assistant.show_all()
        assistant.show_head(False)
        self.tab_claude.set_visible(True)
        self.show("claude")

    def unmount_claude(self):
        """Hand the widget back, leaving the panel as it was."""
        child = self.stack.get_child_by_name("claude")
        if child is not None:
            self.stack.remove(child)
        self.tab_claude.set_visible(False)
        if self.stack.get_visible_child_name() == "claude" or child is not None:
            self.show("terminal")
        return child

    def claude_here(self):
        return self.stack.get_child_by_name("claude") is not None

    def show(self, which):
        if which == "claude" and self.stack.get_child_by_name("claude") is None:
            which = "terminal"
        self.stack.set_visible_child_name(which)
        if which == "terminal" and not self.tab_terminal.get_active():
            self.tab_terminal.set_active(True)
        elif which == "output" and not self.tab_output.get_active():
            self.tab_output.set_active(True)
        elif which == "claude" and not self.tab_claude.get_active():
            self.tab_claude.set_active(True)
        # the + and the bin belong to terminals, not to Claude
        for button in getattr(self, "terminal_actions", []):
            button.set_visible(which == "terminal")
        self.picker.set_visible(which == "terminal" and len(self.terminals) > 1)

    def restyle(self, theme, cfg):
        for terminal in self.terminals:
            terminal.restyle(theme, cfg)
