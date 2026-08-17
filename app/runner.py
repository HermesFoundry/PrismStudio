"""runner — run the file you are editing, with a choice of how much isolation.

The modes offered are the ones that actually work on this machine, probed at
the moment you open the menu. Where a mode is unavailable it says why, and
where possible what would make it work, rather than pretending.
"""
import os
import shlex
import shutil
import subprocess
import time

HOME = os.path.expanduser("~")

# how to run a file, by extension
RUNNERS = {
    ".py": ("Python", "python3 {file}"),
    ".sh": ("bash", "bash {file}"),
    ".bash": ("bash", "bash {file}"),
    ".js": ("node", "node {file}"),
    ".mjs": ("node", "node {file}"),
    ".cjs": ("node", "node {file}"),
    ".ts": ("node", "node {file}"),
    ".rb": ("ruby", "ruby {file}"),
    ".pl": ("perl", "perl {file}"),
    ".php": ("php", "php {file}"),
    ".lua": ("lua", "lua {file}"),
    ".go": ("go", "go run {file}"),
    ".rs": ("rust", "rustc {file} -o {tmp} && {tmp}"),
    ".c": ("gcc", "gcc {file} -o {tmp} && {tmp}"),
    ".cpp": ("g++", "g++ {file} -o {tmp} && {tmp}"),
    ".java": ("java", "java {file}"),
}
BY_NAME = {
    "Makefile": ("make", "make"),
    "makefile": ("make", "make"),
    "package.json": ("npm", "npm start"),
}


def command_for(path):
    """(label, shell command) for a file, or (None, why not)."""
    if not path:
        return None, "open a file first"
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    entry = BY_NAME.get(name) or RUNNERS.get(ext)
    if entry is None:
        if os.access(path, os.X_OK):
            return "executable", shlex.quote(path)
        return None, "no way to run %s files" % (ext or "these")
    label, template = entry
    tool = template.split()[0]
    if not shutil.which(tool):
        return None, "%s is not installed" % tool
    tmp = os.path.join("/tmp", "prism-run-%s" % os.path.splitext(name)[0])
    return label, template.format(file=shlex.quote(path), tmp=shlex.quote(tmp))


# --------------------------------------------------------------------------- #
# what isolation is available, checked rather than assumed
# --------------------------------------------------------------------------- #
_cache = {"at": 0.0, "modes": None}
CACHE_SECONDS = 30


def _probe(argv, timeout=6):
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _bwrap_ok():
    if not shutil.which("bwrap"):
        return False, "bubblewrap is not installed"
    if not _probe(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", "/tmp", "/bin/true"]):
        return False, ("the kernel refuses unprivileged namespaces here. "
                       "sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0")
    return True, ""


def _bwrap_net_ok():
    return _probe(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", "/tmp",
                   "--unshare-net", "/bin/true"])


def _docker_ok():
    if not shutil.which("docker"):
        return False, "docker is not installed"
    if not _probe(["docker", "info"], timeout=8):
        return False, "docker is installed but not running. Start Docker Desktop"
    return True, ""


def _systemd_ok():
    if not shutil.which("systemd-run"):
        return False, "systemd-run is not available"
    if not _probe(["systemd-run", "--user", "--scope", "--quiet", "/bin/true"]):
        return False, "the user systemd manager will not take a scope here"
    return True, ""


IMAGES = {
    "Python": "python:3-slim", "node": "node:slim", "bash": "debian:stable-slim",
    "ruby": "ruby:slim", "go": "golang:alpine", "gcc": "gcc", "g++": "gcc",
}


def modes(refresh=False):
    """[{id, label, detail, available, why}] in the order to show them."""
    now = time.time()
    if not refresh and _cache["modes"] and now - _cache["at"] < CACHE_SECONDS:
        return _cache["modes"]

    bwrap_ok, bwrap_why = _bwrap_ok()
    docker_ok, docker_why = _docker_ok()
    systemd_ok, systemd_why = _systemd_ok()
    netless = bwrap_ok and _bwrap_net_ok()

    found = [
        {"id": "direct", "label": "Run",
         "detail": "in the shell below, in this folder",
         "available": True, "why": ""},
        {"id": "limited", "label": "Run with limits",
         "detail": "1 GB of memory, one core, 2 minute cap, its own HOME and TMPDIR",
         "available": systemd_ok, "why": systemd_why},
        {"id": "sandbox", "label": "Run sandboxed",
         "detail": ("read-only system, your home hidden, private /tmp, this folder only"
                    + (", no network" if netless else "")),
         "available": bwrap_ok, "why": bwrap_why},
        {"id": "container", "label": "Run in a container",
         "detail": "throwaway container, no network, only this folder mounted",
         "available": docker_ok, "why": docker_why},
    ]
    _cache.update({"at": now, "modes": found, "netless": netless})
    return found


def wrap(mode, command, cwd, label=""):
    """Turn a plain command into the command line for the chosen mode."""
    cwd = cwd or HOME
    if mode == "direct":
        return "cd %s && %s" % (shlex.quote(cwd), command)

    if mode == "limited":
        scratch = "/tmp/prism-run-home"
        return ("mkdir -p %s && cd %s && "
                "systemd-run --user --scope --quiet -p MemoryMax=1G -p CPUQuota=100%% -- "
                "env HOME=%s TMPDIR=%s timeout 120 sh -c %s"
                % (shlex.quote(scratch), shlex.quote(cwd),
                   shlex.quote(scratch), shlex.quote(scratch), shlex.quote(command)))

    if mode == "sandbox":
        netless = _cache.get("netless")
        parts = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                 "--tmpfs", "/tmp", "--tmpfs", HOME,
                 "--bind", cwd, cwd, "--chdir", cwd,
                 "--unshare-pid", "--unshare-ipc", "--unshare-uts",
                 "--die-with-parent", "--new-session"]
        if netless:
            parts.append("--unshare-net")
        parts += ["sh", "-c", command]
        return " ".join(shlex.quote(p) for p in parts)

    if mode == "container":
        image = IMAGES.get(label, "debian:stable-slim")
        return ("docker run --rm -it --network none "
                "-v %s:/work -w /work %s sh -c %s"
                % (shlex.quote(cwd), shlex.quote(image), shlex.quote(command)))

    return command
