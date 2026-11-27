"""The setup guide's decisions: who is offered it, and what each step says. No Qt.

The first rule is the one that matters: an existing install is never offered the guide.
"""
from __future__ import annotations

import pytest

from yazses.config import load_config
from yazses.settingsui import first_run
from yazses.system import firstrun

WINDOW = first_run.OFFER_WINDOW_S


def _paths(tmp_path):
    return tmp_path / "yazses" / "config.toml", tmp_path / "legacy" / "config.toml"


def _marker(config):
    path = firstrun.setup_marker_path(config)
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


# --- who is offered the guide -------------------------------------------------------


@pytest.mark.parametrize(
    ("marker", "age", "config", "legacy", "offered"),
    [
        (None, 0, False, False, True),                  # nothing configured yet
        (None, 0, True, False, False),                  # an install from before the guide
        (None, 0, False, True, False),                  # a stranded pre-#330 config
        ("pending", 60, True, False, True),             # seeded by the daemon just now
        ("pending", WINDOW + 1, True, False, False),    # used for weeks since
        ("seen", 0, True, False, False),
        ("seen", 0, False, False, False),               # a deleted config is a reset
        ("", 0, False, False, False),
        ("something else", 0, False, False, False),
    ],
)
def test_who_is_offered_the_guide(marker, age, config, legacy, offered):
    assert first_run.should_offer(
        marker, marker_age_s=age, config_exists=config, legacy_config_exists=legacy
    ) is offered


def test_a_brand_new_install_is_offered_and_gets_the_recommended_config(tmp_path):
    config, legacy = _paths(tmp_path)
    assert first_run.prepare(config, legacy) is True
    assert config.exists() and _marker(config) == "pending"
    seeded = tmp_path / "seeded.toml"
    firstrun.ensure_recommended_config(seeded)
    assert load_config(config) == load_config(seeded)


def test_it_is_offered_until_it_has_been_shown_and_never_after(tmp_path):
    config, legacy = _paths(tmp_path)
    assert first_run.prepare(config, legacy)
    assert first_run.prepare(config, legacy)        # the window never got to show it
    assert first_run.mark_seen(config)
    assert not first_run.prepare(config, legacy)


def test_an_existing_config_is_never_offered_and_nothing_is_written(tmp_path):
    config, legacy = _paths(tmp_path)
    config.parent.mkdir()
    config.write_text('[hotkey]\nkey = "left_ctrl"\n', encoding="utf-8")
    assert not first_run.prepare(config, legacy)
    assert [p.name for p in config.parent.iterdir()] == ["config.toml"]
    assert config.read_text(encoding="utf-8") == '[hotkey]\nkey = "left_ctrl"\n'


def test_a_stranded_legacy_config_is_left_for_the_daemon_to_migrate(tmp_path):
    config, legacy = _paths(tmp_path)
    legacy.parent.mkdir()
    legacy.write_text("[overlay]\nenabled = false\n", encoding="utf-8")
    assert not first_run.prepare(config, legacy)
    assert not config.exists()


def test_the_daemons_first_start_leaves_the_guide_pending(tmp_path):
    config, legacy = _paths(tmp_path)
    assert firstrun.ensure_recommended_config(config)
    assert _marker(config) == "pending"
    assert first_run.prepare(config, legacy)


def test_a_pending_guide_expires(tmp_path):
    config, legacy = _paths(tmp_path)
    firstrun.ensure_recommended_config(config)
    written = firstrun.setup_marker_path(config).stat().st_mtime
    assert first_run.prepare(config, legacy, now=written + WINDOW - 60)
    assert not first_run.prepare(config, legacy, now=written + WINDOW + 60)


def test_reseeding_after_a_deleted_config_does_not_offer_it_again(tmp_path):
    config, legacy = _paths(tmp_path)
    firstrun.ensure_recommended_config(config)
    first_run.mark_seen(config)
    config.unlink()
    assert firstrun.ensure_recommended_config(config)
    assert _marker(config) == "seen"
    assert not first_run.prepare(config, legacy)


def test_starting_the_daemon_on_an_existing_config_marks_nothing(tmp_path):
    config, _legacy = _paths(tmp_path)
    config.parent.mkdir()
    config.write_text("", encoding="utf-8")
    assert not firstrun.ensure_recommended_config(config)
    assert _marker(config) is None


def test_an_unreadable_marker_is_not_an_offer(tmp_path):
    config, legacy = _paths(tmp_path)
    firstrun.setup_marker_path(config).mkdir(parents=True)
    assert not first_run.prepare(config, legacy)


def test_a_seed_that_fails_is_not_an_offer_and_does_not_raise(tmp_path):
    config, legacy = _paths(tmp_path)

    def _refuse(_path):
        raise PermissionError("read-only")

    assert not first_run.prepare(config, legacy, seed=_refuse)


def test_a_marker_that_cannot_be_written_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("", encoding="utf-8")
    assert first_run.mark_seen(blocker / "config.toml") is False


# --- the steps ----------------------------------------------------------------------


def test_the_four_steps_in_order():
    assert [s.key for s in first_run.STEPS] == ["welcome", "microphone", "key", "try"]
    assert first_run.step_counter(0) == "Step 1 of 4"
    assert first_run.LIVE_STEPS == {"microphone", "try"}


