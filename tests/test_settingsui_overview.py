"""The Overview page's decisions: one state in words, with at most one fix. No Qt."""
from __future__ import annotations

import pytest

from yazses.settingsui import overview


def _status(**extra) -> dict:
    return {
        "state": "idle", "ready": True, "model": "base.en", "engine": "faster-whisper",
        "engine_model": "base.en", "input_device": None, "silent_streak": 0,
        "silent_streak_threshold": 3, "target_ok": None, "hotkey": "right_alt",
        "injection_backend": "ydotool", "version": "9.9.9", **extra,
    }


def test_no_daemon_offers_to_start_it():
    health = overview.health(None)
    assert health.action == "start"
    assert health.level == "warn"
    assert "not running" in health.title


def test_an_idle_daemon_is_ready_with_nothing_to_fix():
    health = overview.health(_status())
    assert (health.level, health.action) == ("ok", "")
    assert health.title == "Ready to dictate"


def test_a_silent_streak_at_the_threshold_offers_recalibration():
    assert overview.health(_status(silent_streak=3)).action == "recalibrate"


def test_one_silent_clip_below_the_threshold_is_not_a_problem():
    assert overview.health(_status(silent_streak=1)).level == "ok"


def test_an_error_shows_the_daemons_own_reason_and_offers_a_restart():
    health = overview.health(_status(state="error", last_error="model file is missing"))
    assert health.level == "bad"
    assert health.action == "restart"
    assert "model file is missing" in health.detail


def test_loading_is_reported_while_the_daemon_is_not_ready():
    health = overview.health(_status(ready=False, state="loading"))
    assert health.level == "warn" and health.action == ""


def test_dictating_with_no_text_field_says_where_the_words_go():
    health = overview.health(_status(state="recording", target_ok=False))
    assert health.level == "warn"
    assert "clipboard" in health.detail


@pytest.mark.parametrize(
    "extra, title",
    [
        ({"state": "recording"}, "Listening"),
        ({"state": "transcribing"}, "Transcribing"),
        ({"state": "meeting", "meeting_active": True}, "Recording a meeting"),
    ],
)
def test_activity_is_named(extra, title):
    assert overview.health(_status(**extra)).title == title


@pytest.mark.parametrize("junk", ({}, {"silent_streak": "x", "silent_streak_threshold": None}))
def test_a_partial_reply_never_raises(junk):
    assert overview.health(junk).title


def test_the_system_check_names_what_is_in_use():
    checks = {c.name: c for c in overview.system_checks(_status(input_device="USB mic"))}
    assert "USB mic" in checks["Microphone"].value
    assert "base.en" in checks["Speech model"].value
    assert checks["Typing into apps"].value == "ydotool"
    assert overview.system_checks(None) == ()


def test_the_default_microphone_is_named_in_words():
    checks = {c.name: c for c in overview.system_checks(_status())}
    assert checks["Microphone"].value == "System default"


def test_the_hotkey_is_spoken_in_title_case():
    assert overview.key_label("right_alt") == "Right Alt"
    assert overview.key_label("") == "Your hold-to-talk key"


def test_a_busy_daemon_is_not_reported_as_stopped():
    health = overview.health(overview.UNRESPONSIVE)
    assert "busy" in health.title and health.action == ""
    assert overview.system_checks(overview.UNRESPONSIVE) == ()


def test_auto_is_never_shown_as_if_it_were_a_key():
    assert overview.key_label("auto") == "Your hold-to-talk key"
