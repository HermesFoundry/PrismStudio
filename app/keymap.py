"""keymap — every shortcut in PrismStudio, in one editable table.

Two presets ship:

  standard  what an editor user expects: Ctrl+S, Ctrl+P, Ctrl+F …  (the default)
  reach     the same set moved off the plain control keys, for people who want
            those reaching the terminal panel untouched

Bindings live in ~/.config/prismstudio/keys.conf as `action = accel, accel`.
"""
import os
import re

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk  # noqa: E402

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME",
                                         os.path.join(os.path.expanduser("~"), ".config")),
                          "prismstudio")
KEYS_CONFIG = os.path.join(CONFIG_DIR, "keys.conf")

# action id, label, group, standard accels, reach accels
ACTIONS = [
    ("new-file",        "New file",                 "File",   "Ctrl+N",            "Ctrl+Shift+N"),
    ("open-file",       "Open file…",               "File",   "Ctrl+O",            "Ctrl+Shift+O"),
    ("open-folder",     "Open folder…",             "File",   "Ctrl+K",            "Ctrl+Shift+K"),
    ("save",            "Save",                     "File",   "Ctrl+S",            "Ctrl+Shift+S"),
    ("save-as",         "Save as…",                 "File",   "Ctrl+Shift+S",      "Ctrl+Alt+S"),
    ("close-file",      "Close this file",          "File",   "Ctrl+W",            "Ctrl+Shift+W"),
    ("close-folder",    "Close the folder",         "File",   "Ctrl+Shift+K",      "Ctrl+Alt+K"),
    ("next-file",       "Next file",                "File",   "Ctrl+Tab, Ctrl+Page_Down",
                                                              "Ctrl+Page_Down"),
    ("prev-file",       "Previous file",            "File",   "Ctrl+Shift+Tab, Ctrl+Page_Up",
                                                              "Ctrl+Page_Up"),

    ("undo",            "Undo",                     "Edit",   "Ctrl+Z",            "Ctrl+Shift+Z"),
    ("redo",            "Redo",                     "Edit",   "Ctrl+Y",            "Ctrl+Alt+Z"),
    ("find",            "Find in this file",        "Edit",   "Ctrl+F",            "Ctrl+Shift+F"),
    ("replace",         "Find and replace",         "Edit",   "Ctrl+H",            "Ctrl+Shift+H"),
    ("search",          "Search the workspace",     "Edit",   "Ctrl+Shift+F",      "Ctrl+Alt+F"),
    ("go-to-line",      "Go to line…",              "Edit",   "Ctrl+G",            "Ctrl+Shift+G"),

    ("side-explorer",   "Explorer",                 "View",   "Ctrl+Shift+E",      "Ctrl+Shift+E"),
    ("side-search",     "Search panel",             "View",   "Ctrl+Alt+F",        "Ctrl+Alt+F"),
    ("side-git",        "Source control",           "View",   "Ctrl+Shift+G",      "Ctrl+Shift+G"),
    ("side-run",        "Run panel",                "View",   "Ctrl+Shift+D",      "Ctrl+Shift+D"),
    ("side-extensions", "Extensions panel",         "View",   "Ctrl+Shift+X",      "Ctrl+Shift+X"),
    ("toggle-sidebar",  "Show or hide the side bar", "View",  "Ctrl+B",            "Ctrl+Shift+B"),
    ("toggle-panel",    "Show or hide the panel",   "View",   "Ctrl+J",            "Ctrl+Shift+J"),
    ("toggle-assistant", "Show or hide Claude",     "View",   "Ctrl+Shift+C",      "Ctrl+Shift+C"),
    ("palette",         "Command palette",          "View",   "Ctrl+Shift+P",      "Ctrl+Shift+P"),
    ("zoom-in",         "Bigger text",              "View",   "Ctrl+plus, Ctrl+equal",
                                                              "Ctrl+plus, Ctrl+equal"),
    ("zoom-out",        "Smaller text",             "View",   "Ctrl+minus",        "Ctrl+minus"),
    ("zoom-reset",      "Reset text size",          "View",   "Ctrl+0",            "Ctrl+0"),
    ("fullscreen",      "Full screen",              "View",   "F11",               "F11"),

    ("git-commit",      "Commit",                   "Git",    "Ctrl+Return",       "Ctrl+Return"),
    ("git-sync",        "Sync with the remote",     "Git",    "",                  ""),
    ("git-refresh",     "Refresh source control",   "Git",    "",                  ""),
    ("run-app",         "Run the app",              "Run",    "Ctrl+Shift+B",      "Ctrl+Alt+B"),
    ("stop-app",        "Stop it",                  "Run",    "Shift+F5",          "Shift+F5"),
    ("open-app",        "Open it in the browser",   "Run",    "Ctrl+Shift+L",      "Ctrl+Shift+L"),
    ("run-file",        "Run this file",            "Run",    "F5",                "F5"),
    ("new-terminal",    "New terminal",             "Run",    "Ctrl+grave",        "Ctrl+Shift+grave"),

    ("suggest",         "Suggest here",             "Claude", "Ctrl+space",        "Ctrl+space"),
    ("suggest-mode",    "Change suggestion source", "Claude", "Ctrl+Shift+space",  "Ctrl+Shift+space"),
    ("claude-edit",     "Have Claude change this",  "Claude", "Ctrl+I",            "Ctrl+I"),
    ("ask-claude",      "Point Claude at this file", "Claude", "Ctrl+Alt+A",       "Ctrl+Alt+A"),
    ("restart-claude",  "Restart Claude",           "Claude", "Ctrl+Alt+R",        "Ctrl+Alt+R"),

    ("new-window",      "New window",               "App",    "Ctrl+Shift+M",      "Ctrl+Shift+M"),
    ("preferences",     "Preferences",              "App",    "Ctrl+comma",        "Ctrl+comma"),
    ("keymap",          "Keyboard shortcuts",       "App",    "F1, Ctrl+slash",    "F1"),
    ("about",           "About PrismStudio",        "App",    "",                  ""),
    ("quit",            "Quit",                     "App",    "Ctrl+Q",            "Ctrl+Shift+Q"),
]

