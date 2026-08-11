# ADR-v2-028 — Multi-User Voiceprint Profiles

**Status:** Accepted (2026-07-02) · Wave E
**Context links:** [[adr-v2-018-voice-biometric-guard]] (distinct: binary gate vs N-way route), [[adr-012-self-improvement-loop]] (encrypted voiceprint), [[adr-011]]

## Context

The Wave E research (#5) proposes recognizing *who* is speaking on a shared machine and
loading that person's vocabulary/hotkey/cleanup profile — no manual switching. This reuses
YazSes's ECAPA/resemblyzer d-vector infra (`voiceprint/`, ADR-012). It is distinct from
Voice Guard (ADR-v2-018), which uses the voiceprint as a *binary injection gate* ("is it the
authorized user?"). Here the same embedding drives *N-way profile routing*.

## Decision

Add an opt-in **multi-profile router**: `[voiceprint] multi_profile=false,
profile_min_similarity=0.5`. The pure core `nearest_profile(embedding, profiles,
min_similarity)` returns the enrolled profile whose stored embedding is closest by cosine,
or `None` (→ keep the default profile) when the best match is below threshold or no profiles
are enrolled. The embedder stays lazy behind the `voiceprint` extra; profile embeddings live
only in the encrypted corpus (ADR-012). Dormant unless ≥2 profiles are enrolled. OFF by
default.

## Consequences

- Reuses the existing biometric embedding — no new plaintext storage; on-device (ADR-011/012).
- Pure nearest-profile decision → fully testable with no model.
- Distinct function from Voice Guard (routing vs gating) though it shares the d-vector.
- Caveat: a wrong match would load the wrong profile → conservative `profile_min_similarity`
  and a `None`→default fallback; off by default.
