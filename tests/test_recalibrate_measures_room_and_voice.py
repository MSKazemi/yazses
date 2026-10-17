"""The tray's [Re-calibrate] places the gate between a measured room and a measured voice.

It used to record one 3 s clip and write half its level -- the rule `yazses mic-level`
dropped in v2.36.0 (`test_miclevel_measures_twice.py`). Issue #579 is that rule's output
on a real microphone: a gate of 0.0220 set from a 0.0441 sample, after which `verify`
rejected 0.0208 speech from the same person. The numbers below are that report's.
"""

from __future__ import annotations

import numpy as np
import pytest

from yazses.config import Config
from yazses.core import daemon as daemon_mod
from yazses.core.daemon import Daemon
from yazses.platform import get_platform

# From issue #579: one person, one microphone.
ROOM = 0.0041
LOUD_SAMPLE = 0.0441      # what was said during calibration
QUIET_SPEECH = 0.0208     # the same person, later, that verify then rejected


def _clip(level: float) -> np.ndarray:
    """Constant-amplitude audio whose mean(|x|) -- the metric the gate uses -- is `level`."""
    return np.full(16000, level, dtype=np.float32)


@pytest.fixture
def recal(mocker):
    mocker.patch.object(daemon_mod, "_RECAL_LEAD_S", 0.0)
    d = Daemon(config=Config(), platform=get_platform())
    d._notify_mic = mocker.MagicMock()
    write = mocker.patch("yazses.system.miclevel.update_threshold_in_config", return_value="ok")

    def run(room: float, speech: float):
        rec = mocker.patch(
            "yazses.system.miclevel.record", side_effect=[_clip(room), _clip(speech)]
        )
        before = d._config.accessibility.vad_threshold
        d._recalibrate_mic()
        return d, write, rec, before

    return run


def test_a_loud_sample_does_not_set_a_gate_that_rejects_quieter_speech(recal):
    d, write, _, _ = recal(ROOM, LOUD_SAMPLE)

    written = write.call_args.args[1]
    assert written < QUIET_SPEECH, (
        f"gate {written} would discard the same person's {QUIET_SPEECH} speech"
    )
    assert written > ROOM  # and is still above the room
    assert d._config.accessibility.vad_threshold == written


def test_it_records_the_room_before_the_voice(recal):
    _, _, rec, _ = recal(ROOM, LOUD_SAMPLE)

    seconds = [c.args[0] for c in rec.call_args_list]
    assert seconds == [daemon_mod._RECAL_ROOM_S, daemon_mod._RECAL_SPEECH_S]


def test_nobody_speaking_changes_nothing(recal):
    """Two recordings of the same room: the old rule wrote half of the second one."""
    d, write, _, before = recal(ROOM, ROOM * 1.1)

    write.assert_not_called()
    assert d._config.accessibility.vad_threshold == before
    title, body = d._notify_mic.call_args.args[:2]
    assert title == "Mic not changed" and "Nothing was changed" in body


def test_a_silent_mic_changes_nothing(recal):
    d, write, _, before = recal(0.0, 0.0)

    write.assert_not_called()
    assert d._config.accessibility.vad_threshold == before


@pytest.mark.parametrize("loud", [LOUD_SAMPLE, 0.0407, 0.0394])
def test_the_cli_rule_leaves_room_for_quieter_speech_too(loud):
    """The acceptance in #579 for `yazses mic-level --set`, which already places the gate
    between room and voice: a loud calibration sentence must not push the gate above
    the quieter speech of the same person."""
    from yazses.system.miclevel import analyze, calibrate

    sr = 16000
    result = calibrate(analyze(_clip(ROOM), sr), analyze(_clip(loud), sr))

    assert result.ok
    assert ROOM < result.recommended_threshold < QUIET_SPEECH