GROUPS = ["File", "Edit", "View", "Git", "Run", "Claude", "App"]

# Control characters the standard preset takes over. The terminal panel is not
# the main event here, so only the few that would be genuinely missed are
# handed back, as Ctrl+Shift+<same key>.
LITERAL_GIVEBACK = ["w", "n", "q", "f", "g"]

MOD_NAMES = {
    "ctrl": Gdk.ModifierType.CONTROL_MASK, "control": Gdk.ModifierType.CONTROL_MASK,
    "primary": Gdk.ModifierType.CONTROL_MASK,
    "shift": Gdk.ModifierType.SHIFT_MASK,
    "alt": Gdk.ModifierType.MOD1_MASK, "meta": Gdk.ModifierType.MOD1_MASK,
    "super": Gdk.ModifierType.SUPER_MASK, "cmd": Gdk.ModifierType.SUPER_MASK,
}
RELEVANT = (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
            | Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SUPER_MASK)

KEY_ALIASES = {
    "pageup": "Page_Up", "pgup": "Page_Up", "pagedown": "Page_Down", "pgdn": "Page_Down",
    "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
    "space": "space", "tab": "Tab", "backspace": "BackSpace", "delete": "Delete",
    "del": "Delete", "insert": "Insert", "home": "Home", "end": "End",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "plus": "plus", "minus": "minus", "equal": "equal", "comma": "comma",
    "period": "period", "slash": "slash", "backslash": "backslash",
    "bracketleft": "bracketleft", "bracketright": "bracketright",
    "grave": "grave", "apostrophe": "apostrophe", "semicolon": "semicolon",
}
PRETTY = {"Page_Up": "PageUp", "Page_Down": "PageDown", "Return": "Enter", "BackSpace": "Backspace",
          "bracketleft": "[", "bracketright": "]", "comma": ",", "period": ".", "slash": "/",
          "backslash": "\\", "grave": "`", "plus": "+", "minus": "-", "equal": "=",
          "space": "Space", "semicolon": ";", "apostrophe": "'"}


def _keyval(name):
    """Gdk hands back VoidSymbol, not 0, for a name it does not know."""
    keyval = Gdk.keyval_from_name(name)
    return 0 if keyval in (0, Gdk.KEY_VoidSymbol) else keyval


def parse_accel(text):
    """'Ctrl+Shift+PageUp' -> (keyval_lower, mask). None if it makes no sense."""
    if not text or not text.strip():
        return None
    parts = [p.strip() for p in text.replace("-", "+").split("+") if p.strip()]
    if not parts:
        return None
    # a trailing empty piece means the key itself was '+'
    if text.rstrip().endswith("++"):
        parts.append("plus")
    mask = Gdk.ModifierType(0)
    key = None
    for part in parts:
        low = part.lower()
        if low in MOD_NAMES:
            mask |= MOD_NAMES[low]
        else:
            key = part
    if key is None:
        return None
    name = KEY_ALIASES.get(key.lower(), key)
    if re.fullmatch(r"[fF]\d{1,2}", name):
        name = "F" + name[1:]
    keyval = _keyval(name) or _keyval(name.lower())
    if not keyval:
        return None
    return (Gdk.keyval_to_lower(keyval), mask)


def format_accel(keyval, mask):
    """The inverse, for showing and for saving."""
    bits = []
    if mask & Gdk.ModifierType.CONTROL_MASK:
        bits.append("Ctrl")
    if mask & Gdk.ModifierType.MOD1_MASK:
        bits.append("Alt")
    if mask & Gdk.ModifierType.SHIFT_MASK:
        bits.append("Shift")
    if mask & Gdk.ModifierType.SUPER_MASK:
        bits.append("Super")
    name = Gdk.keyval_name(Gdk.keyval_to_lower(keyval)) or "?"
    bits.append(PRETTY.get(name, name.upper() if len(name) == 1 else name))
    return "+".join(bits)


