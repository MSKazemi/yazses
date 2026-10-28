#!/usr/bin/env python3
"""Synthetic replay for the EEG/EOG feasibility protocol, stages P0 and P1 (issue #696).

    uv run python scripts/hci_eegeog_replay.py            # JSON report, seed 0
    uv run python scripts/hci_eegeog_replay.py --seed 7

The protocol is `design/hci-huggingface/EEG_EOG_FEASIBILITY_PROTOCOL.md`. **Everything here is
generated.** The signals are seeded Gaussian noise with injected bursts whose size, shape and leakage
into the EEG channel are parameters chosen for this experiment. They are not physiology, and nothing
in the output says whether EEG or EOG can serve as a switch: it says whether this *pipeline* (windowing,
envelope, threshold from a rest block, refractory, artifact rejection, scoring against ground truth)
behaves as specified, and how a naive and an artifact-aware detector differ on *this* injection.

* P0 (plumbing): a noise-only stream through the detector, and the same seed twice giving the same bytes.
* P1 (injected artifacts): blinks (EOG burst that leaks into the EEG channel), clenches (EMG burst that
  leaks), speech-like muscle activity, rest, and intended switches (an EEG burst), each with known onsets.

It drives no real action, needs no device or network, and uses no clock. It is stdlib only, and it lives
outside `src/yazses/` on purpose: nothing in the daemon imports it.

No hourly rate is printed unless the scored control exposure reaches the repository's provisional minimum
(`yazses.eyeeval.analysis.DEFAULT_MIN_EXPOSURE_S`); below it the report gives the counts and the
exposure, and the rate is `null`.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections.abc import Sequence
from typing import Any

from yazses.eyeeval.analysis import DEFAULT_MIN_EXPOSURE_S

PROTOCOL_VERSION = "0.1-proposed"

NOTICE = (
    "SYNTHETIC DATA. Generated noise with injected bursts; the amplitudes and the leakage into the EEG channel "
    "are parameters of this experiment, not physiology. This checks a pipeline against ground truth. It says "
    "nothing about whether EEG or EOG can be used as a switch, and it makes no medical or thought-reading claim."
)

CHANNELS = ("eeg", "eog", "emg")

#: Everything a reader needs to reproduce or challenge a result. All values are choices, none is measured.
PARAMS: dict[str, float] = {
    "fs_hz": 100,
    "noise_sigma": 1.0,
    "envelope_window_s": 0.1,
    "threshold_k": 6.0,  # threshold = mean + k * std of the envelope on the calibration rest block
    "min_hold_s": 0.2,
    "refractory_s": 1.0,
    "match_window_s": 1.0,  # a candidate this soon after an onset is attributed to that event
    "suppress_window_s": 0.3,  # artifact-aware: look this far around a crossing for an EOG or EMG burst
    "switch_amplitude": 5.0,  # intended switch: an EEG burst
    "switch_width_s": 0.4,
    "blink_amplitude": 8.0,  # blink: an EOG burst
    "blink_width_s": 0.3,
    "blink_leak_into_eeg": 0.5,
    "clench_amplitude": 6.0,  # clench: an EMG burst
    "clench_width_s": 0.5,
    "clench_leak_into_eeg": 0.45,
    "speech_emg_sigma": 1.6,  # speech-like: continuous extra muscle activity
    "speech_leak_into_eeg": 0.15,
}

#: (block label, duration in s, number of injected events). Calibration rest is used only to set thresholds.
BLOCKS: tuple[tuple[str, int, int], ...] = (
    ("calibration_rest", 60, 0),
    ("rest", 60, 0),
    ("speaking", 60, 0),
    ("blink", 60, 10),
    ("clench", 60, 10),
    ("intended", 60, 10),
)
CONTROL_LABELS = ("rest", "speaking", "blink", "clench")


def _hann(n: int) -> list[float]:
    if n <= 1:
        return [1.0]
    return [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]


def synthesize(seed: int, blocks: Sequence[tuple[str, int, int]] = BLOCKS, inject: bool = True) -> dict[str, Any]:
    """Seeded signals, three channels, with the ground-truth events that were injected.

    Returns ``{"channels": {name: [samples]}, "events": [{"t_s", "kind"}], "blocks": [{"label", "start_s",
    "end_s"}]}``. With ``inject=False`` the events and leakage are omitted, which is the P0 noise-only case.
    """
    rng = random.Random(seed)
    fs = int(PARAMS["fs_hz"])
    sigma = PARAMS["noise_sigma"]
    channels: dict[str, list[float]] = {name: [] for name in CHANNELS}
    events: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    cursor = 0
    for label, duration_s, n_events in blocks:
        n = duration_s * fs
        block = {name: [rng.gauss(0.0, sigma) for _ in range(n)] for name in CHANNELS}
        if inject and label == "speaking":
            for i in range(n):
                muscle = rng.gauss(0.0, PARAMS["speech_emg_sigma"])
                block["emg"][i] += muscle
                block["eeg"][i] += PARAMS["speech_leak_into_eeg"] * muscle
        if inject and n_events:
            # Evenly spaced onsets with a seeded jitter, never inside the last second of the block.
            slot = (duration_s - 2.0) / n_events
            for k in range(n_events):
                onset = 1.0 + k * slot + rng.uniform(0.0, 0.3 * slot)
                _inject(block, label, onset, fs)
                events.append({"t_s": cursor / fs + onset, "kind": label})
        for name in CHANNELS:
            channels[name].extend(block[name])
        spans.append({"label": label, "start_s": cursor / fs, "end_s": (cursor + n) / fs})
        cursor += n
    return {"channels": channels, "events": events, "blocks": spans}


def _inject(block: dict[str, list[float]], label: str, onset_s: float, fs: int) -> None:
    """Add one burst. `label` says which kind: blink, clench or intended."""
    if label == "blink":
        main, amp, width, leak = "eog", PARAMS["blink_amplitude"], PARAMS["blink_width_s"], PARAMS["blink_leak_into_eeg"]
    elif label == "clench":
        main, amp, width, leak = "emg", PARAMS["clench_amplitude"], PARAMS["clench_width_s"], PARAMS["clench_leak_into_eeg"]
    else:
        main, amp, width, leak = "eeg", PARAMS["switch_amplitude"], PARAMS["switch_width_s"], 0.0
    start = int(onset_s * fs)
    window = _hann(int(width * fs))
    for i, w in enumerate(window):
        j = start + i
        if j >= len(block[main]):
            break
        # A clench is high-frequency, so its sign alternates; the others are slow bumps.
        sign = (-1.0) ** i if label == "clench" else 1.0
        block[main][j] += amp * w * sign
        if leak:
            block["eeg"][j] += leak * amp * w * sign


def envelope(samples: Sequence[float], fs: int, window_s: float) -> list[float]:
    """Moving average of |x| over a trailing window (causal: no look-ahead)."""
    w = max(1, int(round(window_s * fs)))
    out: list[float] = []
    running = 0.0
    absolute = [abs(x) for x in samples]
    for i, value in enumerate(absolute):
        running += value
        if i >= w:
            running -= absolute[i - w]
        out.append(running / min(i + 1, w))
    return out


def _mean_std(values: Sequence[float]) -> tuple[float, float]:
    mean = sum(values) / len(values)
    return mean, math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def thresholds_from(envelopes: dict[str, list[float]], start: int, end: int, k: float) -> dict[str, float]:
    """mean + k * std of each channel's envelope on the calibration rest block only."""
    out: dict[str, float] = {}
    for name, env in envelopes.items():
        mean, std = _mean_std(env[start:end])
        out[name] = mean + k * std
    return out


