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

## Wiring (2026-10-21, #164)

What is reachable, and what is not:

- **Hook point.** `Daemon._voiceguard_refusal`, called once per burst after the
  speech-presence check and before decode. It judges the burst *as heard* -- before
  Cocktail Filter removes non-target frames, which would raise another speaker's
  score. It embeds the *whole* burst with the speaker
  embedder `[voiceprint]` already builds, takes the cosine similarity to the enrolled
  voiceprint, and calls `admit(similarity, None, config)` through
  `voiceguard/admission.py`. A refused burst is never decoded, so no text from it exists
  to type; the log carries the reason (a similarity score), never words, and the event
  records `discard_reason = "voiceguard_rejected"` (classified as doubting capture). The
  learning corpus keeps that event without its audio, even with `[learning]
  capture_audio` on: a refused burst is most likely a third party's voice, a category
  ADR-019 says may never be kept. With `[streaming]` on, partials already typed during
  the hold reach the window and are erased by backspaces on refusal.
- **No anti-spoof producer exists.** The spoof score is always `None`. With the default
  `fail_open = true` the guard is a speaker match only; a recording or synthesis of the
  user's voice is admitted. `yazses doctor` says so on the Voice Guard row.
- **It refuses to run rather than misjudge every burst.** Enabled with `[voiceprint]` off,
  with no embedder, with no enrolled voiceprint, or with `fail_open = false` (which would
  refuse everything for want of a spoof score nobody produces), the guard lets bursts
  through and says why: once in the daemon log at start, and as a WARN row in
  `yazses doctor`. The same applies to a voiceprint file that exists but cannot be
  decrypted or loaded, and to a burst the embedder cannot score (an enrolled voiceprint
  from a different `[voiceprint] backend` has a different length on every burst): the
  burst is admitted and the reason is logged once at WARNING. It never silently admits
  or silently rejects everything. `doctor` reads only whether the voiceprint file
  exists, so its OK row says the daemon log is where a load or scoring failure shows.
- **The toggle cannot lie.** `yazses features enable voiceguard` writes `[voiceprint]
  enabled = true` as well, and prints that a voiceprint must be enrolled (and that
  `fail_open = false` stays inactive). `yazses features` lists the guard as off, with
  the reason, while `[voiceprint]` is off.
- **Thresholds are tuned on synthetic signals only** (fixed vectors in
  `tests/test_voiceguard_wiring.py`); how often a real voice clears `match_threshold =
  0.5` on the shipped ECAPA backend is unmeasured.
- **Paths the guard does not see.** Punch-in respeak (`_record_respeak` ->
  `_apply_punch_in`) retypes a span without passing through the guard; only the main
  hold-to-talk burst is judged.
- Off by default; a default daemon never imports `yazses.voiceguard`.
