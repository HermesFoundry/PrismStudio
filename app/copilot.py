"""copilot — GitHub Copilot as a suggestion source, over its language server.

`SUGGEST=copilot` used to be a setting with nothing behind it, which is worse
than not offering it at all. This is the thing behind it.

Copilot ships `@github/copilot-language-server`, which speaks LSP with a few
additions of its own, so the wire format is the one `lsp.py` already handles
and this only has to know the differences:

  · `initialize` wants `editorInfo` and `editorPluginInfo` in
    `initializationOptions`, not the standard `clientInfo`
  · auth state arrives unasked as `didChangeStatus` and `didChangeStatus/v2`
  · `signIn` returns a device flow: a user code, a URL, and a command to run
    once the code has been entered
  · suggestions come from `textDocument/inlineCompletion`, which answers
    `{"items": [...]}`, or errors with 1000 "Not authenticated" when signed out
  · accepting one is reported back with `workspace/executeCommand`, and
    showing one with `textDocument/didShowCompletion`

Installing it:

    npm install -g @github/copilot-language-server

then set `COPILOT_CMD` if the binary is not on PATH under that name. Copilot
is a paid GitHub product; being signed in to `gh` is not the same as having
it, and the server says so plainly, which is what gets shown.
"""
import os
import shutil

from gi.repository import GLib

import core
import lsp

# What the language server calls each language. Copilot keys its models off
# these, so a wrong one gives worse suggestions rather than none.
LANGUAGE_ID = dict(lsp.LSP_ID)


def find(command):
    """Where the language server is, if it is anywhere."""
    if not command:
        return None
    if os.path.sep in command:
        return command if os.access(command, os.X_OK) else None
    return shutil.which(command)


def installed(command="copilot-language-server"):
    return find(command) is not None


