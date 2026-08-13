"""Hotkey picker, mic dropdown and VAD slider — the models (#62).

No Qt, no keyboard, no microphone. Each control has a way of being wrong that a
checkbox cannot be, and those are what is tested here.
"""

from __future__ import annotations

import pytest

from yazses.settingsui.controls import (
    VAD_MAX,
    VAD_MIN,
    apply_setting,
    clamp_threshold,
    meter_reading,
    mic_choices,
    recommend_threshold,
    slider_to_threshold,
    supported_hotkeys,
    threshold_to_slider,
    validate_hotkey,
)

KEY_MAP = {"space": 57, "right_ctrl": 97, "left_ctrl": 29, "right_alt": 100}


class _Dev:
    def __init__(self, name):
        self.name = name


DEVICES = [_Dev("Built-in Microphone"), _Dev("Yeti Stereo Microphone"), _Dev("HDMI Audio")]


# ---- hotkey ----------------------------------------------------------------


def test_only_bindable_keys_are_offered():
    assert supported_hotkeys(KEY_MAP) == ["left_ctrl", "right_alt", "right_ctrl", "space"]


def test_a_bindable_key_validates():
    assert validate_hotkey("right_ctrl", KEY_MAP) is None
    assert validate_hotkey("  RIGHT_CTRL  ", KEY_MAP) is None


def test_an_unbindable_key_is_refused_with_the_supported_list():
    """Writing it would leave the user unable to dictate, with no explanation."""
    reason = validate_hotkey("f13", KEY_MAP)
    assert reason and "cannot be used" in reason
    assert "right_ctrl" in reason, "must say what IS supported"


def test_capturing_nothing_is_refused():
    assert validate_hotkey("", KEY_MAP)
    assert validate_hotkey("   ", KEY_MAP)


# ---- microphone ------------------------------------------------------------


def test_the_first_row_is_follow_the_system_default():
    rows = mic_choices(DEVICES, default_name="Built-in Microphone", pinned="")
    assert rows[0].value == "", "an empty [audio] device means 'follow the default'"
    assert "Built-in Microphone" in rows[0].label


def test_the_default_device_is_marked_like_the_cli():
    rows = mic_choices(DEVICES, default_name="Built-in Microphone", pinned="")
    assert any("●" in r.label for r in rows)


def test_a_pinned_device_is_marked_like_the_cli():
    rows = mic_choices(DEVICES, default_name="Built-in Microphone", pinned="Yeti")
    yeti = next(r for r in rows if r.value == "Yeti Stereo Microphone")
    assert "★" in yeti.label and yeti.is_pinned


def test_pinning_matches_a_substring_because_that_is_what_the_recorder_does():
    """`[audio] device` is a name fragment, not an exact device name."""
    rows = mic_choices(DEVICES, default_name=None, pinned="yeti")
    assert next(r for r in rows if "Yeti" in r.value).is_pinned


def test_with_nothing_pinned_the_default_row_is_the_selected_one():
    rows = mic_choices(DEVICES, default_name="Built-in Microphone", pinned="")
    assert rows[0].is_pinned is True


def test_no_devices_still_offers_the_default_row():
    rows = mic_choices([], default_name=None, pinned="")
    assert len(rows) == 1 and rows[0].value == ""


# ---- VAD threshold ---------------------------------------------------------


def test_the_slider_is_logarithmic_so_the_useful_range_is_reachable():
    """Linear would put every usable value in the leftmost pixel."""
    low = threshold_to_slider(0.0005)
    mid = threshold_to_slider(0.005)
    high = threshold_to_slider(0.05)
    assert 0 < low < mid < high < 1000
    # A linear map would compress these into a few percent of the track.
    assert mid - low > 100 and high - mid > 100


def test_slider_and_threshold_round_trip():
    for value in (0.0005, 0.004, 0.02, 0.1):
        assert slider_to_threshold(threshold_to_slider(value)) == pytest.approx(value, rel=0.02)


def test_thresholds_are_clamped_into_a_range_that_means_something():
    assert clamp_threshold(0) == VAD_MIN, "zero accepts silence as speech"
    assert clamp_threshold(5.0) == VAD_MAX, "above this it rejects a shout"
    assert clamp_threshold("nonsense") == VAD_MIN


def test_the_written_value_is_a_readable_float_not_a_long_tail():
    """0.004000000000000001 in someone's config file is a bug report."""
    value = slider_to_threshold(437)
    assert len(repr(value)) <= 8, repr(value)


def test_the_meter_answers_is_my_voice_above_the_line():
    _, clears = meter_reading(level=0.01, threshold=0.004)
    assert clears is True
    _, quiet = meter_reading(level=0.001, threshold=0.004)
    assert quiet is False


def test_the_meter_bar_stays_in_range():
    for level in (0.0, 0.0001, 0.01, 5.0):
        position, _ = meter_reading(level, 0.004)
        assert 0 <= position <= 100


def test_the_recommendation_sits_below_measured_speech():
    """High enough to reject a quiet room, low enough that a soft sentence passes."""
    assert recommend_threshold(0.02) == pytest.approx(0.01, rel=0.01)
    assert recommend_threshold(0.0) == VAD_MIN


# ---- writing ---------------------------------------------------------------


def test_a_successful_write_tells_the_user_to_restart():
    ok, message = apply_setting("hotkey", "key", "right_ctrl", write=lambda *a: True)
    assert ok and "Restart" in message


def test_a_failed_write_is_reported_rather_than_silently_lost():
    ok, message = apply_setting("hotkey", "key", "right_ctrl", write=lambda *a: False)
    assert not ok and "Could not save" in message


def test_a_raising_writer_does_not_escape_into_qt():
    def boom(*args):
        raise PermissionError("read-only config")

    ok, message = apply_setting("audio", "device", "Yeti", write=boom)
    assert not ok and "read-only config" in message


def test_the_numeric_threshold_is_written_as_a_number():
    """Type inference matters: "0.004" as a string breaks the gate."""
    captured = {}

    def write(section, key, value):
        captured.update(section=section, key=key, value=value)
        return True

    apply_setting("accessibility", "vad_threshold", slider_to_threshold(500), write=write)
    assert isinstance(captured["value"], float)
