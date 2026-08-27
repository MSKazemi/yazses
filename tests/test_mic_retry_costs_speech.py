"""The pause between microphone-open attempts is speech the user has already said.

`AudioRecorder.start` retries a transient open failure, and the retry works: on a
real machine (`daemon.log`, 2026-08-18→20) 12 opens failed across 149 bursts and
every one recovered on the second attempt. What nothing recorded is what the
recovery *cost*. By the time `start()` runs the key is down, the tray is green and
the earcon has told an eyes-free user to speak — so a flat 300 ms pause is 300 ms
of speech dropped on the floor, with no buffer to recover it from, because the
stream that would fill one is the stream that failed to open.

`system/diagnosis.py` already carried the observation ("retries three times, and on
this machine it has always recovered") without anyone asking the follow-up question.
The old tests pinned how many times the retry slept and never once what it slept
for, which is why the number could be six times larger than the fault and nothing
noticed.
"""

from __future__ import annotations

import logging

import pytest

from yazses.audio import recorder
from yazses.audio.recorder import AudioRecorder
from yazses.system.diagnosis import diagnose

CAPTURE = "capture"

# What the flat 0.3 s × 2 schedule gave the audio server to recover in. A change
# that shortens this makes a fault that used to heal fail instead.
_PREVIOUS_BUDGET_S = 0.6


@pytest.fixture(autouse=True)
def _no_sleep(mocker):
    return mocker.patch.object(recorder.time, "sleep")


def _stream(mocker):
    return mocker.MagicMock()

def _set_input_stream(mocker, **kwargs):
    """Point the recorder's lazily-imported sounddevice at a fake InputStream.

    The recorder imports sounddevice on first use rather than at module scope, so
    that a host with no audio system can still *import* YazSes (see
    tests/test_no_audio_device_is_not_an_import_error.py). Patching the `_sd` seam
    keeps these tests runnable on such a host too.
    """
    fake = mocker.MagicMock(name="sounddevice")
    fake.InputStream.configure_mock(**kwargs)
    mocker.patch.object(recorder, "_sd", return_value=fake)
    return fake.InputStream


# --- the schedule itself -------------------------------------------------------

def test_the_first_retry_is_shorter_than_the_speech_it_would_swallow():
    """Every real failure healed by attempt 2, so the first pause is the whole cost."""
    assert recorder._OPEN_RETRY_DELAYS_S[0] <= 0.1


def test_the_recovery_window_did_not_shrink():
    """The regression this fix could have introduced, pinned.

    Front-loading is only free if the *cumulative* wait before the last attempt is
    unchanged; shorten it and a server that needed 400 ms stops recovering.
    """
    assert sum(recorder._OPEN_RETRY_DELAYS_S) == pytest.approx(_PREVIOUS_BUDGET_S)


def test_the_delays_get_longer_rather_than_shorter():
    delays = recorder._OPEN_RETRY_DELAYS_S
    assert list(delays) == sorted(delays)


def test_the_attempt_count_is_derived_from_the_delays():
    """Two constants for one idea are how a schedule silently loses an attempt."""
    assert recorder._OPEN_ATTEMPTS == len(recorder._OPEN_RETRY_DELAYS_S) + 1


def test_there_is_still_a_pause_for_every_retry():
    assert len(recorder._OPEN_RETRY_DELAYS_S) == recorder._OPEN_ATTEMPTS - 1


# --- what start() actually waits ------------------------------------------------

def test_a_first_time_open_waits_for_nothing(mocker, _no_sleep):
    _set_input_stream(mocker, return_value=_stream(mocker))
    AudioRecorder().start()
    _no_sleep.assert_not_called()


def test_one_failure_costs_only_the_short_pause(mocker, _no_sleep):
    good = _stream(mocker)
    _set_input_stream(mocker, side_effect=[RuntimeError("Error querying device -1"), good])
    AudioRecorder().start()
    assert [c.args[0] for c in _no_sleep.call_args_list] == [
        recorder._OPEN_RETRY_DELAYS_S[0]
    ]
    good.start.assert_called_once()


def test_a_second_failure_falls_back_to_the_long_pause(mocker, _no_sleep):
    good = _stream(mocker)
    _set_input_stream(mocker, side_effect=[RuntimeError("busy"), RuntimeError("busy"), good])
    AudioRecorder().start()
    assert [c.args[0] for c in _no_sleep.call_args_list] == list(
        recorder._OPEN_RETRY_DELAYS_S
    )


def test_the_last_attempt_does_not_pause_before_giving_up(mocker, _no_sleep):
    _set_input_stream(mocker, side_effect=RuntimeError("busy"))
    with pytest.raises(RuntimeError, match="Could not open microphone"):
        AudioRecorder().start()
    assert _no_sleep.call_count == recorder._OPEN_ATTEMPTS - 1


# --- what the log says it cost ---------------------------------------------------

def test_the_warning_says_the_speech_is_gone(mocker, caplog):
    _set_input_stream(mocker, side_effect=[RuntimeError("Error querying device -1"), _stream(mocker)])
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        AudioRecorder().start()
    first = caplog.records[0].getMessage()
    assert "not captured" in first
    assert "50 ms" in first


def test_the_final_warning_promises_no_retry_it_will_not_make(mocker, caplog):
    _set_input_stream(mocker, side_effect=RuntimeError("busy"))
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        with pytest.raises(RuntimeError):
            AudioRecorder().start()
    last = caplog.records[-1].getMessage()
    assert "retrying" not in last
    assert "not captured" not in last


def test_the_warning_still_names_the_attempt_and_the_cause(mocker, caplog):
    _set_input_stream(mocker, side_effect=[RuntimeError("Error querying device -1"), _stream(mocker)])
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        AudioRecorder().start()
    first = caplog.records[0].getMessage()
    assert f"attempt 1/{recorder._OPEN_ATTEMPTS}" in first
    assert "Error querying device -1" in first


# --- the surface one file away ----------------------------------------------------

def test_the_diagnosis_still_recognises_the_reworded_warning(mocker, caplog):
    """The wording carries a cause `system/diagnosis.py` matches on; keep them agreeing."""
    _set_input_stream(mocker, side_effect=[RuntimeError("Error querying device -1"), _stream(mocker)])
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        AudioRecorder().start()
    assert diagnose(caplog.records[0].getMessage(), where=CAPTURE).slug == (
        "mic-default-unresolved"
    )
