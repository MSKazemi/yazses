"""``field-test --minutes`` keeps the switch filter on every path (#888).

A short ``--minutes`` used to make scaling raise inside ``_scaled_protocol``; the fallback
returned ``None`` and the session ran the module's full default protocol: the standard
length, and gesture phases for switches that were off (squeeze, jaw clench). Now a length
the cues cannot fit is refused with the minimum, before any source is opened, and every
accepted length is the filtered protocol scaled.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from yazses.biosignal import cli_impl, fieldtest
from yazses.biosignal.cli_impl import ProtocolTooShort, Switches, run_field_test
from yazses.biosignal.sources import SyntheticSource
from yazses.config import BiosignalConfig, Config

BLINK_ONLY = Switches(emg=False, double_blink=True, jaw_clench=False)


def _cfg() -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), enabled=True,
                                        source="synthetic:eog", emg=False,
                                        double_blink=True, jaw_clench=False)
    return cfg


def _gestures(phases: Any) -> list[str]:
    return [p.name for p in phases if p.expects_intent]


def _minimum(switches: Switches = BLINK_ONLY) -> float:
    with pytest.raises(ProtocolTooShort) as info:
        cli_impl._scaled_protocol(fieldtest, 0.01, switches)
    return info.value.minimum


def test_the_minimum_is_where_the_gesture_phase_stops_counting() -> None:
    """The cues alone would fit from about 5.32 min (#888), but a session also refuses a
    phase under 30 s: the 45 s gesture phase of a 495 s protocol reaches that at 5.50."""
    expected = 30.0 / 45.0 * (450.0 + 45.0) / 60.0                     # 5.5 min
    minimum = _minimum()
    assert expected - 1e-9 <= minimum <= expected + 0.01
    assert minimum == pytest.approx(5.50)


@pytest.mark.parametrize("minutes", [1.5, 5.3, 5.35, 5.49])
def test_below_the_minimum_is_refused_naming_it(minutes: float) -> None:
    with pytest.raises(ProtocolTooShort) as info:
        cli_impl._scaled_protocol(fieldtest, minutes, BLINK_ONLY)
    assert f"--minutes {_minimum():.2f}" in str(info.value)


@pytest.mark.parametrize("minutes", ["minimum", 5.51, 10.0, 0.0])
def test_every_accepted_length_keeps_only_the_enabled_gestures(minutes: Any) -> None:
    value = _minimum() if minutes == "minimum" else float(minutes)
    phases, total, note = cli_impl._scaled_protocol(fieldtest, value, BLINK_ONLY)
    assert phases is not None
    assert _gestures(phases) == ["gesture_double_blink"]
    assert note == ""
    if value:
        assert total == pytest.approx(value * 60.0)


def test_the_minimum_depends_on_the_switches() -> None:
    every = Switches(emg=True, double_blink=True, jaw_clench=True)
    assert _minimum(every) > _minimum(BLINK_ONLY)


def _open_spy(opened: list[str]) -> Any:
    def _open(spec: str, realtime: bool = False) -> Any:
        opened.append(spec)
        return SyntheticSource("eog", seed=3, duration=4.0, mains_uv=0.0)
    return _open


def test_run_field_test_refuses_a_too_short_run_before_opening_the_source(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    opened: list[str] = []
    monkeypatch.setattr(cli_impl, "_open", _open_spy(opened))
    code = run_field_test(_cfg(), tmp_path, source="synthetic:eog", minutes=1.5, as_json=True)
    assert code == cli_impl.UNUSABLE
    assert opened == []
    err = capsys.readouterr().err
    assert "--minutes 1.5 is too short" in err and "--minutes 5.50" in err


def test_run_field_test_hands_the_session_the_filtered_scaled_protocol(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[Any] = []

    class Session:
        def __init__(self, source: Any, factory: Any, **kw: Any) -> None:
            seen.append(kw.get("protocol"))
            raise ValueError("stop here")

    monkeypatch.setattr(cli_impl, "_open", _open_spy([]))
    monkeypatch.setattr(fieldtest, "FieldTestSession", Session)
    run_field_test(_cfg(), tmp_path, source="synthetic:eog", minutes=6.0, as_json=True)
    assert len(seen) == 1 and seen[0] is not None
    assert _gestures(seen[0]) == ["gesture_double_blink"]
    assert sum(p.duration_s for p in seen[0]) == pytest.approx(360.0)
