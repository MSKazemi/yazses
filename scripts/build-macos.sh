#!/usr/bin/env bash
# Build an unsigned YazSes .dmg on macOS.
#
# Steps:
#   1. Resolve runtime deps with uv (pulls PyObjC + rumps via env markers).
#   2. Install PyInstaller and create-dmg (build-only deps; not in pyproject).
#   3. Run PyInstaller against packaging/macos/yazses.spec → dist/YazSes.app
#   4. Wrap the .app in a .dmg with create-dmg.
#
# Outputs:
#   dist/YazSes-<VERSION>-macos-<arch>.dmg     (arch = arm64 | x86_64)
#
# Requires:  macOS, Xcode command-line tools, Homebrew (for create-dmg).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "build-macos.sh requires macOS; got $(uname -s)" >&2
    exit 1
fi

VERSION="$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/version = "(.+)"/\1/')"
echo "==> Building YazSes ${VERSION}"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi
if ! command -v create-dmg >/dev/null 2>&1; then
    echo "create-dmg not found. Install: brew install create-dmg" >&2
    exit 1
fi

echo "==> Syncing runtime dependencies"
uv sync

echo "==> Installing PyInstaller"
uv pip install 'pyinstaller>=6.10'

echo "==> Cleaning previous build"
rm -rf build dist

echo "==> Running PyInstaller"
uv run pyinstaller packaging/macos/yazses.spec --clean --noconfirm

if [[ ! -d dist/YazSes.app ]]; then
    echo "PyInstaller did not produce dist/YazSes.app" >&2
    exit 1
fi

# --- target architecture --------------------------------------------------
# PyInstaller freezes for the machine it runs on -- it does not cross-compile,
# and `target_arch=None` in the spec means "host architecture" -- so the build
# host IS the target and the runner label is what selects it. Derived here
# rather than passed as a flag, for the same reason build-windows.ps1 derives
# it: a flag and a runner label are two things that can disagree, and the
# failure is a correctly-built binary with the wrong name on it.
#
# Until ADR-017 there was one .dmg and its name said nothing about architecture,
# which is a large part of why an arm64-only bundle went unnoticed for months:
# `YazSes-2.20.0.dmg` looks like it is for everybody.
ARCH="$(uname -m)"
echo "==> Target architecture: ${ARCH} (from the build host)"

echo "==> Building .dmg"
DMG="dist/YazSes-${VERSION}-macos-${ARCH}.dmg"
rm -f "${DMG}"
create-dmg \
    --volname "YazSes ${VERSION} (${ARCH})" \
    --window-size 540 380 \
    --icon-size 96 \
    --app-drop-link 380 180 \
    --hide-extension "YazSes.app" \
    "${DMG}" \
    dist/YazSes.app

echo "==> Done: ${DMG}"
ls -lh "${DMG}"