def pretty(accel_text):
    parsed = parse_accel(accel_text)
    return format_accel(*parsed) if parsed else accel_text


def normalise_event(event):
    """(keyval_lower, mask) for a key event, with the odd cases smoothed out."""
    keyval = event.keyval
    if keyval == Gdk.KEY_ISO_Left_Tab:      # Shift+Tab arrives as its own keysym
        keyval = Gdk.KEY_Tab
    return Gdk.keyval_to_lower(keyval), Gdk.ModifierType(event.state & RELEVANT)


def defaults(preset):
    idx = 3 if preset != "reach" else 4
    return {a[0]: a[idx] for a in ACTIONS}


def load():
    """Return (preset, {action: 'accel, accel'}) merged over the preset."""
    preset, custom = "standard", {}
    try:
        with open(KEYS_CONFIG) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^([A-Za-z0-9_.-]+)\s*=\s*(.*)$", line)
                if not m:
                    continue
                key, value = m.group(1).strip(), m.group(2).strip()
                if key.lower() == "preset":
                    preset = value.lower() if value.lower() in ("standard", "reach") \
                        else "standard"
                else:
                    custom[key] = value
    except OSError:
        pass
    binds = defaults(preset)
    known = {a[0] for a in ACTIONS}
    binds.update({k: v for k, v in custom.items() if k in known})
    return preset, binds


def save(preset, binds):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    base = defaults(preset)
    lines = [
        "# ~/.config/prismstudio/keys.conf — PrismStudio shortcuts.",
        "# Edit here or in Preferences → Keys (which writes this file back).",
        "#",
        "# preset = standard  what an editor user expects: Ctrl+S, Ctrl+P, Ctrl+F …",
        "# preset = reach     the same set moved off the plain control keys",
        "#",
        "# Only the lines that differ from the preset are kept. Several accels per",
        "# action are allowed, comma separated. An empty value unbinds the action.",
        "",
        f"preset = {preset}",
        "",
    ]
    for action, label, group, _a, _t in ACTIONS:
        value = binds.get(action, "")
        if value.strip() != base.get(action, "").strip():
            lines.append(f"{action} = {value}".rstrip())
    with open(KEYS_CONFIG, "w") as fh:
        fh.write("\n".join(lines).rstrip("\n") + "\n")


class Keymap:
    """Compiled bindings: match(event) -> action id."""

    def __init__(self):
        self.reload()

    def reload(self):
        self.preset, self.binds = load()
        self.table = {}
        for action, accels in self.binds.items():
            for accel in [a.strip() for a in accels.split(",") if a.strip()]:
                parsed = parse_accel(accel)
                if parsed:
                    self.table.setdefault(parsed, action)
        self.literals = {}
        if self.preset == "standard":
            for letter in LITERAL_GIVEBACK:
                combo = (Gdk.keyval_from_name(letter),
                         Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
                if combo not in self.table:      # a real binding always wins
                    self.literals[combo] = bytes([ord(letter) - 96])

    def match(self, event):
        return self.table.get(normalise_event(event))

    def literal(self, event):
        """The control byte to send for a 'give it back' combo, if any."""
        return self.literals.get(normalise_event(event))

    def accel_for(self, action):
        return self.binds.get(action, "")

    def conflicts(self):
        """{accel: [action, action]} for anything bound twice."""
        seen, clash = {}, {}
        for action, accels in self.binds.items():
            for accel in [a.strip() for a in accels.split(",") if a.strip()]:
                parsed = parse_accel(accel)
                if not parsed:
                    continue
                if parsed in seen and seen[parsed] != action:
                    clash.setdefault(format_accel(*parsed), [seen[parsed]]).append(action)
                else:
                    seen[parsed] = action
        return clash


def as_markdown(km):
    """The key map as markdown, generated from what is actually bound."""
    labels = {a[0]: (a[1], a[2]) for a in ACTIONS}
    out = []
    for group in GROUPS:
        out.append(f"# {group}")
        out.append("")
        for action, label, grp, _a, _t in ACTIONS:
            if grp != group:
                continue
            accels = [pretty(x.strip()) for x in km.accel_for(action).split(",") if x.strip()]
            if not accels:
                continue
            keys = "  ·  ".join(f"**{a}**" for a in accels)
            out.append(f"- {keys} — {label}")
        out.append("")
    if km.preset == "app" and km.literals:
        # only the combos that really are givebacks — a bound one is not
        gives = ", ".join("**%s**" % format_accel(kv, mask)
                          for kv, mask in sorted(km.literals,
                                                 key=lambda c: Gdk.keyval_name(c[0]) or ""))
        out += [
            "# Getting a control key back",
            "",
            "The app-style preset takes control keys the shell also wants. These send",
            f"the real control character instead: {gives}.",
            "",
            "**Ctrl+C** copies when text is selected and interrupts when it is not, so it",
            "behaves the way you expect either way.",
            "",
            "Prefer the shell to keep everything? Preferences → Keys → *Terminal-style*,",
            "or `preset = reach` in `~/.config/prismstudio/keys.conf`.",
            "",
        ]
    return "\n".join(out)