class Server(lsp.Server):
    """The Copilot language server. Same wire, different handshake."""

    def __init__(self, root, on_status=None, on_log=None):
        lsp.Server.__init__(self, "copilot", [], root, on_log=on_log)
        self.on_status = on_status or (lambda kind, message: None)
        self.status_kind = "starting"
        self.status_message = ""

    def _initialize(self):
        self.request("initialize", {
            "processId": os.getpid(),
            "workspaceFolders": ([{"uri": lsp.uri_for(self.root),
                                   "name": os.path.basename(self.root)}]
                                 if self.root else []),
            "capabilities": {"workspace": {"workspaceFolders": True}},
            "initializationOptions": {
                "editorInfo": {"name": core.APP_NAME, "version": core.VERSION},
                "editorPluginInfo": {"name": core.APP_NAME,
                                     "version": core.VERSION},
            },
        }, self._initialized)

    def _initialized(self, result, error):
        if error:
            self._set_status("error", str(error))
            return
        self.capabilities = (result or {}).get("capabilities", {})
        self.notify("initialized", {})
        self.ready = True

    def _set_status(self, kind, message):
        self.status_kind, self.status_message = kind, message
        self.on_status(kind, message)

    def _dispatch(self, message):
        method = message.get("method")
        if method in ("didChangeStatus", "statusNotification"):
            params = message.get("params") or {}
            self._read_status(params.get("kind", ""), params.get("message", ""))
            return
        if method == "didChangeStatus/v2":
            for entry in (message.get("params") or {}).get("statuses", []):
                if entry.get("category") == "auth":
                    result = entry.get("result") or {}
                    self._read_status(entry.get("kind", ""),
                                      entry.get("message", ""),
                                      result.get("status", ""))
            return
        lsp.Server._dispatch(self, message)

    def _read_status(self, kind, message, code=""):
        """Turn the server's own words into something a status bar can show."""
        if code == "NotSignedIn" or "not signed in" in (message or "").lower():
            self._set_status("signed-out", message or "not signed in to GitHub")
        elif code in ("NotAuthorized", "NoSubscription"):
            self._set_status("no-subscription",
                             message or "this account has no Copilot subscription")
        elif kind == "Error":
            self._set_status("error", message or "Copilot reported an error")
        elif kind in ("Normal", "", "Inactive"):
            self._set_status("ready" if kind != "Inactive" else "inactive",
                             message)
        elif kind == "Warning":
            self._set_status("warning", message)

    # -- signing in --------------------------------------------------------
    def sign_in(self, on_code):
        """Start the device flow. on_code(code, url, error) on the main loop."""
        def answered(result, error):
            if error or not result:
                on_code("", "", str(error or "Copilot did not answer"))
                return
            status = result.get("status", "")
            if status in ("AlreadySignedIn", "OK"):
                on_code("", "", "")
                self._set_status("ready", "signed in")
                return
            code = result.get("userCode", "")
            url = result.get("verificationUri", "https://github.com/login/device")
            on_code(code, url, "")
            command = result.get("command")
            if isinstance(command, dict) and command.get("command"):
                # Runs the half that waits for the browser. It only returns
                # once the code has been entered, so it is fire and forget.
                self.request("workspace/executeCommand",
                             {"command": command["command"],
                              "arguments": command.get("arguments") or []},
                             lambda _r, _e: None)
        self.request("signIn", {}, answered)

    def sign_out(self, on_done=None):
        def answered(_result, error):
            self._set_status("signed-out", "signed out")
            if on_done:
                on_done(error)
        self.request("signOut", {}, answered)

    # -- documents ---------------------------------------------------------
    def open_document(self, path, language, text, version=1):
        self.open_files[path] = version
        self.notify("textDocument/didOpen", {"textDocument": {
            "uri": lsp.uri_for(path), "languageId": LANGUAGE_ID.get(language, "plaintext"),
            "version": version, "text": text}})

    def change_document(self, path, text):
        version = self.open_files.get(path, 1) + 1
        self.open_files[path] = version
        self.notify("textDocument/didChange", {
            "textDocument": {"uri": lsp.uri_for(path), "version": version},
            "contentChanges": [{"text": text}]})

    def close_document(self, path):
        if self.open_files.pop(path, None) is not None:
            self.notify("textDocument/didClose",
                        {"textDocument": {"uri": lsp.uri_for(path)}})

    def focus_document(self, path):
        self.notify("textDocument/didFocus",
                    {"textDocument": {"uri": lsp.uri_for(path)}})

    # -- suggestions -------------------------------------------------------
    def complete(self, path, line, character, on_items, tab_size=4,
                 spaces=True, automatic=True, _tries=0):
        """Ask for ghost text. on_items(list_of_items, error) on the main loop.

        The server takes a couple of seconds to come up, and the request that
        triggered the start is exactly the one worth keeping, so wait for it
        rather than throwing the first one away.
        """
        if not self.ready:
            if _tries >= 12:                       # about six seconds
                on_items([], "Copilot is still starting")
                return
            GLib.timeout_add(
                500, lambda: (self.complete(path, line, character, on_items,
                                            tab_size, spaces, automatic,
                                            _tries + 1), False)[1])
            return
        version = self.open_files.get(path, 1)

        def answered(result, error):
            if error:
                on_items([], self._friendly(error))
                return
            items = (result or {}).get("items") or []
            on_items(items, "")

        self.request("textDocument/inlineCompletion", {
            "textDocument": {"uri": lsp.uri_for(path), "version": version},
            "position": {"line": line, "character": character},
            "context": {"triggerKind": 2 if automatic else 1},
            "formattingOptions": {"tabSize": tab_size, "insertSpaces": spaces},
        }, answered)

    def _friendly(self, error):
        text = str(error)
        if "NotSignedIn" in text or "Not authenticated" in text:
            return "not signed in to Copilot"
        if "NotAuthorized" in text or "subscription" in text.lower():
            return "this GitHub account has no Copilot subscription"
        return text

    def shown(self, item):
        """Copilot counts impressions; not telling it skews its own model."""
        if item:
            self.notify("textDocument/didShowCompletion", {"item": item})

    def accepted(self, item):
        command = (item or {}).get("command")
        if isinstance(command, dict) and command.get("command"):
            self.request("workspace/executeCommand",
                         {"command": command["command"],
                          "arguments": command.get("arguments") or []},
                         lambda _r, _e: None)


class Client:
    """One Copilot server for the window, started only when it is wanted."""

    def __init__(self, window):
        self.window = window
        self.server = None
        self.last_status = ("off", "")

    @property
    def command(self):
        return self.window.cfg.get("COPILOT_CMD", "copilot-language-server")

    def available(self):
        return find(self.command) is not None

    def status(self):
        if self.server is None:
            return self.last_status
        return (self.server.status_kind, self.server.status_message)

    def ensure(self):
        """Start it if it is wanted, installed and not already running."""
        if self.server is not None and self.server.alive():
            return self.server
        binary = find(self.command)
        if binary is None:
            self.last_status = ("missing", "install @github/copilot-language-server")
            return None
        self.server = Server(self.window.root, on_status=self._status,
                             on_log=lambda text: None)
        self.server.argv = [binary, "--stdio"]
        if not self.server.start():
            self.server = None
            self.last_status = ("error", "the Copilot server did not start")
            return None
        self.last_status = ("starting", "")
        return self.server

    def _status(self, kind, message):
        self.last_status = (kind, message)
        if hasattr(self.window, "copilot_status_changed"):
            GLib.idle_add(self.window.copilot_status_changed, kind, message)

    def shutdown(self):
        if self.server is not None:
            self.server.stop()
            self.server = None
