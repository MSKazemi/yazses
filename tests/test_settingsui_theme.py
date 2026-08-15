"""Secondary text in the settings window must be readable on any theme.

It was `color: gray` — a literal `#808080`, repeated in five places — and that fails
WCAG AA on both of Qt's default backgrounds: **3.43:1** on the light window and
**3.44:1** on the dark one, against the 4.5:1 normal text requires. Not marginally, and
not on an unusual theme.

That is worth a test rather than a code review, because the failure is invisible to the
person who wrote it: `gray` looks fine to someone with unimpaired vision on the display
they happen to have, and this is a project whose own research pages argue that assistive
technology skips Linux and is priced out of reach.

The maths is Qt-free so it runs everywhere, in the same way the tray's icon decisions are
separated from its painting.
"""

from __future__ import annotations

import pytest

from yazses.settingsui.theme import (
    AA_NORMAL,
    blend,
    contrast_ratio,
    muted,
    muted_stylesheet,
    relative_luminance,
    to_hex,
)

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
QT_LIGHT = (239, 239, 239)
QT_DARK = (46, 46, 46)
OLD_GRAY = (128, 128, 128)


# ---- the maths is right ----------------------------------------------------


def test_luminance_endpoints():
    assert relative_luminance(BLACK) == pytest.approx(0.0)
    assert relative_luminance(WHITE) == pytest.approx(1.0)


def test_contrast_is_symmetric_and_bounded():
    assert contrast_ratio(BLACK, WHITE) == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio(WHITE, BLACK) == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio(WHITE, WHITE) == pytest.approx(1.0)


def test_blend_endpoints_and_clamping():
    assert blend(BLACK, WHITE, 0.0) == BLACK
    assert blend(BLACK, WHITE, 1.0) == WHITE
    assert blend(BLACK, WHITE, -5) == BLACK
    assert blend(BLACK, WHITE, 5) == WHITE


# ---- the defect this replaces ----------------------------------------------


@pytest.mark.parametrize("background", [QT_LIGHT, QT_DARK], ids=["light", "dark"])
def test_the_old_hardcoded_gray_really_did_fail(background):
    """Recorded so the change cannot later be mistaken for a matter of taste."""
    assert contrast_ratio(OLD_GRAY, background) < AA_NORMAL


# ---- what replaces it ------------------------------------------------------


@pytest.mark.parametrize(
    "fg, bg",
    [(BLACK, QT_LIGHT), (WHITE, QT_DARK), (BLACK, WHITE), (WHITE, BLACK),
     ((238, 238, 238), (30, 30, 30)), ((20, 20, 30), (250, 250, 245))],
    ids=["qt-light", "qt-dark", "max-light", "max-dark", "very-dark", "warm-light"],
)
def test_muted_text_meets_aa_on_every_theme(fg, bg):
    assert contrast_ratio(muted(fg, bg), bg) >= AA_NORMAL


@pytest.mark.parametrize(
    "fg, bg", [(BLACK, QT_LIGHT), (WHITE, QT_DARK)], ids=["light", "dark"]
)
def test_muted_text_is_actually_muted(fg, bg):
    """It has to *look* secondary, or the fix trades one defect for another."""
    result = muted(fg, bg)
    assert result != fg, "no fading happened at all"
    assert contrast_ratio(result, bg) < contrast_ratio(fg, bg), (
        "muted text should be lower-contrast than body text, just not illegibly so"
    )


def test_a_theme_whose_own_text_fails_is_left_alone():
    """If the desktop's text colour already fails AA, fading it further would make a bad
    theme worse. That is the theme's problem, not one a stylesheet can fix."""
    bad_fg, bad_bg = (150, 150, 150), (170, 170, 170)
    assert contrast_ratio(bad_fg, bad_bg) < AA_NORMAL
    assert muted(bad_fg, bad_bg) == bad_fg


def test_it_adapts_rather_than_returning_one_colour():
    """The whole point: a fixed value cannot be right on both."""
    assert muted(BLACK, QT_LIGHT) != muted(WHITE, QT_DARK)


# ---- the stylesheet it produces --------------------------------------------


def test_stylesheet_is_a_valid_colour_rule():
    css = muted_stylesheet(BLACK, QT_LIGHT)
    assert css.startswith("color: #") and css.endswith(";")


def test_extra_declarations_are_preserved():
    css = muted_stylesheet(BLACK, QT_LIGHT, "margin-left: 24px;")
    assert "margin-left: 24px;" in css and "color: #" in css


def test_hex_formatting():
    assert to_hex((128, 128, 128)) == "#808080"
    assert to_hex((0, 0, 0)) == "#000000"


# ---- and it is actually used -----------------------------------------------


def test_no_hardcoded_grey_remains_in_the_settings_window():
    """A correct helper nothing calls would leave the defect in place."""
    import inspect

    from yazses.settingsui import app

    source = inspect.getsource(app)
    assert "color: gray" not in source, (
        "the settings window still hardcodes `color: gray`, which fails WCAG AA on "
        "both light and dark backgrounds"
    )
    assert "muted_style_for" in source, "the theme helper is imported but never used"
