# ADR-v2-023 — Silent-Speech / Subvocal (sEMG) Input

**Status:** Accepted — design only, implementation deferred (2026-07-02) · Wave D (research tier)
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-004-emg-backend]] (existing EMGBackend/YESP), [[adr-011]]

## Context

The Wave D research (#9) proposes dictating by *mouthing words silently* — surface EMG
(sEMG) on the face/neck decodes articulation without audible speech, for privacy, noisy
environments, and users who cannot phonate. Anchors: microneedle SSI reaching 8.5% WER
(ScienceDirect S2666053925001249), emg2speech (arXiv 2510.23969). YazSes already has an
`EMGBackend` (ADR-004) that reads squeeze events over USB serial (YESP) — a natural
hardware seam to extend from single-gesture triggering to continuous articulation decode.

## Decision

**Design accepted; implementation deferred until hardware is in hand.** The intended shape,
consistent with the v2 pattern: a `[silentspeech]` config (`enabled=false`, `port`,
`baud_rate`, `model_path`), an experimental feature (refused by `features enable` without
`--force`), and a decode model lazy behind a `silentspeech` extra. The *pure* seam that can
ship first (a future iteration) is the articulation→text post-processing (the same
`clean_text`/disfluency chain the audio path uses), reusing the existing EMG serial reader.
The neural sEMG→text decoder needs a real electrode array + labelled data to build and
verify, so no code lands now — only this ADR and the research record.

## Consequences

- Extends the existing EMGBackend rather than adding a parallel hardware stack.
- On-device only (ADR-011); no audio leaves the machine (there is none).
- Honest scoping: accuracy + hardware are the bottleneck → experimental, `--force`, deferred.
- Caveat: silent articulation lacks voicing cues → expect higher WER than audible speech;
  the held-out validation gate (ADR-014) applies to any personalization here.
