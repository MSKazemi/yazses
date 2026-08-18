#!/usr/bin/env python3
"""Generate the packaged application icons from the shared brand mark.

Writes `assets/yazses.ico` (Windows: the .exe resource, so the desktop shortcut,
the Start menu, the taskbar button, Add/Remove Programs and the installer all
inherit it) and `assets/yazses.icns` (macOS: the .app bundle icon). Both are
drawn by `yazses.brandmark.render_mark` — the same renderer the Windows tray
glyph uses, so the shortcut icon and the tray badge cannot drift apart.

The outputs are **committed artifacts**, not build-time products: PyInstaller and
Inno Setup need the file present in a plain source checkout, and Pillow is not a
runtime dependency outside Windows. Re-run this whenever the mark changes.

    uv run python scripts/gen-icons.py            # write assets/
    uv run python scripts/gen-icons.py --check    # fail if the committed files drifted

Both containers are written by Pillow, but each needs coaxing to embed the
per-size frames we render rather than downscaling one image (verified against
Pillow 12.3.0's source, not just its docs):

* `IcoImagePlugin._save` uses an `append_images` entry verbatim when its size
  matches a requested size — but it **skips any requested size larger than the
  base image**, so the base must be the *largest* frame. Passing the smallest
  silently yields a one-frame .ico.
* `IcnsImagePlugin._save` keys `append_images` by width and falls back to a plain
  `im.resize()` for anything missing, so every size it asks for is supplied.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from yazses.brandmark import render_mark  # noqa: E402  (needs the sys.path above)

ICO_PATH = REPO / "assets" / "yazses.ico"
ICNS_PATH = REPO / "assets" / "yazses.icns"

# The Linux icons, which this script did not own until they had already drifted.
#
# `contrib/icons/yazses-<size>.png` are copied into `usr/share/icons/hicolor/` by
# `scripts/build-deb.sh`, so they are the app-grid icon for every .deb install.
# `snap/gui/yazses.png` is the `icon:` in `snapcraft.yaml` — the Snap Store listing
# and the app grid on every snap install.
#
# What being unowned cost, measured rather than assumed:
#
# * the .deb PNGs are the right *design*, rendered by an earlier version of
#   `render_mark`: composited over white they differ on 0.6–5.9% of pixels, max
#   delta 30/255. Anti-aliasing drift, invisible in use, but nothing would ever
#   have corrected it.
# * `snap/gui/yazses.png` is **a different logo entirely** — a white square with a
#   blue speech-bubble outline, a navy Y and a violet-to-cyan waveform, against the
#   purple-gradient badge every other surface uses. It was drawn by hand in June and
#   no generator has looked at it since, so the icon in the Snap Store and in every
#   Ubuntu app grid is not the icon on the website, in the .exe, in the .app, in the
#   .deb, or on the tray.
DEB_ICON_SIZES = (48, 64, 128, 256)
DEB_ICON_DIR = REPO / "contrib" / "icons"
# 512 is what the Snap Store shows and what snapcraft's own guidance asks for.
SNAP_ICON_PATH = REPO / "snap" / "gui" / "yazses.png"
SNAP_ICON_SIZE = 512

# The frames Windows picks between. 16/20/24/32 are the small-icon sizes for
# 100/125/150/200% display scaling — an exact frame always beats Explorer's own
# scaler, and they cost about a kilobyte each. 48 is medium icons, 256 extra-large.
# Each is rendered natively, so the small ones get the simplified wave-less mark
# (see brandmark.WAVE_MIN_PX) instead of a sub-pixel smear.
ICO_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)

# Exactly the set IcnsImagePlugin asks for (ic07…ic14), so none falls through to
# its unfiltered resize.
ICNS_SIZES = (32, 64, 128, 256, 512, 1024)


def build_ico(sizes: tuple[int, ...] = ICO_SIZES) -> bytes:
    """Assemble a multi-resolution ICO, one natively-rendered frame per size."""
    frames = [render_mark(px) for px in sorted(sizes)]
    buf = io.BytesIO()
    # The largest frame is the base; see the module docstring for why.
    frames[-1].save(
        buf,
        format="ICO",
        sizes=[(px, px) for px in sorted(sizes)],
        append_images=frames[:-1],
    )
    return buf.getvalue()


def build_icns(sizes: tuple[int, ...] = ICNS_SIZES) -> bytes:
    """Assemble the macOS .icns, one natively-rendered frame per size."""
    frames = [render_mark(px) for px in sorted(sizes)]
    buf = io.BytesIO()
    frames[-1].save(buf, format="ICNS", append_images=frames)
    return buf.getvalue()


def build_png(size: int) -> bytes:
    """One PNG frame at *size*, rendered natively rather than downscaled.

    `optimize=True` so the committed artifact is as small as it can be, and — more
    importantly — so the bytes are a deterministic function of the pixels. `--check`
    compares bytes, and a compressor that varied its output would make every run
    report drift that is not there.
    """
    buf = io.BytesIO()
    render_mark(size).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def wanted_assets() -> dict[Path, bytes]:
    """Every icon this repo ships, and the bytes it should contain.

    One dict so that `--check` and the write path cannot cover different sets — which
    is exactly how the Linux icons came to be shipped by the build scripts while being
    regenerated by nothing.
    """
    assets: dict[Path, bytes] = {ICO_PATH: build_ico(), ICNS_PATH: build_icns()}
    for size in DEB_ICON_SIZES:
        assets[DEB_ICON_DIR / f"yazses-{size}.png"] = build_png(size)
    assets[SNAP_ICON_PATH] = build_png(SNAP_ICON_SIZE)
    return assets


def _frames(blob: bytes) -> dict:
    """Every frame in *blob*, decoded to raw RGBA, keyed by size.

    Compared as pixels and never as bytes, for the reason `tests/test_icon_assets.py`
    already had to learn: **PNG output is not reproducible across platforms.** The
    zlib version and the Pillow build change the compressed stream for pixel-identical
    input, so a byte comparison answers "was this file produced on this machine",
    which is not the question. It passed locally and turned the Windows and macOS CI
    legs red on assets that were perfectly correct.

    `--check` is a maintainer command today, so bytes would have worked by accident.
    Decoding removes the landmine for whoever wires it into CI later.
    """
    import io

    from PIL import Image, ImageSequence

    out = {}
    with Image.open(io.BytesIO(blob)) as im:
        for frame in ImageSequence.Iterator(im):
            out[frame.size] = frame.convert("RGBA").tobytes()
    return out


def _drifted(path: Path, expected: bytes) -> bool:
    """True when the committed file is missing, unreadable, or pixel-different."""
    if not path.exists():
        return True
    try:
        return _frames(path.read_bytes()) != _frames(expected)
    except Exception:
        return True  # unreadable or not an image any more — regenerate it


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate every shipped icon from the one brand-mark renderer.",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and fail if the committed assets differ",
    )
    args = ap.parse_args()

    wanted = wanted_assets()

    if args.check:
        stale = [p for p, data in wanted.items() if _drifted(p, data)]
        for path in stale:
            print(f"stale or missing: {path.relative_to(REPO)}", file=sys.stderr)
        if stale:
            print("run: uv run python scripts/gen-icons.py", file=sys.stderr)
            return 1
        print("icons are up to date")
        return 0

    for path, data in wanted.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"wrote {path.relative_to(REPO)} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
