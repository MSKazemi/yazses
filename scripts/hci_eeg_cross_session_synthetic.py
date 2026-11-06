#!/usr/bin/env python3
"""Research-only cross-session / participant-disjoint *synthetic* EEG harness.

Successor to the closed #696 stress replay (``scripts/hci_eeg_mi_synthetic.py``),
which explicitly did not test cross-session or participant-disjoint evaluation.
This harness exists to make *evaluation leakage* visible and testable, not to
decode anything:

* a pure, seeded generator of several synthetic "subjects", each with several
  "sessions" that differ by an authored gain, mu-amplitude drift and noise level;
* overlapping 1 s windows sliced from each continuous recording, with metadata
  (subject, session, sample span, label, block) so splits can be audited;
* subject-disjoint and session-disjoint splits plus a deliberately *leaky*
  random-window split kept as a negative control;
* a numpy-only bandpower + shrinkage-LDA classifier whose standardisation is
  fitted on training windows only, and a 1-nearest-neighbour classifier that is
  the canonical victim of window-overlap leakage;
* per-subject failure reporting, and a causal activation replay with a
  consecutive-window rule, a refractory period, false activations per hour of
  synthetic rest exposure and an exact Poisson upper bound.

Every number is produced by an authored generator. Nothing here is human EEG,
nothing here is evidence about brain decoding, and nothing here can control
YazSes (ADR-030: no production EEG interface).

Run: python scripts/hci_eeg_cross_session_synthetic.py --seed 0
Needs only numpy (already a base dependency). No downloads, devices or network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

FS = 128
WINDOW_S = 1.0
HOP_S = 0.25
BLOCK_S = 4.0
BLOCKS_PER_SESSION = 12  # alternating rest / imagery, rest first
AR_RHO = 0.90
MU_BAND = (8.0, 13.0)
BETA_BAND = (16.0, 26.0)
NON_RESPONDER_SUPPRESSION = 0.97  # authored: imagery barely changes mu power
FAIL_BALANCED_ACCURACY = 0.60
THRESHOLD = 0.70
CONSECUTIVE = 2
REFRACTORY_S = 2.0
LDA_SHRINKAGE = 0.10
STD_FLOOR = 1e-6
LEAKY_FOLDS = 3
REST, IMAGERY = 0, 1
FEATURE_NAMES = ("log_mu_c3", "log_mu_c4", "log_beta_c3", "log_beta_c4")

NOTICE = (
    "SYNTHETIC research harness: every number comes from an authored generator, not human EEG. "
    "NOT proof of brain decoding, NOT a validated model; nothing here can control YazSes."
)
LIMITATIONS = (
    "No human participants, no recorded EEG and no device: subjects and sessions are parameter draws.",
    "Session drift is an authored gain / mu-amplitude / noise change; real cross-session shifts "
    "(electrode placement, impedance, fatigue, medication, posture) are not modelled.",
    "Two channels and a single 10 Hz rhythm; no artifacts, no unknown mental states, no head motion.",
    "False activations per hour are extrapolated from minutes of synthetic rest exposure; "
    "read the exposure and the Poisson upper bound, not the point rate.",
    "The non-responder subject is authored; its failure demonstrates the report, not a prevalence.",
    "Leaky-split inflation depends on the authored within-block correlation and window overlap.",
)


@dataclass(frozen=True)
class Dataset:
    """Windows plus the metadata needed to audit a split."""

    x: np.ndarray  # (n, 2, window_samples)
    subject: np.ndarray
    session: np.ndarray
    start: np.ndarray  # sample index within its (subject, session) recording, inclusive
    stop: np.ndarray  # exclusive
    label: np.ndarray
    block: np.ndarray  # block index within its recording
    subject_params: tuple[dict[str, float], ...]
    session_params: tuple[dict[str, float], ...]
    non_responder: int

    def __len__(self) -> int:
        return int(self.label.shape[0])


@dataclass(frozen=True)
class Standardizer:
    mean: np.ndarray
    scale: np.ndarray

    def transform(self, features: np.ndarray) -> np.ndarray:
        return (features - self.mean) / self.scale


@dataclass(frozen=True)
class LDA:
    w: np.ndarray
    b: float

    def decision(self, features: np.ndarray) -> np.ndarray:
        return features @ self.w + self.b

    def proba(self, features: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(self.decision(features), -50.0, 50.0)))


def _samples(seconds: float) -> int:
    return int(round(seconds * FS))


def _ar1(rng: np.random.Generator, n: int, sd: float) -> np.ndarray:
    """Stationary AR(1) noise with marginal standard deviation ``sd``."""
    innov = rng.normal(0.0, sd * math.sqrt(1.0 - AR_RHO**2), size=n)
    out = np.empty(n)
    prev = rng.normal(0.0, sd)
    for i in range(n):
        prev = AR_RHO * prev + innov[i]
        out[i] = prev
    return out


def generate(seed: int = 0, n_subjects: int = 6, n_sessions: int = 3) -> Dataset:
    """Pure, seeded multi-subject, multi-session synthetic windows.

    The last subject is an authored non-responder. Windows never straddle a
    block boundary, so each window has exactly one label; windows inside a block
    overlap by ``1 - HOP_S / WINDOW_S``, which is what a leaky split exploits.
    """
    if n_subjects < 2 or n_sessions < 2:
        raise ValueError("need at least 2 subjects and 2 sessions for disjoint splits")
    rng = np.random.default_rng(seed)
    win, hop, blk = _samples(WINDOW_S), _samples(HOP_S), _samples(BLOCK_S)
    n_samples = blk * BLOCKS_PER_SESSION
    t = np.arange(n_samples) / FS
    labels = np.array([REST if b % 2 == 0 else IMAGERY for b in range(BLOCKS_PER_SESSION)])
    non_responder = n_subjects - 1
    xs: list[np.ndarray] = []
    meta: dict[str, list[int]] = {k: [] for k in ("subject", "session", "start", "stop", "label", "block")}
    subject_params: list[dict[str, float]] = []
    session_params: list[dict[str, float]] = []
    for s in range(n_subjects):
        base_amp = float(np.exp(rng.normal(0.0, 0.25)))
        mu_freq = float(np.clip(10.0 + rng.normal(0.0, 0.6), 9.0, 11.5))
        drawn = float(rng.uniform(0.35, 0.60))
        supp = NON_RESPONDER_SUPPRESSION if s == non_responder else drawn
        subject_params.append({"subject": s, "base_amp": base_amp, "mu_hz": mu_freq, "suppression": supp})
        for k in range(n_sessions):
            gain = float(np.exp(rng.normal(0.0, 0.35)))
            session_mu = float(np.exp(rng.normal(0.0, 0.20)))
            noise_sd = float(0.5 * np.exp(rng.normal(0.0, 0.20)))
            jitter = np.exp(rng.normal(0.0, 0.25, size=BLOCKS_PER_SESSION))
            session_params.append({"subject": s, "session": k, "gain": gain,
                                   "session_mu": session_mu, "noise_sd": noise_sd})
            amp_c3 = np.empty(n_samples)
            amp_c4 = np.empty(n_samples)
            for b in range(BLOCKS_PER_SESSION):
                sl = slice(b * blk, (b + 1) * blk)
                a = base_amp * session_mu * float(jitter[b])
                if labels[b] == IMAGERY:
                    amp_c3[sl] = a * supp
                    amp_c4[sl] = a * (1.0 - 0.3 * (1.0 - supp))
                else:
                    amp_c3[sl] = a
                    amp_c4[sl] = a
            phase = rng.uniform(0.0, 2.0 * math.pi, size=2)
            c3 = amp_c3 * np.sin(2.0 * math.pi * mu_freq * t + phase[0]) + _ar1(rng, n_samples, noise_sd)
            c4 = amp_c4 * np.sin(2.0 * math.pi * mu_freq * t + phase[1]) + _ar1(rng, n_samples, noise_sd)
            sig = gain * np.stack([c3, c4])
            for b in range(BLOCKS_PER_SESSION):
                b0 = b * blk
                for w0 in range(b0, b0 + blk - win + 1, hop):
                    xs.append(sig[:, w0:w0 + win])
                    for key, val in (("subject", s), ("session", k), ("start", w0),
                                     ("stop", w0 + win), ("label", int(labels[b])), ("block", b)):
                        meta[key].append(val)
    arr = {k: np.asarray(v, dtype=np.int64) for k, v in meta.items()}
    return Dataset(x=np.stack(xs), subject=arr["subject"], session=arr["session"], start=arr["start"],
                   stop=arr["stop"], label=arr["label"], block=arr["block"],
                   subject_params=tuple(subject_params), session_params=tuple(session_params),
                   non_responder=non_responder)


def bandpower_features(x: np.ndarray) -> np.ndarray:
    """Log mean Hann-windowed power in the mu and beta bands, per channel -> (n, 4)."""
    n = x.shape[-1]
    centred = x - x.mean(axis=-1, keepdims=True)
    spec = np.abs(np.fft.rfft(centred * np.hanning(n), axis=-1)) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / FS)
    bands = []
    for lo, hi in (MU_BAND, BETA_BAND):
        mask = (freqs >= lo) & (freqs <= hi)
        bands.append(np.log(spec[..., mask].mean(axis=-1) + 1e-12))
    return np.concatenate(bands, axis=-1)


def fit_standardizer(train_features: np.ndarray) -> Standardizer:
    """Fit on training rows only; callers must never pass test rows here."""
    return Standardizer(mean=train_features.mean(axis=0),
                        scale=np.maximum(train_features.std(axis=0), STD_FLOOR))


def fit_lda(features: np.ndarray, y: np.ndarray, shrinkage: float = LDA_SHRINKAGE) -> LDA:
    """Two-class LDA with trace shrinkage; posterior via the equal-covariance logit."""
    f0, f1 = features[y == REST], features[y == IMAGERY]
    if len(f0) == 0 or len(f1) == 0:
        raise ValueError("both classes must be present in the training split")
    mu0, mu1 = f0.mean(axis=0), f1.mean(axis=0)
    centred = np.concatenate([f0 - mu0, f1 - mu1])
    cov = centred.T @ centred / max(len(features) - 2, 1)
    d = cov.shape[0]
    cov = (1.0 - shrinkage) * cov + shrinkage * float(np.trace(cov)) / d * np.eye(d)
    w = np.linalg.solve(cov, mu1 - mu0)
    b = -0.5 * float((mu0 + mu1) @ w) + math.log(len(f1) / len(f0))
    return LDA(w=w, b=b)


def predict_1nn(train_f: np.ndarray, train_y: np.ndarray, test_f: np.ndarray) -> np.ndarray:
    d = (test_f**2).sum(axis=1)[:, None] + (train_f**2).sum(axis=1)[None, :] - 2.0 * test_f @ train_f.T
    return train_y[np.argmin(d, axis=1)]


Fold = tuple[str, np.ndarray, np.ndarray]


def split_by_subject(ds: Dataset) -> list[Fold]:
    """Leave-one-subject-out: no subject's windows in both train and test."""
    idx = np.arange(len(ds))
    return [(f"subject={s}", idx[ds.subject != s], idx[ds.subject == s]) for s in np.unique(ds.subject)]


