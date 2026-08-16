# YazSes Mobile — programme overview

**Status (2026-08-07): design complete, no code yet.** Nothing in this directory ships
today. The Android app does not exist; these documents are what has to be true before it
does, and they are deliberately written before the first line of Kotlin so that the work
can be done by many people at once.

> **Honesty rule.** Nothing here may be described in the README, the docs site, the store
> listings or a release note as "supported" until it is wired, tested and shipped. The
> project's existing rule — 147 capabilities, 85 wired and 62 honestly marked *planned* —
> applies to mobile without exception.

---

## Why

YazSes' thesis is dictation that never leaves your device. That thesis is *strongest* on a
phone: the default dictation on Android is a service the user cannot audit, and the
confidential conversations YazSes exists to protect — the client call, the patient note,
the source interview — happen where the phone is, not where the laptop is. It is also the
project's most-requested missing platform.

## Why Android first

Not preference — platform capability. Android's `InputMethodService` lets a third-party
keyboard hold the microphone and commit text into any app, which reproduces the desktop's
hold-to-talk model exactly. **iOS forbids microphone access to every app extension,
including keyboards, and has since iOS 8**, so an iOS app must be a different product
shape (app-switch handoff). Doing Android first means the harder, better design is built
first and the iOS wave inherits a proven contract. macOS, meanwhile, is *already* a
supported YazSes platform — it belongs to the desktop line, not here. See
[ADR-MOB-010](adr/adr-mob-010-apple-second-wave.md).

## The decisions

| ADR | Decision |
|---|---|
| [MOB-001](adr/adr-mob-001-android-first-monorepo.md) | Mobile is a first-class port; Android wave 1; **in this repository** under `android/` |
| [MOB-002](adr/adr-mob-002-native-kotlin-stack.md) | Native Kotlin + Compose; pure-Kotlin `:core:*` (keeps the KMP door open); no Python-on-Android, no Flutter |
| [MOB-003](adr/adr-mob-003-text-delivery-surfaces.md) | IME first, `RecognitionService` second, share/clipboard fallback; **no AccessibilityService**, no typing keyboard |
| [MOB-004](adr/adr-mob-004-activation-model.md) | Hold the mic key; hold/toggle switch for accessibility; headset button; **no wake word, ever** |
| [MOB-005](adr/adr-mob-005-stt-runtime.md) | An engine seam; whisper.cpp default; sherpa-onnx second (VAD, diarization, Parakeet); benchmarks over claims |
| [MOB-006](adr/adr-mob-006-model-distribution.md) | Models downloaded, SHA-256 verified, user-owned; never bundled; works with network permanently denied |
| [MOB-007](adr/adr-mob-007-privacy-permissions-lifecycle.md) | Permission budget, `INTERNET` in one module only, CI privacy gate, foreground-service rules |
| [MOB-008](adr/adr-mob-008-cross-platform-contract.md) | **One behaviour, many implementations** — a `contract/` of golden vectors both platforms run |
| [MOB-009](adr/adr-mob-009-distribution-and-signing.md) | F-Droid-shaped by default; GitHub APK first, F-Droid/Accrescent next, Play later; own tags and keystore |
| [MOB-010](adr/adr-mob-010-apple-second-wave.md) | iOS/iPadOS after Android M2, different product shape; Swift-vs-KMP deferred with evidence |

## The documents

| Document | What it is for |
|---|---|
| [architecture.md](architecture.md) | module map, pipeline, threading, error behaviour, testing — read this before your first PR |
| [contract.md](contract.md) | the golden-vector mechanism that defines "correct" for every implementation |
| [portability.md](portability.md) | every desktop capability → port / adapt / later / no, with milestones |
| [contributing.md](contributing.md) | how the Mobile Working Group works: stewards, claiming, review bar, no-device path |

## Milestones

Each milestone is a shippable statement, not a date. Dates are not promised: this is a
volunteer effort and pretending otherwise sets everyone up to be disappointed.

**M0 — Foundations** *(no app yet; can be done entirely by Python contributors)*
`contract/` exists with vectors for the shared units, generated from the desktop and
guarded by a pytest; the Gradle skeleton, module structure and CI (unit tests + the
manifest/dependency privacy gates) are in place. **Done when:** `./gradlew test` runs green
on an empty core and `pytest tests/test_contract_vectors.py` guards the desktop.

**M1 — "It types what I say"** *(the first real release)*
Keyboard with a mic key; capture → VAD → whisper.cpp → cleanText → disfluency → commit;
model chooser and verified download; clipboard fallback; onboarding; About. **Done when:**
a signed `android-v0.1.0` APK on GitHub Releases dictates reliably into a third-party app
on a real phone, with network access revoked.

**M2 — "It's actually good"**
`RecognitionService`; voice punctuation, continuation spacing, command grammar, personal
vocabulary; the settings screen generated from the feature registry; a diagnostics screen;
headset-button activation; F-Droid submission and Accrescent. **Done when:** a user can
replace their phone's dictation for a week without reaching for Gboard. **The iOS wave may
start once M2 ships.**

**M3 — "Beyond dictation"**
File/share transcription; the sherpa-onnx flavour with diarization; Meeting Mode with its
foreground service; the floating bubble; the public device-performance matrix from `:bench`.

**M4 — Reach**
Play listing, localisation, and whatever the M1–M3 device reports say is actually broken.

## How to help right now

[The tracking epic, #81](https://github.com/MSKazemi/yazses/issues/81), carries the full
work breakdown, and every sub-issue says what it needs from you and what "done" means.
Three ways in that need **no Android device and no Kotlin**:

1. **M0 contract vectors** — Python; write the ugly cases for a unit and generate its
   expectations. [#82](https://github.com/MSKazemi/yazses/issues/82) builds the mechanism,
   [#83](https://github.com/MSKazemi/yazses/issues/83) is a good first issue.
2. **Device reports** — run the benchmark on your phone (once `:bench` exists,
   [#92](https://github.com/MSKazemi/yazses/issues/92)) and file the JSON; the performance
   matrix is community-built by design.
3. **Review these ADRs** — the best time to disagree with an architecture is before it is
   built. [#98](https://github.com/MSKazemi/yazses/issues/98) is an open invitation to
   attack them.

Read [contributing.md](contributing.md) next.
