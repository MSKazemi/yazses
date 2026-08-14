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


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate assets/yazses.{ico,icns}.")
    ap.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and fail if the committed assets differ",
    )
    args = ap.parse_args()

    wanted = {ICO_PATH: build_ico(), ICNS_PATH: build_icns()}

    if args.check:
        stale = [p for p, data in wanted.items() if not p.exists() or p.read_bytes() != data]
        for path in stale:
            print(f"stale or missing: {path.relative_to(REPO)}", file=sys.stderr)
        if stale:
            print("run: uv run python scripts/gen-icons.py", file=sys.stderr)
            return 1
        print("icons are up to date")
        return 0

    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    for path, data in wanted.items():
        path.write_bytes(data)
        print(f"wrote {path.relative_to(REPO)} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
