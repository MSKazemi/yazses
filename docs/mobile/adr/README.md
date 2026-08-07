# Mobile architecture decision records

The ten binding decisions for the YazSes mobile programme. They are **public on purpose**:
the Android app is being built by contributors, and you cannot contribute to an
architecture you are not allowed to read. Every one of them follows the same shape —
Context, Decision, Consequences, **Rejected** — and the Rejected section is usually the
most useful part, because it tells you which arguments have already been had.

| ADR | Title | Status |
|---|---|---|
| [MOB-001](adr-mob-001-android-first-monorepo.md) | Mobile is a first-class port, Android first, in this repository | Accepted |
| [MOB-002](adr-mob-002-native-kotlin-stack.md) | Native Kotlin + Compose, pure-Kotlin cores, no cross-platform runtime | Accepted |
| [MOB-003](adr-mob-003-text-delivery-surfaces.md) | Text delivery: IME first, RecognitionService second, share/clipboard fallback | Accepted |
| [MOB-004](adr-mob-004-activation-model.md) | Activation: hold the mic key, with a hold/toggle accessibility switch | Accepted |
| [MOB-005](adr-mob-005-stt-runtime.md) | STT runtime: an engine seam, whisper.cpp default, sherpa-onnx second | Accepted |
| [MOB-006](adr-mob-006-model-distribution.md) | Models downloaded, verified and user-owned; never bundled | Accepted |
| [MOB-007](adr-mob-007-privacy-permissions-lifecycle.md) | Permission budget, one networked module, CI-enforced privacy gate | Accepted |
| [MOB-008](adr-mob-008-cross-platform-contract.md) | One behaviour, many implementations: a contract with golden vectors | Accepted |
| [MOB-009](adr-mob-009-distribution-and-signing.md) | F-Droid-shaped by default; GitHub APK first, Play later | Accepted |
| [MOB-010](adr-mob-010-apple-second-wave.md) | The Apple wave: iOS/iPadOS is a different product shape | Accepted (deferred execution) |

## Reading notes

- **`[[adr-011]]`, `[[adr-v2-129]]` and similar links** point into the desktop ADR series,
  which is an internal maintainer document and is not published. Where a desktop ADR is
  load-bearing for a mobile decision, the mobile ADR restates what it says, so you never
  need the original. The most important one, **ADR-011 (zero telemetry, offline by default,
  no cloud fallback, no ambient capture)**, is published in user-facing form as the
  [privacy statement](../../privacy-statement.md), and it governs the Android app
  unchanged.
- **"Accepted" here means the decision is binding, not that the code exists.** As of
  2026-08-07 there is no Android code at all. See [the programme overview](../index.md) for
  what actually ships today (nothing) and what M0–M4 mean.
- **To change a decision**, open a PR adding a new ADR that supersedes the old one. Do not
  edit an accepted ADR to say something different from what was decided; the point of the
  series is that the reasoning survives the decision.
