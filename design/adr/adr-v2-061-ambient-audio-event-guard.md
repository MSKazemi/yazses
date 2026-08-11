# ADR-v2-061 — Ambient Audio-Event Guard

**Status:** Accepted (2026-07-02) · Wave H
**Context links:** [[adr-v2-033-wake-word]] (activation vs environmental awareness), [[adr-011]]

## Context

Wave H research (#2) — auto-pause dictation (and optionally alert) when an interrupting
real-world sound is heard: doorbell, phone ring, alarm, your name, a baby cry. So you neither
dictate over an interruption nor miss it (a Deaf/HoH awareness win too). Anchors: lightweight
SELD for wearables (arXiv 2509.14650), E2PANNs real-time emergency-sound detection (2506.23437).

Distinct from Wake-Word (an *activation* phrase) — this is *environmental awareness /
interruption handling*, the inverse.

## Decision

Add an opt-in **Ambient Audio-Event Guard**: `[audioguard] enabled=false, cooldown_frames=30`.
Two pure cores: `event_policy(label)` maps a detected sound-event label to a policy
(`pause` | `notify` | `ignore`), and `EventDebouncer` fires a policy once then suppresses repeats
during a cooldown (so a ringing phone doesn't retrigger every frame). Both dependency-free. The
PANNs/SELD sound-event classifier is lazy behind a `soundawareness` extra. OFF by default.

## Consequences

- First environmental-awareness feature; strong accessibility value.
- Pure policy map + debounce → fully testable with no audio.
- Privacy (ADR-011): frames classified in-RAM, never stored/sent (mirrors the gaze pattern).
- Caveat: sound classifiers misfire → conservative default (`ignore` unknown labels) + cooldown;
  off by default.
