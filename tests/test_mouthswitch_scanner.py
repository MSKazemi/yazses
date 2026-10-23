"""The single-switch scan state machine (`yazses.mouthswitch.scanner`) — pure, no clock.

Every call takes the time it is asked about, so these tests drive it with plain numbers. The
claims that matter for a user who cannot correct a wrong action quickly:

* the highlight steps through the items on a fixed interval and wraps;
* a click selects the item lit **when the click began**, even if the detector reports it
  after the highlight has moved on;
* a click outside the scan it is meant for, the same click twice, and a stale report select
  nothing; and a scan nobody is using stops by itself;
* a selection does not end the scan: the highlight stays on the selected item for a dwell,
  so a second click repeats it, and the inactivity stop counts from the last selection;
* when the scan is heard, each step is lit for its announcement (the injected
  ``announce_s``), the detector's post-voice deafness (``post_voice_s``), and then a full
  interval -- so a long name slows the scan but never shortens the time to click, the
  highlight never advances mid-word, and select-at-onset stays exact on that longer
  timeline; a scan that passes neither keeps its plain steps.
"""
from __future__ import annotations

import pytest

from yazses.mouthswitch.scanner import (
    DEFAULT_INTERVAL_S,
    DEFAULT_SCAN_ITEMS,
    MAX_ANNOUNCE_S,
    MAX_INTERVAL_S,
    MAX_LOOPS,
    MAX_POST_VOICE_S,
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


def test_a_selection_keeps_the_scan_going_with_the_highlight_on_the_selected_item():
    s = _scanner(3, 1.0)
    s.start(0.0)
    assert s.select(onset=1.5, now=1.7) == ScanItem("item 1", "command")
    assert s.scanning is True
    # Item 1 stays lit for a full dwell from the selection (1.7 s), where the old timeline
    # would have moved to item 2 at 2.0 s; then the highlight steps on as before.
    assert [s.tick(t) for t in (1.7, 2.0, 2.69, 2.7, 3.7, 4.7)] == [1, 1, 1, 2, 0, 1]


def test_a_second_click_on_the_same_item_repeats_it():
    s = _scanner(3, 1.0)
    s.start(0.0)
    assert s.select(1.5, 1.7) == ScanItem("item 1", "command")
    assert s.select(2.2, 2.4) == ScanItem("item 1", "command")  # still lit: selected again
    assert s.tick(3.39) == 1 and s.tick(3.4) == 2               # and re-anchored again


def test_one_click_selects_at_most_once():
    """The same click reported twice, or a click older than the last selection, is ignored."""
    s = _scanner(3, 1.0)
    s.start(0.0)
    assert s.select(1.5, 1.7) is not None
    assert s.select(1.5, 1.8) is None   # the same onset again
    assert s.select(1.4, 1.8) is None   # began before the click that already selected


def test_a_click_that_began_before_the_re_anchor_selects_what_was_lit_then():
    """Select-at-onset holds across a selection: the old timeline answers for its own past."""
    s = _scanner(3, 1.0)
    s.start(0.0)
    assert s.select(0.9, 1.4) == ScanItem("item 0", "command")  # re-anchored on item 0 at 1.4
    # This click began at 1.2 s, when the strip still showed item 1 (the re-anchor came at
    # 1.4 s), and is reported at 1.6 s, when item 0 is lit again.
    assert s.select(1.2, 1.6) == ScanItem("item 1", "command")


def test_the_inactivity_stop_counts_passes_since_the_last_selection():
    s = _scanner(3, 1.0)
    s.start(0.0)
    span = s.span_s                     # 3 passes x 3 items x 1.0 s = 9 s
    assert s.select(8.4, 8.5) is not None
    assert s.tick(8.5 + span - 0.01) is not None
    assert s.tick(8.5 + span) is None and s.scanning is False


def test_a_pop_still_stops_a_scan_that_has_selected():
    s = _scanner(3, 1.0)
    s.start(0.0)
    s.select(1.5, 1.7)
    assert s.toggle(2.0) is False and s.scanning is False
    assert s.select(2.1, 2.3) is None


def test_a_click_that_lands_after_a_stop_does_not_restart_the_scan():
    s = _scanner(3, 1.0)
    s.start(0.0)
    s.stop(2.0)
    assert s.select(1.95, 2.2) == ScanItem("item 1", "command")
    assert s.scanning is False and s.tick(2.3) is None


def test_steps_keep_counting_up_across_a_selection():
    s = _scanner(3, 1.0)
    s.start(0.0)
    assert s.view(1.6).step == 1
    s.select(1.5, 1.7)
    steps = [s.view(t).step for t in (1.7, 2.69, 2.7)]
    assert steps == [2, 2, 3]  # the re-anchored item is a new step: it is announced again


def test_a_long_run_of_selections_keeps_a_bounded_history():
    s = _scanner(3, 1.0)
    s.start(0.0)
    for k in range(1, 200):
        assert s.select(k - 0.2, float(k)) is not None
    assert len(s._segments) <= 2 * int(MAX_SELECT_LAG_S) + 3
    assert s.scanning is True


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


# ---- an announced scan: the name, the deafness, then a full interval to click -------------


def _announced(seconds: dict[str, float], n: int = 3, interval: float = 1.0,
               post_voice_s: float = 0.0) -> SwitchScanner:
    items = [ScanItem(f"item {i}", "command") for i in range(n)]
    return SwitchScanner(items, interval, announce_s=lambda item: seconds.get(item.label, 0.0),
                         post_voice_s=post_voice_s)


def test_an_announced_step_is_its_announcement_then_a_full_interval():
    """Never the longer of the two: a full interval always follows, however long the name."""
    s = _announced({"item 0": 0.4, "item 1": 1.75})
    assert s.dwells == pytest.approx((1.4, 2.75, 1.0))
    s.start(0.0)
    # item 0 for [0, 1.4), item 1 for [1.4, 4.15), item 2 for [4.15, 5.15), then item 0.
    assert [s.tick(t) for t in (1.39, 1.41, 4.14, 4.16, 5.14, 5.16)] == [0, 1, 1, 2, 2, 0]
    # The next pass keeps the same per-item dwells.
    assert [s.tick(t) for t in (5.15 + 1.41, 5.15 + 4.14, 5.15 + 4.16)] == [1, 1, 2]


def test_the_inactivity_stop_counts_whole_passes_of_the_longer_timeline():
    s = _announced({"item 1": 1.75})
    s.start(0.0)
    assert s.span_s == pytest.approx(MAX_LOOPS * (1.0 + 2.75 + 1.0))
    assert s.tick(s.span_s - 0.01) == 2
    assert s.tick(s.span_s) is None and s.scanning is False


def test_select_at_onset_stays_exact_on_a_lengthened_step():
    s = _announced({"item 1": 1.75})
    s.start(0.0)
    # Began at 3.6 s: still item 1 (lit until 3.75 s), reported at 3.9 s (item 2 lit).
    assert s.select(onset=3.6, now=3.9) == ScanItem("item 1", "command")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -2.0, 0.0, "soon", None])
