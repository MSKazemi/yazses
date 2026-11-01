"""End-to-end proof of the safety claim: a broken stream produces no switch event.

Pins, through the real objects (``IntegrityGuard`` -> ``IntegrityGate`` -> ``BiosignalPipeline``
built by ``build_runner_from_config`` and driven by ``BiosignalRunner.run``), what the stream
gate does to a double blink: a clean pair is an event; a pair that a corruption (a t0 jump,
a t0 step back, a NaN burst, a channel swap) precedes is not; the same corruption is
recovered from once the gate reopens; and an event the detector emits while the gate is
closed is dropped.

The double-blink detector emits about 1.3 s after the second blink, by which time
``RECOVER_S`` has reopened the gate, so these cases hold only because the pipeline judges an
event by the time it happened as well as the block that reported it.

Deterministic ``SyntheticSource`` with a fixed seed; no device, no wall-clock sleeping.
"""
from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest

from yazses.biosignal import integrity as integrity_mod
from yazses.biosignal import sources as sources_mod
from yazses.biosignal.integrity import RECOVER_S
from yazses.biosignal.runner import BiosignalRunner, RunnerCallbacks, build_runner_from_config
from yazses.biosignal.sources import SyntheticSource
from yazses.biosignal.types import SampleBlock
from yazses.config import BiosignalConfig, Config

SEED = 2
DURATION_S = 9.0
# Blink pair (the second blink's peak completes a DOUBLE_BLINK; the pair is 0.3 s apart).
PAIR = (4.3, 4.6)
# Corruption lands just before the pair, after the detector's 2 s warm-up.
CORRUPT_AT = 4.0
# Well beyond RECOVER_S of clean stream after the corruption.
LATE_PAIR = (6.0, 6.3)
# The pair's event is emitted around 6.0 s, so a corruption at 5.6 s closes the gate over it.
CLOSED_EMIT_AT = 5.6


class CorruptingSource:
    """Test-local BlockSource: a ``SyntheticSource`` whose stream is corrupted from ``at`` on.

    kind ``jump``  : every block from ``at`` is stamped ``amount`` s later (dropped packets).
    kind ``back``  : every block from ``at`` is stamped ``amount`` s earlier (clock stepped back).
    kind ``swap``  : from ``at`` on, channel order is reversed in data and channel list.
    kind ``nan``   : blocks starting in ``[at, at + amount)`` carry NaN in their first samples.
    """

    def __init__(self, inner: SyntheticSource, *, kind: str, at: float,
                 amount: float = 0.0) -> None:
        self._inner = inner
        self._kind = kind
        self._at = at
        self._amount = amount

    @property
    def fs(self) -> float:
        return self._inner.fs

    @property
    def channels(self) -> Any:
        return self._inner.channels

    def start(self) -> None:
        self._inner.start()

    def stop(self) -> None:
        self._inner.stop()

    def read(self) -> SampleBlock | None:
        block = self._inner.read()          # EOFError passes through, as a real source's does
        if block is None or block.t0 < self._at - 1e-9:
            return block
        if self._kind == "jump":
            return _restamp(block, block.t0 + self._amount)
        if self._kind == "back":
            return _restamp(block, block.t0 - self._amount)
        if self._kind == "swap":
            return SampleBlock(data=block.data[::-1].copy(), fs=block.fs,
                               channels=tuple(reversed(block.channels)), t0=block.t0)
        if self._kind == "nan":
            if block.t0 < self._at + self._amount:
                data = block.data.copy()
                data[:, :3] = np.nan
                return SampleBlock(data=data, fs=block.fs, channels=block.channels, t0=block.t0)
            return block
        raise AssertionError(f"unknown corruption {self._kind!r}")


def _restamp(block: SampleBlock, t0: float) -> SampleBlock:
    return SampleBlock(data=block.data, fs=block.fs, channels=block.channels, t0=t0)


def _cfg(**bio: Any) -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), enabled=True,
                                        source="synthetic:eog", double_blink=True, **bio)
    return cfg


def _schedule(src: SyntheticSource, blinks: tuple[float, ...]) -> SyntheticSource:
    for t in blinks:
        src.schedule_blink(t)
    return src


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path, *, corruption: str | None = None,
         at: float = CORRUPT_AT, amount: float = 0.0,
         blinks: tuple[float, ...] = PAIR) -> tuple[BiosignalRunner, list[str]]:
    """Run the real runner over a (possibly corrupted) EOG stream; return it and the intents."""
    # No mains hum: the quality gate (not the stream gate) suppresses blinks on a 10 uV hum.
    base = _schedule(SyntheticSource("eog", seed=SEED, duration=DURATION_S, mains_uv=0.0),
                     blinks)
    source: Any = base if corruption is None else CorruptingSource(
        base, kind=corruption, at=at, amount=amount)
    monkeypatch.setattr(sources_mod, "open_source", lambda spec: source)
    labels: list[str] = []
    runner = build_runner_from_config(
        _cfg(), RunnerCallbacks(on_intent=lambda intent: labels.append(intent.label)),
        ledger_path="")
    assert runner is not None
    runner.run()                            # finite source: ends on EOFError, no thread left
    return runner, labels


