# ADR-v2-053 — Silent Lip-Reading Input (VSR)

**Status:** Accepted (2026-07-02) · Wave G
**Context links:** [[adr-v2-023-semg-silent-input]] (muscle vs video), [[adr-v2-006-gaze-routing]] (camera for targeting vs content), Modality Router, [[adr-011]]

## Context

Wave G research (#7) — dictate with no audible voice: a webcam reads your lips when you can't or
shouldn't phonate. A major accessibility + situational win (laryngectomy, aphonia, severe
dysphonia, vocal fatigue; also libraries/quiet offices/noisy factory floors where audio STT
fails). Hold-to-talk becomes hold-to-mouth. Anchors: Auto-AVSR (arXiv 2303.14307, 0.9% WER on
LRS3), VALLR (2503.21408, 2025 SOTA), GLip (2509.16031).

Distinct from the sEMG Command Layer (reads *muscle* signals via electrodes) — this reads *lip
video* from a commodity webcam, no hardware. Gaze uses the camera for *targeting*, not speech
content. It slots into the existing Modality Router as a new input.

## Decision

Add an opt-in **Silent Lip-Reading**: `[lipread] enabled=false, mouth_threshold=0.35`. The pure
core `mouth_aspect_ratio(top, bottom, left, right)` + `mouth_active(ratio, threshold)` gate when
the heavy VSR model runs (mouth open/moving) — dependency-free ratio math from face landmarks.
The VSR conformer/VALLR model + MediaPipe face mesh are lazy behind a `vsr` extra. OFF by default.

## Consequences

- A whole new silent input modality via commodity webcam; strong accessibility value.
- Pure aspect-ratio gate → fully testable with no camera; keeps the heavy model from running on
  a closed mouth.
- Privacy (ADR-011): frames processed in-RAM during the hold, never stored or transmitted.
- Caveat: VSR WER > audio → positioned as an alternative modality, off by default.
