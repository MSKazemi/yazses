"""VAD gate accuracy: separating real speech from quiet-room / silent buffers.

YazSes' gate (yazses.audio.vad_calibrated.is_silent_calibrated) is a deliberately
simple RMS threshold: it discards a recorded buffer when mean(|audio|) < vad_threshold.
This measures how cleanly the default threshold separates:
  - POSITIVES: real speech buffers (LibriSpeech test-clean clips) -> should be KEPT
  - NEGATIVES: silent / quiet-room buffers (digital silence + low-level Gaussian noise
    at realistic quiet-room RMS below the threshold) -> should be GATED OUT

This is a separability check at the operating threshold, not a frame-level VAD benchmark
on a diarized corpus (the gate is not a neural VAD; see the paper's threats-to-validity).
"""
from __future__ import annotations

import numpy as np

from _common import load_audio, librispeech_subset, percentile

SAMPLE_RATE = 16000


def run(n_speech: int) -> dict:
    from yazses.audio.vad_calibrated import is_silent_calibrated
    from yazses.config import AccessibilityConfig

    cfg = AccessibilityConfig()
    threshold = cfg.vad_threshold
    rng = np.random.default_rng(0)

    # --- Positives: real speech clips ---
    subset = librispeech_subset(n_speech)
    speech_rms = []
    speech_kept = 0
    for _, flac, _, _ in subset:
        audio = load_audio(flac)
        speech_rms.append(float(np.abs(audio).mean()))
        if not is_silent_calibrated(audio, cfg):
            speech_kept += 1
    n_pos = len(subset)

    # --- Negatives: silent / quiet-room buffers (1 s each) ---
    negatives = []
    negatives.append(np.zeros(SAMPLE_RATE, dtype=np.float32))  # digital silence
    # Gaussian noise at RMS levels spanning a quiet room, all below the threshold.
    for rms in (threshold * 0.1, threshold * 0.25, threshold * 0.5, threshold * 0.75):
        noise = rng.standard_normal(SAMPLE_RATE).astype(np.float32)
        noise *= rms / float(np.abs(noise).mean())
        negatives.append(noise)
    neg_gated = sum(1 for a in negatives if is_silent_calibrated(a, cfg))
    n_neg = len(negatives)

    speech_recall = 100 * speech_kept / n_pos
    silence_rejection = 100 * neg_gated / n_neg
    balanced_acc = (speech_recall + silence_rejection) / 2

    out = {
        "config": {
            "vad_threshold": threshold,
            "metric": "mean(|audio|) < threshold => silent (gated out)",
            "n_speech_clips": n_pos,
            "n_silence_clips": n_neg,
            "dataset_positives": "LibriSpeech test-clean",
            "negatives": "digital silence + Gaussian noise at 0.1/0.25/0.5/0.75x threshold",
        },
        "results": {
            "speech_detection_rate_pct": round(speech_recall, 2),
            "silence_rejection_rate_pct": round(silence_rejection, 2),
            "balanced_accuracy_pct": round(balanced_acc, 2),
            "speech_rms_median": round(percentile(speech_rms, 50), 5),
            "speech_rms_p05": round(percentile(speech_rms, 5), 5),
            "speech_rms_to_threshold_margin_x": round(
                percentile(speech_rms, 50) / threshold, 1
            ),
        },
    }
    print(
        f"[vad] speech-detection={out['results']['speech_detection_rate_pct']}%  "
        f"silence-rejection={out['results']['silence_rejection_rate_pct']}%  "
        f"balanced={out['results']['balanced_accuracy_pct']}%  "
        f"(speech RMS median {out['results']['speech_rms_median']} vs threshold {threshold})",
        flush=True,
    )
    return out


if __name__ == "__main__":
    import sys

    from _common import write_result

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    write_result("vad", run(n))
