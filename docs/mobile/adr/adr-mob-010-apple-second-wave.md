---
description: "ADR-MOB-010: the Apple wave covers iOS and iPadOS only, starts after Android reaches M2, and shares the behaviour contract rather than code with the Android app."
---

# ADR-MOB-010 — The Apple wave: iOS/iPadOS is a different product shape; macOS is already shipped

**Status:** Accepted (2026-08-07) · direction fixed, execution deferred to after Android M2
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [ADR-MOB-001](adr-mob-001-android-first-monorepo.md) (Android first), [ADR-MOB-002](adr-mob-002-native-kotlin-stack.md) (pure-Kotlin cores → KMP option),
[ADR-MOB-003](adr-mob-003-text-delivery-surfaces.md) (IME), [ADR-MOB-008](adr-mob-008-cross-platform-contract.md) (contract), [ADR-011](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-011.md)

---

## Context

The mobile programme's stated destination is "Android first, then iPhone, iPad, Mac". Two
of those three need correcting before any planning happens:

- **macOS is already a supported YazSes platform today** — the Python desktop app runs on
  it (`platform/macos/`, a signed `.dmg` build script, Accessibility/Microphone permission
  handling). "Mac support" is a *quality* problem (signing, notarisation, polish), not a
  port. It belongs to the desktop line, not to this programme.
- **iOS and iPadOS are one target, and it cannot be an Android-style port**, because of a
  hard platform restriction: **no iOS app extension — including a custom keyboard — may
  access the microphone.** This has been Apple's rule since iOS 8 and has not moved. It
  removes the entire architecture of the Android app: on iOS there is no such thing as a
  keyboard that listens.

Every iOS competitor works around it the same way: the keyboard extension is a *trigger*
that hands off to the containing app, which records and then returns the text (via the
shared app group and `UIPasteboard`/`textDocumentProxy`), or the user dictates in the app
and pastes. That app-switch is visible and unavoidable, and it is why iOS voice-typing apps
feel worse than Android ones. Design honesty requires planning for that experience rather
than discovering it in month three.

Second-order facts that also shape the wave: Apple ships capable on-device speech APIs that
a privacy-focused user may reasonably not trust for confidential content but which are hard
to beat on latency; whisper.cpp has excellent Apple-silicon support (Metal/Core ML); App
Review scrutinises keyboards with "Full Access" heavily; and there is no F-Droid equivalent
— the App Store is the only mass channel, with the sideloading picture varying by
jurisdiction.

## Decision

1. **The Apple wave is iOS + iPadOS only.** macOS improvements stay in the desktop line and
   are tracked there.
2. **The wave starts after Android reaches M2** (dictation shipping, contract proven by a
   second implementation, a working Mobile Working Group). Starting earlier splits an
   already-thin contributor pool across two platforms with nothing shared yet.
3. **The product shape is fixed now, so the Android work does not have to be redone later:**
   - a **main app** that records, transcribes on-device and holds the settings/model store;
   - a **keyboard extension** that is a *handoff trigger* plus a text-insertion surface —
     it never records, and the UI must make the app-switch feel deliberate rather than
     broken;
   - a **Share extension** and **Shortcuts/App Intents** actions for file transcription and
     for "dictate into anything that accepts text";
   - **no claim of parity with the Android keyboard**, in the App Store listing or the docs.
4. **The shared asset is the contract, not the code** ([ADR-MOB-008](adr-mob-008-cross-platform-contract.md)). The iOS
   implementation is validated by the identical `contract/vectors/*.json`, and it must
   satisfy the same contract version the shipping Android build does.
5. **Language decision is deferred to the wave's own ADR (`adr-mob-011`), with two live
   options**, both kept open by [ADR-MOB-002](adr-mob-002-native-kotlin-stack.md)'s pure-Kotlin `:core:*` rule:
   - **Swift + SwiftUI**, reimplementing `:core:*` against the contract vectors — idiomatic,
     attracts iOS contributors, third implementation of the same logic;
   - **Kotlin Multiplatform**, converting `:core:*` to `commonMain` and writing only the
     Swift shell — no third implementation, but imposes KMP on Android contributors and
     complicates the iOS build.
   The deciding evidence will be how much `:core:*` actually is by then, and whether the
   contributors who show up are iOS people (who will want Swift) or the existing Kotlin
   ones. Choosing now would be guessing.
6. **STT on Apple:** whisper.cpp again, with Metal/Core ML acceleration; [ADR-MOB-006](adr-mob-006-model-distribution.md)'s
   download-and-verify model policy applies unchanged. **Apple's own speech APIs are not
   used** — an on-device path the user cannot audit is not the same promise, and
   [ADR-011](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-011.md) §5's open-weights default applies.
7. **[ADR-011](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-011.md) applies unchanged**: no analytics, no crash reporting SDK, no cloud
   fallback, no ambient capture, and an App Privacy declaration that says "no data
   collected" and matches the binary.

## Consequences

- The programme's public roadmap can state the iOS limitation up front instead of
  discovering it late — and it doubles as an honest explanation of why Android came first.
- The Android work is protected: the pure-Kotlin core rule and the contract are the two
  things that make the Apple wave cheap, and both are already paid for.
- iPadOS gets a genuinely good story even with the keyboard restriction, because
  Shortcuts/App Intents and the Files/Share path cover much of what iPad users want
  (long-form dictation and file transcription).
- An Apple Developer Program membership (annual fee), a Mac for CI/signing, and App Review
  turnaround become real costs and schedule risks. Named now, owned by the maintainer.
- If Apple ever lifts the extension microphone restriction, the Android architecture ports
  almost directly — another reason the contract-first investment is the right hedge.

## Rejected

- **iOS before or alongside Android** — [ADR-MOB-001](adr-mob-001-android-first-monorepo.md); the restriction above means an
  iOS-first wave would ship the worse interaction model and teach the project nothing
  reusable.
- **Treating macOS as part of the mobile programme** — it is a shipped desktop platform;
  folding it in would hide real desktop polish work behind a mobile milestone.
- **Using `SFSpeechRecognizer` / Apple on-device dictation as the engine** — it makes the
  app a UI over a black box, which is not the product.
- **A Catalyst or SwiftUI-multiplatform "one app everywhere" attempt** — the three targets
  differ in exactly the system-integration layer that *is* the product.
- **Deciding Swift-vs-KMP today** — no evidence yet; both are kept viable at zero ongoing
  cost.
