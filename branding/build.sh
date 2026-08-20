#!/usr/bin/env bash
# build — Code - OSS, branded PrismStudio, from a clean checkout.
#
#   ./branding/build.sh deps       say what the machine is still missing
#   ./branding/build.sh dev        install, brand, compile, and run from source
#   ./branding/build.sh package    the same, then a distributable tree
#
# Everything is resumable: npm install and the compile both no-op when they
# have nothing to do, so a failed run costs the failed step and nothing else.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

NEEDED=(libxkbfile-dev libsecret-1-dev libkrb5-dev)

# The same headers, unpacked into a prefix of our own where the system has
# none. Sourcing this is what makes the build work without root.
[ -f "$HERE/localdeps.sh" ] && . "$HERE/localdeps.sh"

# The tree pins its node version and the preinstall check enforces it. Use
# that version for the build only; the shell default is left alone.
if [ -s "$ROOT/.nvmrc" ] && [ -s "$HOME/.nvm/nvm.sh" ]; then
  export NVM_DIR="$HOME/.nvm"
  . "$NVM_DIR/nvm.sh"
  nvm use "$(cat "$ROOT/.nvmrc")" >/dev/null 2>&1 || nvm install "$(cat "$ROOT/.nvmrc")"
fi

deps() {
  local missing=()
  for package in "${NEEDED[@]}"; do
    dpkg -s "$package" >/dev/null 2>&1 || missing+=("$package")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    if [ -d "${PRISM_DEPS:-$HOME/.local/prismdeps}/usr/include" ]; then
      echo "system packages missing (${missing[*]}) — using the local prefix instead"
    else
      echo "missing ${missing[*]}"
      echo "either:  sudo apt install ${missing[*]}"
      echo "or:      ./branding/fetch-localdeps.sh   (no root)"
      return 1
    fi
  else
    echo "every native dependency is present"
  fi
  # the build wants room: node_modules and the compile together are ~5G
  local free
  free=$(df --output=avail -BG "$ROOT" | tail -1 | tr -dc '0-9')
  echo "disk free: ${free}G"
  [ "$free" -ge 6 ] || echo "warning: under 6G free, the build may not finish"
  return 0
}

install_deps() {
  echo "== npm install (this is the long one) =="
  npm install
}

brand() {
  echo "== branding =="
  "$HERE/brand.py"
}

compile() {
  echo "== compile =="
  npm run compile
}

case "${1:-dev}" in
  deps)    deps ;;
  dev)     deps && install_deps && brand && compile
           echo
           echo "run it with:  ./scripts/code.sh" ;;
  package) deps && install_deps && brand && compile
           echo "== packaging =="
           npx gulp vscode-linux-x64-min
           echo
           echo "built into ../VSCode-linux-x64 — rename it and ship" ;;
  *)       echo "usage: build.sh [deps|dev|package]"; exit 2 ;;
esac
