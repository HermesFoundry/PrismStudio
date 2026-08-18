"""assist — the suggestion engine behind the editor's ghost text.

Two tiers, because they have very different speeds and there is no honest way
to pretend otherwise:

  local   identifiers and repeated lines already in your buffer. Microseconds,
          offline, always available. This is what makes typing feel assisted.
  claude  the `claude` CLI in print mode, asked to fill in at the cursor. It
          answers well but takes about ten seconds on this machine, so it runs
          on a thread, only after you stop typing, and only if you turn it on.

Nothing here touches credentials. The Claude tier shells out to the same
`claude` command the terminal uses, so it runs as whoever you are already
signed in as.
"""
import os
import re
import subprocess
import threading
import time

from gi.repository import GLib

WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
IDENT_TAIL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)$")

# Enough to be useful, small enough that ranking stays instant.
MAX_INDEX = 4000
CONTEXT_BEFORE = 120
CONTEXT_AFTER = 60

KEYWORDS = {
    "python3": """and as assert async await break class continue def del elif else except
        finally for from global if import in is lambda nonlocal not or pass raise return
        try while with yield self None True False print len range enumerate isinstance
        super property staticmethod classmethod""".split(),
    "js": """async await break case catch class const continue default delete do else export
        extends finally for function if import instanceof let new return static super switch
        this throw try typeof var void while yield console document window null undefined
        true false""".split(),
    "sh": """case do done elif else esac fi for function if in local return then until while
        echo export readonly shift source unset""".split(),
    "c": """auto break case char const continue default do double else enum extern float for
        goto if inline int long register return short signed sizeof static struct switch
        typedef union unsigned void volatile while""".split(),
    "css": """align-items background border color display flex font-family font-size grid
        height justify-content margin padding position transform transition width
        z-index""".split(),
    "html": """class div href id img input link script span style table tbody td th tr
        button section header footer""".split(),
}
KEYWORDS["python"] = KEYWORDS["python3"]
for _alias, _real in (("typescript", "js"), ("javascript", "js"), ("json", "js"),
                      ("bash", "sh"), ("cpp", "c"), ("chdr", "c"), ("java", "c"),
                      ("go", "c"), ("rust", "c")):
    KEYWORDS.setdefault(_alias, KEYWORDS[_real])


class Suggestion:
    """One thing we think you might be about to type."""

    def __init__(self, text, source, detail=""):
        self.text = text
        self.source = source            # local | claude | copilot | lsp
        self.detail = detail            # shown in the status bar

    def __repr__(self):
        return "Suggestion(%r, %s)" % (self.text[:40], self.source)


# --------------------------------------------------------------------------
# the local tier
# --------------------------------------------------------------------------
class LocalEngine:
    """Completions built out of the text you already have open."""

    def __init__(self):
        self._cache = {}                # key -> (revision, counts)
        self.extra = []                 # callables added by extensions

    # -- the index ---------------------------------------------------------
    def words(self, key, text, stamp):
        """Identifiers in this buffer, cached until it changes."""
        got = self._cache.get(key)
        if got and got[0] == stamp:
            return got[1]
        found = WORD.findall(text)
        if len(found) > MAX_INDEX:
            found = found[:MAX_INDEX]
        counts = {}
        for word in found:
            if len(word) > 2:
                counts[word] = counts.get(word, 0) + 1
        self._cache[key] = (stamp, counts)
        return counts

    def forget(self, key):
        self._cache.pop(key, None)

    # -- the strategies ----------------------------------------------------
    @staticmethod
    def line_echo(before, after):
        """You are retyping a line you already wrote. Offer the rest of it.

        This is the one that earns its keep: repeated calls, repeated dict
        keys, repeated imports. It only fires on a real stem so it does not
        blurt something out after a single character.
        """
        lines = before.split("\n")
        current = lines[-1]
        stem = current.strip()
        if len(stem) < 4 or after[:1] not in ("", "\n"):
            return None
        best, best_gap = None, 1 << 30
        for gap, line in enumerate(reversed(lines[:-1])):
            candidate = line.strip()
            if len(candidate) <= len(stem) or not candidate.startswith(stem):
                continue
            if gap < best_gap:
                best, best_gap = candidate, gap
            if gap > 400:               # do not walk a huge file forever
                break
        if best is None:
            return None
        return Suggestion(best[len(stem):], "local", "repeats line above")

    def word(self, before, after, counts, language):
        """Finish the identifier under the cursor."""
        match = IDENT_TAIL.search(before)
        if not match:
            return None
        prefix = match.group(1)
        if len(prefix) < 2:
            return None
        if after[:1].isalnum() or after[:1] == "_":
            return None                 # you are typing inside a word
        pool = dict(counts)
        for keyword in KEYWORDS.get(language or "", []):
            pool.setdefault(keyword, 1)
        best, best_score = None, None
        for word, count in pool.items():
            if word == prefix or not word.startswith(prefix):
                continue
            # common beats rare, and a short finish beats a rambling one
            score = count * 10 - len(word)
            if best_score is None or score > best_score:
                best, best_score = word, score
        if best is None:
            return None
        return Suggestion(best[len(prefix):], "local", "in this file")

    # -- the front door ----------------------------------------------------
    def suggest(self, before, after, counts, language):
        out = []
        for provider in self.extra:
            try:
                got = provider(before, after, language)
            except Exception:
                continue
            if isinstance(got, Suggestion):
                out.append(got)
            elif isinstance(got, str) and got:
                out.append(Suggestion(got, "local", "extension"))
        echo = self.line_echo(before, after)
        if echo:
            out.append(echo)
        word = self.word(before, after, counts, language)
        if word:
            out.append(word)
        return out


