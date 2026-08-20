#!/usr/bin/env python3
"""brand — turn a Code - OSS checkout into PrismStudio.

Everything this changes is either product.json or an icon, which is the whole
trick: the upstream source is left alone, so `git merge upstream/main` stays a
merge rather than an argument. Run it again after any merge.

    ./branding/brand.py            apply the branding
    ./branding/brand.py --check    say what it would change, change nothing
    ./branding/brand.py --revert   put the original product.json back

The name and the icons are ours; the code under them is Microsoft's under the
MIT licence, which covers the code and not the trademarks. That is exactly why
the branding has to be swapped rather than merely hidden.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PRODUCT = os.path.join(ROOT, "product.json")
BACKUP = os.path.join(HERE, "product.upstream.json")
OVERRIDES = os.path.join(HERE, "product.prism.json")

# where the artwork lives, and everywhere the application's own icon appears.
# The per-filetype icons (python.icns, css.ico and friends) are document icons
# rather than the product's mark, so they are left alone.
ICON_SOURCE = os.path.expanduser("~/PrismStudio/packaging/icons")
MASTER = "512.png"

PNG_TARGETS = [("512.png", "resources/linux/code.png"),
               ("512.png", "resources/darwin/code.png"),
               ("512.png", "resources/server/code-512.png"),
               ("192", "resources/server/code-192.png"),
               ("150", "resources/win32/code_150x150.png"),
               ("70", "resources/win32/code_70x70.png")]
ICO_TARGETS = ["resources/win32/code.ico", "resources/server/favicon.ico"]
ICNS_TARGETS = ["resources/darwin/code.icns"]
# the faint mark on an empty editor, which is the product's logo on screen
LETTERPRESS = ["src/vs/workbench/browser/parts/editor/media/letterpress-dark.svg",
               "src/vs/workbench/browser/parts/editor/media/letterpress-light.svg",
               "src/vs/workbench/browser/parts/editor/media/letterpress-hcDark.svg",
               "src/vs/workbench/browser/parts/editor/media/letterpress-hcLight.svg"]


def load(path):
    with open(path) as handle:
        return json.load(handle)


def main(argv):
    check = "--check" in argv
    revert = "--revert" in argv

    if revert:
        if not os.path.exists(BACKUP):
            print("nothing to revert: no saved upstream product.json")
            return 1
        shutil.copy(BACKUP, PRODUCT)
        print("product.json restored from upstream")
        return 0

    product = load(PRODUCT)
    overrides = load(OVERRIDES)

    if not os.path.exists(BACKUP) and not check:
        shutil.copy(PRODUCT, BACKUP)
        print("kept the upstream product.json at branding/product.upstream.json")

    changed = []
    for key, value in overrides.items():
        if product.get(key) != value:
            changed.append("%s: %r -> %r" % (key, product.get(key), value))
            product[key] = value
    for line in changed:
        print(("would set " if check else "set ") + line)
    if not changed:
        print("product.json already carries the branding")

    if not check:
        with open(PRODUCT, "w") as handle:
            json.dump(product, handle, indent="\t")
            handle.write("\n")

    if check:
        print("would replace %d pngs, %d icos, %d icns and %d letterpress marks"
              % (len(PNG_TARGETS), len(ICO_TARGETS), len(ICNS_TARGETS),
                 len(LETTERPRESS)))
        return 0
    return icons()


def icons():
    """Put our mark everywhere the product's own icon is used."""
    master_path = os.path.join(ICON_SOURCE, MASTER)
    if not os.path.exists(master_path):
        print("no artwork at %s — icons left as they are" % master_path)
        return 1
    try:
        from PIL import Image
    except ImportError:
        print("Pillow is not installed; only the plain copies were made")
        Image = None

    done = 0
    for source, target in PNG_TARGETS:
        full_target = os.path.join(ROOT, target)
        if not os.path.isdir(os.path.dirname(full_target)):
            continue
        if source.endswith(".png"):
            shutil.copy(os.path.join(ICON_SOURCE, source), full_target)
        elif Image is not None:
            size = int(source)
            Image.open(master_path).resize((size, size), Image.LANCZOS).save(full_target)
        else:
            continue
        done += 1

    if Image is not None:
        master = Image.open(master_path).convert("RGBA")
        for target in ICO_TARGETS:
            full_target = os.path.join(ROOT, target)
            if os.path.isdir(os.path.dirname(full_target)):
                master.save(full_target,
                            sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                   (64, 64), (128, 128), (256, 256)])
                done += 1
        for target in ICNS_TARGETS:
            full_target = os.path.join(ROOT, target)
            if os.path.isdir(os.path.dirname(full_target)):
                try:
                    master.resize((1024, 1024), Image.LANCZOS).save(full_target)
                    done += 1
                except Exception as exc:
                    print("could not write %s (%s)" % (target, exc))
        done += letterpress(master_path)
    print("replaced %d icon files" % done)
    return 0


def letterpress(master_path):
    """The mark shown faintly behind an empty editor.

    An SVG carrying the artwork inline, so there is one file to write and no
    second asset to keep in step.
    """
    import base64
    with open(master_path, "rb") as handle:
        data = base64.b64encode(handle.read()).decode("ascii")
    written = 0
    for target in LETTERPRESS:
        full_target = os.path.join(ROOT, target)
        if not os.path.isdir(os.path.dirname(full_target)):
            continue
        faint = 0.14 if "light" in os.path.basename(target).lower() else 0.10
        with open(full_target, "w") as handle:
            handle.write(
                '<svg xmlns="http://www.w3.org/2000/svg" '
                'xmlns:xlink="http://www.w3.org/1999/xlink" '
                'width="260" height="260" viewBox="0 0 260 260">\n'
                '  <image width="260" height="260" opacity="%s" '
                'xlink:href="data:image/png;base64,%s"/>\n</svg>\n'
                % (faint, data))
        written += 1
    return written


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
