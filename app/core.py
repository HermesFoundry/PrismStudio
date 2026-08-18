"""core — where PrismStudio keeps its settings, its skins and its colours.

Everything user-facing that is not a widget lives here: the config file, the
skin files, the colour arithmetic the stylesheet is built from, and the small
amount of state that has to survive a restart.

Skins are the same shell-variable format Iris Terminal uses, so a skin written
for one works in the other.
"""
import os
import re
import subprocess

HOME = os.path.expanduser("~")
APP_NAME = "PrismStudio"
APP_ID = "foundry.hermes.PrismStudio"
VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME",
                                         os.path.join(HOME, ".config")), "prismstudio")
CONFIG = os.path.join(CONFIG_DIR, "settings.conf")
KEYS = os.path.join(CONFIG_DIR, "keys.conf")
EXTENSIONS_DIR = os.path.join(CONFIG_DIR, "extensions")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME",
                                    os.path.join(HOME, ".cache")), "prismstudio")
STATE = os.path.join(CACHE, "state.json")
SOCKET_PATH = os.path.join(CACHE, "prism.sock")
THEME_DIRS = [os.path.join(CONFIG_DIR, "themes"), os.path.join(ROOT, "themes")]

DEFAULTS = {
    # look
    "THEME": "olympus",
    "FONT": "Ubuntu Sans Mono 11",
    "UI_FONT": "",              # blank means whatever the desktop uses
    "TAB_SIZE": "4",
    "SPACES": "1",              # insert spaces instead of tabs
    "WRAP": "0",
    "LINE_NUMBERS": "1",
    "CURRENT_LINE": "1",
    "MINIMAP": "0",             # not built yet; here so the setting is stable
    "RIGHT_MARGIN": "0",        # column to draw a guide at, 0 for none

    # layout
    "SIDEBAR": "explorer",      # explorer | search | git | run | extensions | off
    "SIDEBAR_WIDTH": "240",
    "PANEL": "0",               # bottom panel open at startup
    "PANEL_HEIGHT": "220",
    "ASSISTANT": "1",           # the Claude pane
    "ASSISTANT_WIDTH": "420",

    # editing
    "AUTOSAVE": "0",
    "FLUSH_FOR_CLAUDE": "1",
    "TRIM_ON_SAVE": "0",
    "RESTORE_SESSION": "1",

    # the assistant
    "CLAUDE": "1",              # master switch: 0 removes every Claude feature
    "SUGGEST": "local",         # off | local | claude | copilot
    "SUGGEST_MODEL": "haiku",
    "SUGGEST_DELAY": "1200",
    "CLAUDE_CMD": "claude",
    "COPILOT_CMD": "copilot-language-server",
    "SELECTION_BAR": "1",       # the little popup when you highlight something
    "SHELL": os.environ.get("SHELL", "/bin/bash"),

    # updates
    "UPDATE_CHECK": "1",        # look for a new version when the app starts
    "UPDATE_URL": "https://hermesarcade.co.za/prismstudio/updates.json",
    "UPDATE_INTERVAL": "20",    # hours between checks

    # the rest
    "LSP": "1",                 # use language servers found on your PATH
    "EXTENSIONS": "1",
    "CONFIRM_CLOSE": "1",
    "SCROLLBACK": "50000",
}


# --------------------------------------------------------------------------- #
# reading shell-style config and skin files
# --------------------------------------------------------------------------- #
def _split_assignments(line):
    """Split `A=1; B="x; y"` on semicolons that are outside quotes."""
    parts, buf, quote = [], "", None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
            buf += ch
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ";":
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return parts


def _value(raw):
    """A shell-ish right-hand side: honour quotes, drop a trailing ' # comment'."""
    lead_ws = raw[:1].isspace()
    s = raw.strip()
    if s[:1] in ('"', "'"):
        end = s.find(s[0], 1)
        return s[1:end] if end > 0 else s[1:]
    if s.startswith("#") and lead_ws:
        return ""
    quote = None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and i > 0 and s[i - 1].isspace():
            return s[:i].strip()
    return s


def shvars(path):
    """KEY=value pairs out of a shell-ish file, without running it."""
    out = {}
    try:
        with open(path) as fh:
            body = fh.read()
    except OSError:
        return out
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for piece in _split_assignments(line):
            match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", piece)
            if match:
                out[match.group(1)] = _value(match.group(2))
    return out


def load_settings():
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in shvars(CONFIG).items() if v != ""})
    return cfg


