#!/usr/bin/env bash
# YazSes installer for Ubuntu/Debian
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[x]${NC} $*"; exit 1; }

echo ""
echo "  YazSes Installer"
echo "  Hold Space → speak → release → text appears anywhere"
echo ""

# 1. System dependencies
info "Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y libportaudio2 xdotool xclip pipx

# 2. Input group (evdev keyboard access)
if ! groups "$USER" | grep -qw input; then
    info "Adding $USER to the 'input' group (for keyboard access)..."
    sudo usermod -aG input "$USER"
    NEEDS_RELOGIN=1
else
    info "User $USER is already in the 'input' group."
    NEEDS_RELOGIN=0
fi

# 3. Install YazSes via pipx
info "Installing YazSes..."
pipx install yazses || pipx upgrade yazses
pipx ensurepath

# 4. Systemd user service
info "Installing systemd user service..."
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

DAEMON_BIN="$(pipx environment --value PIPX_LOCAL_VENVS)/yazses/bin/yazses-daemon"
if [ ! -f "$DAEMON_BIN" ]; then
    DAEMON_BIN="$HOME/.local/bin/yazses-daemon"
fi

cat > "$SYSTEMD_DIR/yazses.service" <<EOF
[Unit]
Description=YazSes voice dictation daemon
Documentation=https://github.com/MSKazemi/yazses
After=graphical-session.target sound.target
Wants=graphical-session.target

[Service]
Type=simple
ExecStart=$DAEMON_BIN
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=graphical-session.target
EOF

systemctl --user daemon-reload
systemctl --user enable yazses.service

# 5. Done
echo ""
echo "  ✓ YazSes installed and enabled"
echo ""

if [ "${NEEDS_RELOGIN:-0}" = "1" ]; then
    warn "You must log out and back in before using YazSes."
    warn "The 'input' group change requires a new login session."
    echo ""
    echo "  After re-login, YazSes starts automatically on each login."
    echo "  Hold Space anywhere to dictate."
else
    info "Starting YazSes now..."
    systemctl --user start yazses.service
    echo ""
    echo "  YazSes is running. Hold Space anywhere to dictate."
fi
echo ""
echo "  Commands:"
echo "    yazses status   — check if running"
echo "    yazses doctor   — check prerequisites"
echo "    yazses stop     — stop the daemon"
echo "    yazses start    — start the daemon"
echo ""
