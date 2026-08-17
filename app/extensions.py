"""extensions — small Python add-ons that PrismStudio loads at startup.

An extension is one file (`thing.py`) or one folder (`thing/__init__.py`) in
~/.config/prismstudio/extensions, and it needs exactly one thing: a
`register(prism)` function. Whatever it hangs off that object shows up in the
command palette, in the
suggestion engine, or on the save and open hooks.

They are plain Python running in the same process as the editor, so an
extension can do anything you can do. Install ones you have read.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import traceback

import core

FOLDER = os.path.join(core.CONFIG_DIR, "extensions")
DISABLED = os.path.join(FOLDER, "disabled.list")


class Command:
    def __init__(self, ident, label, run, source="prism", keys=""):
        self.id = ident
        self.label = label
        self.run = run
        self.source = source
        self.keys = keys


class PrismAPI:
    """What an extension is handed. Everything it can reach goes through here."""

    def __init__(self, registry, name):
        self._registry = registry
        self._name = name

    # -- registering -------------------------------------------------------
    def command(self, ident, label, run, keys=""):
        """Add an entry to the command palette."""
        self._registry.commands.append(
            Command("%s.%s" % (self._name, ident), label, run, self._name, keys))

    def completions(self, fn):
        """Offer inline suggestions. fn(before, after, language) -> str | None."""
        self._registry.completers.append((self._name, fn))

    def on_save(self, fn):
        """fn(path) after a file is written."""
        self._registry.on_save.append((self._name, fn))

    def on_open(self, fn):
        """fn(path) after a file is opened in the editor."""
        self._registry.on_open.append((self._name, fn))

    # -- reaching the app --------------------------------------------------
    @property
    def window(self):
        return self._registry.window

    @property
    def editor(self):
        """The editor in the tab you are looking at, or None."""
        win = self._registry.window
        page = win.current() if win else None
        return getattr(page, "editor", None)

    @property
    def config(self):
        return dict(self._registry.window.cfg) if self._registry.window else {}

    def status(self, text):
        editor = self.editor
        if editor:
            editor.status_message(text)
        else:
            self._registry.log(self._name, text)

    def log(self, text):
        self._registry.log(self._name, text)


class Extension:
    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.module = None
        self.error = None
        self.enabled = True

    @property
    def blurb(self):
        if self.module is None:
            return "not loaded"
        doc = (getattr(self.module, "BLURB", None)
               or (self.module.__doc__ or "").strip().split("\n")[0])
        return doc or "no description"

    @property
    def version(self):
        return getattr(self.module, "VERSION", "") if self.module else ""


class Registry:
    """Finds, loads and holds the extensions."""

    def __init__(self, window=None):
        self.window = window
        self.extensions = []
        self.commands = []
        self.completers = []
        self.on_save = []
        self.on_open = []
        self.messages = []

    # -- disk --------------------------------------------------------------
    @staticmethod
    def ensure_folder():
        os.makedirs(FOLDER, exist_ok=True)
        return FOLDER

    @staticmethod
    def disabled_names():
        try:
            with open(DISABLED) as fh:
                return {line.strip() for line in fh if line.strip()}
        except OSError:
            return set()

    @staticmethod
    def set_disabled(names):
        Registry.ensure_folder()
        with open(DISABLED, "w") as fh:
            fh.write("\n".join(sorted(names)) + "\n")

    @staticmethod
    def found():
        """Every extension on disk, enabled or not."""
        Registry.ensure_folder()
        out = []
        try:
            entries = sorted(os.listdir(FOLDER))
        except OSError:
            return out
        for entry in entries:
            full = os.path.join(FOLDER, entry)
            if entry.startswith((".", "_")) or entry == os.path.basename(DISABLED):
                continue
            if entry.endswith(".py") and os.path.isfile(full):
                out.append(Extension(entry[:-3], full))
            elif os.path.isdir(full) and os.path.exists(os.path.join(full, "__init__.py")):
                out.append(Extension(entry, os.path.join(full, "__init__.py")))
        return out

    # -- loading -----------------------------------------------------------
    def log(self, who, text):
        self.messages.append("%s: %s" % (who, text))
        del self.messages[:-200]

    def load_all(self):
        """Import everything enabled. A broken one is reported, not fatal."""
        self.extensions, self.commands = [], []
        self.completers, self.on_save, self.on_open = [], [], []
        off = self.disabled_names()
        for ext in self.found():
            ext.enabled = ext.name not in off
            self.extensions.append(ext)
            if not ext.enabled:
                continue
            self.load(ext)
        return self.extensions

    def load(self, ext):
        try:
            spec = importlib.util.spec_from_file_location("prism_ext_%s" % ext.name,
                                                          ext.path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if not callable(register):
                raise AttributeError("no register(prism) function")
            register(PrismAPI(self, ext.name))
            ext.module, ext.error = module, None
        except Exception:
            ext.error = traceback.format_exc(limit=3).strip().split("\n")[-1]
            self.log(ext.name, "failed to load: %s" % ext.error)
        return ext

    # -- what the app asks for --------------------------------------------
    def completer_functions(self):
        return [fn for _name, fn in self.completers]

    def fire(self, hook, path):
        for name, fn in getattr(self, hook, []):
            try:
                fn(path)
            except Exception as exc:
                self.log(name, "%s failed: %s" % (hook, exc))

    def command(self, ident):
        for cmd in self.commands:
            if cmd.id == ident:
                return cmd
        return None

    # -- installing --------------------------------------------------------
    @staticmethod
    def install_path(source):
        """Copy a .py file or a folder in. Returns (ok, message)."""
        Registry.ensure_folder()
        source = os.path.abspath(os.path.expanduser(source))
        if not os.path.exists(source):
            return False, "no such file or folder"
        name = os.path.basename(source.rstrip(os.sep))
        target = os.path.join(FOLDER, name)
        if os.path.exists(target):
            return False, "%s is already installed" % name
        try:
            if os.path.isdir(source):
                if not os.path.exists(os.path.join(source, "__init__.py")):
                    return False, "a folder extension needs an __init__.py"
                shutil.copytree(source, target)
            else:
                if not source.endswith(".py"):
                    return False, "expected a .py file"
                shutil.copy2(source, target)
        except OSError as exc:
            return False, str(exc)
        return True, "installed %s" % name

    @staticmethod
    def install_git(url):
        """Clone a repository in. Returns (ok, message)."""
        Registry.ensure_folder()
        if not shutil.which("git"):
            return False, "git is not installed"
        name = os.path.basename(url.rstrip("/")).removesuffix(".git")
        if not name:
            return False, "could not work out a name from that URL"
        target = os.path.join(FOLDER, name)
        if os.path.exists(target):
            return False, "%s is already installed" % name
        try:
            done = subprocess.run(["git", "clone", "--depth", "1", url, target],
                                  capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        if done.returncode != 0:
            return False, (done.stderr or "git clone failed").strip().split("\n")[-1]
        if not os.path.exists(os.path.join(target, "__init__.py")):
            shutil.rmtree(target, ignore_errors=True)
            return False, "that repository has no __init__.py at its root"
        return True, "installed %s" % name

    @staticmethod
    def remove(name):
        target = os.path.join(FOLDER, name)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        elif os.path.exists(target + ".py"):
            os.remove(target + ".py")
        else:
            return False, "not installed"
        return True, "removed %s" % name