def split_by_session(ds: Dataset) -> list[Fold]:
    """Leave-one-session-index-out: train on other sessions of every subject."""
    idx = np.arange(len(ds))
    return [(f"session={k}", idx[ds.session != k], idx[ds.session == k]) for k in np.unique(ds.session)]


def split_leaky_windows(ds: Dataset, n_folds: int = LEAKY_FOLDS, seed: int = 0) -> list[Fold]:
    """NEGATIVE CONTROL: random window-level folds. Overlapping windows of one
    continuous recording land on both sides; never use this for a real estimate."""
    perm = np.random.default_rng(seed).permutation(len(ds))
    folds = []
    for i, test in enumerate(np.array_split(perm, n_folds)):
        test = np.sort(test)
        train = np.setdiff1d(perm, test)
        folds.append((f"leaky_fold={i}", train, test))
    return folds


def overlapping_window_pairs(ds: Dataset, train_idx: np.ndarray, test_idx: np.ndarray) -> int:
    """Count (train, test) window pairs that share any sample of the same recording.

    A shared index counts too (a window overlaps itself).
    """
    keys = ds.subject * 1_000_000 + ds.session
    total = 0
    for key in np.unique(keys[test_idx]):
        a = train_idx[keys[train_idx] == key]
        b = test_idx[keys[test_idx] == key]
        if a.size == 0:
            continue
        ov = (ds.start[a][:, None] < ds.stop[b][None, :]) & (ds.start[b][None, :] < ds.stop[a][:, None])
        total += int(ov.sum())
    return total


