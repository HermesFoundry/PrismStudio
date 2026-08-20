#!/usr/bin/env bash
# Build ~/.local/prismdeps from the archive, without touching the system.
set -u
PREFIX="${PRISM_DEPS:-$HOME/.local/prismdeps}"
WORK="$(mktemp -d)"
mkdir -p "$PREFIX"
cd "$WORK"
for p in libxkbfile-dev libsecret-1-dev libkrb5-dev krb5-multidev comerr-dev; do
  apt-get download "$p" >/dev/null 2>&1 && echo "fetched $p" || echo "skipped $p"
done
for d in *.deb; do dpkg -x "$d" "$PREFIX" 2>/dev/null; done
# the unversioned link names ship in the -dev packages but point at files that
# only exist here as versioned libraries, so aim them at those
LIB="$PREFIX/usr/lib/x86_64-linux-gnu"
for name in krb5 krb5support k5crypto gssapi_krb5 com_err; do
  system=$(ls /usr/lib/x86_64-linux-gnu/lib${name}.so.* 2>/dev/null | head -1)
  [ -n "$system" ] && ln -sfn "$system" "$LIB/lib${name}.so"
done
for link in "$LIB"/*.so; do
  [ -L "$link" ] && [ ! -e "$link" ] || continue
  target="/usr/lib/x86_64-linux-gnu/$(basename "$(readlink "$link")")"
  [ -e "$target" ] && ln -sfn "$target" "$link"
done
rm -rf "$WORK"
echo "prefix ready at $PREFIX"
