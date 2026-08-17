# PrismStudio

An editor with Claude beside it. GTK3, Python, no Electron.

It started as the code view inside Iris Terminal and outgrew it: a terminal
with an editor tab is not the same shape as an editor with a terminal panel.
This is the second shape.

```
┌──┬──────────┬───────────────────────────────┬──────────┐
│a │ side bar │ editor                        │ Claude   │
│c │          ├───────────────────────────────┤          │
│t │          │ panel: terminals, output      │          │
├──┴──────────┴───────────────────────────────┴──────────┤
│ ⎇ main    line 12, col 4   Python   assist: file        │
└─────────────────────────────────────────────────────────┘
```

```sh
./install.sh          # links `prism` into ~/.local/bin, adds a desktop entry
prism                 # reopens the folder you had last time
prism .               # this folder
prism ~/project       # that folder
prism a.py b.py       # just those files
```

Needs `python3-gi`, `gir1.2-vte-2.91`, `gir1.2-gtksource-4`. `install.sh` says
which are missing.

---

## The window

**Activity bar** down the left switches the side bar between Explorer, Search,
Run and Extensions. **Ctrl+B** hides the side bar, **Ctrl+J** the panel,
**Ctrl+Shift+C** Claude. Every divider drags.

**It opens empty.** Nothing on the machine is listed until you open a folder;
the panel offers *Open folder*, *Open file* and your recent folders, and
nothing else.

**It remembers.** Close it with four files open and it comes back with those
four files open, cursors where you left them, in the folder you were in.
Turn that off with `RESTORE_SESSION=0`.

## The editor

Several files at once, each with its own tab, undo history and cursor.
Syntax highlighting for 169 languages, **coloured from the active skin** so the
editor matches the terminal and Claude beside it rather than looking like a
different program.

| key | does |
|---|---|
| `Ctrl+N` `Ctrl+O` `Ctrl+K` | new file · open file · open folder |
| `Ctrl+S` / `Ctrl+Shift+S` | save · save as |
| `Ctrl+W` | close this file |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | next · previous file |
| `Ctrl+F` / `Ctrl+H` | find · find and replace, in this file |
| `Ctrl+Shift+F` | search every file in the workspace |
| `Ctrl+G` | go to line |
| `Ctrl+Shift+P` | command palette |

**Search** uses ripgrep when it is installed and falls back to walking the tree
in Python when it is not, so it never simply disappears. It skips `node_modules`,
`.git`, `dist`, `__pycache__` and the rest without being asked.

## Suggestions as you type

Dim text at the cursor showing what you are probably about to type. `Tab` takes
it, `Esc` drops it, `Alt+]` cycles, `Ctrl+Right` takes one word. It is drawn
over the view, never inserted, so it cannot end up in your file or undo history
by accident.

| source | where it comes from | how quick |
|---|---|---|
| **file** | words and whole lines you already have open | instant, offline |
| **Claude** | the `claude` command, asked to fill in at the cursor | about ten seconds |

Ten seconds is not a per-keystroke completion and PrismStudio does not pretend
otherwise: the Claude tier only runs after you stop typing, on a thread, and its
answer is dropped if you have moved on. The file tier is what makes typing feel
assisted; Claude is what gets a whole block right. Switch with the **assist:**
button on the status bar or `Ctrl+Shift+space`.

## Claude working on the file with you

| you do | what happens |
|---|---|
| `Ctrl+I` | say what you want changed. Claude rewrites the selection and it lands as **one** `Ctrl+Z`, tinted so you can see it |
| `Ctrl+Alt+A` | types `@thatfile.py line 40:` into the Claude pane, unsent, for you to finish |
| Claude edits a file on disk | the editor reloads it and highlights exactly what changed |

The open file is saved just before Claude reads it, so it never works from a
stale copy. That is why background autosave is **off** by default — nothing
rewrites your file until there is a reason to.

## Run the app

Open a folder and the bar above the editor reads whatever manifests are in it:

```
 ▶ Run   [ npm run dev ▾ ]   Node · npm    needs setup first    [Install packages]
 ■ Stop  [ npm run dev ▾ ]   Node · npm    http://localhost:5173  [Open in browser]
```

It takes the package manager from the **lock file** (`pnpm-lock.yaml` means
pnpm, not npm), says whether the dependencies are installed, and offers the
targets the project itself declares. **Install** runs the right command;
**Run** starts it. When the thing you started prints a localhost address, the
bar reads it out of the terminal and offers to open a browser there.

