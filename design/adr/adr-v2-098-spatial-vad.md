# ADR-v2-098 — Beam-Steered Spatial VAD (2-mic direction-of-arrival gate)

**Status:** Accepted (2026-07-02) · Wave L
**Context links:** cocktail (identity gate), denoise (spectral), audioguard (event), [[adr-011]]

## Context

Wave L research (#3) — Cocktail Filter gates by **speaker-embedding identity** (needs enrollment,
unreliable on <0.5 s windows per our live-testing memo); Noise Suppression and the Ambient
Audio-Event Guard are spectral/event-based. A **spatial** (geometric) gate — estimate the sound's
direction of arrival from a 2-mic array and drop anything not from the user's seat — is orthogonal,
enrollment-free, cheap, and reverberation-robust, and it composes with Cocktail Filter as an
independent second gate. Anchor: Knapp & Carter GCC-PHAT (classic TDOA); real-time on-device DoA
(PMC8136617) — GCC-PHAT runs real-time on built-in mics.

## Decision

Add an opt-in **Beam-Steered Spatial VAD**: `[spatialvad] enabled=false, target_angle=0.0,
tolerance_deg=35.0, mic_distance_m=0.14`. Pure cores in `spatialvad/beam.py`: `gcc_phat(sig_l,
sig_r, fs, max_tau)` → the inter-mic time delay via a phase-transform FFT cross-correlation (pure
numpy, no model), `tdoa_to_angle(tau, mic_dist_m)` → the arrival angle, and `spatial_gate(angle,
target_angle, tol)` → keep/drop. Stereo capture is the only extra. OFF by default.

## Consequences

- Enrollment-free geometric rejection of off-axis interferers (TV, colleague, passer-by).
- Pure numpy FFT → fully testable with synthetic delayed signals; composes with Cocktail Filter.
- Privacy (ADR-011): local audio only; nothing stored or sent.
- Caveat: needs a 2-mic/stereo source and a rough mic spacing; a single built-in mic can't use it;
  off by default.
