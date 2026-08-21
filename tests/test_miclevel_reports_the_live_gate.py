"""`mic-level` printed the file's threshold under the label *current*.

Measured on the author's machine, 2026-08-20, with the drift live:

    ~/.config/yazses/config.toml   vad_threshold = 0.004
    daemon.log, every discard      "level 0.0000 < vad_threshold 0.0005"
    yazses mic-level               "  current vad_threshold: 0.004"

The daemon reads the threshold once, at start, and never re-reads the file -- the same
staleness that lets `yazses hotkey set` leave a machine holding a key nobody listens for.
It lands hardest here, because this is the one command whose entire subject is that
number, and it is the command the product sends you to when dictation silently stops:
someone diagnosing "Silent audio -- discarding" reads 0.004, judges the gate sane, and is
looking at a gate eight times lower than the one throwing their speech away.

Not a doctor row per cached value -- that stays parked. One command, one mislabel, and a
comparison against a number the daemon already publishes.
"""

from __future__ import annotations

import numpy as np
import pytest

from yazses.system.miclevel import live_threshold_note

# --- the pure rule ---------------------------------------------------------------

def test_no_daemon_says_nothing():
    """Calibrating before the daemon exists is the ordinary first-setup case."""
    assert live_threshold_note(0.004, None) is None


def test_agreement_says_nothing():
    assert live_threshold_note(0.004, 0.004) is None


def test_the_real_drift_names_both_numbers_and_the_fix():
    note = live_threshold_note(0.004, 0.0005)
    assert note is not None
    assert "0.0005" in note and "0.0040" in note
    assert "lower" in note
    assert "yazses restart" in note


def test_a_daemon_gating_higher_is_named_as_higher():
    """The opposite drift is the one where dictation stops rather than hallucinates."""
    note = live_threshold_note(0.004, 0.01)
    assert note is not None
    assert "higher" in note


def test_a_last_bit_float_difference_is_not_drift():
    """Both numbers survive a TOML parse and a JSON round trip. A warning nobody can act
    on is worse than none, so the comparison is `isclose`, not `!=`."""
    assert live_threshold_note(0.004, 0.004 + 1e-17) is None


# --- wired into the command ------------------------------------------------------

class _Client:
    def __init__(self, payload):
        self._payload = payload

    def is_reachable(self):
        return self._payload is not None

    def call(self, method, **params):
        assert method == "status"
        return self._payload


class _Paths:
    def __init__(self, config_file):
        self.config_file = config_file
        self.ipc_socket = config_file.parent / "sock"


class _Platform:
    def __init__(self, config_file, payload):
        self.paths = _Paths(config_file)
        self.ipc_client_factory = lambda _s: _Client(payload)


@pytest.fixture
def calibrate(tmp_path, monkeypatch):
    """Drive the real `_calibrate_mic` with a loud sample and a fake daemon."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("[accessibility]\nvad_threshold = 0.004\n")

    from yazses import cli
    from yazses.system import miclevel

    monkeypatch.setattr(miclevel, "record",
                        lambda seconds, sr: np.full(int(sr * seconds), 0.02, dtype=np.float32))

    def run(payload):
        monkeypatch.setattr(cli, "get_platform", lambda: _Platform(cfg, payload))
        return cli._calibrate_mic(seconds=1.0, set_threshold=False)

    return run


def test_the_command_warns_when_the_daemon_gates_elsewhere(calibrate, capsys):
    assert calibrate({"vad_threshold": 0.0005}) is True
    out = capsys.readouterr().out
    assert "0.0005" in out
    assert "yazses restart" in out


def test_the_command_is_quiet_when_they_agree(calibrate, capsys):
    assert calibrate({"vad_threshold": 0.004}) is True
    assert "yazses restart" not in capsys.readouterr().out


def test_the_command_still_works_with_no_daemon(calibrate, capsys):
    assert calibrate(None) is True
    out = capsys.readouterr().out
    assert "recommended:" in out
    assert "yazses restart" not in out


def test_the_label_no_longer_claims_to_be_current(calibrate, capsys):
    """The word was the defect: "current" is a claim about the running system."""
    calibrate(None)
    out = capsys.readouterr().out
    assert "vad_threshold in config" in out
    assert "current vad_threshold" not in out
