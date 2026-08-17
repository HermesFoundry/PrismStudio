# Writing a PrismStudio extension

An extension is one Python file (`thing.py`) or one folder with an
`__init__.py`, living in `~/.config/prismstudio/extensions/`. It needs one function:

```python
def register(prism):
    ...
```

Install one with **Preferences → Extensions → Install from file / folder / git**,
or just copy it into that folder and restart PrismStudio.

## What `prism` gives you

| Call | What it does |
| --- | --- |
| `prism.command(id, label, fn, keys="")` | Adds an entry to the command palette (`Ctrl+Shift+P`) |
| `prism.completions(fn)` | `fn(before, after, language)` returns a string to offer as ghost text, or `None` |
| `prism.on_save(fn)` | `fn(path)` runs after a file is written |
| `prism.on_open(fn)` | `fn(path)` runs after a file is opened |
| `prism.status(text)` | Puts a line in the editor's status bar |
| `prism.editor` | The editor in the tab you are looking at, or `None` |
| `prism.window` | The PrismStudio window, if you need to go deeper |
| `prism.config` | A copy of the current settings |

Optional module-level `NAME`, `BLURB` and `VERSION` show up in the extensions
list. Without a `BLURB`, the first line of the docstring is used.

## The smallest useful one

```python
BLURB = "Says hello"

def register(prism):
    prism.command("hello", "Say hello", lambda: prism.status("hello"))
```

## The two examples here

- **`wordcount.py`** — one command, reads the open document.
- **`tidy.py`** — a save hook, a command that edits the buffer as one undo
  step, and an inline suggestion provider.

## Things worth knowing

- Extensions are plain Python in the editor's own process. There is no sandbox:
  an extension can do anything you can do. Read one before you install it.
- A broken extension is reported in Preferences → Extensions and skipped. It
  will not stop PrismStudio from starting.
- A suggestion provider runs on every keystroke pause, so keep it quick and
  return `None` early. Raising is caught and ignored, but it costs you the
  suggestion.
- Buffer edits should be wrapped in `begin_user_action()` / `end_user_action()`
  so the whole change is a single `Ctrl+Z`.
