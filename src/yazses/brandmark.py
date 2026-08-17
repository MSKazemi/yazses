"""The YazSes mark as a raster image — the single renderer behind every icon.

``contrib/icons/yazses.svg`` is the canonical mark: a rounded badge carrying a
white "Y" over a listening sound-wave. This module redraws that exact geometry
with Pillow so the *same* code produces both the packaged application icon
(``assets/yazses.ico`` / ``.icns``, via ``scripts/gen-icons.py``) and the live
Windows tray glyph (``platform/windows/tray.py``). They cannot drift apart.

Why redraw rather than rasterise the SVG: no SVG renderer (cairosvg,
rsvg-convert, inkscape, ImageMagick) is available on the build machines or in
CI, and ``contrib/icons/`` has no 16 or 32 px source to downscale from. The mark
is a rounded rect plus eight round-capped strokes, so redrawing it is exact and
adds no dependency.

Three details that matter for how the icons actually *look*:

* **Anti-aliasing is supersampling.** Pillow's drawing primitives have no
  anti-aliasing at all — that is why the old tray glyph had a visibly jagged
  edge. Everything is drawn at ``size * SUPERSAMPLE`` and downsampled with BOX,
  which at an exact integer ratio *is* analytic coverage. (LANCZOS overshoots and
  leaves a bright rim on a 16 px badge.)
* **The shapes are downsampled as coverage masks, never as colour.** Shrinking an
  RGBA image whose transparent pixels are ``(0,0,0,0)`` averages that black into
  every partially-covered edge pixel, so the badge gets a dark halo — measured at
  half the corner-arc pixels before this was fixed. Masks are built in ``L`` mode
  and composited with a constant colour plane, which is what straight (un-
  premultiplied) alpha requires.
* **No font is used.** The "Y" is two round-capped strokes, not a text glyph.
  ``ImageFont.truetype`` needs a font file that may not exist inside a
  PyInstaller bundle, and ``load_default()`` is an unscalable bitmap.

Pillow is a ``sys_platform == "win32"`` runtime dependency (plus a dev-group
dependency for the generator and its tests), so it is imported lazily inside the
functions — importing this module must stay free on every platform.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from yazses.branding import BRAND_BOTTOM, BRAND_TOP

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image
    from PIL.ImageDraw import ImageDraw as Draw

# The mark's design grid. Every coordinate below is in these units and is scaled
# to the requested pixel size, so the geometry is identical at 16 px and 1024 px.
# Matches the viewBox of contrib/icons/yazses.svg.
_GRID = 48.0

# Badge corner radius (SVG: rx="10").
_RADIUS = 10.0

# The "Y": the fork, then the stem. SVG paths "M13 12 L24 26 L35 12" and
# "M24 26 L24 34", stroke-width 4.4, round caps and joins.
_Y_STROKE = 4.4
_Y_PATHS: tuple[tuple[tuple[float, float], ...], ...] = (
    ((13.0, 12.0), (24.0, 26.0), (35.0, 12.0)),
    ((24.0, 26.0), (24.0, 34.0)),
)

# The sound-wave under the Y: six vertical bars, stroke-width 2.6, opacity 0.92.
_WAVE_STROKE = 2.6
_WAVE_ALPHA = 235  # 0.92 * 255, rounded — the SVG's opacity="0.92"
_WAVE_BARS: tuple[tuple[float, float, float], ...] = (
    # (x, y_top, y_bottom)
    (8.0, 38.0, 40.0),
    (14.0, 35.0, 43.0),
    (20.0, 37.0, 41.0),
    (28.0, 37.0, 41.0),
    (34.0, 35.0, 43.0),
    (40.0, 38.0, 40.0),
)

# Draw at this multiple of the target size, then downsample. Pillow anti-aliases
# nothing, so this factor *is* the edge quality.
SUPERSAMPLE = 8

# Below this pixel size the wave bars are sub-pixel — the SVG's stroke-width 2.6
# of 48 units is 0.87 px at 16 px and 1.7 px at 32 px — and no resampling filter
# can rescue detail below Nyquist: they render as a grey smear under the Y. The
# small frames therefore carry the badge and the Y only, which is the ordinary
# optical-size practice for icon families on both Windows and macOS.
WAVE_MIN_PX = 40

# With the wave gone the lower third is dead space, so the wave-less variant
# grows the Y and centres it in the badge instead of leaving it top-heavy.
_SMALL_Y_SCALE = 1.18


def _round_stroke(
    draw: Draw,
    points: Sequence[tuple[float, float]],
    width: float,
    value: int,
) -> None:
    """Add one round-capped, round-joined stroke to a coverage mask.

    Pillow's ``line`` has butt caps and mitre joins whatever ``joint`` is set to,
    so the caps are drawn explicitly as discs at every vertex. At supersampled
    resolution that is indistinguishable from the SVG's ``stroke-linecap="round"``.
    """
    r = width / 2.0
    if len(points) >= 2:
        draw.line(list(points), fill=value, width=max(1, round(width)), joint="curve")
    for x, y in points:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=value)


def _scaled_about_centre(
    points: Sequence[tuple[float, float]], scale: float
) -> list[tuple[float, float]]:
    """Grow a path about the badge centre — used by the wave-less small variant."""
    c = _GRID / 2.0
    # The Y's own bounding box is y 12..34, centred on 23 rather than the badge's
    # 24, so recentring it here is what removes the top-heavy look as well.
    y_centre = 23.0
    return [(c + (x - c) * scale, c + (y - y_centre) * scale) for x, y in points]


def _masks(big: int, wave: bool, small: bool) -> tuple[Image, Image]:
    """Build the (badge, glyph) coverage masks at supersampled resolution."""
    from PIL import Image as PilImage
    from PIL import ImageDraw

    k = big / _GRID  # design units → supersampled pixels

    badge = PilImage.new("L", (big, big), 0)
    ImageDraw.Draw(badge).rounded_rectangle(
        (0, 0, big - 1, big - 1), radius=_RADIUS * k, fill=255
    )

    glyph = PilImage.new("L", (big, big), 0)
    gd = ImageDraw.Draw(glyph)
    scale = _SMALL_Y_SCALE if small else 1.0
    for path in _Y_PATHS:
        pts = _scaled_about_centre(path, scale) if small else list(path)
        _round_stroke(gd, [(x * k, y * k) for x, y in pts], _Y_STROKE * k * scale, 255)
    if wave:
        for x, y0, y1 in _WAVE_BARS:
            _round_stroke(
                gd, [(x * k, y0 * k), (x * k, y1 * k)], _WAVE_STROKE * k, _WAVE_ALPHA
            )
    return badge, glyph


def _colour_plane(size: int, fill: str | tuple[int, int, int] | None) -> Image:
    """The badge's colour: a flat state colour, or the brand vertical gradient."""
    from PIL import Image as PilImage
    from PIL import ImageColor

    if fill is not None:
        rgb = ImageColor.getrgb(fill) if isinstance(fill, str) else tuple(fill)
        return PilImage.new("RGB", (size, size), rgb[:3])

    # linearGradient x1=0 y1=0 x2=0 y2=1 — a straight top-to-bottom sweep.
    grad = PilImage.new("RGB", (1, size))
    px = grad.load()
    assert px is not None
    span = max(1, size - 1)
    for y in range(size):
        t = y / span
        px[0, y] = tuple(  # type: ignore[index]
            round(BRAND_TOP[c] + (BRAND_BOTTOM[c] - BRAND_TOP[c]) * t) for c in range(3)
        )
    return grad.resize((size, size), PilImage.Resampling.NEAREST)


