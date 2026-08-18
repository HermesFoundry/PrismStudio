#!/usr/bin/env python3
"""Does the language server client hold up its end of the protocol?

The pure parts are checked always. The round trip needs a real server, so it
runs only when one is installed and says plainly when it is skipped rather than
quietly passing.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.expanduser("~/PrismStudio/app"))

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
from gi.repository import GLib  # noqa: E402

import lsp  # noqa: E402

fails = []
ran = {"n": 0}


def check(label, got, want=True):
    ran["n"] += 1
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}"
          + ("" if ok else f"   (want {want!r})"))
    if not ok:
        fails.append(label)


print("-- the bits that need no server --")
check("file URIs round trip", lsp.path_for(lsp.uri_for("/tmp/a b/c.py")), "/tmp/a b/c.py")
check("a URI is a URI", lsp.uri_for("/tmp/x.py").startswith("file:///"), True)
check("a non-file URI is left alone", lsp.path_for("http://x/y"), "http://x/y")
check("python maps to the LSP name", lsp.LSP_ID["python3"], "python")
check("so does the shell", lsp.LSP_ID["sh"], "shellscript")
check("an unmapped language passes through",
      lsp.LSP_ID.get("go", "go"), "go")
check("severities are named", lsp.SEVERITY[1], "error")
check("a language with no server gives nothing",
      lsp.available_for("brainfuck"), (None, None))
check("and so does no language at all", lsp.available_for(None), (None, None))
check("several languages are known", len(lsp.SERVERS) >= 10, True)

client = lsp.Client(None)
check("a client with no root starts empty", client.servers, {})
check("counts on an unknown path are zero", client.counts("/nope"), (0, 0))
client.enabled = False
check("a disabled client starts nothing", client.server_for("python3"), None)
client.enabled = True
check("nothing is running yet", client.status(), [])

name, argv = lsp.available_for("python3")
if not name:
    print("\n-- the round trip --")
    print("  SKIPPED: no python language server on PATH")
    print("  (npm install -g pyright, or install python-lsp-server)")
else:
    print("\n-- a real round trip with %s --" % name)
    root = tempfile.mkdtemp(prefix="prism-lsp-")
    path = os.path.join(root, "sample.py")
    with open(path, "w") as fh:
        fh.write("import os\n\n\ndef load(path: str) -> str:\n"
                 "    return open(path).read()\n\n\n"
                 "value = missing_name_here\n")

    state = {}
    loop = GLib.MainLoop()

    def on_diag(_path, items):
        state.setdefault("diags", items)

    live = lsp.Client(root, on_diagnostics=on_diag)
    server = live.server_for("python3")
    check("the server started", server is not None and server.alive(), True)

    def opened():
        state["ready"] = server.ready
        server.did_open(path, "python", open(path).read())
        GLib.timeout_add_seconds(6, ask)
        return False

    def ask():
        server.completion(path, 4, 11, got)         # inside open(...)
        return False

    def got(result, error):
        items = (result or {}).get("items") if isinstance(result, dict) else result
        state["completions"] = len(items or [])
        state["error"] = error
        GLib.timeout_add_seconds(1, stop)

    def stop():
        loop.quit()
        return False

    GLib.timeout_add_seconds(5, opened)
    GLib.timeout_add_seconds(40, lambda: (loop.quit(), False)[1])
    loop.run()

    check("it finished initialising", state.get("ready"), True)
    check("it reported the undefined name", bool(state.get("diags")), True)
    if state.get("diags"):
        messages = " ".join(d.get("message", "") for d in state["diags"])
        check("naming it", "missing_name_here" in messages, True)
        check("as an error", state["diags"][0].get("severity"), 1)
    check("completion came back without an error", state.get("error"), None)
    check("with something in it", (state.get("completions") or 0) > 0, True)
    check("the path it reported is the one we opened",
          list(live.diagnostics)[0] if live.diagnostics else None, path)
    errors, warnings = live.counts(path)
    check("counted as an error", errors >= 1, True)
    check("and not as a warning", warnings, 0)
    check("it is listed as running", live.status()[0][1], name)

    live.shutdown()
    check("shutdown clears the servers", live.servers, {})
    check("and the diagnostics", live.diagnostics, {})
    shutil.rmtree(root, ignore_errors=True)

if not ran["n"]:
    fails.append("no checks ran at all")
print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
