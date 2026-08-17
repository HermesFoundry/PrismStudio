"""Counts what is in the file you are looking at.

Copy this into ~/.config/prismstudio/extensions/ to install it, or use
Preferences -> Extensions -> Install from file.
"""
NAME = "Word count"
BLURB = "Counts lines, words and characters in the open file"
VERSION = "1.0"


def register(prism):
    """Everything an extension does starts here."""

    def count():
        editor = prism.editor
        if editor is None or editor.doc() is None:
            prism.status("nothing open to count")
            return
        text = editor.doc().text()
        lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        prism.status("%d lines, %d words, %d characters"
                    % (lines, len(text.split()), len(text)))

    prism.command("count", "Word count: lines, words, characters", count)
