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
if [[ "$(uname -m)" == "x86_64" ]]; then
    # Intel is the one leg that deliberately builds UNLOCKED, and it has to be.
    #
    # `uv.lock` is a single universal resolution and it pins onnxruntime 1.28.0,
    # which publishes no macOS x86_64 wheel at all -- upstream ships arm64 only.
    # faster-whisper depends on onnxruntime unconditionally, so it is not
    # avoidable by dropping an extra. `uv sync` installs exactly what the lock
    # says, so on Intel it cannot succeed:
    #
    #   error: Distribution `onnxruntime==1.28.0` can't be installed because it
    #   doesn't have a source distribution or wheel for the current platform
    #
    # That is precisely how every Intel .dmg since the leg was added failed,
    # while the workflow reported success -- the job is `continue-on-error`.
    #
    # A fresh resolution *can* satisfy Intel: it backtracks to onnxruntime
    # 1.23.2, the last release with a macosx x86_64 wheel. Verified with
    #   uv pip compile --python-platform x86_64-apple-darwin pyproject.toml
    #
    # The alternative -- pinning onnxruntime below 1.24 in pyproject.toml --
    # would hold every other platform two years back for one architecture Apple
    # has already scheduled for removal (ADR-017). Trading the whole project's
    # runtime for a bundle with a two-year horizon is the wrong way round.
    #
    # The cost is stated rather than hidden: the Intel bundle is not built from
    # the locked dependency set, so it is not bit-reproducible against it. It is
    # that or no Intel bundle, and `pipx install yazses` -- which resolves the
    # same way -- remains the Intel path that outlives the hardware.
    uv venv
    uv pip install .
else
    # `--no-dev` because a desktop bundle has no business carrying the test suite.
    # Measured on the 2.21.0 dispatch: the Apple Silicon .dmg came out at 137 MB
    # against Intel's 85 MB, and the only structural difference between the two
    # legs was that `uv sync` installs the dev group -- pytest, mypy, ruff,
    # hypothesis, Pillow, a moonshine ONNX model -- into the environment
    # PyInstaller then analyses. Shipping a linter inside an application is a size
    # problem and a supply-chain one, and neither is paid for by anything.
    #
    # `--extra desktop` for the opposite reason: Qt left the base dependencies in
    # #259, and a frozen .app cannot install it later. Without it the bundle ships
    # no PySide6, so the tray's "Settings..." opens a process that dies on the
    # import -- silently, because a windowed bundle has no stderr to print to.
    uv sync --no-dev --extra desktop
fi

echo "==> Installing PyInstaller"
uv pip install 'pyinstaller>=6.10'

echo "==> Cleaning previous build"
rm -rf build dist

echo "==> Running PyInstaller"
# --no-sync: `uv run` re-syncs from the lock by default, which on Intel would
# undo the resolution above and fail exactly where `uv sync` did. On arm64 the
# sync has already happened, so it is a no-op there.
uv run --no-sync pyinstaller packaging/macos/yazses.spec --clean --noconfirm

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
