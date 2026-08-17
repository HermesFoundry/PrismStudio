"""Notices trailing whitespace on save, and strips it when you ask.

Shows the three hooks an extension gets beyond commands: a save hook, an open
hook, and an inline suggestion provider.
"""
NAME = "Tidy"
BLURB = "Warns about trailing whitespace and strips it on request"
VERSION = "1.0"

MARKERS = ("TODO", "FIXME", "XXX", "NOTE", "HACK")


def register(prism):
    def offenders(text):
        return [n for n, line in enumerate(text.split("\n"), 1)
                if line != line.rstrip()]

    # -- a save hook -------------------------------------------------------
    def on_save(path):
        editor = prism.editor
        if editor is None or editor.doc() is None:
            return
        bad = offenders(editor.doc().text())
        if bad:
            where = ", ".join(str(n) for n in bad[:6])
            more = " and %d more" % (len(bad) - 6) if len(bad) > 6 else ""
            prism.status("trailing whitespace on line%s %s%s"
                        % ("" if len(bad) == 1 else "s", where, more))

    prism.on_save(on_save)

    # -- a command ---------------------------------------------------------
    def strip():
        editor = prism.editor
        doc = editor.doc() if editor else None
        if doc is None:
            prism.status("nothing open")
            return
        text = doc.text()
        tidied = "\n".join(line.rstrip() for line in text.split("\n"))
        if tidied == text:
            prism.status("no trailing whitespace to strip")
            return
        buffer = doc.buffer
        offset = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
        buffer.begin_user_action()
        buffer.set_text(tidied)
        buffer.end_user_action()
        buffer.place_cursor(buffer.get_iter_at_offset(min(offset, len(tidied))))
        prism.status("stripped trailing whitespace — Ctrl+Z to undo")

    prism.command("strip", "Tidy: strip trailing whitespace", strip)

    # -- an inline suggestion ---------------------------------------------
    def suggest(before, _after, _language):
        """Finish a comment marker you have started typing."""
        tail = before.rsplit("\n", 1)[-1].lstrip("#/ \t-*")
        if len(tail) < 2:
            return None
        for marker in MARKERS:
            if marker.startswith(tail.upper()) and marker != tail.upper():
                return marker[len(tail):] + ": "
        return None

    prism.completions(suggest)
