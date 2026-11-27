"""The window's colour themes: readable by construction, and total on bad input."""
from __future__ import annotations

import pytest

from yazses.settingsui import palette
from yazses.settingsui.theme import contrast_ratio

VIOLET = ("violet-dark", "violet-light")


def _rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


@pytest.mark.parametrize("theme", VIOLET)
@pytest.mark.parametrize("ink", ("text", "muted", "accent", "ok", "warn", "bad"))
@pytest.mark.parametrize("surface", ("bg", "side", "card", "card2"))
def test_every_text_colour_meets_aa_on_every_surface(theme, ink, surface):
    colours = palette.palette_for(theme)
    assert contrast_ratio(_rgb(getattr(colours, ink)), _rgb(getattr(colours, surface))) >= 4.5


@pytest.mark.parametrize("theme", VIOLET)
def test_the_primary_button_label_is_readable(theme):
    colours = palette.palette_for(theme)
    assert contrast_ratio(_rgb(colours.on_primary), _rgb(colours.primary)) >= 4.5


@pytest.mark.parametrize("theme", VIOLET)
@pytest.mark.parametrize("surface", ("bg", "card"))
def test_the_edge_of_a_field_is_visible(theme, surface):
    """WCAG's 3:1 for the boundary of a control."""
    colours = palette.palette_for(theme)
    assert contrast_ratio(_rgb(colours.control), _rgb(getattr(colours, surface))) >= 3.0


@pytest.mark.parametrize("bad", ("", "dark", "VIOLET", None, 3))
def test_an_unknown_theme_falls_back_to_the_default(bad):
    assert palette.normalise_theme(bad) == palette.DEFAULT_THEME == "violet-dark"


def test_system_means_no_palette_and_no_stylesheet():
    assert palette.normalise_theme("system") == "system"
    assert palette.palette_for("system") is None
    assert palette.window_stylesheet(None) == ""


def test_the_stylesheet_paints_cards_and_primary_buttons_from_the_palette():
    colours = palette.palette_for("violet-dark")
    css = palette.window_stylesheet(colours)
    assert '[card="true"]' in css and colours.card in css
    assert '[primary="true"]' in css and colours.primary in css


def test_every_offered_theme_has_a_label():
    assert [value for _label, value in palette.THEME_CHOICES] == list(palette.THEMES)
    assert palette.THEMES == ("violet-dark", "violet-light", "system")


def test_the_config_checker_accepts_exactly_the_themes_the_window_offers():
    from yazses.configcheck import enum_values

    assert tuple(enum_values("window", "theme")) == palette.THEMES