def test_an_unusable_announcement_estimate_falls_back_to_the_interval(bad):
    s = SwitchScanner([ScanItem("a", "command")], 1.0, announce_s=lambda item: bad)
    assert s.dwells == (1.0,)


def test_an_estimate_that_raises_falls_back_to_the_interval():
    def boom(item):
        raise RuntimeError("no voice")

    s = SwitchScanner([ScanItem("a", "command")], 1.0, announce_s=boom)
    assert s.dwells == (1.0,)


def test_an_absurdly_long_announcement_is_capped_so_the_scan_still_moves():
    s = SwitchScanner([ScanItem("a", "command"), ScanItem("b", "command")], 1.0,
                      announce_s=lambda item: 600.0)
    assert s.dwells == (MAX_ANNOUNCE_S + 1.0, MAX_ANNOUNCE_S + 1.0)


# ---- a heard scan: wait out the detector's post-voice deafness ------------------------------


def test_a_heard_step_is_announcement_plus_deafness_plus_a_full_interval():
    s = _announced({"item 0": 0.4, "item 1": 1.75}, post_voice_s=0.4)
    assert s.dwells == pytest.approx((1.8, 3.15, 1.4))
    s.start(0.0)
    # item 0 for [0, 1.8), item 1 for [1.8, 4.95), item 2 for [4.95, 6.35), then item 0.
    assert [s.tick(t) for t in (1.79, 1.81, 4.94, 4.96, 6.34, 6.36)] == [0, 1, 1, 2, 2, 0]
    assert s.span_s == pytest.approx(MAX_LOOPS * (1.8 + 3.15 + 1.4))


