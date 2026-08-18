#!/usr/bin/env bash
# Get PrismStudio running from nothing: check what is missing, offer to install
# it, clone, set it up, and open it.
#
#     bash <(curl -fsSL https://raw.githubusercontent.com/HermesFoundry/PrismStudio/main/get.sh)
#
# It asks before it installs anything and before it uses sudo, and it prints
# every command it is about to run. Nothing here is silent.
#
#   --dry-run     say what would happen, change nothing
#   --yes         do not ask (for scripts)
#   --no-launch   set it up but do not open it
#   --dir PATH    where to put it (default ~/PrismStudio)
#
# PRISM_PM overrides package-manager detection, PRISM_DIR the location.
set -euo pipefail

REPO="https://github.com/HermesFoundry/PrismStudio.git"
DIR="${PRISM_DIR:-$HOME/PrismStudio}"
DRY=0
YES="${PRISM_YES:-0}"
LAUNCH=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)   DRY=1 ;;
    --yes|-y)    YES=1 ;;
    --no-launch) LAUNCH=0 ;;
    --dir)       DIR="${2:?--dir needs a path}"; shift ;;
    -h|--help)   sed -n '2,14p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *)           echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; N=$'\033[0m'
else
  B=""; DIM=""; R=""; G=""; Y=""; N=""
fi
say()  { printf '%s\n' "$*"; }
step() { printf '\n%s==>%s %s%s%s\n' "$G" "$N" "$B" "$*" "$N"; }
warn() { printf '%s!%s  %s\n' "$Y" "$N" "$*" >&2; }
die()  { printf '%sx%s  %s\n' "$R" "$N" "$*" >&2; exit 1; }
show() { printf '   %s$ %s%s\n' "$DIM" "$*" "$N"; }

# Prompts read from the terminal, not stdin, so this works both as
# `bash <(curl ...)` and as `curl ... | bash`, where stdin is the script.
ask() {
  [ "$YES" = "1" ] && return 0
  local reply=""
  # Opening it is the only real test: /dev/tty can exist and still fail to
  # open when there is no controlling terminal, as in a CI job or a pipe.
  if ! { exec 3<>/dev/tty; } 2>/dev/null; then
    warn "no terminal to ask on. Re-run with --yes to accept, or run it directly."
    return 1
  fi
  printf '   %s [y/N] ' "$1" >&3
  read -r reply <&3 || reply=""
  exec 3>&-
  case "$reply" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

run() {
  show "$*"
  [ "$DRY" = "1" ] && return 0
  "$@"
}

# --------------------------------------------------------------------------- #
# is this even the right kind of machine
# --------------------------------------------------------------------------- #
step "Checking the machine"
case "$(uname -s)" in
  Linux) ;;
  Darwin)
    die "PrismStudio is Linux only. It uses VTE for its terminal, which has no
    macOS build. Nothing here will work on a Mac." ;;
  MINGW*|MSYS*|CYGWIN*)
    die "This is Windows, not Linux. VTE needs a Unix pseudoterminal and has no
    Windows port, so PrismStudio cannot run natively here.
    Install WSL2 (wsl --install), open your Linux shell, and run this again." ;;
  *) die "Unsupported system: $(uname -s). PrismStudio needs Linux." ;;
esac

if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
  say "   Linux on WSL — fine, GUI apps need WSLg (Windows 11, or Windows 10 updated)."
else
  say "   $(uname -s) $(uname -m)"
fi

. /etc/os-release 2>/dev/null || true
say "   ${PRETTY_NAME:-unknown distribution}"

# --------------------------------------------------------------------------- #
# what is missing
# --------------------------------------------------------------------------- #
# Checked by importing rather than by asking the package database, because the
# package database can be right while the import still fails.
probe() {
  python3 - "$1" "$2" <<'PY' 2>/dev/null
import sys
import gi
if sys.argv[1] != "-":
    gi.require_version(sys.argv[1], sys.argv[2])
    __import__("gi.repository." + sys.argv[1])
PY
}

