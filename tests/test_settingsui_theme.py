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

import random

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


# Palettes people actually run, rather than synthetic pairs. Solarized earns its place
# twice over: both variants have *theme text* that already fails AA (4.13 and 4.75
# against a 4.5 bar, so light fails outright and dark has almost no room), which is the
# documented leave-it-alone branch reached by a real theme instead of a contrived one.
REAL_THEMES = {
    "adwaita-dark": ((0xFF, 0xFF, 0xFF), (0x24, 0x24, 0x24)),
    "solarized-light": ((0x65, 0x7B, 0x83), (0xFD, 0xF6, 0xE3)),
    "solarized-dark": ((0x83, 0x94, 0x96), (0x00, 0x2B, 0x36)),
    "nord": ((0xD8, 0xDE, 0xE9), (0x2E, 0x34, 0x40)),
    "dracula": ((0xF8, 0xF8, 0xF2), (0x28, 0x2A, 0x36)),
}


@pytest.mark.parametrize("fg, bg", list(REAL_THEMES.values()), ids=list(REAL_THEMES))
def test_real_desktop_themes_are_never_made_worse(fg, bg):
    """Either the muted colour clears AA, or the theme's own text never did.

    The second half is the whole reason this is not a simple assertion: fading text
    that already fails would make it worse, so those are returned unchanged and the
    failure belongs to the theme.
    """
    base = contrast_ratio(fg, bg)
    got = contrast_ratio(muted(fg, bg), bg)
    if base >= AA_NORMAL:
        assert got >= AA_NORMAL, f"muted text scores {got:.2f} on a theme scoring {base:.2f}"
    else:
        assert muted(fg, bg) == fg, "a theme that already fails AA must be left alone"


def test_no_palette_at_all_produces_failing_muted_text():
    """The parametrised cases prove six palettes work; this proves none can break it.

    A fixed list of themes cannot find the combination nobody thought of, and the
    input here is arbitrary — Qt hands over whatever the user's desktop is set to.
    Seeded, so a failure is reproducible rather than a Heisenbug in CI.
    """
    rng = random.Random(0)

    def pair():
        # Modelled on how themes are actually built -- one light end, one dark end,
        # either way round -- with a quarter left fully arbitrary for breadth. Uniform
        # random RGB pairs are mid-grey mush no desktop ships: sampling that way, only
        # 362 of 3000 cleared AA at all, so the sweep spent 88% of its work on the
        # branch that returns early.
        if rng.random() < 0.25:
            return (tuple(rng.randrange(256) for _ in range(3)),
                    tuple(rng.randrange(256) for _ in range(3)))
        dark = tuple(rng.randrange(0, 90) for _ in range(3))
        light = tuple(rng.randrange(165, 256) for _ in range(3))
        return (dark, light) if rng.random() < 0.5 else (light, dark)

    checked = 0
    for _ in range(3000):
        fg, bg = pair()
        if contrast_ratio(fg, bg) < AA_NORMAL:
            continue  # documented: returned unchanged, the theme's own problem
        checked += 1
        got = contrast_ratio(muted(fg, bg), bg)
        assert got >= AA_NORMAL - 1e-9, (
            f"fg={fg} bg={bg} produced muted text at {got:.3f}:1"
        )
    assert checked > 500, (
        f"only {checked} palettes cleared AA to begin with — the sweep is not "
        "exercising the branch it exists to check"
    )