def _event_count(runner: BiosignalRunner) -> int:
    return runner.status()["events"]["accepted"]


@pytest.mark.parametrize(("corruption", "amount"), [("jump", 0.5), ("back", 0.5), ("nan", 0.1)])
def test_an_event_emitted_while_the_gate_is_closed_is_dropped(monkeypatch, tmp_path,
                                                              corruption, amount):
    """The gate's real effect: an event that the pipeline emits inside the closed window is
    refused. The same run with the gate removed emits it, which proves the gate did it."""
    kwargs = {"corruption": corruption, "amount": amount, "at": CLOSED_EMIT_AT}
    with monkeypatch.context() as m:
        m.setattr(integrity_mod, "IntegrityGate", lambda guard, inner=None: inner)
        ungated, ungated_labels = _run(m, tmp_path, **kwargs)
    assert ungated_labels == ["undo"]
    gated, labels = _run(monkeypatch, tmp_path, **kwargs)
    assert labels == []
    assert _event_count(gated) == 0
    assert gated.status()["events"]["dropped_by_reason"].get("stream", 0) >= 1


def test_control_clean_stream_double_blink_emits_one_event(monkeypatch, tmp_path):
    """Without a corruption the pair is an event. If this fails, nothing below proves anything."""
    runner, labels = _run(monkeypatch, tmp_path)
    status = runner.status()
    assert status["last_error"] == ""
    assert status["integrity"]["violations"] == {}
    assert status["integrity"]["gate_closed"] is False
    assert labels == ["undo"]
    assert _event_count(runner) == 1


@pytest.mark.parametrize(("corruption", "amount"), [
    ("jump", 0.5),
    ("back", 0.5),
    # Passes, but NOT because of the gate: the no-gate variant also emits nothing. The quality
    # monitor treats the renamed channels as warming up. See the report.
    ("swap", 0.0),
    ("nan", 0.1),
], ids=["t0-jump", "t0-backwards", "channels-swapped", "nan-burst"])
def test_corruption_just_before_a_double_blink_suppresses_the_event(
        monkeypatch, tmp_path, corruption, amount):
    runner, labels = _run(monkeypatch, tmp_path, corruption=corruption, amount=amount)
    status = runner.status()
    # The corruption was seen and counted.
    assert sum(status["integrity"]["violations"].values()) >= 1
    assert status["last_error"] == ""       # no exception escaped the runner
    # Whatever the signal looked like, no switch event and no intent came out.
    assert _event_count(runner) == 0
    assert labels == []


def test_nan_burst_is_counted_and_raises_nothing(monkeypatch, tmp_path):
    runner, _ = _run(monkeypatch, tmp_path, corruption="nan", amount=0.1)
    status = runner.status()
    assert status["integrity"]["violations"].get("non_finite", 0) >= 1
    assert status["last_error"] == ""
    assert status["blocks"] > 0


def test_recovery_after_the_gate_reopens_lets_the_pair_through(monkeypatch, tmp_path):
    """The same corruption, but the pair lands well after RECOVER_S of clean stream."""
    runner, labels = _run(monkeypatch, tmp_path, corruption="jump", amount=0.5,
                          blinks=LATE_PAIR)
    integrity = runner.status()["integrity"]
    assert sum(integrity["violations"].values()) >= 1
    assert integrity["clean_s"] > RECOVER_S
    assert integrity["gate_closed"] is False
    assert labels == ["undo"]
    assert _event_count(runner) == 1


def test_status_counts_the_violation_with_its_stream_time(monkeypatch, tmp_path):
    runner, _ = _run(monkeypatch, tmp_path, corruption="jump", amount=0.5)
    integrity = runner.status()["integrity"]
    assert integrity["violations"].get("gap", 0) >= 1
    assert integrity["last_violation"]["code"] == "gap"
    assert "missing" in integrity["last_violation"]["detail"]
    assert integrity["lost_s"] == pytest.approx(0.5, abs=0.05)


def test_the_gate_names_the_stream_gap_in_status_while_closed(monkeypatch, tmp_path):
    """The reason reaches the status and the dropped-event reasons, not only the logs."""
    runner, _ = _run(monkeypatch, tmp_path, corruption="jump", amount=0.5, at=CLOSED_EMIT_AT)
    status = runner.status()
    assert _event_count(runner) == 0
    reasons = " ".join([*status["events"]["dropped_by_reason"], status["pipeline"]["reason"]])
    assert "stream" in reasons or "gap" in reasons
