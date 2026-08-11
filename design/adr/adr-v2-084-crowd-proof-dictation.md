# ADR-v2-084 — Crowd-Proof Dictation (target-speaker extraction)

**Status:** Accepted (2026-07-02) · Wave J
**Context links:** [[adr-v2-031-cocktail-filter]] (window gating vs continuous reconstruction), [[adr-v2-018-noise-suppression]] (non-speech vs overlapping speech), [[adr-012-self-improvement-loop]], [[adr-011]]

## Context

Wave J research (#4) — continuously reconstruct the enrolled user's voice out of overlapping
babble *before* STT, so dictation survives an open-plan office or café. Fixes the exact failure
mode that made the window-gating Cocktail Filter default-off (ECAPA false-rejects the user's own
voice on sub-second windows). Distinct from Noise Suppression (non-speech) and the Cocktail Filter
(window gating) — this is continuous signal *reconstruction* via a different mechanism, reusing the
existing voiceprint enrollment. Anchors: LGTSE (arXiv 2508.19583, lightweight TSE, 2025),
SpeakerBeam-SS real-time TSE (arXiv 2407.01857).

## Decision

Add an opt-in **Crowd-Proof Dictation**: `[crowdproof] enabled=false, threshold=0.5`. The pure
numpy core is the framing/reconstruction plumbing: `frame_signal(signal, frame_len, hop)`,
`overlap_add(frames, hop)` (Hann-windowed, normalized), and `apply_target_mask(frames, scores,
threshold, floor)` (attenuate frames whose target-speaker score is below threshold). The Conv-
TasNet/state-space TSE model that produces per-frame scores is deferred behind a `crowdproof`
extra. OFF by default.

## Consequences

- A different mechanism than the Cocktail Filter (continuous reconstruction vs sub-second gating).
- Pure numpy plumbing is testable without a model; the TSE net is the deferred tier.
- Privacy (ADR-011/012): the enrolled embedding stays in the encrypted corpus; audio in-RAM.
- Caveat: quality depends on the deferred TSE model; the mask/overlap-add core is off by default.
