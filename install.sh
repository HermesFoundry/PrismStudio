#!/usr/bin/env bash
# Put PrismStudio on the PATH and in the applications menu.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${HOME}/.local/bin"
APPS="${HOME}/.local/share/applications"
ICONS="${HOME}/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$BIN" "$APPS" "$ICONS"
ln -sf "$HERE/prism" "$BIN/prism"
echo "linked  $BIN/prism"

sed "s|__PRISM__|$HERE/prism|g" \
  "$HERE/packaging/foundry.hermes.PrismStudio.desktop.in" \
  > "$APPS/foundry.hermes.PrismStudio.desktop"
cp "$HERE/packaging/foundry.hermes.PrismStudio.svg" \
  "$ICONS/foundry.hermes.PrismStudio.svg"
echo "installed the desktop entry and icon"

command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" || true
command -v gtk-update-icon-cache >/dev/null && \
  gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true

missing=()
python3 -c "import gi" 2>/dev/null || missing+=("python3-gi")
python3 -c "import gi; gi.require_version('Vte','2.91')" 2>/dev/null || missing+=("gir1.2-vte-2.91")
python3 -c "import gi; gi.require_version('GtkSource','4')" 2>/dev/null || missing+=("gir1.2-gtksource-4")
if [ ${#missing[@]} -gt 0 ]; then
  echo
  echo "still needed:  sudo apt install ${missing[*]}"
else
  echo
  echo "everything it needs is present. Run:  prism ."
fi
