"""The pause-dictation rules of ADR-037 (Proposed; the module is not wired yet)."""
from __future__ import annotations

import threading

import pytest

from yazses.core.dictation_pause import (
    REFUSED_WHILE_PAUSED,
    UNAFFECTED_BY_PAUSE,
    CapturePath,
    DictationPause,
    InFlight,
    in_flight_action,
    visible_state,
)
from yazses.platform.base import TrayState

REFUSED = sorted(REFUSED_WHILE_PAUSED)
UNAFFECTED = sorted(UNAFFECTED_BY_PAUSE)
ANNOUNCED = (
    CapturePath.HOTKEY,
    CapturePath.COMMAND_KEY,
    CapturePath.SWITCH_HOLD,
    CapturePath.HELD_RELEASE,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_every_path_is_classified_exactly_once() -> None:
    assert not REFUSED_WHILE_PAUSED & UNAFFECTED_BY_PAUSE
    assert REFUSED_WHILE_PAUSED | UNAFFECTED_BY_PAUSE == set(CapturePath)


def test_the_classification_is_the_one_the_adr_records() -> None:
    """Moving a path between the sets is a privacy decision: it must show up here."""
    assert {p.value for p in REFUSED_WHILE_PAUSED} == {
        "hotkey", "command_key", "switch_hold", "wake_word", "vocal_morse",
        "punch_in", "ask_human", "held_release",
    }
    assert {p.value for p in UNAFFECTED_BY_PAUSE} == {
        "meeting", "handsfree_control", "explicit_text", "mic_setup",
    }


@pytest.mark.parametrize("path", sorted(CapturePath))
def test_a_new_instance_is_not_paused_and_refuses_nothing(path: CapturePath) -> None:
    pause = DictationPause()
    admission = pause.admit(path)
    assert not pause.paused
    assert pause.paused_for_s() is None
    assert admission.allowed and not admission.announce
    assert pause.still_allowed(admission)


@pytest.mark.parametrize("path", REFUSED)
def test_a_covered_path_is_refused_while_paused_and_allowed_after_resume(
    path: CapturePath,
) -> None:
    pause = DictationPause()
    pause.pause()
    assert not pause.admit(path).allowed
    pause.resume()
    assert pause.admit(path).allowed


@pytest.mark.parametrize("path", UNAFFECTED)
def test_an_uncovered_path_ignores_the_pause(path: CapturePath) -> None:
    pause = DictationPause()
    before = pause.admit(path)
    pause.pause()
    during = pause.admit(path)
    assert during.allowed and not during.announce
    assert pause.still_allowed(before)
    assert pause.still_allowed(during)


@pytest.mark.parametrize("path", REFUSED)
def test_a_pause_voids_what_was_admitted_before_it_even_after_a_resume(
    path: CapturePath,
) -> None:
    """The recording that was open at the pause must not come back with the resume."""
    pause = DictationPause()
    admission = pause.admit(path)
    pause.pause()
    assert not pause.still_allowed(admission)
    pause.resume()
    assert not pause.still_allowed(admission)
    assert pause.still_allowed(pause.admit(path))


def test_a_refused_admission_stays_refused_after_resume() -> None:
    """A key held across a resume does nothing: it was refused when it went down."""
    pause = DictationPause()
    pause.pause()
    refused = pause.admit(CapturePath.HOTKEY)
    pause.resume()
    assert not pause.still_allowed(refused)


def test_pause_and_resume_report_whether_anything_changed() -> None:
    pause = DictationPause()
    assert pause.resume() is False
    assert pause.pause() is True
    assert pause.pause() is False
    assert pause.paused
    assert pause.resume() is True
    assert pause.resume() is False
    assert not pause.paused


def test_paused_for_counts_from_the_first_pause_and_clears_on_resume() -> None:
    clock = _Clock()
    pause = DictationPause(clock)
    pause.pause()
    clock.now += 5.0
    pause.pause()
    clock.now += 2.0
    assert pause.paused_for_s() == pytest.approx(7.0)
    pause.resume()
    assert pause.paused_for_s() is None


@pytest.mark.parametrize("path", ANNOUNCED)
def test_the_user_is_told_once_per_pause(path: CapturePath) -> None:
    pause = DictationPause()
    pause.pause()
    assert pause.admit(path).announce
    assert not pause.admit(path).announce
    assert not pause.admit(CapturePath.HOTKEY).announce
    pause.resume()
    assert not pause.admit(path).announce
    pause.pause()
    assert pause.admit(path).announce


def test_a_repeated_pause_does_not_announce_again() -> None:
    pause = DictationPause()
    pause.pause()
    assert pause.admit(CapturePath.HOTKEY).announce
    pause.pause()
    assert not pause.admit(CapturePath.HOTKEY).announce


@pytest.mark.parametrize("path", sorted(REFUSED_WHILE_PAUSED - set(ANNOUNCED)))
def test_a_refusal_nobody_pressed_for_does_not_use_up_the_announcement(
    path: CapturePath,
) -> None:
    pause = DictationPause()
    pause.pause()
    assert not pause.admit(path).announce
    assert pause.admit(CapturePath.HOTKEY).announce


def test_concurrent_presses_announce_exactly_once() -> None:
    pause = DictationPause()
    pause.pause()
    results: list[bool] = []
    start = threading.Barrier(8)

    def press() -> None:
        start.wait(timeout=10)
        results.append(pause.admit(CapturePath.HOTKEY).announce)

    threads = [threading.Thread(target=press) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(results) == [False] * 7 + [True]


@pytest.mark.parametrize("ready", [True, False])
@pytest.mark.parametrize("state", list(TrayState))
def test_only_a_recording_is_discarded_and_only_an_ended_burst_finishes(
    state: TrayState, ready: bool
) -> None:
    if state is TrayState.RECORDING:
        expected = InFlight.DISCARD
    elif state in (TrayState.TRANSCRIBING, TrayState.INJECTING) or (
        state is TrayState.LOADING and ready
    ):
        expected = InFlight.FINISH
    else:
        expected = InFlight.NONE
    assert in_flight_action(state, ready=ready) is expected


@pytest.mark.parametrize("state", list(TrayState))
def test_paused_replaces_idle_and_hides_nothing_else(state: TrayState) -> None:
    assert visible_state(state, paused=False) is state
    expected = TrayState.PAUSED if state is TrayState.IDLE else state
    assert visible_state(state, paused=True) is expected
