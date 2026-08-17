"""project — work out what a folder is, how to set it up, and how to run it.

The point is that opening a folder should be enough. PrismStudio reads the manifests
that are already there, works out the package manager from the lock file, says
whether the dependencies are installed, and offers the run targets the project
actually declares — `npm run dev`, `manage.py runserver`, `cargo run` — instead
of making you remember them.

Everything here is a guess made from files on disk, so every target carries the
evidence it came from and nothing is ever run without you asking.
"""
import json
import os
import re
import shutil

URL = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|\[::\])(?::\d+)?[^\s\"'<>)]*")
PORT_ONLY = re.compile(r"(?:^|\s)(?:port|listening on|running at|Local:)\D{0,12}(\d{4,5})\b",
                       re.I)

# scripts worth surfacing, best first, and whether they serve something
SCRIPT_ORDER = [
    ("dev", True), ("start", True), ("serve", True), ("preview", True),
    ("develop", True), ("watch", False), ("build", False), ("test", False),
    ("lint", False), ("typecheck", False),
]


class Step:
    """Something to do once before the project will run."""

    def __init__(self, label, command, done, detail="", blocked=""):
        self.label = label
        self.command = command
        self.done = done
        self.detail = detail
        self.blocked = blocked      # non-empty means it cannot be done here


class Target:
    """One way to run this project."""

    def __init__(self, label, command, web=False, detail="", tool=""):
        self.label = label
        self.command = command
        self.web = web              # serves something you open in a browser
        self.detail = detail
        self.tool = tool

    def __repr__(self):
        return "Target(%r, web=%s)" % (self.label, self.web)


class Project:
    def __init__(self, root):
        self.root = root
        self.stack = []             # ["Node", "Python"] etc
        self.manager = ""           # npm / pnpm / pip ...
        self.steps = []
        self.targets = []
        self.notes = []

    @property
    def ready(self):
        """Nothing left to install that we can actually do."""
        return all(step.done or step.blocked for step in self.steps)

    @property
    def blocked(self):
        return [s for s in self.steps if s.blocked and not s.done]

    @property
    def pending(self):
        return [s for s in self.steps if not s.done and not s.blocked]

    @property
    def summary(self):
        bits = " · ".join(self.stack) if self.stack else "no project detected"
        if self.manager:
            bits += " · " + self.manager
        return bits

    def install_command(self):
        """One shell line that does every outstanding step, in order."""
        todo = [s.command for s in self.pending if s.command]
        return " && ".join(todo) if todo else ""


def _read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _exists(root, *names):
    return any(os.path.exists(os.path.join(root, n)) for n in names)