def render_mark(
    size: int,
    *,
    fill: str | tuple[int, int, int] | None = None,
    wave: bool | None = None,
    supersample: int = SUPERSAMPLE,
    glyph_colour: str | tuple[int, int, int] = (255, 255, 255),
) -> Image:
    """Render the YazSes mark at ``size``×``size`` px, RGBA, transparent corners.

    ``fill`` is the badge colour: ``None`` (the default) paints the brand
    gradient, as the application icon does; a hex string or RGB triple paints a
    flat colour, as the tray does with its per-state colour from
    ``tray.menu.icon_spec``.

    ``wave`` draws the sound-wave bars under the Y. The default decides from
    ``size`` (see ``WAVE_MIN_PX``); pass it explicitly to force either form —
    the tray always passes ``False`` so the glyph stays legible at 16 px.
    """
    if size <= 0:
        raise ValueError(f"icon size must be positive, got {size}")
    if supersample < 1:
        raise ValueError(f"supersample must be >= 1, got {supersample}")
    if wave is None:
        wave = size >= WAVE_MIN_PX

    from PIL import Image as PilImage

    # 1. Draw the shapes hard-edged at supersampled resolution, as coverage
    #    masks only — no colour is resampled, so no dark fringe (see the module
    #    docstring). BOX at an exact integer ratio is analytic area coverage.
    big = size * supersample
    badge, glyph = _masks(big, wave=wave, small=not wave)
    if supersample > 1:
        badge = badge.resize((size, size), PilImage.Resampling.BOX)
        glyph = glyph.resize((size, size), PilImage.Resampling.BOX)

    # 2. Composite. The base already carries the badge colour at alpha 0, so
    #    `paste` — which lerps every channel toward the pasted value — ramps only
    #    the alpha through the soft edge and leaves RGB constant. Starting from
    #    (0,0,0,0) instead is what premultiplies the edge toward black.
    plane = _colour_plane(size, fill)
    img = plane.convert("RGBA")
    img.putalpha(badge)
    # Usually white, at mask 235 (the SVG's opacity="0.92") so it blends rather
    # than overwrites. Callers may override it: on the tray's yellow badge a white
    # mark measures 1.71:1 against WCAG AA's 4.5, and black measures 12.3 — see
    # `tray/menu.py::glyph_for`, which decides. The packaged icons keep white,
    # because they are painted on the brand gradient rather than a state colour.
    # Built as an explicit 3-tuple rather than a generator: `tuple(... for ...)` is
    # `tuple[int, ...]` to a type checker, which loses the "exactly three channels"
    # that the RGBA paste below depends on.
    mark: tuple[int, int, int]
    if isinstance(glyph_colour, str):
        text = glyph_colour.strip().lstrip("#")
        mark = (
            (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
            if len(text) == 6
            else (255, 255, 255)
        )
    else:
        mark = glyph_colour
    img.paste((*mark, 255), mask=glyph)
    return img
