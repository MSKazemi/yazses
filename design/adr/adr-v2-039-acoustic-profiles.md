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

## Amendment (2026-10-15) — PROPOSED, for the owner's review

**Status of this amendment: proposed, not accepted.** It records what was built when the feature
was wired (issue #164); it changes the decision above and needs the owner's sign-off.

**Why the decision above could not be wired as written.** There is no scene tagger (the
YAMNet/CLAP model behind the `acoustic` extra does not exist in the tree), and `policy_for`'s
absolute gates (0.010-0.035) are 6-10x above the real level of the owner's microphone (mean |x|
of 0.003-0.005 at full gain). Applying them would have classified all speech as silence.

**Amended decision.**

- The scene set shrinks to **two: `quiet` and `noisy`**. `cafe`, `car` and `meeting` are retired:
  nothing can tell them apart without a model, and none would change what the gate does.
- The classifier is **pure and computed from the speech burst's own audio**:
  `acoustic/scene.py` takes per-frame levels (mean |x| per 20 ms frame, the quantity the silence
  gate compares). The *floor* is the mean of the quietest fifth of the frames; the scene is `noisy`
  when the floor reaches half of the **configured** `vad_threshold`. No absolute level appears
  anywhere, so the same code fits any microphone.
- The gate adjustment is **floor-relative and clamped**: in a noisy scene, a burst whose loud end
  is under 2.5 x its floor (flat noise, no speech-like dynamics) is held to 1.5 x its floor,
  never below the configured gate, never above 1.5 x the configured gate, never above 2 x the
  floor. Any burst with speech-like dynamics keeps the configured gate unchanged. Consequence: a
  burst the user's own gate keeps is lost only if it is flat *and* under 1.5 x its own floor
  (signal-to-noise below about 3.5 dB), which no transcriber could use anyway.
- **In-memory override only.** `config.toml` and `vad_threshold` are never written (the
  auto-retune of `AdaptiveThreshold` is explicitly kept out of it), and a flat-noise discard does
  not count toward the silent-clip streak. It is visible in `yazses status` (`room:` line).
- `should_switch` hysteresis is kept (`min_stable`, default 3 consecutive bursts); the default
  scene is `quiet`, which changes nothing. Whisper Mode (ADR-v2-012) wins: while it lowers the
  gate the profile stands down.
- **Deferred, unchanged:** the YAMNet/CLAP tagger (`acoustic` extra) and denoise switching
  (Noise Suppression, ADR-v2-015, stays a manual on/off). Both are separate decisions.
- Rule 9 (ADR-021): the only user-visible effect is the existing "nothing typed" cue on a hold
  that contained nothing but room noise. It holds on a specific, checkable signal (the burst is
  flat and near the room floor) and releases by speaking.

**Not measured.** The three constants (0.5, 1.5, 2.5) are engineering clamps validated on
synthetic rooms and on the owner's microphone *range*, not on recorded rooms. How often the noisy
scene fires in practice is unknown; a recording campaign would settle it.
