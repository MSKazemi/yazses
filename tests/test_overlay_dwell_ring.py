"""The overlay shows a dwell-click coming, before it fires (#405).

A Head-Pointer click that arrives unannounced is the Midas-touch failure the whole dwell design
is judged against, so the progress has to reach the user's eyes: daemon `status` carries a
0..1 fraction, the poller reads it, `compute_frame` makes the overlay visible even though no
one is dictating and puts the ring *around the pointer*, and the widget draws an arc.

The first four are pure and need no Qt. The last two use the offscreen Qt platform and are
skipped when PySide6 (the `overlay`/`desktop` extra) is absent, like the rest of the widget
tests.
"""
from __future__ import annotations

import os

import pytest

from yazses.config import OverlayConfig
from yazses.overlay.animation import SonarModel
from yazses.overlay.app import compute_frame
from yazses.overlay.envelope import EnvelopeFollower
from yazses.overlay.poller import StatusSnapshot, next_interval, parse_status
from yazses.overlay.position import place_centered

SCREEN = (0, 0, 1920, 1080)


def _frame(snap: StatusSnapshot, cursor=(800, 500), cfg: OverlayConfig | None = None):
    return compute_frame(
        snap, cfg or OverlayConfig(), EnvelopeFollower(), SonarModel(),
        now=0.0, cursor=cursor, screen=SCREEN,
    )


# --------------------------------------------------------------------------- #
# status -> snapshot
# --------------------------------------------------------------------------- #
def test_the_dwell_fraction_is_read_from_the_headpointer_block():
    snap = parse_status({"state": "idle", "headpointer": {"dwell_progress": 0.4}})
    assert snap.dwell_progress == 0.4


@pytest.mark.parametrize(
    "block",
    [None, "nope", {}, {"dwell_progress": "x"}, {"dwell_progress": float("nan")},
     {"dwell_progress": -1.0}, {"dwell_progress": 0.0}],
)
def test_anything_unreadable_or_nonpositive_means_no_ring(block):
    snap = parse_status({"state": "idle", "headpointer": block})
    assert snap.dwell_progress == 0.0


def test_a_status_without_the_block_is_the_old_reply_and_means_no_ring():
    assert parse_status({"state": "idle"}).dwell_progress == 0.0


def test_the_fraction_is_clamped_to_one():
    assert parse_status({"headpointer": {"dwell_progress": 7}}).dwell_progress == 1.0


def test_polling_speeds_up_while_a_dwell_is_building():
    assert next_interval("idle", 0.3) == next_interval("recording")
    assert next_interval("idle", 0.0) > next_interval("idle", 0.3)
    assert next_interval("idle") == next_interval("idle", 0.0)  # old call shape unchanged


# --------------------------------------------------------------------------- #
# the per-frame decision
# --------------------------------------------------------------------------- #
def test_a_building_dwell_makes_the_overlay_visible_while_nobody_is_dictating():
    frame = _frame(StatusSnapshot(state="idle", dwell_progress=0.5))
    assert frame.visible is True
    assert frame.dwell_progress == 0.5


def test_no_dwell_and_no_dictation_still_hides_the_overlay():
    frame = _frame(StatusSnapshot(state="idle"))
    assert frame.visible is False and frame.dwell_progress == 0.0


def test_the_ring_is_centred_on_the_pointer_whatever_position_the_voice_rings_use():
    cfg = OverlayConfig(position="bottom_center")
    frame = _frame(StatusSnapshot(state="idle", dwell_progress=0.5), cursor=(800, 500), cfg=cfg)
    size = cfg.size_px
    assert frame.top_left == (800 - size // 2, 500 - size // 2)


def test_voice_rings_and_the_dwell_ring_can_be_up_together():
    frame = _frame(StatusSnapshot(state="recording", audio_level=0.4, dwell_progress=0.2))
    assert frame.visible and frame.ripples and frame.dwell_progress == 0.2


def test_centred_placement_stays_on_screen_at_every_edge():
    size = 220
    for cursor in [(0, 0), (1919, 0), (0, 1079), (1919, 1079), (960, 540)]:
        x, y = place_centered(cursor, size, SCREEN)
        assert 0 <= x <= 1920 - size and 0 <= y <= 1080 - size


# --------------------------------------------------------------------------- #
# the widget
# --------------------------------------------------------------------------- #
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def _pixels(widget) -> bytes:
    image = widget.grab().toImage()
    return bytes(image.constBits())


def test_the_widget_draws_something_when_a_dwell_is_in_progress(qapp):
    from yazses.overlay.widget import SonarWidget

    widget = SonarWidget(220, "#00e5ff")
    widget.set_ripples([], 0.0)
    blank = _pixels(widget)
    widget.set_dwell(0.5)
    half = _pixels(widget)
    widget.set_dwell(0.9)
    most = _pixels(widget)
    assert half != blank  # a ring appeared
    assert most != half  # and it advances: that is what "progress" means
    widget.set_dwell(0.0)
    assert _pixels(widget) == blank  # withdrawn when the dwell ends


def test_the_widget_survives_garbage_progress(qapp):
    from yazses.overlay.widget import SonarWidget

    widget = SonarWidget(220, "#00e5ff")
    for value in (float("nan"), -3.0, 99.0):
        widget.set_dwell(value)
        assert not widget.grab().isNull()
