#!/usr/bin/env python3
"""Deterministic, standard-library-only transport fault replay for issue #696.

This replays constructed matrices through the *pure* BrainFlow probe integrity
checks; it does not import BrainFlow, open a board or execute desktop actions.
No event classifier or EEG physiology is involved. All numbers are synthetic.

    python scripts/hci_brainflow_integrity_replay.py --seed 0
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from hci_brainflow_synthetic_probe import summarize

FS_HZ = 250
SAMPLES = 500
NOTICE = (
    "SYNTHETIC TRANSPORT REPLAY ONLY: arbitrary waveforms, no BrainFlow native session, "
    "no human sensor data, no neural intent, no calibrated false activation rates."
)


@dataclass
class FakeMatrix:
    rows: list[list[float]]

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.rows), len(self.rows[0])

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.rows)

    def __getitem__(self, index: int) -> list[float]:
        return self.rows[index]


class FakeBrainFlowMetadata:
    """A fabricated four-row board; not the real synthetic board's 32 rows."""

    @staticmethod
    def get_num_rows(board_id: int) -> int:
        return 4

    @staticmethod
    def get_sampling_rate(board_id: int) -> int:
        return FS_HZ

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


def generate(seed: int, fault: str) -> FakeMatrix:
    """Create a new matrix for every scenario; no training-data leakage or clock."""
    rng = random.Random(seed)
    # The nominal interval is exact at this scale, jitter is <5% of an interval.
    timestamps = [1.0 + i / FS_HZ for i in range(SAMPLES)]
    if fault == "small_jitter":
        timestamps = [t + (rng.random() - 0.5) * 0.1 / FS_HZ for t in timestamps]
    rows = [[rng.gauss(0, 1) for _ in range(SAMPLES)] for _ in range(3)]
    if fault == "artifact_burst":
        # A large arbitrary pulse is NOT grounds for this transport probe to
        # conclude it came from an eye, muscle or neural source.
        for i in range(220, 245):
            rows[0][i] += 50.0 * math.sin((i - 220) * math.pi / 25)
    elif fault == "timestamp_duplicate":
        timestamps[220] = timestamps[219]
    elif fault == "timestamp_reverse":
        timestamps[220] = timestamps[219] - 0.001
    elif fault == "timestamp_jump":
        timestamps[220:] = [t + 0.12 for t in timestamps[220:]]
    elif fault == "nonfinite":
        rows[1][220] = float("nan")
    elif fault == "all_signal_flatline":
        rows = [[0.0] * SAMPLES for _ in range(3)]
    elif fault == "insufficient_samples":
        rows = [r[:1] for r in rows]
        timestamps = timestamps[:1]
    elif fault not in ("clean", "small_jitter", "artifact_burst"):
        raise ValueError(f"unknown fault scenario: {fault}")
    return FakeMatrix(rows + [timestamps])


SCENARIOS = (
    ("clean", True, None),
    ("small_jitter", True, None),
    ("artifact_burst", True, None),
    ("timestamp_duplicate", False, "strictly increasing"),
    ("timestamp_reverse", False, "strictly increasing"),
    ("timestamp_jump", False, "timestamp gap"),
    ("nonfinite", False, "non-finite"),
    ("all_signal_flatline", False, "flatlined"),
    ("insufficient_samples", False, "too few"),
)


def run(seed: int = 0) -> dict[str, Any]:
    if seed < 0:
        raise ValueError("seed must be nonnegative")
    records: list[dict[str, Any]] = []
    for scenario, expected_accept, expected_error in SCENARIOS:
        matrix = generate(seed, scenario)
        reason = None
        try:
            summarize(FakeBrainFlowMetadata, -1, matrix)
            accepted = True
        except ValueError as exc:
            accepted = False
            # Error messages are stable and cannot contain human data here.
            reason = str(exc)
        matches = accepted == expected_accept and (expected_error is None or expected_error in (reason or ""))
        records.append(
            {
                "scenario": scenario,
                "expected_transport_valid": expected_accept,
                "observed_transport_valid": accepted,
                "expected_outcome_met": matches,
                "error": reason,
            }
        )
    return {
        "schema_version": "1.0-synthetic-transport",
        "seed": seed,
        "synthetic": True,
        "notice": NOTICE,
        "params": {"sampling_rate_hz": FS_HZ, "sample_count": SAMPLES, "scenarios": len(SCENARIOS)},
        "all_expectations_met": all(x["expected_outcome_met"] for x in records),
        "scenarios": records,
        "physiological_evidence": False,
        "hardware_tested": False,
        "os_actions_emitted": False,
        "raw_samples_exported": False,
        "limitations": [
            "The 0.12 s forward jump and 10-period limit are constructed values, not measured hardware tolerances.",
            "An artifact-looking burst can be transport-valid; classification and artifact origin are outside this probe.",
            "No real device, BoardShim native shared library, or human signal was used.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic board-matrix fault replay; never controls OS actions")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    result = run(args.seed)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["all_expectations_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
