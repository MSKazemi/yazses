"""Offline tests of #696's optional BrainFlow synthetic-board interface probe.

Uses a fake BoardShim and generated data. Does not require or start BrainFlow,
contact an external device, or measure biological performance.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hci_brainflow_synthetic_probe.py"
_spec = importlib.util.spec_from_file_location("hci_brainflow_synthetic_probe", SCRIPT)
assert _spec is not None and _spec.loader is not None
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)


class FakeBoardShim:
    instances: list[FakeBoardShim] = []
    fail_at: str | None = None
    broken_stamps = False

    def __init__(self, board_id: int, params: object) -> None:
        assert board_id == -1
        self.events: list[str] = []
        FakeBoardShim.instances.append(self)

    @staticmethod
    def get_num_rows(board_id: int) -> int:
        return 4

    @staticmethod
    def get_sampling_rate(board_id: int) -> int:
        return 250

    @staticmethod
    def get_timestamp_channel(board_id: int) -> int:
        return 3

    @staticmethod
    def get_eeg_channels(board_id: int) -> list[int]:
        return [0, 1]

    @staticmethod
    def get_eog_channels(board_id: int) -> list[int]:
        return [0, 1]

    @staticmethod
    def get_emg_channels(board_id: int) -> list[int]:
        return [1, 2]

    def prepare_session(self) -> None:
        self.events.append("prepare")

    def start_stream(self) -> None:
        self.events.append("start")

    def get_board_data(self) -> np.ndarray:
        self.events.append("read")
        if self.fail_at == "read":
            raise RuntimeError("read failed")
        stamps = np.array([1.0, 1.004, 1.008], dtype=float)
        if self.broken_stamps:
            stamps[2] = stamps[1]
        return np.array([[1.0, 1.5, 1.1], [0.0, 0.2, 0.3], [0.0, 0.0, 0.0], stamps])

    def stop_stream(self) -> None:
        self.events.append("stop")

    def release_session(self) -> None:
        self.events.append("release")


@pytest.fixture(autouse=True)
def reset_fake() -> None:
    FakeBoardShim.instances.clear()
    FakeBoardShim.fail_at = None
    FakeBoardShim.broken_stamps = False


def test_synthetic_only_report_is_aggregate_and_not_physio() -> None:
    delays: list[float] = []
    report = P.probe(FakeBoardShim, object, seconds=0.5, sleep_fn=delays.append)
    assert delays == [0.5]
    assert FakeBoardShim.instances[0].events == ["prepare", "start", "read", "stop", "release"]
    assert report["sample_count"] == 3
    assert report["sample_rate_hz"] == 250
    assert report["relative_capture_span_ms"] == pytest.approx(8.0)
    assert report["eeg_eog_shared_indices"] == 2
    assert report["eeg_emg_shared_indices"] == 1
    assert report["checks"]["monotonic_timestamps"] is True
    assert report["physiological_evidence"] is False
    assert report["raw_samples_exported"] is False
    serialized = json.dumps(report)
    assert "1.004" not in serialized  # absolute timestamps stay out of reports
    assert "1.5" not in serialized  # raw signal values stay out


def test_rejects_real_board_and_unbounded_duration_without_opening_any_board() -> None:
    with pytest.raises(ValueError, match="real hardware"):
        P.probe(FakeBoardShim, object, board_id=0, sleep_fn=lambda _: None)
    with pytest.raises(ValueError, match="duration"):
        P.probe(FakeBoardShim, object, seconds=99, sleep_fn=lambda _: None)
    with pytest.raises(ValueError, match="duration"):
        P.probe(FakeBoardShim, object, seconds=float("nan"), sleep_fn=lambda _: None)
    assert FakeBoardShim.instances == []


def test_releases_session_on_failed_read() -> None:
    FakeBoardShim.fail_at = "read"
    with pytest.raises(RuntimeError, match="read failed"):
        P.probe(FakeBoardShim, object, sleep_fn=lambda _: None)
    assert FakeBoardShim.instances[0].events == ["prepare", "start", "read", "stop", "release"]


def test_rejects_nonmonotonic_time_without_exporting_samples() -> None:
    FakeBoardShim.broken_stamps = True
    with pytest.raises(ValueError, match="strictly increasing"):
        P.probe(FakeBoardShim, object, sleep_fn=lambda _: None)
    assert FakeBoardShim.instances[0].events[-2:] == ["stop", "release"]


def test_rejects_nonfinite_sample_and_wrong_dimensions() -> None:
    class NonfiniteApi(FakeBoardShim):
        def get_board_data(self) -> np.ndarray:
            data = super().get_board_data()
            data[0, 0] = float("nan")
            return data

    with pytest.raises(ValueError, match="non-finite"):
        P.probe(NonfiniteApi, object, sleep_fn=lambda _: None)
    with pytest.raises(ValueError, match="2D"):
        P.summarize(FakeBoardShim, -1, np.ones(4))
    with pytest.raises(ValueError, match="channel count"):
        P.summarize(FakeBoardShim, -1, np.ones((3, 10)))


def test_releases_session_when_stream_start_fails() -> None:
    class FailingStart(FakeBoardShim):
        def start_stream(self) -> None:
            self.events.append("start")
            raise RuntimeError("start failed")

    with pytest.raises(RuntimeError, match="start failed"):
        P.probe(FailingStart, object, sleep_fn=lambda _: None)
    assert FakeBoardShim.instances[0].events == ["prepare", "start", "release"]


def test_releases_session_even_when_stop_fails() -> None:
    class FailingStop(FakeBoardShim):
        def stop_stream(self) -> None:
            self.events.append("stop")
            raise RuntimeError("stop failed")

    with pytest.raises(RuntimeError, match="stop failed"):
        P.probe(FailingStop, object, sleep_fn=lambda _: None)
    assert FakeBoardShim.instances[0].events == ["prepare", "start", "read", "stop", "release"]