def balanced_accuracy(y: np.ndarray, pred: np.ndarray) -> float | None:
    recalls = [float((pred[y == c] == c).mean()) for c in (REST, IMAGERY) if (y == c).any()]
    return float(np.mean(recalls)) if recalls else None


def evaluate(ds: Dataset, features: np.ndarray, folds: Sequence[Fold], classifier: str) -> dict[str, Any]:
    """Run every fold; standardisation and model are fitted on that fold's train rows only."""
    if classifier not in ("lda", "nearest_neighbour"):
        raise ValueError(f"unknown classifier {classifier!r}")
    pred = np.full(len(ds), -1, dtype=np.int64)
    proba = np.full(len(ds), np.nan)
    overlap = 0
    for _, train, test in folds:
        overlap += overlapping_window_pairs(ds, train, test)
        scaler = fit_standardizer(features[train])
        ftr, fte = scaler.transform(features[train]), scaler.transform(features[test])
        if classifier == "lda":
            p = fit_lda(ftr, ds.label[train]).proba(fte)
            proba[test] = p
            pred[test] = (p >= 0.5).astype(np.int64)
        else:
            pred[test] = predict_1nn(ftr, ds.label[train], fte)
            proba[test] = pred[test].astype(float)
    tested = pred >= 0
    per_subject = {}
    for s in np.unique(ds.subject):
        m = tested & (ds.subject == s)
        per_subject[int(s)] = balanced_accuracy(ds.label[m], pred[m])
    failed = sorted(s for s, acc in per_subject.items() if acc is not None and acc < FAIL_BALANCED_ACCURACY)
    return {
        "balanced_accuracy": balanced_accuracy(ds.label[tested], pred[tested]),
        "per_subject_balanced_accuracy": per_subject,
        "failed_subjects": failed,
        "overlapping_train_test_window_pairs": overlap,
        "tested_windows": int(tested.sum()),
        "_proba": proba,
    }