def save_settings(changed):
    """Write settings back in place, keeping comments and order."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    lines = []
    if os.path.exists(CONFIG):
        with open(CONFIG) as fh:
            lines = fh.read().split("\n")
    for key, value in changed.items():
        pattern = re.compile(rf"^(\s*){re.escape(key)}=(.*)$")
        for i, line in enumerate(lines):
            match = pattern.match(line)
            if match:
                comment = re.search(r"\s+#.*$", match.group(2))
                new = f"{match.group(1)}{key}={value}"
                if comment:
                    new += " " * max(1, 26 - len(new)) + comment.group(0).strip()
                lines[i] = new
                break
        else:
            lines.append(f"{key}={value}")
    with open(CONFIG, "w") as fh:
        fh.write("\n".join(lines).rstrip("\n") + "\n")


# --------------------------------------------------------------------------- #
# skins
# --------------------------------------------------------------------------- #
FALLBACK = {
    "NAME": "Olympus", "BLURB": "the default",
    "BG": "#0b1017", "PANEL": "#16202c", "FG": "#cbd6e3", "DIM": "#6b7a8d",
    "ACCENT": "#4fb3ff", "ACCENT2": "#f0a848", "URGENT": "#ff5f6d",
    "OK": "#3ddc97", "BORDER": "#243447", "ACTIVE_FG": "#08111a",
}
ANSI_FALLBACK = ["#1b232e", "#ff5f6d", "#3ddc97", "#f0a848", "#4fb3ff",
                 "#b48ead", "#5fd7d7", "#cbd6e3", "#3b4a5e", "#ff7b86",
                 "#63e6ad", "#f5bd6d", "#7cc6ff", "#c9a6c2", "#87e5e5", "#e8eef6"]


def theme_names():
    found = []
    for folder in THEME_DIRS:
        try:
            for name in sorted(os.listdir(folder)):
                if name.endswith(".sh") and name[:-3] not in found:
                    found.append(name[:-3])
        except OSError:
            continue
    return found or ["olympus"]


def theme_path(name):
    for folder in THEME_DIRS:
        candidate = os.path.join(folder, "%s.sh" % name)
        if os.path.exists(candidate):
            return candidate
    return None


def load_theme(name):
    """A skin as a plain dict, with its 16 terminal colours under `_ansi`."""
    theme = dict(FALLBACK)
    path = theme_path(name)
    if path:
        found = shvars(path)
        for key in FALLBACK:
            if found.get(key):
                theme[key] = found[key]
        ansi = found.get("ANSI16", "")
        colours = [c for c in re.split(r"[\s,]+", ansi) if c.startswith("#")]
        theme["_ansi"] = (colours + ANSI_FALLBACK[len(colours):]) if colours \
            else list(ANSI_FALLBACK)
    else:
        theme["_ansi"] = list(ANSI_FALLBACK)
    theme["_id"] = name
    theme["_light"] = luminance(theme["BG"]) > 0.5
    return theme


# --------------------------------------------------------------------------- #
# colour arithmetic
# --------------------------------------------------------------------------- #
def rgb(colour):
    colour = (colour or "#000000").lstrip("#")
    if len(colour) == 3:
        colour = "".join(c * 2 for c in colour)
    try:
        return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


def rgba(colour, alpha):
    r, g, b = rgb(colour)
    return "rgba(%d,%d,%d,%.3f)" % (r, g, b, alpha)


def mix(base, other, amount):
    """`amount` of `other` blended into `base`, as #rrggbb."""
    a, b = rgb(base), rgb(other)
    return "#%02x%02x%02x" % tuple(
        int(round(a[i] + (b[i] - a[i]) * amount)) for i in range(3))


def luminance(colour):
    r, g, b = rgb(colour)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def readable_on(background):
    return "#0a0f16" if luminance(background) > 0.55 else "#f2f6fb"


# --------------------------------------------------------------------------- #
# small helpers the whole app wants
# --------------------------------------------------------------------------- #
def short_path(path, root=None):
    """A path a person can read: relative to the workspace, or ~-shortened."""
    if not path:
        return ""
    if root:
        try:
            relative = os.path.relpath(path, root)
            if not relative.startswith(".."):
                return relative
        except ValueError:
            pass
    if path.startswith(HOME):
        return "~" + path[len(HOME):]
    return path


def git_branch(folder):
    """The current branch, or empty if this is not a repository."""
    if not folder or not os.path.isdir(folder):
        return ""
    try:
        done = subprocess.run(["git", "-C", folder, "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""
