---
description: "The YazSes Android programme: what exists under android/ today, which milestone is active, what remains before a first APK, and why iOS is a later wave. There is no app to install yet."
---

# YazSes Mobile — programme overview

**Status: M0 foundations are built and the first M1 work has landed, but there is no app.**
There is no APK and nothing to install. What exists is the module skeleton, the build
rules it enforces, and the first pure-Kotlin ports of desktop logic, all under
[`android/`](https://github.com/MSKazemi/yazses/tree/main/android). The design documents
below were written before that code, so that many people can build it at once.

> **Honesty rule.** Nothing here may be described in the README, the docs site, the store
> listings or a release note as "supported" until it is wired, tested and shipped. The
> project's existing rule — <!-- registry:total -->150<!-- /registry --> capabilities, <!-- registry:wired -->125<!-- /registry --> wired and <!-- registry:unwired -->25<!-- /registry --> honestly marked *planned* —
> applies to mobile without exception.

### What exists in `android/` now

- **The Gradle skeleton** ([#84](https://github.com/MSKazemi/yazses/issues/84)): every
  module from [architecture.md §3](architecture.md#3-module-map) exists and compiles.
  `checkLayering` fails the build when a `:core:*` module depends on a `:feature:*` one,
  and `:core:*` modules are plain JVM modules, so an `android.*` import does not compile.
- **The privacy gates** ([#85](https://github.com/MSKazemi/yazses/issues/85)):
  `checkPrivacy` diffs the merged manifest against `privacy/manifest-golden.txt`, bans
  analytics and crash SDKs, keeps network code inside `:model`, and fails on a log call
  that carries a transcript. The *Android* CI workflow runs these gates plus
  `./gradlew test` and lint.
- **Pure-Kotlin cores that pass the shared contract vectors:** `:core:postprocess`
  (cleanText, disfluency, spacing, voice punctuation —
  [#86](https://github.com/MSKazemi/yazses/issues/86)), `:core:commands` and `:core:vocab`
  ([#94](https://github.com/MSKazemi/yazses/issues/94)), and `:core:audio` (pre-speech
  padding) with `:core:vad` (the silence gate) from
  [#88](https://github.com/MSKazemi/yazses/issues/88). `:core:contract-test` runs the
  same `contract/vectors/*.json` files the Python suite uses.
- **More pure-Kotlin cores, tested on the JVM and not wired to anything:** `:core:stt`
  (the `SttEngine` interface, `DecodeOptions`, `Transcript`, an engine factory and a
  `DecodeDispatcher`; no engine sits behind it yet), `:core:session` (the hold-to-talk
  state machine and activation sources), `:core:features` (the registry the settings
  screen will be generated from), `:core:model` (the model catalogue, checksum check,
  download policy and install ordering, with no network code) and `:core:bench` (the
  benchmark result format, error-rate helpers and the Whisper English normaliser).
- **Microphone capture, written but never run:** `:platform:audio` has the `AudioRecord`
  shim. It compiles and has not run on a device, which is why #88 is still open.
- **Placeholders only:** `:app`, `:model`, `:bench`, every `:feature:*` module (including
  the keyboard), both `:native:*` engines, and `:core:config` (one placeholder class).
  No speech engine is connected yet.

### Where each milestone stands

The milestones are the four GitHub milestones *Android M0 — Foundations* through
*Android M3 — Beyond dictation*; the issue states below were read from them, and the
[tracking epic, #81](https://github.com/MSKazemi/yazses/issues/81), carries the full work
breakdown. No milestone has a date.

| Milestone | Shipped | In progress | Remaining |
|---|---|---|---|
| **M0** Foundations | contract/ (#82), edge-case vectors (#83), Gradle skeleton (#84), privacy gate (#85) | — | the design review #98 is kept open in it (the epic #81 spans M0–M3, so it carries no milestone) |
| **M1** It types what I say | `:core:postprocess` (#86) | capture and silence gate (#88): cores done, device check open; engine seam (#87): `:core:stt` in, whisper.cpp bridge open; keyboard (#89): `:core:session` in, service and key bar open; model download (#90): `:core:model` in, download job open; `:bench` (#92): `:core:bench` in, on-device runner open | onboarding (#91) |
| **M2** It's actually good | command grammar and personal dictionary (#94), ported ahead of M1 | — | `RecognitionService` (#93), generated settings (#95), F-Droid build and submission (#96) |
| **M3** Beyond dictation | — | — | the meeting foreground-service spike (#97); the rest of M3 has no issue yet |

**Active milestone: M0**, which is still open on GitHub. All four of its build issues are
closed. It stays open because it holds the standing design-review invitation (#98).
The epic, #81, spans M0–M3, so it carries no milestone of its own.
M1 has started alongside it, but its done-statement, a signed APK dictating on a real
phone, is several issues away: there is no engine, no keyboard and no model download yet.

### Why iOS is not current work

[ADR-MOB-010](adr/adr-mob-010-apple-second-wave.md) is an **accepted decision with deferred
execution**. The direction is fixed: iOS forbids microphone access in keyboard extensions,
so the Apple app must be a different product shape. Execution waits until Android M2 ships,
and M2 has not shipped. No iOS code exists and no iOS issue is open, so iOS should not be
presented as implementation work.

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

1. **Contract vectors** — Python; write the ugly cases for a unit and generate its
   expectations. M0 built the mechanism and it ships in
   [`contract/`](https://github.com/MSKazemi/yazses/tree/main/contract); adding a
   language or an edge case to it is still a good first issue. New ones are filed under
   the [`contract` label](https://github.com/MSKazemi/yazses/issues?q=label%3Acontract);
   [#512](https://github.com/MSKazemi/yazses/issues/512), the Persian and RTL vectors, is
   a finished example of the shape.
2. **Device reports** — run the benchmark on your phone (once `:bench` exists,
   [#92](https://github.com/MSKazemi/yazses/issues/92)) and file the JSON; the performance
   matrix is community-built by design.
3. **Review these ADRs** — the best time to disagree with an architecture is before it is
   built. [#98](https://github.com/MSKazemi/yazses/issues/98) is an open invitation to
   attack them.

Read [contributing.md](contributing.md) next.
