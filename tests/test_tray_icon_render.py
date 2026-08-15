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