def detect(
    envelopes: dict[str, list[float]],
    thresholds: dict[str, float],
    fs: int,
    start: int,
    end: int,
    artifact_aware: bool,
) -> list[float]:
    """Activation candidate times (seconds) in ``[start, end)``.

    A candidate fires when the EEG envelope has stayed above its threshold for the minimum hold. The
    artifact-aware variant drops a candidate when the EOG or EMG envelope crossed its own threshold in the
    suppress window around the crossing. A fired or dropped crossing starts the refractory period.
    """
    hold = int(round(PARAMS["min_hold_s"] * fs))
    refractory = int(round(PARAMS["refractory_s"] * fs))
    look = int(round(PARAMS["suppress_window_s"] * fs))
    eeg = envelopes["eeg"]
    times: list[float] = []
    above = 0
    quiet_until = start
    for i in range(start, end):
        if i < quiet_until:
            above = 0
            continue
        above = above + 1 if eeg[i] > thresholds["eeg"] else 0
        if above < hold:
            continue
        crossing = i - hold + 1
        lo, hi = max(start, crossing - look), min(end, i + look)
        artifact = artifact_aware and any(
            envelopes[name][j] > thresholds[name] for name in ("eog", "emg") for j in range(lo, hi)
        )
        quiet_until = i + refractory
        above = 0
        if not artifact:
            times.append(i / fs)
    return times


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(percentile / 100.0 * len(ordered))) - 1]


