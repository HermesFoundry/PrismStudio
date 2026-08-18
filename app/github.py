"""github — signing in, cloning and publishing, through the `gh` CLI.

PrismStudio does not implement OAuth, store a token or talk to the GitHub API
itself. It drives `gh`, which is already how most people's machines are
authenticated, and which keeps its credentials in the system keyring where
they belong. That means: nothing here ever reads, prints or logs a token. The
only fields read out of `gh auth status` are the account name, the host and
the git protocol, all of which are public.

Signing in is a device flow, so it runs in the terminal panel where you can
see the code and what it is asking for, rather than behind a spinner.

Anything that touches the network and can take a while (clone, push, create)
also runs in the terminal panel. Quick questions run on a thread and answer
through GLib.idle_add.
"""
import json
import os
import re
import shutil
import subprocess
import threading

from gi.repository import GLib

TIMEOUT = 20


# --------------------------------------------------------------------------- #
# is the tool even here
# --------------------------------------------------------------------------- #
def path():
    return shutil.which("gh")


def available():
    return path() is not None


def git_available():
    return shutil.which("git") is not None


def _run(args, timeout=TIMEOUT, cwd=None):
    """Run gh and hand back (ok, stdout, stderr). Never raises."""
    if not available():
        return False, "", "the GitHub CLI (gh) is not installed"
    env = dict(os.environ)
    env["GH_PROMPT_DISABLED"] = "1"       # never block waiting on a tty
    env["GH_NO_UPDATE_NOTIFIER"] = "1"
    try:
        done = subprocess.run([path()] + args, capture_output=True, text=True,
                              timeout=timeout, cwd=cwd, env=env)
        return done.returncode == 0, done.stdout.strip(), done.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "gh took longer than %ds" % timeout
    except Exception as exc:
        return False, "", str(exc)


# --------------------------------------------------------------------------- #
# who is signed in
# --------------------------------------------------------------------------- #
class Account:
    """What we know about the signed-in user. Deliberately no token field."""

    def __init__(self, signed_in=False, user="", host="github.com",
                 protocol="", scopes="", reason=""):
        self.signed_in = signed_in
        self.user = user
        self.host = host
        self.protocol = protocol
        self.scopes = scopes
        self.reason = reason           # why not, when signed_in is False

    def __repr__(self):
        return "<Account %s@%s%s>" % (self.user or "-", self.host,
                                      " " + self.protocol if self.protocol else "")

    @property
    def summary(self):
        if not self.signed_in:
            return self.reason or "not signed in"
        where = "%s on %s" % (self.user, self.host)
        return where + (" over %s" % self.protocol if self.protocol else "")


def account():
    """Read `gh auth status`. Only the public fields, never --show-token."""
    if not available():
        return Account(reason="the GitHub CLI (gh) is not installed")
    ok, out, err = _run(["auth", "status"])
    text = out + "\n" + err
    if not ok:
        return Account(reason="not signed in")

    user = host = protocol = scopes = ""
    for line in text.splitlines():
        line = line.strip()
        match = re.search(r"Logged in to (\S+) account (\S+)", line)
        if match:
            host, user = match.group(1), match.group(2)
            continue
        match = re.match(r"^-?\s*Git operations protocol:\s*(\S+)", line)
        if match:
            protocol = match.group(1)
            continue
        match = re.match(r"^-?\s*Token scopes:\s*(.+)$", line)
        if match:
            scopes = match.group(1).strip()
    if not user:
        # older phrasings put the account somewhere else on the line
        match = re.search(r"Logged in to \S+ as (\S+)", text)
        if match:
            user = match.group(1)
    if not user:
        return Account(reason="not signed in")
    return Account(True, user, host or "github.com", protocol, scopes)


def login_argv(protocol="ssh"):
    """The command to run in a terminal. Device flow, so it prints a code."""
    return "%s auth login --hostname github.com --git-protocol %s --web" % (
        path() or "gh", protocol)


def logout_argv():
    return "%s auth logout --hostname github.com" % (path() or "gh")


def setup_git_argv():
    """Teach git to use gh for HTTPS, the way `gh auth setup-git` does."""
    return "%s auth setup-git" % (path() or "gh")


