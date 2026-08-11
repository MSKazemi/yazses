# ADR-v2-039 — Acoustic Context Profiles

**Status:** Accepted (2026-07-02) · Wave F
**Context links:** [[adr-v2-015-noise-suppression]], [[adr-v2-012-accessibility-continuum]], [[adr-011]]

## Context

The Wave F research (#5) proposes auto-detecting the acoustic scene (quiet room / café / car /
meeting) and auto-switching VAD threshold, injector, and noise-suppression. Anchors: YAMNet
(MobileNet-v1 edge classifier), DCASE-2024 low-complexity acoustic-scene-classification (arXiv
2405.10018, 2410.20775, 2512.13905), CLAP. Nothing in the prior 38 adapts behavior to the
*environment*; Noise Suppression (ADR-v2-015) is on-or-off, not scene-gated.

## Decision

Add an opt-in **Acoustic Context Profiles**: `[acoustic_profiles] enabled=false, min_stable`.
Two pure cores: `policy_for(scene)` maps a scene label to a `ScenePolicy` (recommended VAD
threshold + denoise on/off), and `should_switch(new, current, stable_count, min_stable)`
applies hysteresis so a transient sound doesn't thrash the profile. The YAMNet/CLAP scene
tagger is lazy behind an `acoustic` extra and classifies ambient audio in RAM to a coarse
label. OFF by default.

## Consequences

- First environment-adaptive behavior; composes with Noise Suppression + the VAD gate.
- Pure policy + hysteresis → fully testable; the tagger stays deferred.
- Privacy (ADR-011): coarse label from in-RAM audio, no audio stored (label optional in corpus).
- Caveat: misclassification could pick the wrong profile → hysteresis (`min_stable`) + conservative
  default (`quiet`); off by default.
