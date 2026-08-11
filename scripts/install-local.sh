#!/usr/bin/env bash
# install-local.sh — dev install of YazSes from the local repo using uv tool.
# Run from the repo root or any subdirectory.
# Usage: bash scripts/install-local.sh [--with-overlay]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
ENV_DIR="$HOME/.config/environment.d"
AUTOSTART_DIR="$HOME/.config/autostart"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; exit 1; }

WITH_OVERLAY=0
WITH_VOICEPRINT=0
for arg in "$@"; do
    [[ "$arg" == "--with-overlay" ]] && WITH_OVERLAY=1
    [[ "$arg" == "--with-voiceprint" ]] && WITH_VOICEPRINT=1
done

# ── 1. Detect X11/Wayland display ───────────────────────────────────────────
DETECTED_DISPLAY="${DISPLAY:-}"
DETECTED_XAUTH="${XAUTHORITY:-}"

if [[ -z "$DETECTED_DISPLAY" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    warn "No DISPLAY or WAYLAND_DISPLAY detected. Run this script from a desktop terminal."
fi

# ── 2. Stop & uninstall existing installation ────────────────────────────────
info "Stopping existing services..."
systemctl --user stop yazses.service 2>/dev/null || true
systemctl --user disable yazses.service 2>/dev/null || true

info "Uninstalling previous uv tool installation..."
uv tool uninstall yazses 2>/dev/null || true

# Drop any cached yazses wheel. uv keys its build cache on the version string, so
# a same-version source change (common during local iteration) would otherwise be
# served stale — the installed code would not match the working tree.
info "Clearing cached yazses build..."
uv cache clean yazses 2>/dev/null || true

# ── 3. Fresh install from local repo ────────────────────────────────────────
info "Installing YazSes from $REPO_ROOT ..."
EXTRA_WITH=()
[[ $WITH_OVERLAY -eq 1 ]] && EXTRA_WITH+=(--with "PySide6>=6.7")
if [[ $WITH_VOICEPRINT -eq 1 ]]; then
    # Speaker voiceprint (Cocktail Filter / Voiceprint Mind). Pin CPU torch wheels
    # (UV_TORCH_BACKEND=cpu) — the default CUDA build is ~5GB and ships a torch
    # that mismatches torchaudio, breaking the ECAPA embedder.
    info "Including the voiceprint extra (speechbrain + CPU torch)..."
    export UV_TORCH_BACKEND=cpu
    EXTRA_WITH+=(--with "speechbrain>=1.1" --with "torchaudio")
fi
uv tool install --force --reinstall "${EXTRA_WITH[@]}" "$REPO_ROOT"

# ── 3b. Provision system prerequisites (idempotent) ─────────────────────────────
# A wheel can't install PortAudio, the injector binaries, or the `input` group,
# so run `yazses setup` here — the single source of truth for what dictation needs.
YZ="$(command -v yazses || echo "$HOME/.local/bin/yazses")"
if [[ -x "$YZ" ]]; then
    info "Provisioning system requirements (yazses setup)..."
    "$YZ" setup || warn "yazses setup reported issues — see above."
    if getent group input 2>/dev/null | grep -qw "$USER" && ! id -nG | grep -qw input; then
        PENDING_RELOGIN=1
    fi
else
    warn "yazses not on PATH yet — run 'yazses setup' in a new shell to finish provisioning."
fi

# ── 4. XDG autostart — makes DISPLAY available to the systemd user manager ──
# This runs at every graphical login and is the reliable cross-DE fix so that
# xdotool injection and the overlay work for any user without manual setup.
info "Installing XDG autostart entry (display environment import)..."
mkdir -p "$AUTOSTART_DIR"
cp "$REPO_ROOT/contrib/yazses-session.desktop" "$AUTOSTART_DIR/yazses-session.desktop"

# Also pin the current display immediately so the running session is covered
# without needing a re-login.
if [[ -n "$DETECTED_DISPLAY" ]]; then
    mkdir -p "$ENV_DIR"
    cat > "$ENV_DIR/yazses-display.conf" <<EOF
# Written by install-local.sh — updated on reinstall.
DISPLAY=$DETECTED_DISPLAY
XAUTHORITY=$DETECTED_XAUTH
EOF
    systemctl --user import-environment DISPLAY XAUTHORITY 2>/dev/null || true
fi

# ── 5. Install systemd unit file ────────────────────────────────────────────
info "Installing systemd unit file..."
mkdir -p "$SYSTEMD_DIR"
cp "$REPO_ROOT/contrib/yazses.service" "$SYSTEMD_DIR/yazses.service"
systemctl --user daemon-reload

# ── 6. Enable and start ──────────────────────────────────────────────────────
info "Enabling and starting yazses.service ..."
systemctl --user enable --now yazses.service

# ── 7. Verify ────────────────────────────────────────────────────────────────
echo ""
info "Service status:"
systemctl --user status yazses.service --no-pager -l | tail -8

echo ""
info "Done. $(yazses --version 2>/dev/null || echo 'Restart shell to refresh PATH')"
info "Run 'yazses status' to confirm IPC is up."
if [[ $WITH_OVERLAY -eq 0 ]]; then
    echo ""
    warn "Overlay not installed (PySide6 skipped). Re-run with --with-overlay to enable sonar rings."
fi

# ── Capabilities showcase ────────────────────────────────────────────────────
# Show everything YazSes can do (● on / ○ off) so a new user sees the full
# feature set right after install. `yazses features` is the single source of
# truth and needs no running daemon (it reads config, defaulting when absent).
echo ""
info "What YazSes can do — every capability (● on / ○ off):"
echo ""
yazses features 2>/dev/null || warn "Run 'yazses features' to list all capabilities."

if [[ "${PENDING_RELOGIN:-0}" -eq 1 ]]; then
    echo ""
    warn "One-time step: LOG OUT and back in (or reboot) to activate 'input' group membership."
    warn "Until then the hotkey can't read the keyboard. To test now without a logout:"
    warn "  sg input -c \"yazses restart\""
fi
