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
    """Token styles.

    A skin may name its token colours — SYN_KEYWORD, SYN_STRING and the rest —
    and a skin copied from somewhere else usually should, because the token
    palette is half of what makes an editor recognisable. Anything it does not
    name is keyed off its own sixteen terminal colours as before.
    """
    a = t["_ansi"]
    fg, dim, accent, accent2 = t["FG"], t["DIM"], t["ACCENT"], t["ACCENT2"]

    def syn(key, fallback):
        return t.get(key) or fallback

    comment = syn("SYN_COMMENT", dim)
    string = syn("SYN_STRING", a[10])
    number = syn("SYN_NUMBER", a[14])
    keyword = syn("SYN_KEYWORD", a[13])
    control = syn("SYN_CONTROL", keyword)
    function = syn("SYN_FUNCTION", a[12])
    type_ = syn("SYN_TYPE", a[11])
    variable = syn("SYN_VARIABLE", fg)
    constant = syn("SYN_CONSTANT", a[14])
    operator = syn("SYN_OPERATOR", accent2)
    if t.get("SYN_KEYWORD"):
        # A named palette means the weights come with it: Dark+ and everything
        # like it colour tokens and leave the weight alone.
        return [
            ("def:comment", comment, False, False),
            ("def:shebang", comment, False, False),
            ("def:doc-comment-element", comment, False, False),
            ("def:constant", constant, False, False),
            ("def:string", string, False, False),
            ("def:special-char", syn("SYN_CONSTANT", constant), False, False),
            ("def:special-constant", constant, False, False),
            ("def:number", number, False, False),
            ("def:floating-point", number, False, False),
            ("def:decimal", number, False, False),
            ("def:base-n-integer", number, False, False),
            ("def:complex", number, False, False),
            ("def:character", string, False, False),
            ("def:boolean", keyword, False, False),
            ("def:identifier", variable, False, False),
            ("def:function", function, False, False),
            ("def:builtin", function, False, False),
            ("def:keyword", control, False, False),
            ("def:type", type_, False, False),
            ("def:preprocessor", function, False, False),
            ("def:statement", control, False, False),
            ("def:operator", operator, False, False),
            ("def:reserved", keyword, False, False),
            ("def:error", t["URGENT"], False, False),
            ("def:warning", syn("SYN_NUMBER", number), False, False),
            ("def:note", comment, False, False),
            ("def:underlined", accent, False, True),
            ("def:heading", keyword, False, False),
            ("def:link-destination", string, False, True),
            ("def:list-marker", keyword, False, False),
            ("xml:tag", keyword, False, False),
            ("xml:attribute-name", variable, False, False),
            ("json:keyname", variable, False, False),
            ("diff:added-line", t["OK"], False, False),
            ("diff:removed-line", t["URGENT"], False, False),
            ("diff:location", function, False, False),
        ]
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
    sel = t.get("SELECTION_BG") or core.mix(bg, accent, 0.32)
    current = t.get("CURRENT_LINE") or core.mix(bg, fg, 0.06)
    gutter = t.get("LINE_NUMBER") or core.mix(bg, fg, 0.30)
    gutter_now = t.get("LINE_NUMBER_ACTIVE") or accent

    text_fg = t.get("SYN_TEXT") or fg
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<style-scheme id="%s" name="Prism %s" version="1.0">' % (ident, saxutils.escape(name)),
           '  <author>PrismStudio</author>',
           '  <description>Generated from the %s skin</description>' % saxutils.escape(name),
           '  <style name="text" foreground="%s" background="%s"/>' % (text_fg, bg),
           '  <style name="selection" background="%s"/>' % sel,
           '  <style name="selection-unfocused" background="%s"/>' % core.mix(bg, fg, 0.14),
           '  <style name="current-line" background="%s"/>' % current,
           '  <style name="current-line-number" foreground="%s"/>' % gutter_now,
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