def _text(root, name, limit=200000):
    try:
        with open(os.path.join(root, name), errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# Node
# --------------------------------------------------------------------------- #
def _node(project):
    root = project.root
    manifest = _read_json(os.path.join(root, "package.json"))
    if manifest is None:
        return
    project.stack.append("Node")

    manager = "npm"
    for lock, name in (("bun.lockb", "bun"), ("pnpm-lock.yaml", "pnpm"),
                       ("yarn.lock", "yarn"), ("package-lock.json", "npm")):
        if os.path.exists(os.path.join(root, lock)):
            manager = name
            break
    project.manager = manager
    # Deliberately no silent fallback to npm: the lock file is the project's
    # decision, and running a different manager would write a second lock file
    # that fights the first one. Say what is missing instead.
    missing = ""
    if not shutil.which(manager):
        missing = "%s is not installed" % manager
        if manager != "npm" and shutil.which("npm"):
            missing += " (this project's lock file asks for it, so npm is not a swap)"

    wants_deps = bool(manifest.get("dependencies") or manifest.get("devDependencies"))
    installed = os.path.isdir(os.path.join(root, "node_modules"))
    if wants_deps:
        project.steps.append(Step(
            "Install packages", "%s install" % manager, installed,
            "%s reads package.json and fills node_modules" % manager, missing))

    scripts = manifest.get("scripts") or {}
    for name, web in SCRIPT_ORDER:
        if name in scripts:
            project.targets.append(Target(
                "%s run %s" % (manager, name), "%s run %s" % (manager, name),
                web, scripts[name], manager))
    for name in sorted(scripts):
        if name not in dict(SCRIPT_ORDER):
            project.targets.append(Target(
                "%s run %s" % (manager, name), "%s run %s" % (manager, name),
                False, scripts[name], manager))

    if not scripts:
        entry = manifest.get("main") or "index.js"
        if os.path.exists(os.path.join(root, entry)):
            project.targets.append(Target("node %s" % entry, "node %s" % entry,
                                          False, "no scripts in package.json", "node"))


# --------------------------------------------------------------------------- #
# Python
# --------------------------------------------------------------------------- #
def _venv_python(root):
    for folder in (".venv", "venv", "env"):
        candidate = os.path.join(root, folder, "bin", "python")
        if os.path.exists(candidate):
            return os.path.join(folder, "bin", "python")
    return ""


def _can_make_venv():
    """This machine's python3 may have no ensurepip, which makes venv useless."""
    try:
        import ensurepip  # noqa: F401
        return True
    except Exception:
        return False


def _python(project):
    root = project.root
    manifests = [n for n in ("requirements.txt", "pyproject.toml", "Pipfile", "setup.py")
                 if os.path.exists(os.path.join(root, n))]
    django = os.path.exists(os.path.join(root, "manage.py"))
    py_files = []
    try:
        py_files = [n for n in os.listdir(root) if n.endswith(".py")]
    except OSError:
        pass
    if not manifests and not django:
        # Loose .py files only make this a Python project when nothing else has
        # claimed the folder. A node app with one helper script is not Python.
        if not py_files or project.stack:
            return
    project.stack.append("Python")

    venv = _venv_python(root)
    python = venv or "python3"
    if venv:
        project.notes.append("using the virtualenv in %s" % venv.split(os.sep)[0])

    if "requirements.txt" in manifests:
        project.manager = project.manager or "pip"
        if venv:
            command = "%s -m pip install -r requirements.txt" % python
            blocked = ""
        elif _can_make_venv():
            command = ("python3 -m venv .venv && "
                       ".venv/bin/pip install -r requirements.txt")
            blocked = ""
        else:
            command = ""
            blocked = ("this python3 has no ensurepip, so it cannot make a "
                       "virtualenv. Install python3-venv, or open a "
                       "folder that already has one")
        project.steps.append(Step(
            "Install requirements", command, bool(venv) and _installed_ok(root, venv),
            "requirements.txt", blocked))
    elif "pyproject.toml" in manifests:
        project.manager = project.manager or "pip"
        blocked = "" if (venv or _can_make_venv()) else "this python3 has no ensurepip"
        command = ("%s -m pip install -e ." % python) if not blocked else ""
        project.steps.append(Step("Install this project", command, False,
                                  "pyproject.toml", blocked))

    # what to actually run
    if django:
        project.targets.append(Target("Django dev server",
                                      "%s manage.py runserver" % python, True,
                                      "manage.py", "django"))
        project.targets.append(Target("Django migrate",
                                      "%s manage.py migrate" % python, False,
                                      "manage.py", "django"))
    body = " ".join(_text(root, n, 6000) for n in py_files[:14])
    if "FastAPI(" in body and shutil.which("uvicorn"):
        module = _module_with(root, py_files, "FastAPI(")
        project.targets.append(Target("uvicorn --reload",
                                      "uvicorn %s:app --reload" % module, True,
                                      "%s.py defines a FastAPI app" % module, "uvicorn"))
    if "Flask(" in body:
        module = _module_with(root, py_files, "Flask(")
        project.targets.append(Target("Flask dev server",
                                      "%s -m flask --app %s run --debug" % (python, module),
                                      True, "%s.py defines a Flask app" % module, "flask"))
    if "streamlit" in body:
        module = _module_with(root, py_files, "streamlit")
        project.targets.append(Target("streamlit run",
                                      "streamlit run %s.py" % module, True,
                                      "imports streamlit", "streamlit"))
    for name in ("main.py", "app.py", "__main__.py", "run.py"):
        if name in py_files:
            project.targets.append(Target("%s %s" % (os.path.basename(python), name),
                                          "%s %s" % (python, name), False, name, "python"))
            break


def _installed_ok(root, venv):
    """A rough check that the virtualenv has more than the basics in it."""
    site = os.path.join(root, venv.split(os.sep)[0], "lib")
    try:
        for base, dirs, _files in os.walk(site):
            if os.path.basename(base) == "site-packages":
                return len([d for d in dirs if not d.startswith("_")]) > 2
    except OSError:
        pass
    return False


def _module_with(root, py_files, needle):
    for name in ("main.py", "app.py", "server.py", "api.py", "wsgi.py"):
        if name in py_files and needle in _text(root, name, 6000):
            return name[:-3]
    for name in py_files:
        if needle in _text(root, name, 6000):
            return name[:-3]
    return "app"


# --------------------------------------------------------------------------- #
# everything else
# --------------------------------------------------------------------------- #
def _rust(project):
    if not os.path.exists(os.path.join(project.root, "Cargo.toml")):
        return
    project.stack.append("Rust")
    project.manager = project.manager or "cargo"
    if not shutil.which("cargo"):
        project.steps.append(Step("Install Rust", "", False, "",
                                  "cargo is not installed"))
        return
    project.targets.append(Target("cargo run", "cargo run", False, "Cargo.toml", "cargo"))
    project.targets.append(Target("cargo test", "cargo test", False, "", "cargo"))


def _go(project):
    if not os.path.exists(os.path.join(project.root, "go.mod")):
        return
    project.stack.append("Go")
    if not shutil.which("go"):
        project.steps.append(Step("Install Go", "", False, "", "go is not installed"))
        return
    body = _text(project.root, "go.mod", 4000)
    project.steps.append(Step("Download modules", "go mod download",
                              os.path.isdir(os.path.expanduser("~/go/pkg/mod")),
                              "go.mod"))
    serves = "net/http" in " ".join(
        _text(project.root, n, 8000) for n in os.listdir(project.root)
        if n.endswith(".go")) if os.path.isdir(project.root) else False
    project.targets.append(Target("go run .", "go run .", serves, body.split("\n")[0], "go"))


def _php(project):
    root = project.root
    if not _exists(root, "composer.json", "index.php"):
        return
    project.stack.append("PHP")
    if os.path.exists(os.path.join(root, "composer.json")) and shutil.which("composer"):
        project.manager = project.manager or "composer"
        project.steps.append(Step("Install packages", "composer install",
                                  os.path.isdir(os.path.join(root, "vendor")),
                                  "composer.json"))
    if shutil.which("php"):
        project.targets.append(Target("php built-in server",
                                      "php -S localhost:8000", True,
                                      "serves this folder", "php"))


def _ruby(project):
    root = project.root
    if not _exists(root, "Gemfile", "config.ru"):
        return
    project.stack.append("Ruby")
    if shutil.which("bundle"):
        project.manager = project.manager or "bundler"
        project.steps.append(Step("Install gems", "bundle install",
                                  os.path.isdir(os.path.join(root, "vendor", "bundle"))
                                  or os.path.exists(os.path.join(root, "Gemfile.lock")),
                                  "Gemfile"))
    if os.path.exists(os.path.join(root, "config", "application.rb")):
        project.targets.append(Target("Rails server", "bundle exec rails server", True,
                                      "config/application.rb", "rails"))
    elif os.path.exists(os.path.join(root, "config.ru")):
        project.targets.append(Target("rackup", "bundle exec rackup", True,
                                      "config.ru", "rack"))


def _docker(project):
    root = project.root
    compose = next((n for n in ("docker-compose.yml", "docker-compose.yaml",
                                "compose.yml", "compose.yaml")
                    if os.path.exists(os.path.join(root, n))), None)
    if not compose:
        return
    project.stack.append("Docker Compose")
    if not shutil.which("docker"):
        project.steps.append(Step("Install Docker", "", False, "",
                                  "docker is not installed"))
        return
    project.targets.append(Target("docker compose up", "docker compose up", True,
                                  compose, "docker"))


def _static(project):
    root = project.root
    if not os.path.exists(os.path.join(root, "index.html")):
        return
    if "Node" in project.stack:          # a built site, npm already covers it
        return
    project.stack.append("Static site")
    project.targets.append(Target("Serve this folder",
                                  "python3 -m http.server 8000", True,
                                  "index.html", "http.server"))


def _make(project):
    root = project.root
    if not _exists(root, "Makefile", "makefile") or not shutil.which("make"):
        return
    body = _text(root, "Makefile") or _text(root, "makefile")
    names = []
    for line in body.split("\n"):
        match = re.match(r"^([a-zA-Z][\w.-]*)\s*:(?!=)", line)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    if not names:
        return
    if "Make" not in project.stack:
        project.stack.append("Make")
    for name in names[:6]:
        project.targets.append(Target("make %s" % name, "make %s" % name,
                                      name in ("serve", "run", "dev", "start"),
                                      "Makefile", "make"))


DETECTORS = [_node, _python, _rust, _go, _php, _ruby, _docker, _static, _make]


def detect(root):
    """Everything PrismStudio can work out about this folder."""
    project = Project(root)
    if not root or not os.path.isdir(root):
        return project
    for detector in DETECTORS:
        try:
            detector(project)
        except Exception:
            continue
    return project


# --------------------------------------------------------------------------- #
# spotting the address a dev server printed
# --------------------------------------------------------------------------- #
def browsable(url):
    """0.0.0.0 and :: mean 'every interface', which no browser can open."""
    if not url:
        return url
    for wildcard in ("0.0.0.0", "[::]", "[::1]", "127.0.0.1"):
        if wildcard in url:
            return url.replace(wildcard, "localhost")
    return url


def find_url(text):
    """The last localhost address in some terminal output, ready to open."""
    if not text:
        return None
    found = URL.findall(text)
    if found:
        return browsable(found[-1].rstrip(".,);:'\""))
    port = PORT_ONLY.findall(text)
    if port:
        return "http://localhost:%s" % port[-1]
    return None
