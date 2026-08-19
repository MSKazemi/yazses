# PyInstaller spec file for YazSes (macOS).
#
# Builds a single-binary, single-bundle .app from src/yazses/__main__.py.
# The binary dispatches by argv: --tray (default) | --daemon | --cli.
#
# Usage (from repo root):
#     uv run pyinstaller packaging/macos/yazses.spec --clean --noconfirm
#
# Outputs:
#     dist/YazSes.app

# ruff: noqa
# mypy: ignore-errors

from __future__ import annotations

import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

REPO = Path(SPECPATH).resolve().parents[1]
ENTRY = str(REPO / "src" / "yazses" / "__main__.py")
ICON = REPO / "assets" / "yazses.icns"
# A hard failure, not `icon=... if ICON.exists() else None`. assets/ never existed,
# so that fallback silently gave every .app the generic bundle icon in Finder and
# the Dock -- the same defect the Windows spec carried.
if not ICON.exists():
    raise SystemExit(
        f"Brand icon missing: {ICON}\n"
        "Run `uv run python scripts/gen-icons.py` and commit assets/yazses.icns."
    )

# Read the version from pyproject rather than restating it here. These two used
# to be separate literals, and the copy in this file was never updated after
# v0.1.2 -- so every .dmg from v0.1.3 to v2.18.0 shipped an .app that told macOS
# it was version 0.1.2. Finder's Get Info, `mdls`, and any updater that compares
# CFBundleShortVersionString all read that number, so a genuine upgrade looked
# like a downgrade. Derive it and the drift cannot come back.
VERSION = tomllib.loads(
    (REPO / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]

block_cipher = None


a = Analysis(
    [ENTRY],
    pathex=[str(REPO / "src")],
    binaries=[],
    # The package's .dist-info. PyInstaller bundles no metadata unless asked, and
    # importlib.metadata.version("yazses") is what --version, the About box, doctor,
    # the updater and the diagnostic report all read. Without it every one of them
    # sees PackageNotFoundError inside the .app.
    #
    # The Windows spec has carried this line, and a test pinning it, since the
    # installer smoke test caught it there. The macOS spec never got either -- so
    # `doctor` in the shipped .app reported "yazses version metadata not found",
    # which is exactly what the first person to run the macOS build on real
    # hardware pasted into #182.
    datas=copy_metadata("yazses"),
    hiddenimports=[
        # PyObjC sub-modules that PyInstaller's static analysis sometimes misses.
        "Quartz",
        "AppKit",
        "Foundation",
        "ApplicationServices",
        "CoreFoundation",
        "AVFoundation",
        # rumps loads its assets dynamically.
        "rumps",
        # faster-whisper / ctranslate2 native bridge.
        "faster_whisper",
        "ctranslate2",
        # Linux backends are skipped on darwin via env markers, but PyInstaller
        # may still try to import them; suppress by keeping the list mac-only.
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "evdev",
        "yazses.platform.linux",
        "yazses.platform.windows",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YazSes",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,         # --windowed
    disable_windowed_traceback=False,
    # Host arch only -- NOT universal2, whatever an earlier comment here claimed.
    # PyInstaller reads target_arch=None as "build for the machine you are on",
    # and CI builds on macos-latest, which is Apple Silicon (the v2.18.0 run
    # resolved its Python to aarch64-apple-darwin). So the released .dmg is
    # arm64-only and will not launch on an Intel Mac.
    #
    # universal2 is not reachable by flipping this value: PyInstaller can only
    # emit a universal2 binary when *every* bundled native dependency is itself
    # universal2, and ctranslate2 (via faster-whisper) publishes separate
    # arm64 and x86_64 macOS wheels. Intel coverage needs a second CI job on an
    # Intel runner, and those are `-large`/`-intel` labels, which GitHub bills
    # even for public repositories. That is a spend decision, so it is filed
    # rather than assumed -- see docs/macos-install.md for what Intel users do
    # in the meantime (pipx install yazses).
    target_arch=None,
    codesign_identity=None,  # signed in a separate step (deferred to public beta)
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="YazSes",
)

app = BUNDLE(
    coll,
    name="YazSes.app",
    icon=str(ICON),
    bundle_identifier="com.yazses.app",
    info_plist={
        # Identity
        "CFBundleName": "YazSes",
        "CFBundleDisplayName": "YazSes",
        "CFBundleIdentifier": "com.yazses.app",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundleExecutable": "YazSes",

        # No Dock icon — tray-only app.
        "LSUIElement": True,

        # Minimum macOS supporting PyObjC 11 + Apple Silicon.
        "LSMinimumSystemVersion": "11.0",

        # Permission prompt strings. Without these the OS rejects access without
        # showing a prompt to the user.
        "NSMicrophoneUsageDescription":
            "YazSes transcribes speech locally; the microphone is used "
            "only while you hold the dictation key.",
        "NSAppleEventsUsageDescription":
            "YazSes does not send Apple Events; this entitlement is "
            "present for compatibility with macOS Accessibility prompts.",

        # High-resolution display support.
        "NSHighResolutionCapable": True,
    },
)