# --------------------------------------------------------------------------- #
# repositories
# --------------------------------------------------------------------------- #
class Remote:
    def __init__(self, data):
        self.full_name = data.get("nameWithOwner", "")
        self.name = self.full_name.split("/")[-1]
        self.owner = self.full_name.split("/")[0] if "/" in self.full_name else ""
        self.description = (data.get("description") or "").strip()
        self.url = data.get("url", "")
        self.ssh_url = data.get("sshUrl", "")
        self.private = bool(data.get("isPrivate"))
        self.updated = (data.get("pushedAt") or data.get("updatedAt") or "")[:10]

    def clone_url(self, protocol="ssh"):
        if protocol == "ssh" and self.ssh_url:
            return self.ssh_url
        return self.url or self.ssh_url


FIELDS = "nameWithOwner,description,url,sshUrl,isPrivate,updatedAt,pushedAt"


def repos(limit=200, on_done=None):
    """Your repositories, newest push first. Threaded when given a callback."""
    def work():
        ok, out, err = _run(["repo", "list", "--limit", str(limit),
                             "--json", FIELDS], timeout=40)
        items, problem = [], ""
        if ok:
            try:
                items = [Remote(entry) for entry in json.loads(out or "[]")]
                items.sort(key=lambda r: r.updated, reverse=True)
            except ValueError:
                problem = "gh returned something that was not JSON"
        else:
            problem = err or "could not list your repositories"
        if on_done:
            GLib.idle_add(on_done, items, problem)
        return items, problem

    if on_done is None:
        return work()
    threading.Thread(target=work, daemon=True).start()
    return None


def clone_argv(url, destination):
    """git, not gh: cloning is a git operation and gh only wraps it."""
    return "git clone %s %s" % (GLib.shell_quote(url),
                                GLib.shell_quote(destination))


def create_argv(name, private=True, description="", source=".", push=True):
    """Publish a folder that is already a git repository."""
    bits = ["%s repo create %s" % (path() or "gh", GLib.shell_quote(name)),
            "--private" if private else "--public",
            "--source %s" % GLib.shell_quote(source),
            "--remote origin"]
    if description:
        bits.append("--description %s" % GLib.shell_quote(description))
    if push:
        bits.append("--push")
    return " ".join(bits)


# --------------------------------------------------------------------------- #
# ssh keys
# --------------------------------------------------------------------------- #
def ssh_keys():
    """Public keys on the account. Titles and fingerprints, nothing secret."""
    ok, out, _ = _run(["ssh-key", "list"])
    if not ok:
        return []
    keys = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            keys.append((parts[0].strip(), parts[-1].strip()))
    return keys


def local_ssh_keys():
    """Public key files in ~/.ssh, so you can pick one to upload."""
    folder = os.path.expanduser("~/.ssh")
    found = []
    if not os.path.isdir(folder):
        return found
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".pub"):
            continue
        full = os.path.join(folder, name)
        try:
            with open(full) as handle:
                first = handle.readline().strip()
        except OSError:
            continue
        # "<type> <base64> <comment>" — the comment is the only friendly part
        bits = first.split()
        comment = bits[2] if len(bits) > 2 else ""
        found.append((full, name[:-4], comment))
    return found


def add_key_argv(public_key_path, title):
    return "%s ssh-key add %s --title %s" % (
        path() or "gh", GLib.shell_quote(public_key_path), GLib.shell_quote(title))


def generate_key_argv(path_out, comment):
    return "ssh-keygen -t ed25519 -f %s -C %s -N ''" % (
        GLib.shell_quote(path_out), GLib.shell_quote(comment))


def test_ssh():
    """Does github.com accept a key? Returns (ok, message)."""
    try:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
             "-o", "ConnectTimeout=8", "-T", "git@github.com"],
            capture_output=True, text=True, timeout=20)
    except Exception as exc:
        return False, str(exc)
    text = (done.stdout + done.stderr).strip()
    # GitHub always exits 1 on -T; the greeting is the thing that matters.
    match = re.search(r"Hi ([^!]+)! You've successfully authenticated", text)
    if match:
        return True, "GitHub knows you as %s" % match.group(1)
    if "Permission denied" in text:
        return False, "GitHub refused the key"
    return False, text.splitlines()[0] if text else "no answer from github.com"
