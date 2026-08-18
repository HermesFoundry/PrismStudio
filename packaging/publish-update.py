#!/usr/bin/env python3
"""Tell every PrismStudio out there that a new version exists.

The manifest lives in the repository at `packaging/updates.json`, so what the
world is being told is in git next to the code that says it. This script edits
that file, checks it, copies it to the Hermes server and then reads it back
over the public address to prove clients will actually see it.

    ./packaging/publish-update.py --version 1.1.0 \\
        --note "Source control, the whole panel." \\
        --note "Language servers for thirteen languages." \\
        --important

    ./packaging/publish-update.py               # publish the file as it stands
    ./packaging/publish-update.py --dry-run     # show it, send nothing

The version has to match `VERSION` in app/core.py, because announcing a
release the code does not claim to be is how people end up in a loop where the
card never goes away.

The server side is set up once by `packaging/hermes-server-setup.sh`.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "updates.json")
sys.path.insert(0, os.path.join(ROOT, "app"))

# Where to publish is deployment detail, not source. It comes from the
# environment or from packaging/publish.conf, which is not in this repository:
# a public repo is no place for the address of a machine you can SSH into.
#
#     packaging/publish.conf
#     PRISM_UPDATE_HOST=user@your-server
#     PRISM_UPDATE_PATH=/var/www/prismstudio/updates.json
#     PRISM_UPDATE_URL=https://your-site/prismstudio/updates.json
SETTINGS = os.path.join(HERE, "publish.conf")


def _configured():
    """The environment wins; publish.conf fills in what it does not set."""
    values = {}
    if os.path.exists(SETTINGS):
        with open(SETTINGS) as handle:
            for line in handle:
                line = line.split("#", 1)[0].strip()
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip("\"'")
    for key in ("PRISM_UPDATE_HOST", "PRISM_UPDATE_PATH", "PRISM_UPDATE_URL"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


_CONF = _configured()
HOST = _CONF.get("PRISM_UPDATE_HOST", "")
REMOTE = _CONF.get("PRISM_UPDATE_PATH", "/var/www/prismstudio/updates.json")
PUBLIC = _CONF.get("PRISM_UPDATE_URL", "")


def today():
    return subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                          text=True).stdout.strip()


def load():
    if not os.path.exists(MANIFEST):
        return {}
    with open(MANIFEST) as handle:
        return json.load(handle)


def save(data):
    with open(MANIFEST, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", help="the version being announced")
    parser.add_argument("--note", action="append", default=[],
                        help="one line for the card; repeat for more")
    parser.add_argument("--title", help="heading on the card")
    parser.add_argument("--url", help="where the release notes live")
    parser.add_argument("--command", help="what the Update now button runs")
    parser.add_argument("--released", help="date, defaults to today")
    parser.add_argument("--important", action="store_true",
                        help="flag it as recommended for everyone")
    parser.add_argument("--not-important", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be published and stop")
    parser.add_argument("--force", action="store_true",
                        help="publish even if it disagrees with app/core.py")
    args = parser.parse_args()

    data = load()
    if args.version:
        data["version"] = args.version.strip().lstrip("vV")
        data["released"] = args.released or today()
        data.setdefault("url", "https://github.com/HermesFoundry/PrismStudio")
        data.setdefault("command", "git pull --ff-only && ./install.sh")
        data["title"] = args.title or "PrismStudio %s" % data["version"]
        if args.note:
            data["notes"] = args.note
        data["important"] = bool(args.important)
    else:
        for key, value in (("title", args.title), ("url", args.url),
                           ("released", args.released), ("command", args.command)):
            if value:
                data[key] = value
        if args.note:
            data["notes"] = args.note
        if args.important:
            data["important"] = True
    if args.not_important:
        data["important"] = False
    if args.url:
        data["url"] = args.url
    if args.command:
        data["command"] = args.command

    # -- does it hold together? --------------------------------------------
    import core
    import updates

    if not updates.parse_version(data.get("version", "")):
        sys.exit("no usable version in the manifest")
    if not data.get("notes"):
        sys.exit("a release with no notes gives people nothing to read; "
                 "add at least one --note")
    if data["version"] != core.VERSION and not args.force:
        sys.exit("the manifest says %s but app/core.py says VERSION = %r.\n"
                 "Bump core.VERSION first (and commit it), or pass --force."
                 % (data["version"], core.VERSION))

    save(data)
    body = json.dumps(data, indent=2)
    print(body)

    parsed = updates.parse_manifest(body)
    if parsed is None or parsed.version != data["version"]:
        sys.exit("the app's own parser could not read that manifest")
    print("\n· the app's parser reads it back as %s (%d notes)"
          % (parsed.version, len(parsed.notes)))

    if args.dry_run:
        print("· dry run, nothing sent")
        return 0

    if not HOST or not PUBLIC:
        return fail("no publishing target configured.\n"
                    "Write packaging/publish.conf (see the top of this file), "
                    "or set PRISM_UPDATE_HOST and PRISM_UPDATE_URL.")

    # -- send it -----------------------------------------------------------
    staging = REMOTE + ".new"
    print("· copying to %s:%s" % (HOST, REMOTE))
    result = subprocess.run(["scp", "-q", MANIFEST, "%s:%s" % (HOST, staging)])
    if result.returncode:
        return fail("could not copy the manifest to the server.\n"
                    "Has packaging/hermes-server-setup.sh been run there?")
    # Move it into place in one step, so nobody ever fetches half a file.
    result = subprocess.run(["ssh", HOST, "mv %s %s" % (staging, REMOTE)])
    if result.returncode:
        return fail("copied but could not move it into place")

    # -- and prove clients can see it --------------------------------------
    print("· reading %s back" % PUBLIC)
    try:
        request = urllib.request.Request(
            PUBLIC, headers={"User-Agent": "%s/%s" % (core.APP_NAME, core.VERSION)})
        with urllib.request.urlopen(request, timeout=15) as response:
            served = json.loads(response.read().decode())
    except Exception as exc:
        return fail("the file is on the server but the public address did not "
                    "serve it: %s" % exc)

    if served.get("version") != data["version"]:
        return fail("the address served version %r, not %r — something is "
                    "caching" % (served.get("version"), data["version"]))

    print("\npublished. PrismStudio %s is what the world is told." % data["version"])
    print("Anyone opening the app will see the card on their next check "
          "(within UPDATE_INTERVAL hours, 20 by default).")
    return 0


def fail(message):
    print("\n" + message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
