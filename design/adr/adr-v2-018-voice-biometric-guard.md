# ADR-v2-018 — Continuous Voice-Biometric Gate + Anti-Spoof

**Status:** Accepted (2026-07-02) · Wave D (experimental)
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-012-self-improvement-loop]] (encrypted voiceprint), [[adr-011]]

## Context

The Wave D research (#5) notes a security posture no dictation tool has: only drive the
keyboard when the *live* speaker matches the enrolled user, and reject synthetic/replayed
audio (a nearby TTS speaker, a recording, or someone else at an unlocked machine). YazSes
already stores an enrolled speaker embedding in the encrypted corpus (`voiceprint/`,
biometric, never leaves the machine — ADR-012). Anchors: ASVspoof 5 countermeasures
(arXiv 2601.03944), SSL spoof detectors (AASIST/wav2vec2, arXiv 2502.03559).

## Decision

Add an opt-in **admission gate**: a pure decision `admit(similarity, spoof_score, config)
→ (admit, reason)` that injects a burst only when the speaker-match similarity clears
`match_threshold` **and** the anti-spoof score is under `spoof_threshold`. Config
`[voiceguard] enabled=false, match_threshold, spoof_threshold, fail_open=true`. The ECAPA
match (reuse enrolled d-vector) and the anti-spoof model are lazy behind a `voiceguard`
extra; when a score is unavailable, `fail_open` (default true) admits to avoid locking the
user out. **EXPERIMENTAL**, off by default, `--force` to enable.

## Consequences

- Reuses the enrolled voiceprint — no new biometric storage; on-device only (ADR-011/012).
- `fail_open` default avoids the false-reject lockout the Cocktail Filter suffered.
- Pure decision layer → fully testable; the scoring models stay opt-in.
- Caveat: false-reject risk for the legitimate user (colds, mic changes) → off by default,
  conservative thresholds, clear override.
