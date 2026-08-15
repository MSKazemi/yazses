"""Theme-aware colours for the settings window, with contrast guaranteed.

The settings window styled its secondary text with `color: gray` — a literal `#808080`,
repeated in five places. Two things are wrong with that, and the second is the one that
matters:

**It ignores the theme.** A fixed colour cannot be right on both a light and a dark
window, and Qt's palette already carries what the desktop chose.

**It fails WCAG AA on both.** Measured: `#808080` scores **3.43:1** on Qt's light window
(`#efefef`) and **3.44:1** on its dark one (`#2e2e2e`), against the 4.5:1 that normal text
requires. Not marginally — on every common background. For a project whose research pages
argue that assistive technology is priced out of reach and skips Linux, unreadable
secondary text in its own settings window is the wrong detail to get wrong.

So the muted colour is *computed*: start from the theme's own text colour and blend it
toward the background only as far as contrast allows. The result is visibly secondary and
still readable, on whatever palette the desktop supplies.

The maths here is deliberately Qt-free so it can be tested without a display, in the same
way the tray's icon logic is separated from its painting.
"""

from __future__ import annotations

RGB = tuple[int, int, int]

#: WCAG 2.1 contrast minimum for normal-size body text. Large text may use 3.0; the
#: strings this styles are captions and hints, which are not large.
AA_NORMAL = 4.5

#: How far to blend toward the background before contrast stops us. Purely aesthetic:
#: it is what makes the text read as secondary rather than merely dimmer.
_MAX_BLEND = 0.55


def _channel(value: float) -> float:
    """sRGB channel → linear light, per WCAG's definition."""
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: RGB) -> float:
    """WCAG relative luminance of an sRGB colour. Pure."""
    r, g, b = (_channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    """WCAG contrast ratio between two colours, 1.0–21.0. Pure and symmetric."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def blend(fg: RGB, bg: RGB, amount: float) -> RGB:
    """Move *fg* toward *bg* by *amount* (0 = unchanged, 1 = the background). Pure."""
    amount = max(0.0, min(1.0, amount))
    return tuple(  # type: ignore[return-value]
        round(f + (b - f) * amount) for f, b in zip(fg, bg, strict=True)
    )


def muted(fg: RGB, bg: RGB, *, minimum: float = AA_NORMAL) -> RGB:
    """A secondary-text colour: as blended as contrast permits, never below *minimum*.

    Searches the blend range rather than picking a fixed opacity, because how far one
    *can* fade depends entirely on the palette — a near-black on white tolerates far more
    fading than a mid-grey on charcoal.

    If the theme's own text colour already fails *minimum* against its own background,
    that is the theme's problem and not one this can fix by fading further, so the text
    colour is returned unchanged. Making it *worse* to satisfy a house style would be the
    wrong trade.
    """
    if contrast_ratio(fg, bg) < minimum:
        return fg
    best = fg
    # 5% steps: finer buys no visible difference and the search runs per widget.
    for step in range(1, int(_MAX_BLEND * 20) + 1):
        candidate = blend(fg, bg, step / 20)
        if contrast_ratio(candidate, bg) < minimum:
            break
        best = candidate
    return best


def to_hex(rgb: RGB) -> str:
    """`(128, 128, 128)` → `#808080`."""
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def muted_stylesheet(fg: RGB, bg: RGB, extra: str = "") -> str:
    """The `color:` rule for secondary text, plus any additional declarations."""
    rule = f"color: {to_hex(muted(fg, bg))};"
    return f"{rule} {extra}".strip() if extra else rule


# --------------------------------------------------------------------------- #
# Qt adapter
# --------------------------------------------------------------------------- #
def palette_colors(widget: object) -> tuple[RGB, RGB]:
    """`(text, window)` from a widget's palette, falling back to a light default.

    Kept tiny and separate so everything above stays testable without a display.
    """
    try:
        palette = widget.palette()  # type: ignore[attr-defined]
        text = palette.windowText().color()
        window = palette.window().color()
        return (text.red(), text.green(), text.blue()), (
            window.red(), window.green(), window.blue())
    except Exception:  # pragma: no cover - only if Qt changes shape underneath us
        return (0, 0, 0), (239, 239, 239)


def muted_style_for(widget: object, extra: str = "") -> str:
    """`muted_stylesheet` for a live widget's palette."""
    fg, bg = palette_colors(widget)
    return muted_stylesheet(fg, bg, extra)
