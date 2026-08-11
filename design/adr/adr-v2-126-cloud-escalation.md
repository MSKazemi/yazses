# ADR-v2-126 — Cloud Transcription Escalation (design-only, deferred)

**Status:** Proposed — design-only, **not scheduled for implementation** (2026-07-04) · Wave O
**Context links:** [[adr-v2-125-diarized-recording-import]] (the offline path this may optionally
escalate), [[adr-011]] (zero telemetry — this ADR defines the *single, explicit, opt-in* exception),
[[adr-012-self-improvement-loop]] (must never touch the encrypted corpus)

## Context

`yazses transcribe` (ADR-125) is offline and CPU-only by design. The user asked whether an API key in
config could later be used to boost quality via a cloud provider. This is a **deliberate exception to
ADR-011** (nothing leaves the machine), so it must be designed carefully and is **explicitly deferred** —
this ADR records the shape and the guardrails now so the offline feature isn't built in a way that
precludes it, but **no cloud code ships in Wave O**.

Research (`17-diarized-recording-import.md` §7) surveyed the 2026 provider landscape. All viable
providers except Azure's disconnected container require **audio to leave the machine**. Shortlist by fit:
**Deepgram Nova-3** (cheap ~$0.26/hr, native word timestamps + `diarize=true`, and — uniquely among the
cheap options — a **self-hosted/on-prem** deployment), **AssemblyAI** (cheapest base ~$0.15/hr, 99
languages, simple async API), **OpenAI `gpt-4o-transcribe-diarize`** ("paste your existing OpenAI key"
convenience, but no word-level timestamps). Azure disconnected containers are the only air-gapped option
(enterprise). Pricing re-verify at implementation time.

## Decision (design intent — not built this wave)

If/when implemented, cloud escalation is a **provider-pluggable adapter** behind an interface
`CloudTranscriber` with `transcribe(path) -> (words, turns)` capabilities flags (`diarize`,
`word_timestamps`, `languages`), shipping Deepgram + AssemblyAI + OpenAI adapters first. Hard guardrails,
all non-negotiable:

- **OFF by default.** No cloud call is possible without an explicit `--cloud <provider>` flag on
  `yazses transcribe` **and** a configured key.
- **Config** `[recimport.cloud] enabled=false, provider="", api_key_env=""` — the key is read from an
  **environment variable named by the user** (never stored in `config.toml`, never logged).
- **One-time consent prompt** on first cloud use, **naming the destination host** and that audio will be
  uploaded; a persisted acknowledgement flag (per ADR-011's explicit-exception principle).
- **Never touches the encrypted learning corpus** (ADR-012) and **never** runs implicitly as a "quality
  fallback" — offline stays the default and only path unless the user opts in per invocation.
- Prefer providers with an **on-prem/self-host** option (Deepgram, Azure disconnected) in docs for users
  whose concern is quality, not privacy.

## Consequences

- Records the guardrails so the ADR-125 pipeline is built provider-agnostic (the `engine`/`diarizer`
  injection seams already allow a cloud adapter to slot in later) without shipping any cloud dependency
  or network code now.
- Keeps ADR-011 intact: the only way data ever leaves the machine is one explicit, per-invocation,
  consent-gated, user-keyed action.
- **Deferred:** no implementation, tests, or dependencies in Wave O. Revisit as its own wave with a
  fresh pricing/API re-verification.
