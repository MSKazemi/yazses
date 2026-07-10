#!/usr/bin/env bash
# YazSes APT installer for Debian/Ubuntu.
# Adds the YazSes APT repository, installs yazses, and enables the user service.
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; exit 1; }

# The apt repo lives on the gh-pages branch. GitHub Pages on this repo serves the
# docs site from main, so it does NOT serve gh-pages — the raw.githubusercontent
# URL is the canonical apt channel; the Pages URL is only tried as a fallback in
# case Pages is ever reconfigured. YAZSES_APT_BASE_URL overrides both.
RAW_BASE="https://raw.githubusercontent.com/MSKazemi/yazses/gh-pages/apt"
PAGES_BASE="https://mskazemi.github.io/yazses/apt"
KEYRING="/usr/share/keyrings/yazses.gpg"
SOURCE_LIST="/etc/apt/sources.list.d/yazses.list"
TMP_KEY="$(mktemp)"
trap 'rm -f "$TMP_KEY"' EXIT

echo ""
echo "  YazSes APT Installer"
echo "  Hold Space → speak → release → text appears anywhere"
echo ""

if ! command -v curl >/dev/null 2>&1; then
  info "Installing curl..."
  sudo apt-get update -qq
  sudo apt-get install -y curl ca-certificates gnupg
else
  sudo apt-get install -y -qq ca-certificates gnupg >/dev/null
fi

info "Locating YazSes APT repository..."
BASE_URL=""
for cand in "${YAZSES_APT_BASE_URL:-}" "$RAW_BASE" "$PAGES_BASE"; do
  [ -n "$cand" ] || continue
  if curl -fsSL "$cand/KEY.gpg" -o "$TMP_KEY" 2>/dev/null; then
    BASE_URL="$cand"
    break
  fi
done
[ -n "$BASE_URL" ] || error "Could not download the YazSes APT signing key from any known URL."
info "Using APT repository: $BASE_URL"

info "Installing APT signing key..."
sudo install -d -m 0755 /usr/share/keyrings
sudo rm -f "$KEYRING"
sudo gpg --batch --yes --dearmor -o "$KEYRING" "$TMP_KEY"
sudo chmod 0644 "$KEYRING"

info "Adding YazSes APT source: $BASE_URL"
echo "deb [signed-by=$KEYRING] $BASE_URL ./" | sudo tee "$SOURCE_LIST" >/dev/null

info "Updating package lists..."
sudo apt-get update

info "Installing YazSes..."
sudo apt-get install -y yazses

# The .deb declares libportaudio2 + pipx hard, but injection/clipboard are
# alternatives (xdotool | ydotool | wtype, xclip | wl-clipboard) so apt installs
# only the first. Install the full set explicitly so dictation works on BOTH X11
# (xdotool/xclip) and Wayland (wtype/ydotool/wl-clipboard) regardless of session.
# libportaudio2 is listed again for the belt-and-braces case. Tolerate any single
# package being absent on older releases — YazSes only needs one backend per role.
info "Installing audio + input/clipboard backends (X11 and Wayland)..."
for pkg in libportaudio2 xdotool ydotool wtype xclip wl-clipboard; do
  sudo apt-get install -y "$pkg" >/dev/null 2>&1 \
    && info "  installed $pkg" \
    || warn "  $pkg unavailable on this release (skipped)"
done

if ! groups "$USER" | grep -qw input; then
  info "Adding $USER to the input group for keyboard access..."
  sudo usermod -aG input "$USER"
  NEEDS_RELOGIN=1
else
  NEEDS_RELOGIN=0
fi

# On Wayland, keystroke injection needs ydotoold running (the only option on
# GNOME/KDE Wayland, where wtype is blocked). Set up + enable its user service so
# injection works out of the box. Needs the input group for /dev/uinput access,
# so it may only start after the next login.
if [ -n "${WAYLAND_DISPLAY:-}" ] && command -v ydotoold >/dev/null 2>&1; then
  info "Setting up ydotoold (Wayland keystroke injection)..."
  install -d "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/ydotoold.service" <<'YDOTOOLD'
[Unit]
Description=ydotoold — virtual input daemon (required for Wayland keystroke injection)
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/ydotoold --socket-path=%t/.ydotool_socket --socket-own=%U:%G
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
YDOTOOLD
fi

if command -v systemctl >/dev/null 2>&1; then
  info "Enabling YazSes user service..."
  systemctl --user daemon-reload || true
  systemctl --user enable yazses.service || true
  if [ -f "$HOME/.config/systemd/user/ydotoold.service" ]; then
    systemctl --user enable ydotoold.service || true
  fi
  if [ "${NEEDS_RELOGIN:-0}" = "0" ]; then
    systemctl --user start yazses.service || true
    [ -f "$HOME/.config/systemd/user/ydotoold.service" ] && systemctl --user start ydotoold.service || true
  fi
fi

echo ""
echo "  ✓ YazSes installed via APT"
echo ""
if [ "${NEEDS_RELOGIN:-0}" = "1" ]; then
  warn "Log out and back in before using YazSes. The input group change needs a new login session."
fi

echo "  Next steps — finish setting up:"
if [ "${NEEDS_RELOGIN:-0}" = "1" ]; then
  echo "    1. Log out and back in            (so the 'input' group takes effect)"
  echo "    2. yazses mic-level --set         connect your voice — tune the mic threshold"
  echo "    3. yazses start                   start dictating (hold the hotkey, speak, release)"
else
  echo "    1. yazses mic-level --set         connect your voice — tune the mic threshold"
  echo "    2. yazses start                   start dictating (hold the hotkey, speak, release)"
fi
echo ""
echo "  Anytime:  yazses doctor  (check prerequisites)   yazses status  (is it running?)"
echo ""

# Show every capability (● on / ○ off) so a new user sees the full feature set.
# `yazses features` is the single source of truth and needs no running daemon.
echo "  What YazSes can do — every capability (● on / ○ off):"
echo ""
yazses features 2>/dev/null || echo "    Run 'yazses features' to list all capabilities."
echo ""
