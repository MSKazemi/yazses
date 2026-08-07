# YazSes for Android

> **Status: design complete, no code yet (2026-08-07).**
> This directory is the future home of the Android app. Right now it contains only this
> file. That is deliberate: the architecture was written down *before* the code so that
> many people can build it at once without colliding or re-deciding the same questions.
>
> **There is no APK. There is nothing to install.** If you came here looking for a working
> app, watch the tracking epic on the issue tracker (labels `android` + `epic`).

Offline, on-device voice dictation for Android: a keyboard whose mic key you hold, speak,
release — and your words appear in whatever app you were in. No cloud, no account, no
telemetry, and it keeps working with the app's network access revoked.

## Start here

| If you want to… | Read |
|---|---|
| understand what we are building and why Android first | [Programme overview](../docs/mobile/index.md) |
| know how the app is structured before your first PR | [Architecture](../docs/mobile/architecture.md) |
| know why a decision was made (and what was rejected) | [ADRs MOB-001..010](../docs/mobile/adr/README.md) |
| know what "correct" means for a module | [The core contract](../docs/mobile/contract.md) |
| know which desktop features are coming, and when | [Portability matrix](../docs/mobile/portability.md) |
| **claim a task and start** | [Contribution model](../docs/mobile/contributing.md) |

## The one-paragraph architecture

An `InputMethodService` (the keyboard) holds the microphone while you press its mic key,
runs `AudioRecord → VAD → whisper.cpp → text clean-up → command classification` entirely
on-device, and delivers the result with `InputConnection.commitText()`. Pure logic lives in
`:core:*` modules that are plain JVM Kotlin — no Android imports, unit-testable with no
emulator, and verified against the same golden test vectors the Python desktop runs, so the
phone and the laptop behave identically. Only one module (`:model`) has the `INTERNET`
permission, and only to download the speech model you chose, with its SHA-256 checked
against a checksum shipped inside the signed APK.

## Ground rules (from the ADRs — not up for grabs in a PR)

- **No `AccessibilityService`.** The IME reaches every text field already; that grant is
  not worth the user's trust. ([MOB-003](../docs/mobile/adr/adr-mob-003-text-delivery-surfaces.md))
- **No wake word, no ambient capture.** The mic opens while you hold a key, or during an
  explicitly started meeting. ([MOB-004](../docs/mobile/adr/adr-mob-004-activation-model.md))
- **No analytics, no crash-reporting SDK, no Firebase, ever.** CI fails the build if a
  networked dependency reaches any module but `:model`.
  ([MOB-007](../docs/mobile/adr/adr-mob-007-privacy-permissions-lifecycle.md))
- **No `android.*` imports in `:core:*`.** That rule is what keeps the test suite fast and
  the iOS door open. ([MOB-002](../docs/mobile/adr/adr-mob-002-native-kotlin-stack.md))
- **New features ship off by default** — the same rule as the desktop.
- **Nothing is advertised before it works.** Not in the README, not in the store listing.

## Building

Nothing to build yet. The M0 issue creates the Gradle skeleton; when it lands, this section
becomes the real build instructions (JDK version, SDK/NDK levels, `./gradlew test`, how to
run the contract vectors, and how to build the `foss` flavour the way F-Droid will).

## Module stewards

| Module | Steward |
|---|---|
| _(all)_ | unclaimed — [claim one](../docs/mobile/contributing.md#3-roles) |

## Licence

Apache-2.0, same as the rest of the project.
