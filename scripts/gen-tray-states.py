#!/usr/bin/env python3
"""Render the tray badge in each of its states, for the documentation.

`docs/tray-and-overlay.md` explains five colours and pictures two. It says so itself:
*"🟡 Yellow (no text target) isn't pictured here"*. Purple (command mode) and green
(recording) are unpictured too — and yellow and purple are precisely the states a
reader has never seen and most needs to recognise, because they mean "your words went
to the clipboard" and "that was parsed as a command".

Capturing them is impractical: the badge is an appindicator in the desktop panel, so a
screenshot means photographing the user's whole top bar, and three of the five states
last only while a key is held. Rendering is better than a photograph here anyway —
exact pixels, no surrounding desktop, no privacy question.

**Derived, never hand-drawn.** The colour comes from `tray.menu.icon_spec`, the glyph
colour from `tray.menu.glyph_for`, and the badge itself from
`brandmark.render_mark` — the same three the trays call. A hand-made swatch would be a
second source of truth for the one thing this page exists to explain.

**The level ring is deliberately not drawn.** `platform/linux/tray.py` paints it with
QPainter; reproducing it in Pillow would be a second implementation of a thing that
already exists once, which is the drift this project keeps paying for. The page
describes the ring in words.

    uv run python scripts/gen-tray-states.py            # write docs/assets/
    uv run python scripts/gen-tray-states.py --check    # fail if committed files drifted
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from yazses.brandmark import render_mark  # noqa: E402  (needs the sys.path above)
from yazses.tray.menu import glyph_for, icon_spec  # noqa: E402

OUT_DIR = REPO / "docs" / "assets"

# 128 px: the docs render it small, and a 2x source stays crisp on a HiDPI screen.
# Above `brandmark.WAVE_MIN_PX`, so these carry the full mark rather than the
# simplified 16 px form — the page is explaining the *colour*, not the small-size
# legibility trade.
SIZE = 128

#: (filename stem, the status dict the daemon would publish, what it means).
#: The dicts are the real shape `icon_spec` reads, so a change to the colour policy
#: shows up here rather than being restated.
STATES: tuple[tuple[str, dict, str], ...] = (
    ("idle", {"state": "idle"}, "ready and waiting"),
    (
        "recording",
        {"state": "recording", "target_ok": True},
        "dictating into a text field",
    ),
    (
        "no-text-target",
        {"state": "recording", "target_ok": False},
        "dictating with nowhere to type — saved to the clipboard",
    ),
    (
        "command-mode",
        {"state": "recording", "command_mode": True},
        "holding the command key",
    ),
    ("error", {"state": "error"}, "a problem needing attention"),
)


def render(status: dict) -> bytes:
    """One badge PNG for *status*, through exactly the tray's own decisions."""
    colour, _tooltip = icon_spec(status)
    image = render_mark(SIZE, fill=colour, wave=False, glyph_colour=glyph_for(colour))
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def wanted_assets() -> dict[Path, bytes]:
    """Every file this script owns. One dict, so `--check` and the writer agree."""
    return {OUT_DIR / f"tray-state-{stem}.png": render(status) for stem, status, _why in STATES}


def _frames(blob: bytes) -> bytes:
    """Decoded pixels. Compared instead of bytes: PNG output is not reproducible
    across platforms (zlib version and Pillow build change the stream for identical
    pixels), which has turned CI red on correct assets before."""
    from PIL import Image

    with Image.open(io.BytesIO(blob)) as im:
        return im.convert("RGBA").tobytes()


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the tray badge states for the docs.")
    ap.add_argument("--check", action="store_true", help="verify without writing")
    args = ap.parse_args()

    wanted = wanted_assets()
    if args.check:
        stale = [
            path for path, data in wanted.items()
            if not path.exists() or _frames(path.read_bytes()) != _frames(data)
        ]
        for path in stale:
            print(f"stale or missing: {path.relative_to(REPO)}", file=sys.stderr)
        if stale:
            print("run: uv run python scripts/gen-tray-states.py", file=sys.stderr)
            return 1
        print("tray state images are up to date")
        return 0

    for path, data in wanted.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"wrote {path.relative_to(REPO)} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