def test_the_forward_button_says_when_it_will_save():
    assert first_run.next_label(0, key_changed=False) == "Next"
    assert first_run.next_label(2, key_changed=False) == "Next"
    assert first_run.next_label(2, key_changed=True) == "Save key and continue"
    assert first_run.next_label(1, key_changed=True) == "Next"
    assert first_run.next_label(3, key_changed=False) == "Finish"


# --- the daemon ---------------------------------------------------------------------


def _status(**extra):
    return {"state": "idle", "ready": True, "hotkey": "right_alt", "vad_threshold": 0.01,
            **extra}


def test_no_daemon_offers_to_start_it():
    prompt = first_run.daemon_prompt(None, "auto", "right_alt")
    assert prompt.action == "start" and "not running" in prompt.text


def test_a_busy_daemon_offers_nothing():
    assert first_run.daemon_prompt({"unresponsive": True}, "auto", "right_alt").action == ""


def test_a_daemon_on_the_saved_key_needs_nothing():
    assert first_run.daemon_prompt(_status(), "auto", "right_alt").action == ""
    # The macOS spelling is the same physical key.
    assert first_run.daemon_prompt(_status(), "right_option", "right_alt").action == ""


def test_a_daemon_on_another_key_offers_a_restart_naming_both():
    prompt = first_run.daemon_prompt(_status(), "left_ctrl", "right_alt")
    assert prompt.action == "restart"
    assert "Right Alt" in prompt.text and "Left Ctrl" in prompt.text


def test_an_unknown_platform_default_never_asks_for_a_restart():
    assert first_run.daemon_prompt(_status(), "auto", "").action == ""


def test_the_key_to_hold_is_the_daemons_then_the_saved_one():
    assert first_run.hold_key_label(_status(), "left_ctrl", "right_alt") == "Right Alt"
    assert first_run.hold_key_label(None, "auto", "right_ctrl") == "Right Ctrl"
    assert first_run.hold_key_label(None, "auto", "") == "Your hold-to-talk key"


@pytest.mark.parametrize(
    ("status", "allowed"),
    [
        (None, False),
        ({"unresponsive": True}, False),
        (_status(ready=False), False),
        (_status(state="recording"), False),
        (_status(), True),
    ],
)
def test_recalibration_needs_a_loaded_idle_daemon(status, allowed):
    assert first_run.can_recalibrate(status) is allowed


# --- the microphone -----------------------------------------------------------------


def test_a_hold_that_reaches_the_threshold_is_heard():
    check = first_run.MicCheck().update(_status(state="recording", audio_level=0.0))
    assert check.recording and first_run.mic_message(check, "Right Alt") == "Listening…"
    check = check.update(_status(state="recording", audio_level=0.05))
    assert check.position > 0
    check = check.update(_status(state="recording", audio_level=0.0))   # a pause
    check = check.update(_status(state="transcribing"))
    assert check.verdict == "heard" and check.position == 0
    assert check.update(_status()).verdict == "heard"


def test_a_quiet_hold_says_so_and_the_next_one_is_judged_afresh():
    loud = first_run.MicCheck().update(_status(state="recording", audio_level=0.05))
    done = loud.update(_status())
    quiet = done.update(_status(state="recording", audio_level=0.0001)).update(_status())
    assert quiet.verdict == "quiet"
    assert "muted" in first_run.mic_message(quiet, "Right Alt")


def test_a_missed_reply_says_nothing_about_the_microphone():
    check = first_run.MicCheck().update(_status(state="recording", audio_level=0.05))
    for reply in (None, {"unresponsive": True}):
        held = check.update(reply)
        assert held.recording and held.position == 0 and held.verdict == ""
        assert held.update(_status()).verdict == "heard"


def test_a_malformed_level_does_not_raise():
    check = first_run.MicCheck().update(_status(state="recording", audio_level="loud"))
    assert check.position == 0 and not check.cleared


def test_before_any_hold_it_says_what_to_do():
    message = first_run.mic_message(first_run.MicCheck(), "Right Alt")
    assert message.startswith("Hold Right Alt")


def test_the_recalibration_prompts_follow_the_daemons_timings():
    from yazses.core import daemon

    lead, room, speech = daemon._RECAL_LEAD_S, daemon._RECAL_ROOM_S, daemon._RECAL_SPEECH_S
    assert first_run.RECAL_ROOM_END_S == lead + room
    assert first_run.RECAL_END_S == lead + room + lead + speech


def test_the_recalibration_prompts_in_order():
    assert "quiet" in first_run.recalibration_prompt(0.0)
    assert "speak" in first_run.recalibration_prompt(first_run.RECAL_ROOM_END_S)
    assert first_run.recalibration_prompt(60.0) is None


def test_the_recalibration_result_is_read_from_the_threshold():
    assert "0.004" in first_run.recalibration_result(0.01, 0.004)
    assert "did not change" in first_run.recalibration_result(0.01, 0.01)
    assert "did not report" in first_run.recalibration_result(0.01, None)
    assert first_run.threshold_of(_status()) == 0.01
    assert first_run.threshold_of(None) is None
