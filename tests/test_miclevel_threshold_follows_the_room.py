"""`mic-level` must not set a gate from how loudly one sample was spoken (issue #579).

Three consecutive runs by one person on one microphone measured the speech sample at
0.0041 / 0.0103 / 0.0441 and recommended 0.0021 / 0.0051 / 0.022; `verify` then found that
person's ordinary speech at 0.0208 BELOW the 0.0220 gate. The gate followed the loudness
of the one sample the user happened to speak.

Rule now: the gate is aimed at a multiple of the measured ROOM level (``_ROOM_TARGET``,
provisional) and the voice can only pull it down through the ``0.5 x voice`` cap. So a
louder sample can never raise it. A recording too short to trust is refused (``--set`` writes
nothing, exit 1). Pure logic: sample arrays are injected, no microphone.
"""

from __future__ import annotations

import numpy as np
import pytest

from yazses.system.miclevel import (
    _MIN_THRESHOLD,
    _ROOM_TARGET,
    MIN_AMBIENT_SECONDS,
    MIN_SPEECH_SECONDS,
    analyze,
    calibrate,
)

SR = 16000
ROOM = 0.0046            # empty-room readings on the author's laptop: 0.0036-0.0050
NORMAL_SPEECH = 0.0208   # the level `verify` found in issue #579
LOUD_RUNS = (0.0441, 0.0894, 0.5)   # speech samples of one person, loud to very loud


def _stats(mean: float, seconds: float):
    return analyze(np.full(int(SR * seconds), mean, dtype=np.float32), SR)


def _cal(room: float, speech: float, *, room_s: float = 2.0, speech_s: float = 4.0):
    return calibrate(_stats(room, room_s), _stats(speech, speech_s))


@pytest.mark.parametrize("loud", LOUD_RUNS)
def test_a_louder_sample_never_raises_the_gate(loud: float) -> None:
    quiet = _cal(ROOM, NORMAL_SPEECH)
    louder = _cal(ROOM, loud)
    assert quiet.ok and louder.ok
    assert louder.recommended_threshold == quiet.recommended_threshold


@pytest.mark.parametrize("loud", LOUD_RUNS)
def test_the_gate_from_a_loud_run_still_passes_the_same_persons_normal_speech(
    loud: float,
) -> None:
    """The acceptance test of #579: run loud, then speak normally; the speech clears."""
    threshold = _cal(ROOM, loud).recommended_threshold
    assert NORMAL_SPEECH > threshold
    assert threshold > ROOM


@pytest.mark.parametrize("room", [0.0036, 0.0041, 0.0046, 0.0050])
def test_the_issues_own_runs_a_loud_run_does_not_reject_the_quieter_one(room: float) -> None:
    """#579's acceptance on its own numbers: consecutive runs spoke at 0.0103 and 0.0441.

    Calibrated on the loud run, the gate must still pass the quieter run's speech. The
    geometric-mean rule this replaced set 0.0126-0.0148 over this range of rooms.
    """
    threshold = _cal(room, 0.0441).recommended_threshold
    assert room < threshold < 0.0103


@pytest.mark.parametrize("speech", [0.0208, 0.0441, 0.0894, 0.5])
def test_the_gate_never_exceeds_a_fixed_multiple_of_the_room(speech: float) -> None:
    """The hard cap: relative to the NOISE FLOOR, whatever the speech level is."""
    result = _cal(ROOM, speech)
    assert result.ok
    assert result.recommended_threshold <= max(_MIN_THRESHOLD, ROOM * _ROOM_TARGET) + 1e-9


def test_a_narrow_band_still_lets_the_voice_pull_the_gate_down() -> None:
    """Voice only lowers: at 3.2x separation the 0.5 x voice cap beats the room target."""
    result = _cal(0.01, 0.032)
    assert result.ok
    assert result.recommended_threshold == pytest.approx(0.016, abs=1e-4)


# ------------------------------------------------------------------ the refusal path


@pytest.mark.parametrize(
    ("room_s", "speech_s"),
    [(2.0, 0.5), (2.0, MIN_SPEECH_SECONDS - 0.5), (0.5, 4.0), (0.0, 0.0)],
    ids=["speech-0.5s", "speech-1.5s", "room-0.5s", "empty"],
)
def test_a_recording_too_short_to_trust_is_refused(room_s: float, speech_s: float) -> None:
    result = _cal(ROOM, 0.0441, room_s=room_s, speech_s=speech_s)
    assert result.ok is False
    assert result.too_short is True
    assert "too short" in result.reason
    assert result.recommended_threshold == _MIN_THRESHOLD   # a constant, never a measurement


def test_the_minimum_lengths_themselves_are_accepted() -> None:
    result = _cal(ROOM, 0.0441, room_s=MIN_AMBIENT_SECONDS, speech_s=MIN_SPEECH_SECONDS)
    assert result.ok is True


def test_the_cli_defaults_clear_the_minimums() -> None:
    """`--seconds 4` records 4 s of speech and 2 s of room: refusing those would be a bug."""
    assert 4.0 >= MIN_SPEECH_SECONDS
    assert max(1.0, 4.0 / 2) >= MIN_AMBIENT_SECONDS


def test_a_level_refusal_is_not_reported_as_too_short() -> None:
    result = _cal(ROOM, ROOM)
    assert result.ok is False
    assert result.too_short is False


# ---------------------------------------------- the command: --set must not write


def test_set_writes_nothing_and_exits_nonzero_on_a_short_recording(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from yazses import cli
    from yazses.system import miclevel

    cfg = tmp_path / "config.toml"
    cfg.write_text("[accessibility]\nvad_threshold = 0.004\n", encoding="utf-8")
    before = cfg.read_text(encoding="utf-8")

    class _Paths:
        config_file = cfg
        ipc_socket = tmp_path / "ipc.sock"

    class _Platform:
        paths = _Paths()

    levels = iter((ROOM, 0.0441))
    monkeypatch.setattr(
        miclevel, "record",
        lambda seconds, sr, device=None: np.full(int(sr * seconds), next(levels), np.float32),
    )
    monkeypatch.setattr(cli, "get_platform", lambda: _Platform())
    monkeypatch.setattr(cli, "_live_vad_threshold", lambda _p: None)

    # `-s 1`: 1 s of speech, below MIN_SPEECH_SECONDS.
    result = CliRunner().invoke(cli.app, ["mic-level", "--set", "-s", "1"])
    assert result.exit_code == 1
    assert "too short" in result.output
    assert cfg.read_text(encoding="utf-8") == before
