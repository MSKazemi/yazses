#!/usr/bin/env bash
# dev-install.sh — one command that makes YazSes work from the local repo.
#
# It does the WHOLE local-dev loop, in order, so you never rediscover a missing
# prerequisite by hand again:
#   1. Provision every system requirement  (yazses setup: PortAudio + injector +
#      the `input` group + ydotoold on Wayland).
#   2. Install YazSes from THIS repo as an editable `uv tool`  (`yazses` on PATH).
#   3. Start exactly one daemon — using `sg input` when the `input` group isn't
#      live yet, so the hotkey works immediately without a logout.
#   4. Tell you clearly if a real re-login is still needed to make it permanent.
#
# Usage:  bash scripts/dev-install.sh [--with-overlay] [--with-voiceprint]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; exit 1; }

PASS_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --with-overlay|--with-voiceprint) PASS_ARGS+=("$arg") ;;
        *) warn "ignoring unknown arg: $arg" ;;
    esac
done

command -v uv >/dev/null 2>&1 || error "uv not found. Install it: https://docs.astral.sh/uv/"

# ── 1. Install YazSes from the local repo (also gives us the `yazses setup` CLI) ─
# install-local.sh does the editable uv-tool install + systemd/autostart wiring.
info "Installing YazSes from $REPO_ROOT (editable uv tool)..."
bash "$REPO_ROOT/scripts/install-local.sh" "${PASS_ARGS[@]}"

YZ="$(command -v yazses || echo "$HOME/.local/bin/yazses")"
[ -x "$YZ" ] || error "yazses not on PATH after install. Open a new shell and re-run, or check 'uv tool dir'."

# ── 2. Provision all system prerequisites in one shot ───────────────────────────
info "Provisioning system requirements (yazses setup)..."
"$YZ" setup || warn "yazses setup reported issues — see above."

# ── 3. Start one daemon, bridging the input group if this session predates it ────
# `getent group input` reflects usermod; os session groups may lag until re-login.
if getent group input 2>/dev/null | grep -qw "${USER}" && ! id -nG | grep -qw input; then
    RELOGIN_PENDING=1
    info "Starting the daemon with 'sg input' (bridges the pending group change)..."
    sg input -c "$YZ restart" || warn "could not start daemon under sg input."
else
    RELOGIN_PENDING=0
    info "Starting the daemon..."
    "$YZ" restart || warn "could not start daemon."
fi

# ── 4. Report ───────────────────────────────────────────────────────────────────
echo ""
"$YZ" status 2>/dev/null | head -6 || true
echo ""
info "Verify prerequisites any time with:  yazses doctor"
if [ "${RELOGIN_PENDING:-0}" = "1" ]; then
    echo ""
    warn "One-time step remaining: LOG OUT and back in (or reboot)."
    warn "You were just added to the 'input' group; this session predates it, so the"
    warn "daemon is running via an 'sg input' bridge for now. After re-login a plain"
    warn "'yazses start' will just work — you won't need to do any of this again."
fi
