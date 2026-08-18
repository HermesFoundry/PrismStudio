"""gitrepo — everything the source control panel needs, spoken to the git CLI.

There is no libgit2 here on purpose. git itself is the reference implementation
of git, it is already installed wherever anyone would use this, and shelling out
means the panel can never disagree with what the command line would tell you.

Reads are quick and synchronous with a short timeout. Anything that touches the
network — fetch, pull, push — goes on a thread and calls back on the main loop,
because those genuinely can take a minute and the window must keep moving.
"""
import os
import subprocess
import threading

from gi.repository import GLib

TIMEOUT = 12
STATUS_WORDS = {
    "M": "modified", "A": "added", "D": "deleted", "R": "renamed",
    "C": "copied", "U": "conflicted", "?": "untracked", "!": "ignored",
    "T": "type changed",
}


class Change:
    """One path git has something to say about."""

    def __init__(self, path, index, worktree, original=None):
        self.path = path
        self.index = index          # staged side, ' ' if nothing staged
        self.worktree = worktree    # unstaged side
        self.original = original    # the old name, for renames

    @property
    def untracked(self):
        return self.index == "?" or self.worktree == "?"

    @property
    def conflicted(self):
        return "U" in (self.index, self.worktree)

    @property
    def staged(self):
        return self.index not in (" ", "?") and not self.conflicted

    @property
    def unstaged(self):
        return self.worktree not in (" ",) and not self.conflicted

    @property
    def letter(self):
        if self.conflicted:
            return "U"
        if self.untracked:
            return "?"
        return (self.index if self.index != " " else self.worktree)

    @property
    def word(self):
        return STATUS_WORDS.get(self.letter, self.letter)

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def folder(self):
        return os.path.dirname(self.path)


class Commit:
    def __init__(self, sha, short, subject, author, when, refs=""):
        self.sha = sha
        self.short = short
        self.subject = subject
        self.author = author
        self.when = when
        self.refs = refs