def replay_activations(times: Sequence[float], proba: Sequence[float], threshold: float = THRESHOLD,
                       consecutive: int = CONSECUTIVE, refractory_s: float = REFRACTORY_S) -> list[int]:
    """Causal rule: fire after ``consecutive`` windows at/above ``threshold``,
    never within ``refractory_s`` of the previous fire. The run counter resets
    only on a fire or a below-threshold window. Returns fired window indices."""
    if consecutive < 1 or refractory_s < 0:
        raise ValueError("consecutive must be >= 1 and refractory_s >= 0")
    fires: list[int] = []
    run = 0
    last: float | None = None
    prev_t = -math.inf
    for i, (t, p) in enumerate(zip(times, proba, strict=True)):
        if t < prev_t:
            raise ValueError("times must be non-decreasing (causal replay)")
        prev_t = t
        run = run + 1 if p >= threshold else 0
        if run >= consecutive and (last is None or t - last >= refractory_s - 1e-9):
            fires.append(i)
            last = t
            run = 0
    return fires


def poisson_upper_bound(k: int, confidence: float = 0.95) -> float:
    """Exact one-sided upper confidence bound on a Poisson mean after ``k`` events."""
    if k < 0 or not 0.0 < confidence < 1.0:
        raise ValueError("k must be >= 0 and 0 < confidence < 1")
    alpha = 1.0 - confidence

    def cdf(lam: float) -> float:
        term = math.exp(-lam)
        total = term
        for i in range(1, k + 1):
            term *= lam / i
            total += term
        return total

    lo, hi = 0.0, 10.0 * (k + 1)
    while cdf(hi) > alpha:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if cdf(mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def activation_metrics(ds: Dataset, proba: np.ndarray) -> dict[str, Any]:
    """Replay each held-out recording in time order; a fire on a rest window is false."""
    false_total = hits = imagery_blocks = 0
    rest_exposure_s = 0.0
    per_subject: dict[int, dict[str, int]] = {}
    for s in np.unique(ds.subject):
        row = per_subject.setdefault(int(s), {"false_activations": 0, "hits": 0, "imagery_blocks": 0})
        for k in np.unique(ds.session[ds.subject == s]):
            m = np.flatnonzero((ds.subject == s) & (ds.session == k) & ~np.isnan(proba))
            if m.size == 0:
                continue
            m = m[np.argsort(ds.start[m], kind="stable")]
            fires = m[replay_activations((ds.stop[m] / FS).tolist(), proba[m].tolist())]
            n_false = int((ds.label[fires] == REST).sum())
            blocks = np.unique(ds.block[m])
            img_blocks = [b for b in blocks if ds.label[m][ds.block[m] == b][0] == IMAGERY]
            hit = sum(1 for b in img_blocks if (ds.block[fires] == b).any())
            rest_exposure_s += BLOCK_S * (len(blocks) - len(img_blocks))
            row["false_activations"] += n_false
            row["hits"] += hit
            row["imagery_blocks"] += len(img_blocks)
            false_total += n_false
            hits += hit
            imagery_blocks += len(img_blocks)
    def per_hour(count: float) -> float | None:
        return count * 3600.0 / rest_exposure_s if rest_exposure_s > 0 else None

    return {
        "false_activations": false_total,
        "synthetic_rest_exposure_s": rest_exposure_s,
        "false_activations_per_hour": per_hour(false_total),
        "false_activations_per_hour_upper95": per_hour(poisson_upper_bound(false_total)),
        "hits": hits,
        "imagery_blocks": imagery_blocks,
        "per_subject": per_subject,
        "rule": {"threshold": THRESHOLD, "consecutive": CONSECUTIVE, "refractory_s": REFRACTORY_S},
        "note": "Synthetic exposure is minutes, not hours; read the upper bound, not the point rate.",
    }


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return round(float(value), 6)
    if isinstance(value, np.integer):
        return int(value)
    return value


def run(seed: int = 0, n_subjects: int = 6, n_sessions: int = 3) -> dict[str, Any]:
    ds = generate(seed, n_subjects, n_sessions)
    feats = bandpower_features(ds.x)
    schemes = {
        "subject_disjoint": split_by_subject(ds),
        "session_disjoint": split_by_session(ds),
        "leaky_window_split": split_leaky_windows(ds, seed=seed),
    }
    results: dict[str, Any] = {}
    for name, folds in schemes.items():
        results[name] = {clf: evaluate(ds, feats, folds, clf) for clf in ("lda", "nearest_neighbour")}
        results[name]["negative_control"] = name == "leaky_window_split"
    inflation = {
        clf: results["leaky_window_split"][clf]["balanced_accuracy"]
        - results["session_disjoint"][clf]["balanced_accuracy"]
        for clf in ("lda", "nearest_neighbour")
    }
    report = {
        "synthetic": True,
        "research_only": True,
        "notice": NOTICE,
        "limitations": list(LIMITATIONS),
        "predecessor": "#696 (closed 2026-11-03); scripts/hci_eeg_mi_synthetic.py",
        "config": {"fs": FS, "window_s": WINDOW_S, "hop_s": HOP_S, "block_s": BLOCK_S,
                   "blocks_per_session": BLOCKS_PER_SESSION, "features": list(FEATURE_NAMES),
                   "lda_shrinkage": LDA_SHRINKAGE, "fail_balanced_accuracy": FAIL_BALANCED_ACCURACY},
        "generator": {"seed": seed, "subjects": n_subjects, "sessions": n_sessions, "windows": len(ds),
                      "non_responder_subject": ds.non_responder,
                      "subject_params": list(ds.subject_params), "session_params": list(ds.session_params)},
        "schemes": results,
        "leak_inflation_vs_session_disjoint": inflation,
        "continuous_replay_session_disjoint_lda": activation_metrics(
            ds, results["session_disjoint"]["lda"]["_proba"]),
        "continuous_replay_subject_disjoint_lda": activation_metrics(
            ds, results["subject_disjoint"]["lda"]["_proba"]),
    }
    report = _clean(report)
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--subjects", type=int, default=6)
    parser.add_argument("--sessions", type=int, default=3)
    parser.add_argument("--out", type=Path, default=None, help="write the JSON report here (UTF-8)")
    args = parser.parse_args(argv)
    text = json.dumps(run(args.seed, args.subjects, args.sessions), indent=2, sort_keys=True) + "\n"
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
