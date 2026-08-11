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
#
# Piping a script from the internet into a shell asks for a lot of trust, so this one can
# show its work first and change nothing:
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh) --dry-run
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; exit 1; }

REPO="${YAZSES_REPO:-https://github.com/MSKazemi/yazses.git}"
REF="${YAZSES_REF:-main}"
DRY_RUN=0

usage() {
  cat <<'USAGE'
YazSes installer — offline voice dictation for Linux.

Usage: install.sh [--dry-run] [--help]

  -n, --dry-run   Inspect this machine and print every change that would be made,
                  then exit without making any of them. Installs nothing, downloads
                  nothing, and needs no privileges.
  -h, --help      Show this message and exit.

Environment:
  YAZSES_REPO     Git repository to install from.
  YAZSES_REF      Branch or tag to install (default: main).

Docs: https://mskazemi.com/yazses/
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    -n|--dry-run) DRY_RUN=1 ;;
    -h|--help)    usage; exit 0 ;;
    *)            error "unknown option: $1  (try --help)" ;;
  esac
  shift
done

# Execute a command, or in --dry-run describe it and change nothing. Every mutating
# step in this script goes through here, so --dry-run cannot drift from the real run.
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo -e "${YELLOW}[dry-run]${NC} would run: $*"
    return 0
  fi
  "$@"
}

echo ""
echo "  YazSes — offline voice dictation"
echo "  Hold a key → speak → release → text appears anywhere. No cloud."
echo ""

case "$(uname -s)" in
  Linux) : ;;
  *) warn "This script targets Linux. On macOS/Windows see the README install steps." ;;
esac

# 0. Preflight: two prerequisites this script needs but cannot obtain on its own.
#
#      git  — step 2 installs with `uv tool install --from git+…`, and uv shells out
#             to a real git binary for git sources. Without it uv aborts with
#             "Git executable not found", ~40 lines into unrelated build output.
#      cc + Python.h — `evdev` (which reads the hold-to-talk key) publishes an sdist
#             and no wheels at all, so it is compiled from C source on every install.
#             uv resolves to the *system* interpreter here, so its headers are what
#             the build needs.
#
#    Both used to fail late, deep inside someone else's output, on a machine the user
#    thought was ready. Detect them first and either fix them or say exactly what to run.
missing_pkgs=""
command -v git >/dev/null 2>&1 || missing_pkgs="$missing_pkgs git"
command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1 || missing_pkgs="$missing_pkgs build-essential"
# Probe the header rather than the package name: `python3-dev` is Debian-specific, but a
# missing Python.h breaks the evdev build identically everywhere.
if command -v python3 >/dev/null 2>&1 && ! python3 - <<'PY' >/dev/null 2>&1
import os, sys, sysconfig
sys.exit(0 if os.path.exists(os.path.join(sysconfig.get_paths()["include"], "Python.h")) else 1)
PY
then
  missing_pkgs="$missing_pkgs python3-dev"
fi

if [ -n "$missing_pkgs" ]; then
  # shellcheck disable=SC2086  # deliberate word-splitting: one package per argument.
  if command -v apt-get >/dev/null 2>&1; then
    # Already root (container, CI image) means no sudo — and requiring it there would
    # fail on boxes that do not ship it at all.
    if [ "${EUID:-1}" -eq 0 ]; then
      as_root() { run "$@"; }
    elif command -v sudo >/dev/null 2>&1; then
      as_root() { run sudo "$@"; }
    else
      error "Missing prerequisites:${missing_pkgs}
    Neither root nor sudo is available to install them. As root, run:
      apt-get install -y${missing_pkgs}
    then re-run this script."
    fi
    info "Installing build prerequisites:${missing_pkgs}"
    as_root apt-get update -qq \
      || warn "apt-get update failed — continuing; the install below may still work."
    as_root apt-get install -y $missing_pkgs \
      || error "Could not install:${missing_pkgs}. Install them and re-run this script."
  else
    error "Missing prerequisites:${missing_pkgs}
    This script needs them before it can build YazSes. On a non-Debian distro the
    equivalents are git, a C compiler (gcc), and the Python development headers —
    e.g.  Fedora: sudo dnf install git gcc python3-devel
          Arch:   sudo pacman -S git base-devel
    Install them and re-run this script."
  fi
fi

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

if ! command -v uv >/dev/null 2>&1 && [ "$DRY_RUN" -eq 1 ]; then
  echo -e "${YELLOW}[dry-run]${NC} would download uv ${UV_INSTALLER_VERSION}, verify it against"
  echo -e "${YELLOW}[dry-run]${NC}   sha256 ${UV_INSTALLER_SHA256}"
  echo -e "${YELLOW}[dry-run]${NC}   and run it (installs to ~/.local/bin; refuses to run on a checksum mismatch)"
elif ! command -v uv >/dev/null 2>&1; then
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
if [ "$DRY_RUN" -eq 0 ]; then
  command -v uv >/dev/null 2>&1 || error "uv is not on PATH. Add ~/.local/bin to PATH and re-run."
fi

# 2. Install YazSes (latest from git). --force upgrades an existing install in place.
if [ "$DRY_RUN" -eq 1 ]; then
  info "Source: ${REPO}@${REF}"
else
  info "Installing YazSes from ${REPO}@${REF} ..."
fi
run uv tool install --force --from "git+${REPO}@${REF}" yazses \
  || error "Install failed. See the output above (need a compiler/Python? uv usually handles it)."

# A dry run stops here: everything past this point drives the freshly installed binary,
# which by definition does not exist yet.
if [ "$DRY_RUN" -eq 1 ]; then
  echo -e "${YELLOW}[dry-run]${NC} would run: yazses setup   (PortAudio, xdotool/ydotool/wtype,"
  echo -e "${YELLOW}[dry-run]${NC}            clipboard tools, add \$USER to the 'input' group, enable ydotoold)"
  echo -e "${YELLOW}[dry-run]${NC} would run: yazses doctor   (read-only verification)"
  echo ""
  info "Dry run complete — nothing was installed, downloaded or changed."
  echo "  Re-run without --dry-run to install for real."
  echo ""
  exit 0
fi

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