class Repo:
    """A git working tree. Every method is safe to call on a folder that is not one."""

    def __init__(self, root):
        self.root = root
        self._top = None

    # -- running git -----------------------------------------------------------
    def _run(self, args, timeout=TIMEOUT, stdin=None):
        """(ok, stdout, stderr). Never raises."""
        if not self.root or not os.path.isdir(self.root):
            return False, "", "no folder open"
        try:
            done = subprocess.run(["git", "-C", self.root] + args,
                                  capture_output=True, text=True,
                                  errors="replace", timeout=timeout,
                                  input=stdin)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, "", str(exc)
        return done.returncode == 0, done.stdout, done.stderr.strip()

    # -- what and where --------------------------------------------------------
    def is_repo(self):
        ok, out, _ = self._run(["rev-parse", "--is-inside-work-tree"], timeout=4)
        return ok and out.strip() == "true"

    def top_level(self):
        if self._top is None:
            ok, out, _ = self._run(["rev-parse", "--show-toplevel"], timeout=4)
            self._top = out.strip() if ok else self.root
        return self._top

    def branch(self):
        ok, out, _ = self._run(["rev-parse", "--abbrev-ref", "HEAD"], timeout=4)
        name = out.strip() if ok else ""
        if name == "HEAD":                      # detached
            ok, out, _ = self._run(["rev-parse", "--short", "HEAD"], timeout=4)
            return "detached at %s" % out.strip() if ok else "detached"
        return name

    def upstream(self):
        ok, out, _ = self._run(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], timeout=4)
        return out.strip() if ok else ""

    def ahead_behind(self):
        """(ahead, behind) against the upstream, or (0, 0) if there is none."""
        if not self.upstream():
            return 0, 0
        ok, out, _ = self._run(["rev-list", "--left-right", "--count", "@{u}...HEAD"],
                               timeout=6)
        if not ok:
            return 0, 0
        try:
            behind, ahead = out.split()
            return int(ahead), int(behind)
        except ValueError:
            return 0, 0

    def branches(self):
        ok, out, _ = self._run(["branch", "--format=%(refname:short)"], timeout=6)
        return [b.strip() for b in out.split("\n") if b.strip()] if ok else []

    def remotes(self):
        ok, out, _ = self._run(["remote", "-v"], timeout=4)
        found = {}
        for line in out.split("\n"):
            bits = line.split()
            if len(bits) >= 2:
                found.setdefault(bits[0], bits[1])
        return found

    # -- what has changed ------------------------------------------------------
    def status(self):
        """Every path with something to report, parsed from porcelain v1 -z."""
        ok, out, _ = self._run(["status", "--porcelain=v1", "-z", "--untracked-files=all"])
        if not ok:
            return []
        changes, parts, i = [], out.split("\0"), 0
        while i < len(parts):
            entry = parts[i]
            i += 1
            if len(entry) < 4:
                continue
            index, worktree, path = entry[0], entry[1], entry[3:]
            original = None
            if index in ("R", "C"):
                # a rename spends a second NUL-separated field on the old name
                original = parts[i] if i < len(parts) else None
                i += 1
            changes.append(Change(path, index, worktree, original))
        changes.sort(key=lambda c: (c.folder, c.name))
        return changes

    def diff(self, path, staged=False, context=3):
        args = ["diff", "--no-color", "-U%d" % context]
        if staged:
            args.append("--cached")
        args += ["--", path]
        ok, out, err = self._run(args, timeout=20)
        if ok and out.strip():
            return out
        if not staged and not out.strip():
            # an untracked file has no diff, so show it as one big addition
            full = os.path.join(self.top_level(), path)
            if os.path.isfile(full):
                try:
                    with open(full, errors="replace") as fh:
                        body = fh.read(200000)
                except OSError as exc:
                    return "cannot read %s: %s" % (path, exc)
                head = "+++ %s (untracked)\n" % path
                return head + "".join("+" + line + "\n" for line in body.split("\n"))
        return out if ok else (err or "no diff")

    def show(self, sha, path=None):
        args = ["show", "--no-color", "--stat", "--patch", sha]
        if path:
            args += ["--", path]
        ok, out, err = self._run(args, timeout=25)
        return out if ok else (err or "cannot show %s" % sha)

    def log(self, count=60, path=None):
        fmt = "%H\x1f%h\x1f%s\x1f%an\x1f%ar\x1f%D"
        args = ["log", "-n", str(count), "--format=" + fmt]
        if path:
            args += ["--", path]
        ok, out, _ = self._run(args, timeout=15)
        if not ok:
            return []
        found = []
        for line in out.split("\n"):
            if not line.strip():
                continue
            bits = line.split("\x1f")
            if len(bits) >= 5:
                found.append(Commit(bits[0], bits[1], bits[2], bits[3], bits[4],
                                    bits[5] if len(bits) > 5 else ""))
        return found

    # -- changing things -------------------------------------------------------
    def stage(self, paths):
        return self._run(["add", "--"] + list(paths), timeout=25)

    def stage_all(self):
        return self._run(["add", "-A"], timeout=30)

    def unstage(self, paths):
        return self._run(["restore", "--staged", "--"] + list(paths), timeout=25)

    def discard(self, paths):
        """Throw away unstaged edits. Untracked files are deleted outright."""
        tracked, untracked = [], []
        by_path = {c.path: c for c in self.status()}
        for path in paths:
            (untracked if by_path.get(path) and by_path[path].untracked
             else tracked).append(path)
        if tracked:
            ok, _, err = self._run(["restore", "--"] + tracked, timeout=25)
            if not ok:
                return False, "", err
        for path in untracked:
            try:
                os.remove(os.path.join(self.top_level(), path))
            except OSError as exc:
                return False, "", str(exc)
        return True, "", ""

    def commit(self, message, amend=False):
        if not message.strip() and not amend:
            return False, "", "write a commit message first"
        args = ["commit", "-F", "-"]
        if amend:
            args.append("--amend")
        return self._run(args, timeout=30, stdin=message)

    def checkout(self, branch):
        return self._run(["checkout", branch], timeout=30)

    def create_branch(self, name):
        return self._run(["checkout", "-b", name], timeout=20)

    # -- the network, off the main loop ---------------------------------------
    def remote_op(self, what, done, extra=None):
        """fetch / pull / push, called back with (ok, output) on the main loop."""
        args = {"fetch": ["fetch", "--prune"],
                "pull": ["pull", "--ff-only"],
                "push": ["push"]}.get(what)
        if args is None:
            done(False, "unknown operation %s" % what)
            return
        if extra:
            args = args + list(extra)

        def work():
            ok, out, err = self._run(args, timeout=180)
            text = (out + "\n" + err).strip() or ("%s finished" % what)
            GLib.idle_add(lambda: (done(ok, text), False)[1])

        threading.Thread(target=work, daemon=True).start()

    def init(self):
        return self._run(["init"], timeout=15)
