"""lsp — a Language Server Protocol client, so the editor understands the code.

This is the difference between an editor that colours text and one that knows
what the text means. A language server gives real completion, the errors as you
type, hover documentation and go-to-definition — and because it is a protocol,
one client gets all of that for every language somebody has written a server
for.

PrismStudio does not bundle servers. It looks for the usual ones on your PATH
and uses whichever are there, so nothing is downloaded behind your back and the
list grows as you install them.

The wire format is Content-Length framed JSON-RPC over the server's stdin and
stdout. Reading happens on a thread; every reply reaches the rest of the app
through GLib.idle_add, so nothing touches a widget off the main loop.
"""
import json
import os
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request

from gi.repository import GLib

# language id -> the servers worth trying, best first. Only what is on PATH runs.
SERVERS = {
    "python3": [("pylsp", ["pylsp"]),
                ("pyright", ["pyright-langserver", "--stdio"]),
                ("jedi", ["jedi-language-server"])],
    "js": [("typescript", ["typescript-language-server", "--stdio"])],
    "javascript": [("typescript", ["typescript-language-server", "--stdio"])],
    "typescript": [("typescript", ["typescript-language-server", "--stdio"])],
    "go": [("gopls", ["gopls"])],
    "rust": [("rust-analyzer", ["rust-analyzer"])],
    "c": [("clangd", ["clangd"])],
    "cpp": [("clangd", ["clangd"])],
    "json": [("json", ["vscode-json-language-server", "--stdio"])],
    "html": [("html", ["vscode-html-language-server", "--stdio"])],
    "css": [("css", ["vscode-css-language-server", "--stdio"])],
    "sh": [("bash", ["bash-language-server", "start"])],
    "yaml": [("yaml", ["yaml-language-server", "--stdio"])],
}
# what GtkSourceView calls a language, mapped to what LSP calls it
LSP_ID = {"python3": "python", "js": "javascript", "sh": "shellscript",
          "cpp": "cpp", "chdr": "c"}

SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}


def available_for(language):
    """(name, argv) of the first server for this language that is installed."""
    for name, argv in SERVERS.get(language or "", []):
        if shutil.which(argv[0]):
            return name, argv
    return None, None


def installed():
    """Every server this build knows about that is actually on the PATH."""
    found = []
    for language, options in SERVERS.items():
        for name, argv in options:
            if shutil.which(argv[0]) and name not in [f[0] for f in found]:
                found.append((name, argv[0], language))
    return found


def uri_for(path):
    return "file://" + urllib.request.pathname2url(os.path.abspath(path))


def path_for(uri):
    if not uri.startswith("file://"):
        return uri
    return urllib.request.url2pathname(urllib.parse.urlparse(uri).path)


