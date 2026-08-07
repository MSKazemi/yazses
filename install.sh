#!/usr/bin/env bash
# YazSes universal installer.
#
# Installs the latest YazSes, provisions every system prerequisite (audio, keystroke
# injection, clipboard, input-group, Wayland ydotoold), and verifies the result with
# `yazses doctor` — so a missing tool surfaces during install, not as a silent failure.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)
#
# This is the recommended install on Linux. It uses `uv` (installed if absent) and pulls
# the current code from git, so you get the latest fixes without waiting on a PyPI release.
# Env overrides: YAZSES_REPO, YAZSES_REF (branch/tag).
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; exit 1; }

REPO="${YAZSES_REPO:-https://github.com/MSKazemi/yazses.git}"
REF="${YAZSES_REF:-main}"

echo ""
echo "  YazSes — offline voice dictation"
echo "  Hold a key → speak → release → text appears anywhere. No cloud."
echo ""

case "$(uname -s)" in
  Linux) : ;;
  *) warn "This script targets Linux. On macOS/Windows see the README install steps." ;;
esac

# 1. Ensure uv (fast, isolated Python-tool installer). Installed to ~/.local/bin.
#    Pinned to a specific uv release and checksummed before it runs, rather than piping
#    whatever astral.sh/uv/install.sh currently serves straight into sh.
#
#    To bump: set both variables together, then verify the new digest with
#      curl -LsSf https://astral.sh/uv/<version>/install.sh | sha256sum
#    A version bumped without its digest fails closed (mismatch → abort), which is the
#    intended direction to be wrong in.
UV_INSTALLER_VERSION="0.12.3"
UV_INSTALLER_SHA256="a7e3924ea1cd06bf1518c577d635c624ae2e2db030e0fc8ff8cf426224384e17"

# sha256sum is GNU coreutils; macOS ships `shasum` instead and has no sha256sum unless
# the user installed coreutils. Without this the verification step itself fails there
# and reports a *checksum mismatch* for a file that is fine — the worst kind of security
# error, because it looks like an attack and is really a missing tool.
verify_sha256() {  # verify_sha256 <file> <expected-hex>
  if command -v sha256sum >/dev/null 2>&1; then
    echo "$2  $1" | sha256sum -c - >/dev/null 2>&1
  elif command -v shasum >/dev/null 2>&1; then
    echo "$2  $1" | shasum -a 256 -c - >/dev/null 2>&1
  else
    error "no sha256 tool found (need sha256sum or shasum) — cannot verify the uv installer."
  fi
}

if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv ${UV_INSTALLER_VERSION} (Python tool manager)..."
  uv_installer="$(mktemp)"
  # Delete the unverified download on *any* exit path, including the checksum
  # failure below — otherwise a rejected installer is left sitting in /tmp.
  trap 'rm -f "$uv_installer"' EXIT
  curl -LsSf "https://astral.sh/uv/${UV_INSTALLER_VERSION}/install.sh" -o "$uv_installer" \
    || error "could not download the uv ${UV_INSTALLER_VERSION} installer."
  verify_sha256 "$uv_installer" "$UV_INSTALLER_SHA256" \
    || error "uv installer checksum mismatch — refusing to run it. Expected ${UV_INSTALLER_SHA256}."
  sh "$uv_installer"
  rm -f "$uv_installer"
  trap - EXIT
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || error "uv is not on PATH. Add ~/.local/bin to PATH and re-run."

# 2. Install YazSes (latest from git). --force upgrades an existing install in place.
info "Installing YazSes from ${REPO}@${REF} ..."
uv tool install --force --from "git+${REPO}@${REF}" yazses \
  || error "Install failed. See the output above (need a compiler/Python? uv usually handles it)."

YZ="$(command -v yazses || echo "$HOME/.local/bin/yazses")"
[ -x "$YZ" ] || error "yazses not found after install — add ~/.local/bin to your PATH."

# 3. Provision system prerequisites in one shot: PortAudio, xdotool/ydotool/wtype,
#    xclip/wl-clipboard, the `input` group, and ydotoold on Wayland. `yazses setup` is
#    the single source of truth (it detects X11 vs Wayland and installs the right set).
info "Installing system prerequisites (yazses setup)..."
"$YZ" setup || warn "yazses setup reported issues — see above."

# 4. Verify end-to-end. doctor checks every prerequisite and prints a one-line verdict.
#    A [WARN] about the `input` group is expected until you log out and back in once.
info "Verifying your installation (yazses doctor)..."
echo ""
"$YZ" doctor 2>/dev/null || warn "Run 'yazses doctor' after the re-login below to verify."
echo ""

# 5. Next steps.
echo "  ✓ YazSes installed."
echo ""
echo "  Finish setup:"
echo "    1. If doctor flagged the 'input' group → log out and back in (once)."
echo "    2. yazses mic-level --set     tune the mic to your voice"
echo "    3. yazses start               start dictating — hold the hotkey, speak, release"
echo ""
echo "  Anytime:  yazses doctor  ·  yazses status  ·  yazses quickstart"
echo ""
