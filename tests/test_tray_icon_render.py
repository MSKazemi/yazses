"""The tray icon actually renders — including the level ring.

`test_tray_level_ring.py` covers the pure decision (what fraction, above the gate or
not, show or hide). None of that touches QPainter, and the ring is drawn with
`drawArc` inside the icon paint path, where an exception does not raise a visible
error — it loses the tray icon.

This project has been here before: every Qt test was skipped in CI and hung locally,
so the settings window was verified by nothing at all. Hence a headless render of the
real code path, with the offscreen platform, on the same footing as the overlay's
smoke test.

Note on what is asserted. Pixel-comparing an icon is a change-detector that fails on
every intentional tweak, so the assertions are structural: the paint completes, the
result is a real pixmap, and the ring band is drawn exactly when `level_ring` says to
show it and left alone when it does not.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.platform.linux.tray import _ICON_PX, LinuxTray  # noqa: E402

RECORDING = {"state": "recording", "audio_level": 0.03, "vad_threshold": 0.01}
QUIET = {"state": "recording", "audio_level": 0.001, "vad_threshold": 0.01}
IDLE = {"state": "idle", "audio_level": 0.03, "vad_threshold": 0.01}


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _ring_band_pixels(icon) -> int:
    """Non-transparent pixels in the outermost rows, where only the ring reaches.

    The badge is inset by 5px and the ring by 1.5px, so these rows are ring-only —
    which makes this a direct answer to "was an arc drawn" without asserting colours.
    """
    image = icon.pixmap(_ICON_PX, _ICON_PX).toImage()
    return sum(
        1
        for x in range(_ICON_PX)
        for y in (1, 2, _ICON_PX - 2, _ICON_PX - 3)
        if image.pixelColor(x, y).alpha() > 0
    )


def test_the_icon_renders_at_all(qapp):
    icon = LinuxTray()._make_icon("#1a73e8", IDLE)
    assert not icon.pixmap(_ICON_PX, _ICON_PX).isNull()


def test_recording_draws_the_ring(qapp):
    assert _ring_band_pixels(LinuxTray()._make_icon("#34a853", RECORDING)) > 0


def test_a_quiet_microphone_still_draws_the_ring(qapp):
    """Nothing drawn would look identical to 'not recording' — the one confusion
    this ring exists to prevent."""
    assert _ring_band_pixels(LinuxTray()._make_icon("#34a853", QUIET)) > 0


def test_idle_draws_no_ring(qapp):
    """A ring on an idle badge would imply YazSes is listening when it is not."""
    assert _ring_band_pixels(LinuxTray()._make_icon("#1a73e8", IDLE)) == 0


@pytest.mark.parametrize(
    "status",
    [
        None,
        {},
        {"state": "recording", "audio_level": "loud", "vad_threshold": None},
        {"state": "recording", "audio_level": 0.03, "vad_threshold": 0},
    ],
)
def test_a_bad_status_still_paints_an_icon(qapp, status):
    """Losing the tray to a malformed status dict would be a poor trade for a ring."""
    icon = LinuxTray()._make_icon("#1a73e8", status)
    assert not icon.pixmap(_ICON_PX, _ICON_PX).isNull()
    assert _ring_band_pixels(icon) == 0


def test_every_state_colour_paints(qapp):
    """The five badge colours all still render with the ring code in the path."""
    for colour in ("#34a853", "#fbbc04", "#9c27b0", "#1a73e8", "#e53935"):
        assert not LinuxTray()._make_icon(colour, RECORDING).pixmap(
            _ICON_PX, _ICON_PX
        ).isNull()


# --- the mark is the canonical one, not a font glyph -------------------------
#
# The Linux badge used to be drawn freehand: a rounded rect with an arbitrary
# radius, and a bold letter "Y" from whatever QFont the system happened to supply.
# Windows draws the same badge from brandmark.py, whose geometry is the committed
# SVG's. So the two platforms rendered visibly different icons for identical state,
# and the Linux glyph changed with the user's fonts.
#
# The geometry is now shared: brandmark owns the numbers, and each platform paints
# them with its own toolkit. Reusing brandmark's *renderer* was the obvious move and
# is a trap — Pillow is a win32-only runtime dependency, so importing it here would
# either add it to every Linux install or fail silently into a tray with no icon.


def test_the_badge_geometry_comes_from_brandmark(qapp):
    """Not a font, and not a second set of numbers that can drift."""
    from yazses.brandmark import _GRID, _RADIUS, _Y_PATHS

    assert _GRID and _RADIUS and _Y_PATHS, "brandmark no longer exposes its geometry"

    import yazses.platform.linux.tray as tray_mod

    source = (tray_mod.__file__ or "").replace(".pyc", ".py")
    text = open(source, encoding="utf-8").read()
    assert "brandmark" in text, (
        "the Linux tray no longer references brandmark — if it went back to drawing "
        "its own badge, Linux and Windows will drift apart again"
    )
    assert "setFont" not in text, (
        "the mark is a stroked path, not a text glyph: a QFont makes the icon depend "
        "on the user's installed fonts (brandmark.py:28-30 rejects this for the same "
        "reason)"
    )


def test_pillow_is_not_imported_by_the_linux_tray(qapp):
    """The dependency trap, pinned.

    Pillow is `sys_platform == "win32"` in [project.dependencies] plus a dev-group
    dependency. A Linux user on the snap, the .deb, the AUR package or
    `pip install yazses[desktop]` has PySide6 and no Pillow. An import here raises
    inside the paint path's `except`, which swallows it — so the tray would appear
    with no icon at all, silently, and no test would notice.
    """
    import yazses.platform.linux.tray as tray_mod

    source = (tray_mod.__file__ or "").replace(".pyc", ".py")
    text = open(source, encoding="utf-8").read()
    assert "from PIL" not in text and "import PIL" not in text, (
        "the Linux tray imports Pillow, which is not installed on most Linux "
        "installs — the icon would vanish silently"
    )
    # Checked as a call/import rather than as the bare word: the module docstring
    # names render_mark precisely to explain why it must not be used here, and a
    # substring match would forbid saying so. (The windowctl guard takes the
    # opposite view on purpose — parsing negation in prose is unreliable, but
    # telling a call from a mention is not.)
    assert "import render_mark" not in text and "render_mark(" not in text, (
        "render_mark is the Pillow renderer; the Linux tray must paint the shared "
        "geometry with QPainter instead"
    )


def test_the_ring_band_is_still_clear_when_idle(qapp):
    """The badge must keep its 5px inset, or the ring band fills and every
    ring assertion in this file becomes meaningless."""
    icon = LinuxTray()._make_icon("#1a73e8", IDLE)
    assert _ring_band_pixels(icon) == 0


def test_the_mark_is_drawn_inside_the_badge(qapp):
    """A blank badge would pass every structural assertion above. This checks the
    Y actually put light pixels on the dark badge."""
    icon = LinuxTray()._make_icon("#1a73e8", None)
    image = icon.pixmap(_ICON_PX, _ICON_PX).toImage()
    centre = _ICON_PX // 2
    light = sum(
        1
        for x in range(centre - 12, centre + 12)
        for y in range(centre - 12, centre + 12)
        if image.pixelColor(x, y).lightness() > 200
    )
    assert light > 20, "no light pixels where the Y should be — the mark did not draw"
