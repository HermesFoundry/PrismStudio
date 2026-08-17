"""sourcestyle — build a GtkSourceView colour scheme out of the active skin.

GtkSourceView ships schemes like cobalt and tango, none of which match a
PrismStudio skin, so the editor always looked like a visitor from another program. This
writes a scheme from the skin's own palette and registers it, which means the
editor, the terminal, the preview cards and the chrome finally agree.
"""
import os
import xml.sax.saxutils as saxutils

import gi
gi.require_version("GtkSource", "4")
from gi.repository import GtkSource  # noqa: E402

import core  # noqa: E402

CACHE = os.path.join(core.CACHE, "styles")


def _rules(t):
    """Token styles, keyed off the skin's own 16 terminal colours."""
    a = t["_ansi"]
    fg, dim, accent, accent2 = t["FG"], t["DIM"], t["ACCENT"], t["ACCENT2"]
    return [
        # name, foreground, bold, italic
        ("def:comment", dim, False, True),
        ("def:shebang", dim, True, True),
        ("def:doc-comment-element", dim, False, True),
        ("def:constant", a[14], False, False),
        ("def:string", a[10], False, False),
        ("def:special-char", a[14], False, False),
        ("def:special-constant", a[13], True, False),
        ("def:number", a[14], False, False),
        ("def:floating-point", a[14], False, False),
        ("def:decimal", a[14], False, False),
        ("def:base-n-integer", a[14], False, False),
        ("def:complex", a[14], False, False),
        ("def:character", a[10], False, False),
        ("def:boolean", a[13], True, False),
        ("def:identifier", fg, False, False),
        ("def:function", a[12], True, False),
        ("def:builtin", a[12], False, False),
        ("def:keyword", a[13], True, False),
        ("def:type", a[11], True, False),
        ("def:preprocessor", a[11], False, False),
        ("def:statement", a[13], True, False),
        ("def:operator", accent2, False, False),
        ("def:reserved", a[13], True, False),
        ("def:error", t["URGENT"], True, False),
        ("def:warning", t["ACCENT2"], False, False),
        ("def:note", accent, True, False),
        ("def:underlined", accent, False, True),
        ("def:heading", accent, True, False),
        ("def:link-destination", accent, False, True),
        ("def:list-marker", accent, True, False),
        ("xml:tag", a[13], True, False),
        ("xml:attribute-name", a[14], False, False),
        ("json:keyname", accent, False, False),
        ("diff:added-line", t["OK"], False, False),
        ("diff:removed-line", t["URGENT"], False, False),
        ("diff:location", accent2, True, False),
    ]


def scheme_xml(t):
    name = t.get("NAME", t.get("_id", "Prism"))
    ident = "prism-%s" % t.get("_id", "custom")
    bg, fg = t["BG"], t["FG"]
    panel, dim, accent = t["PANEL"], t["DIM"], t["ACCENT"]
    sel = core.mix(bg, accent, 0.32)
    current = core.mix(bg, fg, 0.06)
    gutter = core.mix(bg, fg, 0.30)

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<style-scheme id="%s" name="Prism %s" version="1.0">' % (ident, saxutils.escape(name)),
           '  <author>PrismStudio</author>',
           '  <description>Generated from the %s skin</description>' % saxutils.escape(name),
           '  <style name="text" foreground="%s" background="%s"/>' % (fg, bg),
           '  <style name="selection" foreground="%s" background="%s"/>' % (fg, sel),
           '  <style name="selection-unfocused" background="%s"/>' % core.mix(bg, fg, 0.14),
           '  <style name="current-line" background="%s"/>' % current,
           '  <style name="current-line-number" foreground="%s" bold="true"/>' % accent,
           '  <style name="line-numbers" foreground="%s" background="%s"/>' % (gutter, bg),
           '  <style name="right-margin" foreground="%s" background="%s"/>' % (dim, panel),
           '  <style name="draw-spaces" foreground="%s"/>' % core.mix(bg, fg, 0.22),
           '  <style name="background-pattern" background="%s"/>' % core.mix(bg, fg, 0.03),
           '  <style name="bracket-match" foreground="%s" background="%s" bold="true"/>'
           % (t["ACTIVE_FG"], accent),
           '  <style name="bracket-mismatch" foreground="%s" background="%s"/>'
           % (t["ACTIVE_FG"], t["URGENT"]),
           '  <style name="search-match" foreground="%s" background="%s"/>'
           % (t["ACTIVE_FG"], t["ACCENT2"]),
           ]
    for name_, colour, bold, italic in _rules(t):
        bits = ['name="%s"' % name_, 'foreground="%s"' % colour]
        if bold:
            bits.append('bold="true"')
        if italic:
            bits.append('italic="true"')
        out.append("  <style %s/>" % " ".join(bits))
    out.append("</style-scheme>")
    return "\n".join(out) + "\n"


_registered = False


def scheme_for(theme):
    """Write, register and return the scheme that matches this skin."""
    global _registered
    os.makedirs(CACHE, exist_ok=True)
    ident = "prism-%s" % theme.get("_id", "custom")
    path = os.path.join(CACHE, "%s.xml" % ident)
    try:
        wanted = scheme_xml(theme)
        if not os.path.exists(path) or open(path).read() != wanted:
            with open(path, "w") as fh:
                fh.write(wanted)
    except OSError:
        pass

    manager = GtkSource.StyleSchemeManager.get_default()
    if not _registered:
        manager.append_search_path(CACHE)
        _registered = True
    manager.force_rescan()
    scheme = manager.get_scheme(ident)
    if scheme is None:                       # never leave the editor unstyled
        scheme = manager.get_scheme("oblivion" if not theme.get("_light") else "tango")
    return scheme