def score(candidates: Sequence[float], data: dict[str, Any]) -> dict[str, Any]:
    """Attribute every candidate to ground truth and count, with denominators."""
    match = PARAMS["match_window_s"]
    events = data["events"]
    spans = [b for b in data["blocks"] if b["label"] != "calibration_rest"]
    hits: dict[int, float] = {}
    false_by_class = {label: 0 for label in CONTROL_LABELS}
    for t in candidates:
        cause = next((i for i, e in enumerate(events) if e["t_s"] <= t < e["t_s"] + match), None)
        if cause is not None and events[cause]["kind"] == "intended":
            hits.setdefault(cause, t - events[cause]["t_s"])
            continue
        if cause is not None:
            false_by_class[events[cause]["kind"]] += 1
            continue
        block = next((b["label"] for b in spans if b["start_s"] <= t < b["end_s"]), None)
        if block in false_by_class:
            false_by_class[block] += 1
        # a candidate in the intended block outside any event window, or in calibration, is not a control
        # activation; it is counted below as an unattributed candidate so it is never silently dropped
    attributed = sum(false_by_class.values()) + len(hits)
    intended_total = sum(1 for e in events if e["kind"] == "intended")
    latencies_ms = sorted(round(1000 * v, 1) for v in hits.values())
    counts = {kind: sum(1 for e in events if e["kind"] == kind) for kind in ("blink", "clench")}
    seconds = {b["label"]: b["end_s"] - b["start_s"] for b in spans}
    exposure_s = sum(seconds.get(label, 0.0) for label in CONTROL_LABELS)
    false_total = sum(false_by_class.values())
    return {
        "candidates": len(candidates),
        "unattributed_candidates": len(candidates) - attributed,
        "hits": {"numerator": len(hits), "denominator": intended_total},
        "missed_switches": {"numerator": intended_total - len(hits), "denominator": intended_total},
        "latency_ms": {
            "n": len(latencies_ms),
            "median": _nearest_rank(latencies_ms, 50) if latencies_ms else None,
            "max": latencies_ms[-1] if latencies_ms else None,
        },
        "false_activations": {
            "blink": {"numerator": false_by_class["blink"], "denominator": counts["blink"], "unit": "blink events"},
            "clench": {"numerator": false_by_class["clench"], "denominator": counts["clench"], "unit": "clench events"},
            "rest": {"numerator": false_by_class["rest"], "denominator": seconds.get("rest", 0.0), "unit": "seconds"},
            "speaking": {"numerator": false_by_class["speaking"], "denominator": seconds.get("speaking", 0.0), "unit": "seconds"},
            "total": false_total,
        },
        "false_activations_per_hour": _per_hour(false_total, exposure_s),
    }


def _per_hour(events: int, exposure_s: float) -> dict[str, Any]:
    out: dict[str, Any] = {"events": events, "exposure_s": exposure_s, "minimum_exposure_s": DEFAULT_MIN_EXPOSURE_S}
    if exposure_s < DEFAULT_MIN_EXPOSURE_S:
        out["value"] = None
        out["note"] = "insufficient data: exposure is below the repository's provisional minimum, so no hourly rate is printed"
    else:
        out["value"] = round(events * 3600.0 / exposure_s, 3)
        out["note"] = "synthetic; not a measurement"
    return out


def run(seed: int = 0) -> dict[str, Any]:
    """The full P0 + P1 report for one seed. Deterministic: the same seed gives the same report."""
    fs = int(PARAMS["fs_hz"])
    window = PARAMS["envelope_window_s"]

    # P0: noise only, no injected events and no leakage.
    noise = synthesize(seed, (("calibration_rest", 60, 0), ("rest", 120, 0)), inject=False)
    env0 = {name: envelope(noise["channels"][name], fs, window) for name in CHANNELS}
    thr0 = thresholds_from(env0, 0, 60 * fs, PARAMS["threshold_k"])
    p0 = detect(env0, thr0, fs, 60 * fs, 180 * fs, artifact_aware=False)

    # P1: the injected blocks. Thresholds come from the calibration rest block only.
    data = synthesize(seed)
    env = {name: envelope(data["channels"][name], fs, window) for name in CHANNELS}
    calibration = data["blocks"][0]
    thresholds = thresholds_from(env, int(calibration["start_s"] * fs), int(calibration["end_s"] * fs), PARAMS["threshold_k"])
    first_scored = int(data["blocks"][1]["start_s"] * fs)
    total = len(env["eeg"])
    configs = {}
    for name, aware in (("naive", False), ("artifact_aware", True)):
        configs[name] = score(detect(env, thresholds, fs, first_scored, total, aware), data)

    return {
        "protocol_version": PROTOCOL_VERSION,
        "synthetic": True,
        "notice": NOTICE,
        "seed": seed,
        "parameters": dict(PARAMS),
        "blocks": [list(b) for b in BLOCKS],
        "thresholds": {k: round(v, 6) for k, v in thresholds.items()},
        "p0_noise_only": {
            "scored_seconds": 120,
            "candidates": len(p0),
            "note": "Plumbing only: a pure-noise stream through the detector. Says nothing about EEG.",
        },
        "p1_injected": configs,
        "limitations": [
            "Injected bursts and their leakage are chosen parameters; a different leakage changes both detectors' results.",
            "One seed is one draw; the counts are small and carry no confidence interval.",
            "Gaussian noise has no drift, no sensor fatigue and no between-session change.",
            "Nothing here supports a claim about real EEG or EOG.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic P0/P1 replay for the EEG/EOG feasibility protocol (#696).")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    sys.stdout.write(json.dumps(run(args.seed), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
