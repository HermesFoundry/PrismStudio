#!/usr/bin/env python3
"""Does opening a folder tell you what it is and how to run it?

Detection is all guesswork from files on disk, so the things worth asserting
are that it reads the right manifest, picks the package manager from the lock
file rather than assuming npm, knows whether the dependencies are already
installed, refuses to pretend when a tool is missing, and can spot the address
a dev server printed.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))
import project  # noqa: E402

fails = []
ran = {"n": 0}
BASE = tempfile.mkdtemp(prefix="prism-project-")


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


def folder(name, files):
    path = os.path.join(BASE, name)
    os.makedirs(path, exist_ok=True)
    for filename, body in files.items():
        full = os.path.join(path, filename)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(body if isinstance(body, str) else json.dumps(body))
    return path


def labels(found):
    return [t.label for t in found.targets]


try:
    print("-- a node project --")
    node = folder("node", {
        "package.json": {"name": "x", "scripts": {"dev": "vite", "build": "vite build",
                                                  "test": "vitest", "zzz": "echo z"},
                         "dependencies": {"vue": "^3"}},
        "package-lock.json": "{}",
    })
    found = project.detect(node)
    check("it is called Node", found.stack, ["Node"])
    check("the lock file picks npm", found.manager, "npm")
    check("dependencies are noticed as missing", found.ready, False)
    check("with one thing to do", [s.label for s in found.pending], ["Install packages"])
    check("and a command to do it", found.install_command(), "npm install")
    check("dev comes before build", labels(found)[:2], ["npm run dev", "npm run build"])
    check("dev is a web target", found.targets[0].web, True)
    check("build is not", found.targets[1].web, False)
    check("an unknown script is still offered, but last",
          labels(found)[-1], "npm run zzz")

    os.makedirs(os.path.join(node, "node_modules"), exist_ok=True)
    found = project.detect(node)
    check("node_modules means it is ready", found.ready, True)
    check("and nothing is pending", found.pending, [])
    check("so there is nothing to install", found.install_command(), "")

    print("\n-- the lock file decides the manager --")
    for lock, manager in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
                          ("bun.lockb", "bun")):
        one = folder("mgr-" + manager, {
            "package.json": {"scripts": {"dev": "x"}, "dependencies": {"a": "1"}},
            lock: "",
        })
        got = project.detect(one)
        check("%s picks %s" % (lock, manager), got.manager, manager)
        step = got.steps[0]
        if shutil.which(manager):
            check("  and can run it", step.blocked, "")
        else:
            check("  and says it is missing rather than using npm",
                  "not installed" in step.blocked, True)
            check("  without silently swapping the command",
                  step.command, "%s install" % manager)

    print("\n-- python --")
    django = folder("django", {"manage.py": "# django",
                               "requirements.txt": "Django>=5\n"})
    found = project.detect(django)
    check("it is called Python", found.stack, ["Python"])
    check("the dev server is offered", labels(found)[0], "Django dev server")
    check("and it is a web target", found.targets[0].web, True)
    check("migrate is offered too, not as web",
          (labels(found)[1], found.targets[1].web), ("Django migrate", False))

    flask = folder("flask", {"app.py": "from flask import Flask\napp = Flask(__name__)\n",
                             "requirements.txt": "flask\n"})
    found = project.detect(flask)
    check("a Flask app is spotted", "Flask dev server" in labels(found), True)
    check("pointed at the right module",
          "--app app" in found.targets[0].command, True)

    plain = folder("plainpy", {"main.py": "print(1)\n"})
    found = project.detect(plain)
    check("a lone script is still runnable", labels(found), ["python3 main.py"])
    check("with nothing to install", found.steps, [])

    print("\n-- a virtualenv is used when there is one --")
    venv = folder("venv", {"requirements.txt": "flask\n", "main.py": "print(1)\n",
                           ".venv/bin/python": "#!/bin/sh\n"})
    found = project.detect(venv)
    check("the venv python is used",
          found.targets[0].command.startswith(".venv/bin/python"), True)
    check("and pip goes through it",
          ".venv/bin/python -m pip" in found.steps[0].command, True)

    print("\n-- a static site --")
    static = folder("static", {"index.html": "<h1>hi</h1>"})
    found = project.detect(static)
    check("it is called a static site", found.stack, ["Static site"])
    check("and gets a server", found.targets[0].web, True)

    built = folder("built", {"index.html": "<h1>hi</h1>",
                             "package.json": {"scripts": {"dev": "vite"}}})
    found = project.detect(built)
    check("a built node site is not double counted", found.stack, ["Node"])

    print("\n-- a Makefile --")
    make = folder("make", {"Makefile": "run:\n\techo hi\nclean:\n\trm -f x\n"})
    found = project.detect(make)
    if shutil.which("make"):
        check("targets are read out of it", labels(found), ["make run", "make clean"])
        check("run counts as serving", found.targets[0].web, True)
    else:
        check("make missing means no targets", labels(found), [])

    print("\n-- nothing recognisable --")
    empty = folder("empty", {"notes.txt": "hello"})
    found = project.detect(empty)
    check("no stack is claimed", found.stack, [])
    check("no targets are invented", found.targets, [])
    check("and it says so", found.summary, "no project detected")
    check("a missing folder is handled", project.detect("/no/such/place").targets, [])
    check("so is None", project.detect(None).targets, [])

    print("\n-- a tool that is not installed --")
    rust = folder("rust", {"Cargo.toml": "[package]\nname='x'\n"})
    found = project.detect(rust)
    if shutil.which("cargo"):
        check("cargo run is offered", labels(found)[0], "cargo run")
    else:
        check("no cargo means no run target", found.targets, [])
        check("and it says why", "not installed" in found.steps[0].blocked, True)
        check("blocked is not the same as pending", found.pending, [])
        check("so the bar will not offer a useless Install", found.ready, True)

    print("\n-- reading the address out of the output --")
    cases = [
        ("  ➜  Local:   http://localhost:5173/", "http://localhost:5173/"),
        ("Starting development server at http://127.0.0.1:8000/", "http://localhost:8000/"),
        ("* Running on http://0.0.0.0:5000", "http://localhost:5000"),
        ("Serving HTTP on :: port 8000 (http://[::]:8000/)", "http://localhost:8000/"),
        ("Listening on port 3000", "http://localhost:3000"),
        ("nothing to see", None),
        ("", None),
    ]
    for text, want in cases:
        check("%-46r" % text[:44], project.find_url(text), want)

    check("the last address wins when there are several",
          project.find_url("http://localhost:1111\nhttp://localhost:2222"),
          "http://localhost:2222")
    check("trailing punctuation is trimmed",
          project.find_url("open (http://localhost:9000)."), "http://localhost:9000")
    check("a wildcard address is made browsable",
          project.browsable("http://0.0.0.0:1234"), "http://localhost:1234")
    check("a real host is left alone",
          project.browsable("http://example.com:80"), "http://example.com:80")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("exception during the checks")
finally:
    shutil.rmtree(BASE, ignore_errors=True)

if not ran["n"]:
    fails.append("no checks ran at all")
print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
