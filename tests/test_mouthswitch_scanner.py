"""The single-switch scan state machine (`yazses.mouthswitch.scanner`) — pure, no clock.

Every call takes the time it is asked about, so these tests drive it with plain numbers. The
claims that matter for a user who cannot correct a wrong action quickly:

* the highlight steps through the items on a fixed interval and wraps;
* a click selects the item lit **when the click began**, even if the detector reports it
  after the highlight has moved on;
* a click outside the scan it is meant for, a second click in the same scan, and a stale
  report select nothing; and a scan nobody is using stops by itself.
"""
from __future__ import annotations

import pytest

from yazses.mouthswitch.scanner import (
    DEFAULT_INTERVAL_S,
    DEFAULT_SCAN_ITEMS,
    MAX_INTERVAL_S,
    MAX_LOOPS,
    MAX_SELECT_LAG_S,
    MIN_INTERVAL_S,
    SCROLL_NOTCHES,
    ScanItem,
    SwitchScanner,
    normalise_label,
    parse_scan_items,
    scan_interval,
)


def _scanner(n: int = 3, interval: float = 1.0) -> SwitchScanner:
    return SwitchScanner([ScanItem(f"item {i}", "command") for i in range(n)], interval)


# ---- parsing the configured items ----------------------------------------------------------


def test_the_defaults_are_the_owner_set_with_pointer_items_typed():
    items, problems = parse_scan_items(list(DEFAULT_SCAN_ITEMS))
    assert problems == []
    assert [i.label for i in items] == ["enter", "undo", "scroll up", "scroll down", "click"]
    by_label = {i.label: i for i in items}
    assert by_label["enter"].kind == "command" and by_label["undo"].kind == "command"
    assert by_label["click"] == ScanItem("click", "pointer", op="click", dy=0)
    assert by_label["scroll up"] == ScanItem("scroll up", "pointer", op="scroll",
                                             dy=-SCROLL_NOTCHES)
    assert by_label["scroll down"].dy == SCROLL_NOTCHES  # +dy scrolls down (pointer/base.py)


def test_the_config_default_is_the_same_list():
    from yazses.config import Config

    assert tuple(Config().mouthswitch.scan_items) == DEFAULT_SCAN_ITEMS
    assert Config().mouthswitch.enabled is False


def test_labels_are_normalised_and_junk_is_skipped_with_a_reason():
    items, problems = parse_scan_items(["  Page   DOWN ", "", 7, None, "page down", "Copy"])
    assert [i.label for i in items] == ["page down", "copy"]
    assert len(problems) == 4  # "", 7, None, and the duplicate


@pytest.mark.parametrize("raw", [None, "enter", 3, {"enter": 1}])
def test_a_value_that_is_not_a_list_falls_back_to_the_defaults(raw):
    items, problems = parse_scan_items(raw)
    assert [i.label for i in items] == list(DEFAULT_SCAN_ITEMS)
    assert problems


def test_an_empty_list_falls_back_to_the_defaults():
    items, problems = parse_scan_items([])
    assert [i.label for i in items] == list(DEFAULT_SCAN_ITEMS)
    assert problems == ["scan_items has no usable item; using the defaults"]


def test_normalise_label():
    assert normalise_label("  Scroll\tUp ") == "scroll up"
    assert normalise_label(None) == ""


@pytest.mark.parametrize("value,expected", [
    (1.2, 1.2), (0.1, MIN_INTERVAL_S), (99, MAX_INTERVAL_S), ("x", DEFAULT_INTERVAL_S),
    (float("nan"), DEFAULT_INTERVAL_S), (float("inf"), DEFAULT_INTERVAL_S),
    (None, DEFAULT_INTERVAL_S),
])
def test_the_interval_is_clamped_to_something_usable(value, expected):
    assert scan_interval(value) == expected


# ---- the highlight -------------------------------------------------------------------------


def test_nothing_is_lit_before_a_scan_starts():
    s = _scanner()
    assert s.scanning is False
    assert s.tick(5.0) is None
    view = s.view(5.0)
    assert (view.scanning, view.index, view.item) == (False, -1, None)


def test_the_highlight_steps_on_the_interval_and_wraps():
    s = _scanner(3, 1.0)
    assert s.start(10.0) is True
    assert [s.tick(t) for t in (10.0, 10.99, 11.0, 12.5, 13.0, 14.2)] == [0, 0, 1, 2, 0, 1]
    assert s.view(12.5).item == ScanItem("item 2", "command")


def test_a_scanner_with_no_items_cannot_start():
    s = SwitchScanner([], 1.0)
    assert s.start(0.0) is False
    assert s.scanning is False


def test_toggle_starts_and_stops():
    s = _scanner()
    assert s.toggle(0.0) is True and s.scanning
    assert s.toggle(0.5) is False and not s.scanning
    assert s.tick(0.6) is None


def test_a_scan_nobody_uses_stops_by_itself_after_its_loops():
    s = _scanner(3, 1.0)
    s.start(0.0)
    assert s.span_s == MAX_LOOPS * 3 * 1.0
    assert s.tick(s.span_s - 0.01) == 2
    assert s.tick(s.span_s) is None and s.scanning is False


# ---- the select ----------------------------------------------------------------------------


def test_a_click_selects_the_item_lit_when_it_began_not_when_it_was_heard():
    s = _scanner(3, 1.0)
    s.start(0.0)
    # The click began at 0.9 s (item 0 lit); the detector reported it at 1.2 s (item 1 lit).
    assert s.select(onset=0.9, now=1.2) == ScanItem("item 0", "command")


def test_a_selection_stops_the_scan_and_a_second_click_selects_nothing():
    s = _scanner(3, 1.0)
    s.start(0.0)
    assert s.select(1.5, 1.7) is not None
    assert s.scanning is False
    assert s.select(1.6, 1.8) is None


def test_a_click_with_no_scan_selects_nothing():
    s = _scanner()
    assert s.select(0.5, 0.7) is None


def test_a_click_that_began_before_the_scan_selects_nothing():
    s = _scanner()
    s.start(10.0)
    assert s.select(9.9, 10.2) is None
    assert s.scanning is True  # and the scan is not consumed by it


def test_a_click_that_began_after_the_scan_was_stopped_selects_nothing():
    s = _scanner()
    s.start(0.0)
    s.stop(2.0)
    assert s.select(2.1, 2.3) is None


def test_a_click_that_began_just_before_a_stop_still_lands():
    """The detector reports a sound only after quiet behind it; the stop may come first."""
    s = _scanner(3, 1.0)
    s.start(0.0)
    s.stop(2.0)
    assert s.select(1.95, 2.2) == ScanItem("item 1", "command")


def test_a_click_on_the_last_moment_of_a_timed_out_scan_still_lands():
    s = _scanner(3, 1.0)
    s.start(0.0)
    end = s.span_s
    assert s.tick(end + 0.1) is None  # the worker saw the scan run out
    assert s.select(end - 0.05, end + 0.2) == ScanItem("item 2", "command")


def test_a_stale_click_selects_nothing():
    s = _scanner()
    s.start(0.0)
    assert s.select(0.5, 0.5 + MAX_SELECT_LAG_S + 0.01) is None


def test_a_restarted_scan_begins_at_the_first_item_and_can_select_again():
    s = _scanner(3, 1.0)
    s.start(0.0)
    assert s.select(1.2, 1.4) == ScanItem("item 1", "command")
    s.start(5.0)
    assert s.tick(5.1) == 0
    assert s.select(5.2, 5.4) == ScanItem("item 0", "command")