# PRISM_PM overrides the detection, for systems carrying more than one
# package manager and for exercising the other branches of pkg_for.
PM="${PRISM_PM:-}"
if [ -z "$PM" ]; then
  for candidate in apt-get dnf pacman zypper apk xbps-install eopkg; do
    command -v "$candidate" >/dev/null 2>&1 && { PM="$candidate"; break; }
  done
fi

# Package names differ everywhere. Keyed by what is missing, not by one blob,
# so you are only asked to install what you actually lack.
pkg_for() {
  local what="$1"
  case "$PM:$what" in
    apt-get:gi)         echo "python3-gi python3-gi-cairo" ;;
    apt-get:Gtk)        echo "gir1.2-gtk-3.0" ;;
    apt-get:Vte)        echo "gir1.2-vte-2.91" ;;
    apt-get:GtkSource)  echo "gir1.2-gtksource-4" ;;
    apt-get:PangoCairo) echo "gir1.2-pango-1.0 python3-gi-cairo" ;;
    apt-get:git)        echo "git" ;;

    dnf:gi)             echo "python3-gobject python3-cairo" ;;
    dnf:Gtk)            echo "gtk3" ;;
    dnf:Vte)            echo "vte291" ;;
    dnf:GtkSource)      echo "gtksourceview4" ;;
    dnf:PangoCairo)     echo "pango" ;;
    dnf:git)            echo "git" ;;

    pacman:gi)          echo "python-gobject python-cairo" ;;
    pacman:Gtk)         echo "gtk3" ;;
    pacman:Vte)         echo "vte3" ;;
    pacman:GtkSource)   echo "gtksourceview4" ;;
    pacman:PangoCairo)  echo "pango" ;;
    pacman:git)         echo "git" ;;

    zypper:gi)          echo "python3-gobject python3-gobject-cairo" ;;
    zypper:Gtk)         echo "typelib-1_0-Gtk-3_0" ;;
    zypper:Vte)         echo "typelib-1_0-Vte-2_91" ;;
    zypper:GtkSource)   echo "typelib-1_0-GtkSource-4" ;;
    zypper:PangoCairo)  echo "typelib-1_0-PangoCairo-1_0" ;;
    zypper:git)         echo "git" ;;

    apk:gi)             echo "py3-gobject3 py3-cairo" ;;
    apk:Gtk)            echo "gtk+3.0" ;;
    apk:Vte)            echo "vte3" ;;
    apk:GtkSource)      echo "gtksourceview4" ;;
    apk:PangoCairo)     echo "pango" ;;
    apk:git)            echo "git" ;;

    *) echo "" ;;
  esac
}

install_cmd() {
  case "$PM" in
    apt-get)      echo "apt-get install -y" ;;
    dnf)          echo "dnf install -y" ;;
    pacman)       echo "pacman -S --needed --noconfirm" ;;
    zypper)       echo "zypper install -y" ;;
    apk)          echo "apk add" ;;
    xbps-install) echo "xbps-install -y" ;;
    eopkg)        echo "eopkg install -y" ;;
    *)            echo "" ;;
  esac
}

step "Checking what PrismStudio needs"
missing_keys=()
command -v python3 >/dev/null 2>&1 || missing_keys+=("python3")
command -v git     >/dev/null 2>&1 || missing_keys+=("git")

if command -v python3 >/dev/null 2>&1; then
  python3 -c "import gi" 2>/dev/null || missing_keys+=("gi")
  for pair in "Gtk 3.0" "Vte 2.91" "GtkSource 4" "PangoCairo 1.0"; do
    set -- $pair
    if probe "$1" "$2"; then
      printf '   %sok%s   %s %s\n' "$G" "$N" "$1" "$2"
    else
      printf '   %s--%s   %s %s  %smissing%s\n' "$R" "$N" "$1" "$2" "$R" "$N"
      missing_keys+=("$1")
    fi
  done
else
  warn "no python3 at all"
  missing_keys+=("gi" "Gtk" "Vte" "GtkSource" "PangoCairo")
