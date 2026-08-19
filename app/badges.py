"""badges — the little tile that says what a file is.

No icon theme on Linux ships a symbol per language, and shipping a few hundred
SVGs to solve it would be a strange thing for an editor this size to carry. So
the tiles are drawn: a rounded square tinted by the file's family with one or
two letters of its extension in it. `py` is blue, `sh` is green, `json` is
mint, and a folder is still a folder.

They are drawn once per (letters, colour, size) and kept, because this runs for
every visible row of the tree on every draw.
"""
import math

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Pango, PangoCairo  # noqa: E402

import cairo  # noqa: E402  (pulled in by gi, but named for clarity)

_cache = {}

# What goes on the tile, by extension. Anything not here falls back to the
# first two letters, which is right far more often than it is wrong. The few
# that get a symbol get it because the symbol is the thing you recognise.
LETTERS = {
    "json": "{}", "xml": "<>", "html": "<>", "htm": "<>", "svg": "<>",
    "yml": "ym", "yaml": "ym", "toml": "tm", "ini": "cf", "cfg": "cf",
    "conf": "cf", "env": "en", "lock": "lk", "css": "cs", "scss": "sc",
    "cpp": "c+", "cc": "c+", "hpp": "h+", "cs": "c#", "java": "jv",
    "php": "ph", "lua": "lu", "vue": "vu", "svelte": "sv", "swift": "sw",
    "dart": "dt", "kt": "kt", "sql": "sq", "txt": "tx", "csv": "cv",
    "mk": "mk", "bat": "bt", "ps1": "ps",
}


def letters_for(name):
    """One or two letters for a file name."""
    lowered = name.lower()
    if lowered in ("makefile", "dockerfile", "justfile", "procfile"):
        return {"makefile": "mk", "dockerfile": "dk"}.get(lowered, lowered[:2])
    if lowered.startswith(".") and "." not in lowered[1:]:
        return lowered[1:3]                 # .env -> en, .gitignore -> gi
    if "." not in lowered:
        return lowered[:2]
    ext = lowered.rsplit(".", 1)[-1]
    return LETTERS.get(ext, ext[:2] if len(ext) > 1 else ext)


def _rounded(ctx, x, y, width, height, radius):
    ctx.new_sub_path()
    ctx.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    ctx.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    ctx.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    ctx.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def _rgb(colour):
    got = Gdk.RGBA()
    got.parse(colour)
    return got.red, got.green, got.blue


def badge(text, colour, size=16):
    """A tinted tile with `text` on it, as a pixbuf, cached.

    Drawn at exactly the size it is shown at: two letters inside sixteen
    pixels only survive if Pango hints them at that size, and anything drawn
    larger and scaled down arrives as a smudge.
    """
    key = (text, colour, size)
    if key in _cache:
        return _cache[key]

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    red, green, blue = _rgb(colour)

    inset = 0.5
    _rounded(ctx, inset, inset, size - inset * 2, size - inset * 2, size * 0.26)
    ctx.set_source_rgba(red, green, blue, 0.16)
    ctx.fill_preserve()
    ctx.set_source_rgba(red, green, blue, 0.55)
    ctx.set_line_width(1)
    ctx.stroke()

    if text:
        layout = PangoCairo.create_layout(ctx)
        # Two letters have to fit inside sixteen pixels: the tile is the shape
        # you read at a glance, the letters are for when you look properly.
        points = 6.5 if len(text) > 1 else 8.5
        layout.set_font_description(
            Pango.FontDescription("Sans Bold %.1f" % points))
        layout.set_text(text, -1)
        width, height = layout.get_pixel_size()
        ctx.move_to((size - width) / 2.0, (size - height) / 2.0)
        ctx.set_source_rgba(red, green, blue, 1.0)
        PangoCairo.show_layout(ctx, layout)

    surface.flush()
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)
    _cache[key] = pixbuf
    return pixbuf


def forget():
    """A new skin means new colours, so the tiles are drawn again."""
    _cache.clear()
