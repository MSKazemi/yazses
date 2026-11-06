"""The ``max_seconds`` cap must announce itself instead of dropping audio silently.

Before this change the first callback past the cap simply returned: the take stopped
growing while the user kept talking, with no log line and nothing a caller could read.
These tests drive ``_callback`` directly with synthetic blocks -- no real PortAudio --
and patch ``recorder._sd`` for the one ``start()`` call, as ``tests/test_recorder.py``
does.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import numpy as np

from yazses.audio import recorder
from yazses.audio.recorder import AudioRecorder

SR = 100  # tiny rate so a 1 s cap is 100 samples
BLOCK = 40


def _block(n: int = BLOCK) -> np.ndarray:
    return np.full((n, 1), 0.1, dtype=np.float32)


def _cap_warnings(caplog) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "max_seconds" in r.getMessage()
    ]


def test_flag_starts_false():
    assert AudioRecorder(sample_rate=SR, max_seconds=1).truncated is False


def test_first_drop_warns_once_and_sets_flag(caplog):
    rec = AudioRecorder(sample_rate=SR, max_seconds=1)
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        for _ in range(6):  # 2 blocks fit (80 samples); the 3rd would make 120 > 100
            rec._callback(_block(), BLOCK, None, 0)

    # The cap logic itself is unchanged: the first frame past the cap is dropped.
    assert sum(len(c) for c in rec._chunks) == 2 * BLOCK
    assert rec.truncated is True
    warnings = _cap_warnings(caplog)
    assert len(warnings) == 1  # once per recording, not once per dropped block
    msg = warnings[0].getMessage()
    assert "1 s" in msg  # names the cap
    assert "0.80 s" in msg  # names what was captured


def test_under_the_cap_is_silent_and_unflagged(caplog):
    rec = AudioRecorder(sample_rate=SR, max_seconds=1)
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        rec._callback(_block(), BLOCK, None, 0)
        rec._callback(_block(), BLOCK, None, 0)
    assert rec.truncated is False
    assert not _cap_warnings(caplog)


def test_zero_disables_cap_and_never_flags(caplog):
    rec = AudioRecorder(sample_rate=SR, max_seconds=0)
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        for _ in range(50):
            rec._callback(_block(), BLOCK, None, 0)
    assert rec.truncated is False
    assert sum(len(c) for c in rec._chunks) == 50 * BLOCK
    assert not _cap_warnings(caplog)


def test_flag_survives_stop_and_is_reset_by_start(caplog, mocker):
    fake_sd = MagicMock()
    fake_sd.InputStream.return_value = MagicMock()
    mocker.patch.object(recorder, "_sd", return_value=fake_sd)

    rec = AudioRecorder(sample_rate=SR, max_seconds=1)
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        for _ in range(4):
            rec._callback(_block(), BLOCK, None, 0)
        assert rec.truncated is True
        rec.stop()
        assert rec.truncated is True  # readable after stop(), like stream_interrupted

        rec.start()
        assert rec.truncated is False  # a new take starts clean

        # ...and the warning re-arms for the new recording.
        for _ in range(4):
            rec._callback(_block(), BLOCK, None, 0)
    assert rec.truncated is True
    assert len(_cap_warnings(caplog)) == 2
