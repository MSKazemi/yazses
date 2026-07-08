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

# 1. Bootstrap dependency: pipx (the rest are provisioned by `yazses setup` below,
#    which installs the full audio + injection stack for BOTH X11 and Wayland and
#    joins the `input` group — the single source of truth so this never drifts).
info "Installing pipx..."
sudo apt-get update -qq
sudo apt-get install -y pipx

# 2. Install YazSes via pipx
info "Installing YazSes..."
pipx install yazses || pipx upgrade yazses
pipx ensurepath
YZ="$(command -v yazses || echo "$HOME/.local/bin/yazses")"

# 3. Provision every runtime prerequisite in one shot (PortAudio, xdotool/xclip,
#    ydotool/wtype/wl-clipboard, `input` group, and ydotoold on Wayland).
info "Provisioning system requirements (yazses setup)..."
if getent group input 2>/dev/null | grep -qw "$USER"; then NEEDS_RELOGIN=0; else NEEDS_RELOGIN=1; fi
"$YZ" setup || warn "yazses setup reported issues — see above."
# Re-check: setup may have just added us to the group (needs a fresh login).
if getent group input 2>/dev/null | grep -qw "$USER" && ! id -nG | grep -qw input; then
    NEEDS_RELOGIN=1
fi

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
StartLimitIntervalSec=60
StartLimitBurst=5

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

# Show every capability (● on / ○ off) so a new user sees the full feature set.
# `yazses features` is the single source of truth and needs no running daemon.
echo "  What YazSes can do — every capability (● on / ○ off):"
echo ""
yazses features 2>/dev/null || echo "    Run 'yazses features' to list all capabilities."
echo ""
