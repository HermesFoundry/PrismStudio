#!/usr/bin/env bash
# Give PrismStudio somewhere on the Hermes server to publish updates from.
#
# Run this ON the server, once, as root:
#
#     sudo bash hermes-server-setup.sh
#
# It makes /var/www/prismstudio, writable by the deploy user, and serves it at
# https://hermesarcade.co.za/prismstudio/. It touches nothing else: the casino
# proxy, the HermesOS downloads and the Jenkins redirects are left exactly as
# they are, and if nginx does not like the result the old config goes back.
#
# Running it twice is fine. It replaces its own block rather than stacking.
set -euo pipefail

SITE="${SITE:-/etc/nginx/sites-available/hermesarcade.co.za}"
OWNER="${OWNER:-${SUDO_USER:-root}}"
ROOT_DIR="${ROOT_DIR:-/var/www/prismstudio}"
BEGIN="# >>> prismstudio updates >>>"
END="# <<< prismstudio updates <<<"

if [ "$(id -u)" -ne 0 ]; then
  echo "this needs root: sudo bash $0" >&2
  exit 1
fi
[ -f "$SITE" ] || { echo "no site config at $SITE" >&2; exit 1; }
id "$OWNER" >/dev/null 2>&1 || { echo "no such user: $OWNER" >&2; exit 1; }

# ---- the directory --------------------------------------------------------
mkdir -p "$ROOT_DIR"
chown "$OWNER":www-data "$ROOT_DIR"
chmod 755 "$ROOT_DIR"
echo "· $ROOT_DIR ready, owned by $OWNER"

# A manifest so the address answers something the moment nginx reloads.
if [ ! -f "$ROOT_DIR/updates.json" ]; then
  cat > "$ROOT_DIR/updates.json" <<'JSON'
{
  "version": "1.0.0",
  "released": "2026-08-18",
  "title": "PrismStudio 1.0.0",
  "notes": ["Nothing newer yet."],
  "url": "https://github.com/HermesFoundry/PrismStudio"
}
JSON
  chown "$OWNER":www-data "$ROOT_DIR/updates.json"
  echo "· wrote a placeholder updates.json"
fi

# ---- the nginx block ------------------------------------------------------
BACKUP="${SITE}.bak.$(date +%Y%m%d-%H%M%S)"
cp -a "$SITE" "$BACKUP"
echo "· backed the config up to $BACKUP"

# Drop any previous copy of our block, then add the current one before the
# closing brace of the hermesarcade.co.za server.
python3 - "$SITE" "$BEGIN" "$END" "$ROOT_DIR" <<'PY'
import re
import sys

path, begin, end, root = sys.argv[1:5]
with open(path) as handle:
    text = handle.read()

text = re.sub(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", "",
              text, flags=re.S)

block = """%s
    # The desktop app asks here whether there is a newer version. A few
    # hundred bytes of JSON, and a stale answer just delays the notice, so
    # there is nothing to gain by caching it.
    location = /prismstudio { return 301 /prismstudio/; }
    location /prismstudio/ {
        alias %s/;
        autoindex off;
        types { application/json json; }
        default_type application/json;
        add_header Cache-Control "no-cache";
        add_header X-Content-Type-Options nosniff;
    }
%s
""" % (begin, root.rstrip("/"), end)

# Find the server block for the bare domain and insert before its final brace.
match = re.search(r"server\s*\{[^{}]*server_name\s+hermesarcade\.co\.za\s*;",
                  text)
if not match:
    sys.exit("could not find the hermesarcade.co.za server block")
depth, index = 0, match.start()
while index < len(text):
    if text[index] == "{":
        depth += 1
    elif text[index] == "}":
        depth -= 1
        if depth == 0:
            break
    index += 1
else:
    sys.exit("the server block is not closed")

with open(path, "w") as handle:
    handle.write(text[:index] + block + text[index:])
print("· inserted the /prismstudio/ location")
PY

# ---- prove it before committing to it -------------------------------------
if nginx -t >/dev/null 2>&1; then
  systemctl reload nginx
  echo "· nginx checked out and reloaded"
else
  cp -a "$BACKUP" "$SITE"
  echo "nginx rejected the new config, so the old one is back:" >&2
  nginx -t || true
  exit 1
fi

sleep 1
if curl -fsS --max-time 10 https://hermesarcade.co.za/prismstudio/updates.json \
     >/dev/null 2>&1; then
  echo
  echo "done. https://hermesarcade.co.za/prismstudio/updates.json is live."
  echo "publish new versions from the workstation with:"
  echo "    ~/PrismStudio/packaging/publish-update.py --version 1.1.0 --note \"...\""
else
  echo
  echo "the location is in place but the public URL did not answer." >&2
  echo "check DNS/TLS by hand: curl -v https://hermesarcade.co.za/prismstudio/updates.json" >&2
fi