@pytest.mark.parametrize("edge", ["opens", "closes"])
def test_a_long_name_still_leaves_a_full_dwell_to_click_after_the_deafness(edge):
    """"scroll down" at the default 1.2 s dwell takes about as long to say as the dwell.

    After the name and the deaf window behind it, a whole 1.2 s is left, and a click
    anywhere in it -- just after it opens or just before it closes -- selects that item.
    """
    from yazses.mouthswitch.announce import speech_duration_s

    items, _ = parse_scan_items(list(DEFAULT_SCAN_ITEMS))
    s = SwitchScanner(items, 1.2, announce_s=lambda item: speech_duration_s(item.label),
                      post_voice_s=0.4)
    k = [item.label for item in items].index("scroll down")
    name_s = speech_duration_s("scroll down")
    assert name_s >= 1.0  # the case this pins: a name about as long as the dwell
    assert s.dwells[k] == pytest.approx(name_s + 0.4 + 1.2)
    lit_at = sum(s.dwells[:k])
    heard_from = lit_at + name_s + 0.4      # the name has ended and the detector hears again
    window_end = lit_at + s.dwells[k]
    assert window_end - heard_from == pytest.approx(1.2)
    s.start(0.0)
    onset = heard_from + 0.01 if edge == "opens" else window_end - 0.01
    assert s.select(onset=onset, now=onset + 0.3) == items[k]


def test_a_cue_only_step_waits_for_its_tick_and_the_deafness():
    """No spoken name, but the tick is voiced too: its length and the window still apply."""
    s = SwitchScanner([ScanItem("a", "command"), ScanItem("b", "command")], 1.2,
                      announce_s=lambda item: 0.03, post_voice_s=0.4)
    assert s.dwells == pytest.approx((1.63, 1.63))
    s.start(0.0)
    assert [s.tick(t) for t in (1.62, 1.64, 3.25, 3.27)] == [0, 1, 1, 0]


def test_without_a_post_voice_window_the_steps_are_unchanged():
    """The overlay's silent scan passes nothing: the plain fixed-step timeline, exactly."""
    items = [ScanItem(f"item {i}", "command") for i in range(3)]
    assert SwitchScanner(items, 1.0).dwells == (1.0, 1.0, 1.0)
    assert SwitchScanner(items, 1.0, post_voice_s=0.0).dwells == (1.0, 1.0, 1.0)


def test_a_click_in_the_interval_after_the_deafness_selects_the_item_still_lit():
    s = SwitchScanner([ScanItem(f"item {i}", "command") for i in range(3)], 1.0,
                      post_voice_s=0.4)
    s.start(0.0)
    # Item 0 is lit for [0, 1.4): deaf until 0.4 s, then a full 1.0 s to click. This click
    # began at 1.3 s, inside that interval, and was reported at 1.6 s with item 1 lit.
    assert s.select(onset=1.3, now=1.6) == ScanItem("item 0", "command")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.4, "soon", None])
def test_an_unusable_post_voice_window_adds_nothing(bad):
    s = SwitchScanner([ScanItem("a", "command")], 1.0, post_voice_s=bad)
    assert s.dwells == (1.0,)


def test_an_absurd_post_voice_window_is_capped_so_the_scan_still_moves():
    s = SwitchScanner([ScanItem("a", "command")], 1.0, post_voice_s=600.0)
    assert s.dwells == (1.0 + MAX_POST_VOICE_S,)


def test_the_view_counts_steps_even_when_the_index_repeats():
    """A one-item scan lights item 0 every step; the step number still moves on."""
    s = SwitchScanner([ScanItem("only", "command")], 1.0)
    s.start(0.0)
    assert [(v.index, v.step) for v in (s.view(0.1), s.view(1.1), s.view(2.1))] == [
        (0, 0), (0, 1), (0, 2)]
    assert s.view(-1.0).step == -1  # a moment before the scan: no step at all


def test_steps_count_across_lengthened_passes():
    s = _announced({"item 1": 1.75})
    s.start(0.0)
    # Dwells (1.0, 2.75, 1.0): item 1 is lit for [1.0, 3.75), so the steps land here.
    assert [s.view(t).step for t in (0.5, 1.5, 4.0, 5.0, 6.0, 8.6)] == [0, 1, 2, 3, 4, 5]


def test_each_start_is_a_new_generation():
    s = _scanner()
    assert s.generation == 0
    s.start(0.0)
    s.stop(1.0)
    s.start(2.0)
    assert s.generation == 2
