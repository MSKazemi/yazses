"""Tests for the shared brand-mark renderer.

The mark is drawn twice over: once here in Pillow (`yazses.brandmark`) and once
as vector art in `contrib/icons/yazses.svg`, which is what the docs site, the
Snap listing and the Linux hicolor icons use. Two sources of truth are only safe
if something compares them, so `test_geometry_matches_the_source_svg` does.

The pixel assertions below are regression tests for the two defects that made
the Windows tray icon look wrong in the first place: no anti-aliasing at all
(Pillow's primitives are hard-edged), and a dark halo once anti-aliasing is
added naively (downsampling an RGBA image averages the transparent background's
black into every partially-covered edge pixel).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from yazses.brandmark import (
    _GRID,
    _RADIUS,
    _WAVE_ALPHA,
    _WAVE_BARS,
    _WAVE_STROKE,
    _Y_PATHS,
    _Y_STROKE,
    WAVE_MIN_PX,
    render_mark,
)

pytest.importorskip("PIL", reason="Pillow is a dev/win32 dependency")

_SVG = Path(__file__).resolve().parents[1] / "contrib" / "icons" / "yazses.svg"

# The five colours tray/menu.py::icon_spec can return.
_STATE_COLORS = ["#1a73e8", "#34a853", "#fbbc04", "#9c27b0", "#e53935"]

# Sizes that actually ship: the .ico ladder plus the tray canvas.
_SHIPPED = [16, 20, 24, 32, 48, 64, 128, 256]


@pytest.mark.parametrize("size", _SHIPPED)
def test_render_is_square_rgba_at_every_shipped_size(size: int) -> None:
    img = render_mark(size)
    assert img.size == (size, size)
    assert img.mode == "RGBA"


@pytest.mark.parametrize("size", [16, 32, 64, 256])
def test_corners_are_fully_transparent(size: int) -> None:
    """The badge is a rounded square, so its corners must be cut out."""
    px = render_mark(size).load()
    last = size - 1
    for xy in [(0, 0), (last, 0), (0, last), (last, last)]:
        assert px[xy][3] == 0, f"corner {xy} is not transparent"


@pytest.mark.parametrize("color", _STATE_COLORS)
def test_badge_body_is_exactly_the_state_colour(color: str) -> None:
    """A flat fill must survive the mask/composite path unchanged."""
    from PIL import ImageColor

    want = ImageColor.getrgb(color)
    px = render_mark(64, fill=color, wave=False).load()
    # Bottom centre: clear of the Y, and clear of the wave bars when present.
    got = px[32, 59]
    assert got[:3] == want, f"badge body is {got[:3]}, expected {want}"
    assert got[3] == 255


def test_edges_are_antialiased() -> None:
    """The regression test for the jagged tray icon the user reported.

    The old implementation was a single `draw.ellipse`, which Pillow renders with
    hard edges — this count was exactly zero.
    """
    px = render_mark(64, fill="#1a73e8", wave=False).load()
    soft = [
        (x, y)
        for y in range(16)
        for x in range(16)
        if 0 < px[x, y][3] < 255
    ]
    assert len(soft) >= 8, f"only {len(soft)} anti-aliased pixels on the corner arc"


def test_soft_edge_has_no_dark_fringe() -> None:
    """Anti-aliased pixels must keep the badge colour and vary only in alpha.

    Downsampling colour instead of coverage averages the transparent background's
    black into the edge and rims the badge in dark grey. Measured at half the
    corner-arc pixels before the renderer switched to compositing through masks.
    """
    from PIL import ImageColor

    want = ImageColor.getrgb("#1a73e8")
    px = render_mark(64, fill="#1a73e8", wave=False).load()
    bad = []
    for y in range(16):
        for x in range(16):
            r, g, b, a = px[x, y]
            if 0 < a < 255 and max(abs(r - want[0]), abs(g - want[1]), abs(b - want[2])) > 1:
                bad.append(((x, y), (r, g, b, a)))
    assert not bad, f"{len(bad)} edge pixels drifted from the fill: {bad[:5]}"


def test_small_sizes_drop_the_wave_bars() -> None:
    """Below WAVE_MIN_PX the bars are sub-pixel, so the small variant omits them."""

    def wave_ink(size: int) -> int:
        px = render_mark(size, fill="#1a73e8").load()
        # The band the bars occupy: y 35..43 of 48. Restricted to the left group
        # (grid x 4..18, i.e. the bars at x=8 and x=14) so the Y's stem — which
        # the wave-less variant enlarges down into this band — cannot be counted.
        y0, y1 = round(35 / _GRID * size), round(44 / _GRID * size)
        x0, x1 = round(4 / _GRID * size), round(18 / _GRID * size)
        return sum(
            1
            for y in range(y0, y1)
            for x in range(x0, x1)
            if px[x, y][0] > 200 and px[x, y][1] > 200 and px[x, y][2] > 200
        )

    assert wave_ink(16) == 0, "16 px frame should carry no wave bars"
    assert wave_ink(64) > 0, "64 px frame should carry the wave bars"


def test_wave_default_follows_the_size_threshold() -> None:
    below = render_mark(WAVE_MIN_PX - 8)
    forced = render_mark(WAVE_MIN_PX - 8, wave=False)
    assert below.tobytes() == forced.tobytes()
    assert render_mark(64).tobytes() != render_mark(64, wave=False).tobytes()


def test_render_is_deterministic() -> None:
    assert render_mark(64).tobytes() == render_mark(64).tobytes()


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_a_non_positive_size(bad: int) -> None:
    with pytest.raises(ValueError):
        render_mark(bad)


def test_geometry_matches_the_source_svg() -> None:
    """Guard the second source of truth: contrib/icons/yazses.svg.

    If a designer edits the SVG and not this module (or vice versa), the app icon
    and the docs/Snap/Linux artwork silently become different logos.
    """
    ns = {"s": "http://www.w3.org/2000/svg"}
    root = ET.parse(_SVG).getroot()

    assert root.get("viewBox") == f"0 0 {int(_GRID)} {int(_GRID)}"

    rect = root.find("s:rect", ns)
    assert rect is not None
    assert float(rect.get("rx", "0")) == _RADIUS

    def coords(d: str) -> tuple[tuple[float, float], ...]:
        nums = [float(n) for n in re.findall(r"-?\d+\.?\d*", d)]
        return tuple(zip(nums[::2], nums[1::2]))

    y_paths = root.findall("s:path", ns)
    assert tuple(coords(p.get("d", "")) for p in y_paths) == _Y_PATHS
    assert {float(p.get("stroke-width", "0")) for p in y_paths} == {_Y_STROKE}

    group = root.find("s:g", ns)
    assert group is not None
    assert float(group.get("stroke-width", "0")) == _WAVE_STROKE
    assert round(float(group.get("opacity", "1")) * 255) == _WAVE_ALPHA
    bars = tuple(
        (c[0][0], c[0][1], c[1][1])
        for c in (coords(p.get("d", "")) for p in group.findall("s:path", ns))
    )
    assert bars == _WAVE_BARS