| it finds | it offers |
|---|---|
| `package.json` | every script, `dev` and `start` first, via npm / pnpm / yarn / bun |
| `manage.py` | Django's dev server, and migrate |
| Flask, FastAPI, Streamlit | the right dev server for each |
| `requirements.txt`, `pyproject.toml` | the install step, using the project's virtualenv if it has one |
| `Cargo.toml`, `go.mod`, `composer.json`, `Gemfile` | cargo, go, php, bundler |
| `docker-compose.yml` | `docker compose up` |
| `index.html` alone | a static server for the folder |
| a `Makefile` | its targets |

Everything runs in the terminal panel where you can see it, so output, prompts
and `Ctrl+C` behave exactly as if you had typed the command. Where a tool is
missing it says so rather than substituting one — a pnpm project will not
quietly get `npm install`, because that writes a second lock file that fights
the first.

`Ctrl+Shift+B` runs, `Shift+F5` stops, `Ctrl+Shift+L` opens the browser,
`F5` runs just the open file.

## The terminal panel

`Ctrl+J`, or the button in the title bar. Several terminals, a picker once
there is more than one, each with its own working directory. **Terminal here**
in the tree's right-click menu opens one in that folder. The **Output** tab is
where the app talks to you at length instead of in the status bar.

## Extensions

`Ctrl+Shift+P` opens one searchable list of everything the app can do, built-in
commands and extension commands together — loose matching, so `hvcct` finds
*Have Claude change this*. That list is what makes an extension findable.

An extension is a Python file in `~/.config/prismstudio/extensions` with a
`register(prism)` function:

```python
BLURB = "Says hello"

def register(prism):
    prism.command("hello", "Say hello", lambda: prism.status("hello"))
```

It can add commands, offer inline suggestions, and hook save and open. Install
one from **Settings → Extensions** (a file, a folder, or a git URL), toggle it
off, or remove it. A broken one is listed with its error and skipped; it cannot
stop the app from starting. They run in the editor's own process with your
permissions, so read one before you install it.

Two worked examples and the full API: [`extensions/`](extensions/).

## Skins

The same shell-variable format Iris Terminal uses, so a skin written for one
works in the other. Seven ship. The skin drives everything: window chrome,
editor syntax colours, terminal palette, the ghost text, the run bar.

Drop more in `~/.config/prismstudio/themes/`, pick one in **Settings → Look**.

## Settings

`~/.config/prismstudio/settings.conf`, shell-style `KEY=value`. Everything in
Settings writes here and applies immediately.

| | |
|---|---|
| `THEME` `FONT` `UI_FONT` | skin and type |
| `TAB_SIZE` `SPACES` `WRAP` `LINE_NUMBERS` `RIGHT_MARGIN` | the text |
| `SUGGEST` `SUGGEST_MODEL` `SUGGEST_DELAY` | inline suggestions |
| `AUTOSAVE` `FLUSH_FOR_CLAUDE` `TRIM_ON_SAVE` | saving |
| `SIDEBAR` `PANEL` `ASSISTANT` and their sizes | layout |
| `RESTORE_SESSION` `CONFIRM_CLOSE` | on open and close |
| `CLAUDE_CMD` `SHELL` `EXTENSIONS` | what it runs |

Shortcuts live in `~/.config/prismstudio/keys.conf`. Two presets: `standard`
(what an editor user expects) and `reach` (the same set moved off the plain
control keys). Rebind any of them in **Settings → Keys**.

## Checks

```sh
python3 tests/test_app.py         # window, workspace, session, panel, search
python3 tests/test_assist.py      # suggestions, ghost text, Claude's edits
python3 tests/test_extensions.py  # loading, isolation of a broken one, the palette
python3 tests/test_project.py     # what each kind of folder is detected as
python3 tests/test_runbar.py      # install, run, find the address, stop
```

283 checks. Each starts its own headless display on its own port and uses a
private application id, so a running PrismStudio cannot swallow them.
`test_runbar.py` really starts a server and really fetches from it, so it needs
a free port and takes about half a minute.

## Where things live

| what | where |
|---|---|
| the app | `app/` |
| window, layout, actions | `app/main.py` |
| settings, skins, colours | `app/core.py`, `app/styling.py` |
| editor, ghost text, suggestions | `app/editor.py`, `app/inline.py`, `app/assist.py` |
| tree, search, panel, Claude | `app/explorer.py`, `app/search.py`, `app/panel.py`, `app/assistant.py` |
| detecting and running a project | `app/project.py`, `app/runbar.py`, `app/runner.py` |
| extensions and the palette | `app/extensions.py`, `app/palette.py` |
| skins | `themes/` |
| settings | `~/.config/prismstudio/settings.conf` |
| shortcuts | `~/.config/prismstudio/keys.conf` |
| installed extensions | `~/.config/prismstudio/extensions/` |
| session and recent folders | `~/.cache/prismstudio/state.json` |

## Related

[Iris Terminal](https://github.com/HermesFoundry/iris-terminal) — the terminal
this grew out of. They share the skin format; neither needs the other.