class Server:
    """One language server process, and the conversation with it."""

    def __init__(self, name, argv, root, on_diagnostics=None, on_log=None):
        self.name = name
        self.argv = argv
        self.root = root
        self.on_diagnostics = on_diagnostics or (lambda path, items: None)
        self.on_log = on_log or (lambda text: None)
        self.proc = None
        self.ready = False
        self.capabilities = {}
        self.open_files = {}            # path -> version
        self._next = 1
        self._waiting = {}              # request id -> callback
        self._lock = threading.Lock()
        self._stop = False

    # -- lifecycle -------------------------------------------------------------
    def start(self):
        try:
            self.proc = subprocess.Popen(
                self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, cwd=self.root or None, bufsize=0)
        except OSError as exc:
            self.on_log("%s did not start: %s" % (self.name, exc))
            return False
        threading.Thread(target=self._read_loop, daemon=True).start()
        self._initialize()
        return True

    def stop(self):
        self._stop = True
        if self.proc and self.proc.poll() is None:
            try:
                self._send({"jsonrpc": "2.0", "id": self._id(), "method": "shutdown"})
                self._send({"jsonrpc": "2.0", "method": "exit"})
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except OSError:
                    pass

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _initialize(self):
        self.request("initialize", {
            "processId": os.getpid(),
            "rootUri": uri_for(self.root) if self.root else None,
            "workspaceFolders": ([{"uri": uri_for(self.root),
                                   "name": os.path.basename(self.root)}]
                                 if self.root else None),
            "clientInfo": {"name": "PrismStudio", "version": "1.0"},
            "capabilities": {
                "textDocument": {
                    "synchronization": {"didSave": True, "dynamicRegistration": False},
                    "completion": {
                        "completionItem": {"snippetSupport": False,
                                           "documentationFormat": ["plaintext"]},
                        "contextSupport": True},
                    "hover": {"contentFormat": ["plaintext", "markdown"]},
                    "definition": {"linkSupport": False},
                    "publishDiagnostics": {"relatedInformation": False},
                },
                "workspace": {"workspaceFolders": True, "configuration": True},
            },
        }, self._initialized)

    def _initialized(self, result, error):
        if error:
            self.on_log("%s could not start: %s" % (self.name, error))
            return
        self.capabilities = (result or {}).get("capabilities", {})
        self.notify("initialized", {})
        self.ready = True
        self.on_log("%s ready" % self.name)

    # -- the wire --------------------------------------------------------------
    def _id(self):
        with self._lock:
            self._next += 1
            return self._next

    def _send(self, message):
        if not self.alive():
            return
        body = json.dumps(message).encode()
        head = b"Content-Length: %d\r\n\r\n" % len(body)
        try:
            self.proc.stdin.write(head + body)
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method, params, callback):
        """callback(result, error) on the main loop."""
        ident = self._id()
        with self._lock:
            self._waiting[ident] = callback
        self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        return ident

    def _read_loop(self):
        stream = self.proc.stdout
        while not self._stop:
            length = 0
            while True:                                  # headers
                line = stream.readline()
                if not line:
                    return
                line = line.strip()
                if not line:
                    break
                if line.lower().startswith(b"content-length:"):
                    try:
                        length = int(line.split(b":", 1)[1])
                    except ValueError:
                        length = 0
            if not length:
                continue
            body = b""
            while len(body) < length:
                chunk = stream.read(length - len(body))
                if not chunk:
                    return
                body += chunk
            try:
                message = json.loads(body.decode("utf-8", "replace"))
            except ValueError:
                continue
            GLib.idle_add(self._dispatch, message)

    def _dispatch(self, message):
        if "id" in message and "method" not in message:
            with self._lock:
                callback = self._waiting.pop(message["id"], None)
            if callback:
                error = message.get("error")
                callback(message.get("result"),
                         error.get("message") if isinstance(error, dict) else error)
        elif message.get("method") == "textDocument/publishDiagnostics":
            params = message.get("params") or {}
            self.on_diagnostics(path_for(params.get("uri", "")),
                                params.get("diagnostics") or [])
        elif message.get("method") in ("window/logMessage", "window/showMessage"):
            text = (message.get("params") or {}).get("message", "")
            if text:
                self.on_log("%s: %s" % (self.name, text[:200]))
        elif "id" in message:
            # the server asked us something; answer politely rather than hang it
            self._send({"jsonrpc": "2.0", "id": message["id"], "result": None})
        return False

    # -- documents -------------------------------------------------------------
    def did_open(self, path, language_id, text):
        self.open_files[path] = 1
        self.notify("textDocument/didOpen", {
            "textDocument": {"uri": uri_for(path), "languageId": language_id,
                             "version": 1, "text": text}})

    def did_change(self, path, text):
        if path not in self.open_files:
            return
        self.open_files[path] += 1
        self.notify("textDocument/didChange", {
            "textDocument": {"uri": uri_for(path), "version": self.open_files[path]},
            "contentChanges": [{"text": text}]})       # whole document, simplest correct

    def did_save(self, path, text):
        if path not in self.open_files:
            return
        self.notify("textDocument/didSave",
                    {"textDocument": {"uri": uri_for(path)}, "text": text})

    def did_close(self, path):
        if self.open_files.pop(path, None):
            self.notify("textDocument/didClose",
                        {"textDocument": {"uri": uri_for(path)}})

    # -- asking it things ------------------------------------------------------
    def completion(self, path, line, column, callback):
        self.request("textDocument/completion", {
            "textDocument": {"uri": uri_for(path)},
            "position": {"line": line, "character": column}}, callback)

    def hover(self, path, line, column, callback):
        self.request("textDocument/hover", {
            "textDocument": {"uri": uri_for(path)},
            "position": {"line": line, "character": column}}, callback)

    def definition(self, path, line, column, callback):
        self.request("textDocument/definition", {
            "textDocument": {"uri": uri_for(path)},
            "position": {"line": line, "character": column}}, callback)


class Client:
    """One server per language, started when a file of that language opens."""

    def __init__(self, root=None, on_diagnostics=None, on_log=None):
        self.root = root
        self.servers = {}
        self.diagnostics = {}           # path -> [diagnostic]
        self.on_diagnostics = on_diagnostics or (lambda path, items: None)
        self.on_log = on_log or (lambda text: None)
        self.enabled = True
        self._starting = set()          # languages whose server is booting
        self.on_ready = lambda language: None   # set by the editor, to re-open

    def set_root(self, root):
        if root == self.root:
            return
        self.shutdown()
        self.root = root

    def server_for(self, language, start=True):
        """The server for a language, or None while one is on its way.

        Starting a language server means forking an interpreter, which is a
        sixth of a second the editor used to spend frozen on the first file of
        a language you opened. It boots on a thread now and says so when it is
        up; until then this answers None and the caller simply does without.
        """
        if not self.enabled or not language:
            return None
        if language in self.servers:
            server = self.servers[language]
            return server if server.alive() else None
        if not start or language in self._starting:
            return None
        name, argv = available_for(language)
        if not name:
            return None
        self._starting.add(language)

        def boot():
            made = Server(name, argv, self.root, self._diagnostics, self.on_log)
            started = made.start()
            GLib.idle_add(landed, made, started)

        def landed(made, started):
            self._starting.discard(language)
            if started:
                self.servers[language] = made
                try:
                    self.on_ready(language)
                except Exception:
                    pass
            return False

        threading.Thread(target=boot, daemon=True).start()
        return None

    def _diagnostics(self, path, items):
        self.diagnostics[path] = items
        self.on_diagnostics(path, items)

    def counts(self, path):
        """(errors, warnings) for a path."""
        items = self.diagnostics.get(path) or []
        errors = sum(1 for d in items if d.get("severity", 1) == 1)
        warnings = sum(1 for d in items if d.get("severity") == 2)
        return errors, warnings

    def shutdown(self):
        for server in list(self.servers.values()):
            server.stop()
        self.servers.clear()
        self.diagnostics.clear()

    def status(self):
        """What is running, for the status bar and the settings page."""
        return [(lang, s.name, s.ready) for lang, s in self.servers.items()
                if s.alive()]
