"""When the mic guard fires, the log must say so — even when it cannot heal.

Found running the product. `yazses status` reported 15 of 50 recent bursts producing
no text and `daemon.log` carried 50 `Empty transcription -- discarding.` lines, with
nothing anywhere saying the guard built for exactly that symptom had ever fired.

It may well have. That was the problem: it left no way to tell.

`_note_silent_discard` had two outputs. `log.info("Auto-healed capture: …")` ran only
inside the heal branch, which needs a *different* last-good device — and on a machine
whose microphone has not changed, `last_good == active`, so it never runs. Everything
else went to a desktop toast, and `system/notify.py` logs at INFO only when
`notify-send` is **unavailable**: a toast that is successfully delivered leaves
nothing behind. So on an ordinary desktop the guard was silent in precisely the case
it was built for — a working mic capturing unusable audio.

The cost is not the missing line, it is where the line was missing from. `yazses logs`
is what the product tells you to read when dictation stops, and `yazses report` bundles
that same tail into a bug report — so a report about "dictation stopped working" showed
the run of discards and no evidence the daemon had noticed.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from yazses.config import AudioConfig, Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


class _FakeRecorder:
    def __init__(self, name="USB PnP Audio Device"):
        self.device = None
        self.current_device_name = name


def _daemon(mocker, audio: AudioConfig | None = None, *, active="USB PnP Audio Device"):
    """A daemon with both device names pinned by the caller.

    `_active_device_name()` otherwise calls `current_default_input_name()`, which
    reads the *host's* sound devices — so whether the heal branch ran would depend
    on the machine running the suite rather than on the code under test.
    """
    cfg = Config()
    if audio is not None:
        cfg = replace(cfg, audio=audio)
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder()
    d._notify_mic = mocker.MagicMock()
    d._active_device_name = lambda: active
    return d


def _trip(d, times=3):
    for _ in range(times):
        d._note_silent_discard()


def _guard_lines(caplog):
    return [r.message for r in caplog.records if "in a row" in r.message]


def test_the_guard_logs_when_it_cannot_heal(mocker, caplog):
    """The reported machine's exact shape: nothing else to switch to."""
    d = _daemon(
        mocker,
        AudioConfig(silent_streak_threshold=3, auto_heal_device=True,
                    silent_streak_notify=True),
    )
    # A success first, so last_good is set — and equal to the active device, which
    # is what a machine whose microphone never changed looks like.
    d._note_good_capture()
    assert d._state.last_good_device == d._active_device_name()

    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        _trip(d)

    lines = _guard_lines(caplog)
    assert lines, "the guard fired and left no record in the log"
    assert "3 burst(s)" in lines[0], lines[0]
    assert "no different last-good device" in lines[0], lines[0]
    # It really could not heal — otherwise this test proves the wrong branch.
    assert d._recorder.device is None


def test_the_guard_logs_when_it_does_heal(mocker, caplog):
    d = _daemon(
        mocker,
        AudioConfig(silent_streak_threshold=3, auto_heal_device=True,
                    silent_streak_notify=True),
    )
    d._recorder.current_device_name = "Yeti Stereo Microphone"
    d._note_good_capture()
    # The default has since flipped to a dead monitor input.
    d._active_device_name = lambda: "monitor audio"
    d._state.input_device = "monitor audio"

    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        _trip(d)

    lines = _guard_lines(caplog)
    assert lines, "the healing branch lost its log line"
    assert "Yeti Stereo Microphone" in lines[0], lines[0]
    assert "auto-healed" in lines[0], lines[0]
    assert d._recorder.device == "Yeti Stereo Microphone"


def test_the_record_survives_notifications_being_turned_off(mocker, caplog):
    """`silent_streak_notify = false` is when a log line is the *only* record.

    Logging after the opt-out would have left this configuration with no evidence
    at all — the strictly worst case, and the easy one to get wrong.
    """
    d = _daemon(
        mocker,
        AudioConfig(silent_streak_threshold=3, auto_heal_device=True,
                    silent_streak_notify=False),
    )
    d._note_good_capture()
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        _trip(d)

    assert _guard_lines(caplog), "no toast and no log: the event vanished"
    d._notify_mic.assert_not_called()


def test_it_does_not_log_before_the_threshold(mocker, caplog):
    """Two discards in a row is ordinary. A line per burst is noise, not a record."""
    d = _daemon(
        mocker,
        AudioConfig(silent_streak_threshold=3, auto_heal_device=True,
                    silent_streak_notify=True),
    )
    d._note_good_capture()
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        _trip(d, times=2)
    assert _guard_lines(caplog) == []


def test_it_logs_once_per_streak_not_once_per_burst(mocker, caplog):
    """`_healed_this_streak` already gated the toast; the log must share that gate."""
    d = _daemon(
        mocker,
        AudioConfig(silent_streak_threshold=3, auto_heal_device=True,
                    silent_streak_notify=True),
    )
    d._note_good_capture()
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        _trip(d, times=9)
    assert len(_guard_lines(caplog)) == 1, "one fault, one line"


def test_a_good_capture_re_arms_the_record(mocker, caplog):
    """A second, later fault is a second event and must be recorded again."""
    d = _daemon(
        mocker,
        AudioConfig(silent_streak_threshold=3, auto_heal_device=True,
                    silent_streak_notify=True),
    )
    d._note_good_capture()
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        _trip(d)
        d._note_good_capture()
        _trip(d)
    assert len(_guard_lines(caplog)) == 2


def test_the_line_carries_no_dictated_text(mocker, caplog):
    """ADR-011: only DEBUG may carry what the user said. This runs at INFO."""
    d = _daemon(
        mocker,
        AudioConfig(silent_streak_threshold=3, auto_heal_device=True,
                    silent_streak_notify=True),
    )
    d._note_good_capture()
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        _trip(d)
    line = _guard_lines(caplog)[0]
    # Counts, a device name and a threshold — the same class of metadata the
    # neighbouring "Silent audio -- discarding" line already carries.
    assert "3 burst(s)" in line and "threshold 3" in line
