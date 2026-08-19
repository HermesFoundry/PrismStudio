"""workspace — the folder you have open, and what to reopen next time.

A workspace is just a folder. What is worth remembering about it is which files
you had open, where the cursor was in each, and how the window was arranged, so
that closing and reopening puts you back where you were rather than at a blank
screen.

State lives in one small JSON file under the cache directory. It is a
convenience, never a source of truth: if it is missing or corrupt the app opens
empty and says nothing.
"""
import json
import os
import time

import core

MAX_RECENT = 12
MAX_REMEMBERED_FILES = 24
MAX_INDEXED_FILES = 20000       # a fuzzy list this long still filters instantly


def _load():
    try:
        with open(core.STATE) as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state):
    try:
        os.makedirs(core.CACHE, exist_ok=True)
        with open(core.STATE, "w") as fh:
            json.dump(state, fh, indent=1)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# recent folders
# --------------------------------------------------------------------------- #
def recent_folders():
    """Most recent first, dropping any that have since been deleted."""
    state = _load()
    found = [f for f in state.get("recent", []) if isinstance(f, str) and os.path.isdir(f)]
    return found[:MAX_RECENT]


def remember_folder(path):
    if not path or not os.path.isdir(path):
        return
    path = os.path.abspath(path)
    state = _load()
    recent = [f for f in state.get("recent", []) if f != path]
    recent.insert(0, path)
    state["recent"] = recent[:MAX_RECENT]
    _save(state)


def forget_folder(path):
    state = _load()
    state["recent"] = [f for f in state.get("recent", []) if f != path]
    _save(state)


# --------------------------------------------------------------------------- #
# per-workspace session
# --------------------------------------------------------------------------- #
def _key(root):
    return os.path.abspath(root) if root else "__no_folder__"


def save_session(root, files, active=None, layout=None):
    """`files` is [{path, line}] for the tabs that had somewhere to be saved."""
    state = _load()
    sessions = state.setdefault("sessions", {})
    sessions[_key(root)] = {
        "files": files[:MAX_REMEMBERED_FILES],
        "active": active,
        "layout": layout or {},
        "at": int(time.time()),
    }
    # do not let this grow without bound
    if len(sessions) > 40:
        oldest = sorted(sessions.items(), key=lambda kv: kv[1].get("at", 0))
        for name, _ in oldest[:len(sessions) - 40]:
            sessions.pop(name, None)
    state["last"] = _key(root) if root else None
    _save(state)


def load_session(root):
    session = _load().get("sessions", {}).get(_key(root), {})
    files = [f for f in session.get("files", [])
             if isinstance(f, dict) and os.path.isfile(f.get("path", ""))]
    return {"files": files, "active": session.get("active"),
            "layout": session.get("layout", {})}


def last_folder():
    """The folder open when the app last closed, if it still exists."""
    state = _load()
    last = state.get("last")
    if last and last != "__no_folder__" and os.path.isdir(last):
        return last
    return None


def clear_session(root):
    state = _load()
    state.get("sessions", {}).pop(_key(root), None)
    _save(state)


# --------------------------------------------------------------------------- #
# describing a folder
# --------------------------------------------------------------------------- #
def name_for(root):
    """What to call this workspace in the title bar."""
    if not root:
        return "no folder"
    return os.path.basename(os.path.abspath(root)) or root


IGNORE = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
          ".mypy_cache", ".pytest_cache", ".next", ".nuxt", "dist", "build",
          ".idea", ".vscode", "target", ".tox", ".cache", ".gradle", "vendor"}


def walk_files(root, limit=MAX_INDEXED_FILES):
    """Every interesting file under a folder, as paths relative to it.

    For the go-to-file box. It skips whatever the tree skips, so a node_modules
    or a .git never lands in the list, and it stops at a limit rather than
    walking a home directory somebody opened by mistake for a minute.
    """
    if not root or not os.path.isdir(root):
        return []
    found, stack = [], [root]
    while stack and len(found) < limit:
        here = stack.pop()
        try:
            entries = sorted(os.scandir(here), key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            if not interesting(entry.name):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    found.append(os.path.relpath(entry.path, root))
                    if len(found) >= limit:
                        break
            except OSError:
                continue
    found.sort(key=str.lower)
    return found


def interesting(name, path=None):
    """Should this entry show in the tree and be searched?"""
    if name in IGNORE:
        return False
    if name.startswith(".") and name not in (".env.example", ".gitignore"):
        return False
    return True