fi
command -v git >/dev/null 2>&1 \
  && printf '   %sok%s   git\n' "$G" "$N" \
  || printf '   %s--%s   git  %smissing%s\n' "$R" "$N" "$R" "$N"

# --------------------------------------------------------------------------- #
# offer to install it
# --------------------------------------------------------------------------- #
if [ ${#missing_keys[@]} -gt 0 ]; then
  packages=""
  for key in "${missing_keys[@]}"; do
    [ "$key" = "python3" ] && { packages="$packages python3"; continue; }
    packages="$packages $(pkg_for "$key")"
  done
  # squash duplicates while keeping the order readable
  packages="$(printf '%s\n' $packages | awk '!seen[$0]++' | tr '\n' ' ')"
  base="$(install_cmd)"

  if [ -z "$PM" ] || [ -z "$base" ] || [ -z "${packages// /}" ]; then
    warn "I do not know this distribution's package names."
    say  "   You need: PyGObject, GTK 3, VTE 2.91, GtkSourceView 4, PangoCairo, git."
    say  "   Install those, then run this again."
    exit 1
  fi

  step "Missing packages"
  say "   $packages"
  sudo_prefix=""
  [ "$(id -u)" -ne 0 ] && sudo_prefix="sudo "
  show "${sudo_prefix}${base} ${packages}"
  if ask "Install them now?"; then
    if [ "$DRY" = "0" ]; then
      # shellcheck disable=SC2086
      ${sudo_prefix}${base} ${packages} || die "the package install failed"
    fi
  else
    say "   Nothing installed. Run the command above yourself, then re-run this."
    exit 1
  fi
else
  say "   Everything it needs is already here."
fi

# --------------------------------------------------------------------------- #
# get the source
# --------------------------------------------------------------------------- #
step "Getting PrismStudio into $DIR"
if [ -d "$DIR/.git" ]; then
  if git -C "$DIR" remote get-url origin 2>/dev/null | grep -q "PrismStudio"; then
    say "   Already there; updating."
    run git -C "$DIR" pull --ff-only
  else
    die "$DIR is a git repository, but not PrismStudio. Move it, or pass --dir."
  fi
elif [ -e "$DIR" ]; then
  die "$DIR already exists and is not a PrismStudio checkout. Pass --dir somewhere else."
else
  run git clone "$REPO" "$DIR"
fi

# Nothing is compiled: PrismStudio is Python and is run from where it sits.
# install.sh only puts it on the PATH and in the applications menu.
step "Setting it up"
run bash "$DIR/install.sh"

# --------------------------------------------------------------------------- #
# the optional extras, reported and never installed behind your back
# --------------------------------------------------------------------------- #
step "Optional, for the parts that use them"
optional() {
  if command -v "$1" >/dev/null 2>&1; then
    printf '   %sok%s   %-10s %s\n' "$G" "$N" "$1" "$2"
  else
    printf '   %s--%s   %-10s %s\n' "$DIM" "$N" "$1" "$2"
  fi
}
optional rg     "much faster workspace search"
optional git    "the source control panel"
optional gh     "signing in to GitHub, cloning your repositories"
optional claude "the Claude pane and Claude suggestions"
optional node   "running Node projects, and Copilot's language server"

# --------------------------------------------------------------------------- #
step "Done"
say "   Installed at $DIR"
say "   Run it with:  prism ."
if ! printf '%s' ":$PATH:" | grep -q ":$HOME/.local/bin:"; then
  warn "$HOME/.local/bin is not on your PATH."
  say  "   Add it:  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
  say  "   Until then, run it as:  $DIR/prism ."
fi

if [ "$LAUNCH" = "1" ] && [ "$DRY" = "0" ]; then
  if [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    warn "no display detected, so not opening it. On WSL you need WSLg."
  elif ask "Open it now?"; then
    say "   starting…"
    setsid "$DIR/prism" "$DIR" >/dev/null 2>&1 < /dev/null &
    say "   opened."
  fi
fi