# --------------------------------------------------------------------------
# the Claude tier
# --------------------------------------------------------------------------
FILL_SYSTEM = (
    "You complete code at a cursor. The text in <before> ends exactly at the cursor "
    "and <after> is what follows it. Reply with ONLY the raw characters to insert at "
    "the cursor: no prose, no explanation, no markdown fences, and never repeat text "
    "that is already in <before>. Complete at most a few lines. If nothing sensible "
    "fits, reply with nothing at all."
)

EDIT_SYSTEM = (
    "You rewrite a fragment of a file to satisfy an instruction. Reply with ONLY the "
    "replacement text for the fragment: no prose, no explanation, no markdown fences, "
    "and no commentary about what you changed. Keep the surrounding indentation style. "
    "If the instruction cannot be applied, reply with the fragment unchanged."
)

FENCE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\n(.*?)\n?```\s*$", re.S)


def strip_fence(text):
    """Models add fences even when told not to. Take them back off."""
    match = FENCE.match(text)
    if match:
        return match.group(1)
    return text


class ClaudeEngine:
    """Runs `claude -p` off the main loop, one question at a time."""

    def __init__(self, command="claude", model="haiku"):
        self.command = command
        self.model = model
        self.busy = False
        self.last_error = None
        self._proc = None
        self._generation = 0
        self._lock = threading.Lock()

    def available(self):
        exe = self.command.split()[0] if self.command else "claude"
        if os.path.sep in exe:
            return os.access(exe, os.X_OK)
        for folder in os.environ.get("PATH", "").split(os.pathsep):
            if folder and os.access(os.path.join(folder, exe), os.X_OK):
                return True
        return False

    def cancel(self):
        """Give up on whatever is in flight; its answer will be ignored."""
        with self._lock:
            self._generation += 1
            proc = self._proc
            self._proc = None
        self.busy = False
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def ask(self, prompt, system, cwd, done, timeout=45):
        """Run one prompt. `done(text_or_None, error_or_None)` on the main loop."""
        self.cancel()
        with self._lock:
            self._generation += 1
            mine = self._generation
        self.busy = True

        def work():
            argv = [self.command.split()[0] if self.command else "claude",
                    "-p", prompt,
                    "--model", self.model,
                    "--system-prompt", system,
                    "--disallowed-tools",
                    "Bash Edit Write Read Glob Grep WebSearch WebFetch Task TodoWrite",
                    "--no-session-persistence",
                    "--output-format", "text"]
            text, error, proc = None, None, None
            started = time.time()
            try:
                proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        cwd=cwd or None, text=True, errors="replace")
                with self._lock:
                    if mine != self._generation:
                        proc.kill()
                        return
                    self._proc = proc
                out, err = proc.communicate(timeout=timeout)
                if proc.returncode == 0:
                    text = strip_fence(out).rstrip("\n")
                else:
                    error = (err or out or "claude exited %d" % proc.returncode).strip()
            except subprocess.TimeoutExpired:
                error = "no answer within %ds" % timeout
                if proc is not None:
                    try:
                        proc.kill()
                    except OSError:
                        pass
            except OSError as exc:
                error = str(exc)
            finally:
                with self._lock:
                    if mine == self._generation:
                        self._proc = None
            if error:
                error = "%s (%.0fs)" % (error, time.time() - started)

            def deliver():
                with self._lock:
                    stale = mine != self._generation
                if not stale:
                    self.busy = False
                    self.last_error = error
                    done(text, error)
                return False

            GLib.idle_add(deliver)

        threading.Thread(target=work, daemon=True).start()

    # -- prompt shapes -----------------------------------------------------
    @staticmethod
    def fill_prompt(path, language, before, after):
        head = "\n".join(before.split("\n")[-CONTEXT_BEFORE:])
        tail = "\n".join(after.split("\n")[:CONTEXT_AFTER])
        return ('<file path="%s" language="%s">\n<before>\n%s\n</before>\n'
                '<after>\n%s\n</after>\n</file>'
                % (path or "untitled", language or "text", head, tail))

    @staticmethod
    def edit_prompt(path, language, instruction, fragment, before, after):
        head = "\n".join(before.split("\n")[-60:])
        tail = "\n".join(after.split("\n")[:40])
        return ('<file path="%s" language="%s">\n'
                '<context_before>\n%s\n</context_before>\n'
                '<fragment>\n%s\n</fragment>\n'
                '<context_after>\n%s\n</context_after>\n</file>\n\n'
                '<instruction>\n%s\n</instruction>'
                % (path or "untitled", language or "text", head, fragment, tail,
                   instruction))
