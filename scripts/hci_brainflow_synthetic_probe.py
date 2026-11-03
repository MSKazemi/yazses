#!/usr/bin/env python3
"""Research-only BrainFlow SYNTHETIC_BOARD interface smoke test (issue #696).

Run explicitly on a host with the optional BrainFlow package installed::

    uv run --extra emg-band python scripts/hci_brainflow_synthetic_probe.py --seconds 2

No hardware or user data; this connects to BrainFlow's software-generated board
only (id -1). Nothing is written to disk, and no OS actions are emitted.
The sample stream is not deterministic: BrainFlow generates it as time passes.
This validates plumbing, NOT EEG/EOG/EMG physiology or neural control.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

BOARD_ID = -1
MODALITIES = ("eeg", "eog", "emg")
NOTICE = (
    "SYNTHETIC BOARD ONLY. A BrainFlow channel can have multiple modality labels; "
    "this checks the interface, not independent human EEG, EOG, EMG, neural intent, "
    "real-world false activations or clinical function."
)


def summarize(board_api: Any, board_id: int, data: Any) -> dict[str, Any]:
    """Pure report computation. Never serialize raw samples or absolute timestamps."""
    if board_id != BOARD_ID:
        raise ValueError("only BrainFlow's SYNTHETIC_BOARD (-1) is permitted")
    shape = getattr(data, "shape", None)
    if shape is None or len(shape) != 2:
        raise ValueError("expected 2D BrainFlow sample matrix")
    rows, samples = (int(dimension) for dimension in shape)
    expected_rows = int(board_api.get_num_rows(board_id))
    if rows != expected_rows or samples < 2:
        raise ValueError("unexpected channel count or too few synthetic samples")
    sample_rate_hz = int(board_api.get_sampling_rate(board_id))
    if sample_rate_hz <= 0:
        raise ValueError("invalid sample rate")
    timestamp_channel = int(board_api.get_timestamp_channel(board_id))
    if not 0 <= timestamp_channel < rows:
        raise ValueError("timestamp index outside sample matrix")

    channels: dict[str, list[int]] = {}
    for modality in MODALITIES:
        indices = [int(v) for v in getattr(board_api, f"get_{modality}_channels")(board_id)]
        if len(set(indices)) != len(indices) or any(not 0 <= idx < rows for idx in indices):
            raise ValueError(f"invalid {modality} indices")
        channels[modality] = indices

    # Read values only to validate them. Do not serialize the matrix or any sample.
    for row in data:
        if any(not math.isfinite(float(value)) for value in row):
            raise ValueError("non-finite synthetic samples")
    stamps = [float(value) for value in data[timestamp_channel]]
    gaps = [end - start for start, end in zip(stamps, stamps[1:])]
    if any(gap <= 0 for gap in gaps):
        raise ValueError("timestamps are not strictly increasing")

    sorted_gaps = sorted(gaps)
    rank = max(0, math.ceil(0.95 * len(sorted_gaps)) - 1)
    return {
        "synthetic": True,
        "brainflow_board_id": board_id,
        "notice": NOTICE,
        "checks": {"finite_data": True, "monotonic_timestamps": True, "channel_indices_in_range": True},
        "rows": rows,
        "sample_count": samples,
        "sample_rate_hz": sample_rate_hz,
        "relative_capture_span_ms": round((stamps[-1] - stamps[0]) * 1000, 3),
        "timestamp_gap_p95_ms": round(sorted_gaps[rank] * 1000, 3),
        "channels_by_label": channels,
        "eeg_eog_shared_indices": len(set(channels["eeg"]) & set(channels["eog"])),
        "eeg_emg_shared_indices": len(set(channels["eeg"]) & set(channels["emg"])),
        "physiological_evidence": False,
        "human_data": False,
        "hardware_connected": False,
        "os_actions_emitted": False,
        "raw_samples_exported": False,
    }


def probe(
    board_api: Any,
    params_type: Callable[[], Any],
    *,
    board_id: int = BOARD_ID,
    seconds: float = 2.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Acquire a short, synthetic-only stream; always stop and release session."""
    if board_id != BOARD_ID:
        raise ValueError("real hardware and other board types are not permitted")
    if not (0.2 <= seconds <= 5.0) or not math.isfinite(seconds):
        raise ValueError("duration must be between 0.2 and 5 seconds")
    board = board_api(board_id, params_type())
    prepared = False
    streaming = False
    try:
        board.prepare_session()
        prepared = True
        board.start_stream()
        streaming = True
        sleep_fn(seconds)
        data = board.get_board_data()
    finally:
        if streaming:
            try:
                board.stop_stream()
            finally:
                if prepared:
                    board.release_session()
        elif prepared:
            board.release_session()
    report = summarize(board_api, board_id, data)
    report["requested_capture_seconds"] = seconds
    report["host_platform"] = platform.system().lower()
    report["host_architecture"] = platform.machine().lower()
    report["python_version"] = platform.python_version()
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local BrainFlow synthetic-board interface smoke test; no physiology")
    parser.add_argument("--seconds", type=float, default=2.0, help="synthetic stream duration (0.2 to 5 seconds)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or not 0.2 <= args.seconds <= 5.0:
        parser.error("--seconds must be between 0.2 and 5")
    try:
        # Explicitly optional: no BrainFlow import for normal app/test execution.
        from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams
    except ImportError:
        print("BrainFlow is not installed; this opt-in test needs the emg-band extra.", file=sys.stderr)
        return 2
    if BoardIds.SYNTHETIC_BOARD.value != BOARD_ID:
        print("BrainFlow changed the synthetic board ID; aborting", file=sys.stderr)
        return 2
    try:
        result = probe(BoardShim, BrainFlowInputParams, seconds=args.seconds)
    except Exception as exc:
        print(f"Synthetic BrainFlow interface check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    try:
        result["brainflow_version"] = importlib.metadata.version("brainflow")
    except importlib.metadata.PackageNotFoundError:
        result["brainflow_version"] = "unknown"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
