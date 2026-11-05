#!/usr/bin/env python3
"""Research-only, causal *synthetic* motor-imagery EEG stress replay (#696).

This is an adversarial software test, not an EEG decoder or a validated model.
The 10 Hz amplitude suppression, drift, artifacts and thresholds are authored
parameters; no human or device data exists. Nothing can control YazSes.

Run: python scripts/hci_eeg_mi_synthetic.py --seed 0
No models, downloads, devices, network or extra Python packages are required.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from collections.abc import Sequence
from typing import Any

FS = 100
MU_HZ = 10
WINDOW_S = 1.0
HOP_S = 0.25
THRESHOLD_RATIO = 0.55
REARM_RATIO = 0.80
CONSECUTIVE = 2
ARTIFACT_EOG_PEAK = 0.85
ARTIFACT_EMG_RMS = 0.30
MIN_EEG_STD = 0.05

# (label, duration_seconds, nominal mu-amplitude). The exact parameters are
# invented, never derived from human EEG. Distinct segments avoid data leakage.
BLOCKS: tuple[tuple[str, int, float], ...] = (
    ("calibration_rest", 6, 1.00),
    ("rest", 8, 1.00),
    ("imagery", 8, 0.30),
    ("recovery_rest", 8, 1.00),
    ("drift_rest", 8, 0.48),
    ("rest_after_drift", 8, 1.00),
    ("blink", 8, 1.00),
    ("clench", 8, 1.00),
    ("speaking", 8, 1.00),
    ("recovered_rest", 8, 1.00),
    ("imagery_second", 8, 0.32),
    ("dropout", 8, 1.00),
    ("flatline", 8, 0.00),
    ("final_rest", 8, 1.00),
)
CONTROL_LABELS = frozenset(n for n, _, _ in BLOCKS if n != "calibration_rest" and not n.startswith("imagery"))


def generate(seed: int = 0, drift_amplitude: float | None = None) -> dict[str, Any]:
    """Make time-ordered, synthetic C3/C4-like, eye and muscle channels.

    ``drift_amplitude`` overrides the authored mu-amplitude of the ``drift_rest``
    block only; ``None`` keeps the original authored value (byte-identical output).
    """
    rng = random.Random(seed)
    channels: dict[str, list[float | None]] = {name: [] for name in ("c3", "c4", "eog", "emg")}
    spans: list[dict[str, Any]] = []
    cursor = 0
    for label, duration, mu_amp in BLOCKS:
        if label == "drift_rest" and drift_amplitude is not None:
            mu_amp = drift_amplitude
        first = cursor
        for j in range(duration * FS):
            t = (cursor + j) / FS
            noise = rng.gauss(0, 0.08)
            emg = rng.gauss(0, 0.05)
            eog = rng.gauss(0, 0.05)
            if label == "blink" and 2.7 <= j / FS < 3.1:
                eog += 3.0 * math.sin(math.pi * (j / FS - 2.7) / 0.4) ** 2
            if label == "clench" and 2.5 <= j / FS < 3.0:
                emg += 2.5 * ((-1) ** j)
            if label == "speaking":
                emg += rng.gauss(0, 0.75)
            c3 = mu_amp * math.sin(2 * math.pi * MU_HZ * t) + noise + 0.14 * eog + 0.10 * emg
            c4 = mu_amp * math.cos(2 * math.pi * MU_HZ * t) + rng.gauss(0, 0.08) + 0.10 * eog + 0.10 * emg
            if label == "dropout" and 2 <= j / FS < 6:
                c3 = c4 = eog = emg = None
            if label == "flatline":
                c3 = c4 = 0.0
            for name, sample in (("c3", c3), ("c4", c4), ("eog", eog), ("emg", emg)):
                channels[name].append(sample)
        cursor += duration * FS
        spans.append({"label": label, "start_s": first / FS, "end_s": cursor / FS})
    return {"synthetic": True, "seed": seed, "channels": channels, "blocks": spans}


def drift_sweep(amplitudes: Sequence[float], seeds: Sequence[int]) -> list[dict[str, Any]]:
    """Pure sweep: per drift amplitude, how many seeds give a false candidate in drift_rest.

    Seeds change only the noise, so the counts describe the authored thresholds
    against one authored waveform, not physiology or between-subject variation.
    """
    rows: list[dict[str, Any]] = []
    for amp in amplitudes:
        firing = 0
        for seed in seeds:
            out = run(seed, drift_amplitude=amp)
            if out["scores"]["false_candidates_by_control"]["drift_rest"] >= 1:
                firing += 1
        rows.append({"drift_amplitude": amp, "seeds_firing": firing, "seeds": len(seeds)})
    return rows


def _std(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values))


def _power_10hz(values: list[float]) -> float:
    """Causal trailing-window 10 Hz quadrature power, not a learned model."""
    n = len(values)
    re = sum(x * math.cos(2 * math.pi * MU_HZ * j / FS) for j, x in enumerate(values))
    im = sum(x * math.sin(2 * math.pi * MU_HZ * j / FS) for j, x in enumerate(values))
    return (2 * re / n) ** 2 + (2 * im / n) ** 2


def feature_at(channels: dict[str, list[float | None]], end: int) -> tuple[float | None, str]:
    """Score a trailing 1 s window using only samples strictly before end."""
    n = int(WINDOW_S * FS)
    if end < n:
        return None, "warmup"
    tails = {name: raw[end - n : end] for name, raw in channels.items()}
    if any(len(values) != n or any(v is None or not math.isfinite(v) for v in values)
           for values in tails.values()):
        return None, "missing_or_nonfinite"
    safe = {name: [float(v) for v in values] for name, values in tails.items()}
    if any(_std(safe[name]) < MIN_EEG_STD or _std(safe[name][-int(HOP_S * FS):]) < MIN_EEG_STD
           for name in ("c3", "c4")):
        return None, "flatline"
    if max(abs(x) for x in safe["eog"]) > ARTIFACT_EOG_PEAK:
        return None, "ocular_artifact"
    if _rms(safe["emg"]) > ARTIFACT_EMG_RMS:
        return None, "muscle_artifact"
    return sum(_power_10hz(safe[name]) for name in ("c3", "c4")) / 2, "usable"


def replay(data: dict[str, Any], stop_at_s: float | None = None) -> dict[str, Any]:
    """Fit baseline on calibration only, then make causal candidate *proposals*."""
    channels = data["channels"]
    calibration_end = int(data["blocks"][0]["end_s"] * FS)
    stride = int(HOP_S * FS)
    calibration = [power for end in range(FS, calibration_end + 1, stride)
                   if (power := feature_at(channels, end)[0]) is not None]
    if not calibration:
        raise ValueError("no usable calibration windows")
    reference = sum(calibration) / len(calibration)
    if reference <= 0:
        raise ValueError("no valid mu-power baseline")
    proposals: list[dict[str, float]] = []
    reasons: Counter[str] = Counter()
    armed = True
    consecutive = 0
    eligible = 0
    for end in range(calibration_end + stride, len(channels["c3"]) + 1, stride):
        t_s = end / FS
        if stop_at_s is not None and t_s >= stop_at_s:
            reasons["external_stop"] += 1
            armed = False
            consecutive = 0
            continue
        power, quality = feature_at(channels, end)
        if power is None:
            reasons[quality] += 1
            armed = False   # require a *new* observed rest before re-arming
            consecutive = 0
            continue
        eligible += 1
        ratio = power / reference
        if ratio >= REARM_RATIO:
            armed = True
            consecutive = 0
        elif armed and ratio < THRESHOLD_RATIO:
            consecutive += 1
            if consecutive >= CONSECUTIVE:
                # Heuristic suppression score is NOT calibrated probability.
                proposals.append({"t_s": round(t_s, 3), "suppression_score": round(max(0.0, 1.0 - ratio), 6)})
                armed = False
                consecutive = 0
        else:
            consecutive = 0
    return {"proposals": proposals, "abstention_reasons": dict(sorted(reasons.items())),
            "eligible_windows": eligible, "reference_power": round(reference, 6),
            "stop_at_s": stop_at_s}


def score(data: dict[str, Any], replay_out: dict[str, Any]) -> dict[str, Any]:
    """Count candidate errors using synthetic labels *only after* inference."""
    blocks = data["blocks"]
    candidates = replay_out["proposals"]
    by_label: Counter[str] = Counter()
    hit_latency: list[int] = []
    for proposal in candidates:
        t = proposal["t_s"]
        span = next((b for b in blocks if b["start_s"] <= t < b["end_s"]), None)
        if span is None:
            by_label["unattributed"] += 1
        else:
            by_label[span["label"]] += 1
            if span["label"].startswith("imagery") and t - span["start_s"] <= 3.0:
                hit_latency.append(round(1000 * (t - span["start_s"])))
    possible_events = sum(1 for b in blocks if b["label"].startswith("imagery") and
                          (replay_out["stop_at_s"] is None or b["start_s"] < replay_out["stop_at_s"] - 3.0))
    hits = min(len(hit_latency), possible_events)
    false = {key: by_label[key] for key in sorted(CONTROL_LABELS)}
    false["unattributed"] = by_label["unattributed"]
    exposure = sum(b["end_s"] - b["start_s"] for b in blocks if b["label"] in CONTROL_LABELS and
                   (replay_out["stop_at_s"] is None or b["end_s"] <= replay_out["stop_at_s"]))
    return {"imagery_hits": {"numerator": hits, "denominator": possible_events},
            "missed_events": possible_events - hits,
            "hit_latency_ms": hit_latency,
            "false_candidates_by_control": false,
            "false_candidates_total": sum(false.values()),
            "synthetic_control_exposure_s": exposure,
            "false_activations_per_hour": None,
            "false_rate_note": "Not estimated: short, scripted synthetic blocks are not real idle exposure or device behavior."}


def run(seed: int = 0, stop_at_s: float | None = None,
        drift_amplitude: float | None = None) -> dict[str, Any]:
    data = generate(seed, drift_amplitude)
    evaluated = replay(data, stop_at_s)
    return {"research_only": True, "synthetic": True, "provenance": "hand-authored waveforms, Python stdlib, seed fixed",
            "notice": "This is a synthetic software stress-test, NOT proof of brain decoding, intent recognition, device performance, or clinical efficacy.",
            "seed": seed,
            "settings": {"fs_hz": FS, "mu_hz": MU_HZ, "window_s": WINDOW_S, "hop_s": HOP_S,
                         "threshold_ratio": THRESHOLD_RATIO, "rearm_ratio": REARM_RATIO,
                         "consecutive_windows": CONSECUTIVE, "ocular_peak_gate": ARTIFACT_EOG_PEAK,
                         "muscle_rms_gate": ARTIFACT_EMG_RMS, "min_eeg_std": MIN_EEG_STD},
            "events": evaluated, "scores": score(data, evaluated),
            "limitations": ["Generator hard-codes a 10 Hz amplitude change on imagery labels.",
                            "Calibration and testing share authored signal formulas, not independent subjects.",
                            "Artificial drift/rest and artifacts are chosen adversarial conditions, not physiology.",
                            "No human sessions, EEG device, independent dataset, statistical generalization, or OS actions."]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic motor-imagery EEG replay. Never drives an action.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--stop-at-s", type=float, default=None, help="simulated independent stop time")
    parser.add_argument("--drift-amplitude", type=float, default=None,
                        help="override the authored drift_rest mu-amplitude (default: authored value)")
    parser.add_argument("--sweep-drift", default=None, metavar="A,B,...",
                        help="comma-separated drift amplitudes; print the seed-count sweep instead of one run")
    parser.add_argument("--sweep-seeds", type=int, default=20, help="seeds 0..N-1 for --sweep-drift")
    args = parser.parse_args()
    if args.sweep_drift is not None:
        amps = [float(a) for a in args.sweep_drift.split(",")]
        print(json.dumps({"research_only": True, "synthetic": True,
                          "note": "Follows from the authored thresholds, not physiology.",
                          "sweep": drift_sweep(amps, range(args.sweep_seeds))}, indent=2, sort_keys=True))
        return 0
    print(json.dumps(run(args.seed, args.stop_at_s, args.drift_amplitude), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
