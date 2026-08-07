# ADR-MOB-002 — Native Kotlin + Jetpack Compose, pure-Kotlin cores, no cross-platform runtime

**Status:** Accepted (2026-08-07) · design only, no code yet
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-mob-001]] (Android first, monorepo), [[adr-mob-003]] (IME),
[[adr-mob-005]] (STT runtime), [[adr-mob-008]] (contract), [[adr-mob-010]] (Apple wave)

---

## Context

The obvious first instinct — "run the existing Python daemon on the phone" — has to be
tested against what the Android product actually *is*. YazSes on Android is not an app
with a transcribe button; it is three pieces of **operating-system integration**:

- an `InputMethodService` (a keyboard) that holds the mic and commits text into other apps,
- a `RecognitionService` that other apps' `SpeechRecognizer` calls can be routed to,
- a foreground service that survives the screen turning off during a meeting.

All three are Android framework services declared in the manifest and instantiated by the
system. They cannot be implemented from a Python interpreter embedded in the app, nor from
a Flutter/React Native engine — those can only ever be the *UI* inside a shell that is
already native. Meanwhile the heavy lifting (STT decode) is a C/C++ library reached over
JNI regardless of what language the app layer is written in.

Concretely on the Python route: `faster-whisper` requires CTranslate2, which publishes no
Android/NDK build; Chaquopy adds a licensing and APK-size burden and is unusable for
F-Droid; a Kivy/BeeWare app cannot register an IME. The Python tree is reusable as
*specification*, not as *implementation*.

The second question is iOS-shaped: if the Apple wave ([[adr-mob-010]]) is real, should the
Android app be written in Kotlin Multiplatform (KMP) now so `commonMain` can be shared with
an iOS app later? Paying for KMP tooling, dependency constraints and slower builds at M0 —
before a single line of the app exists, and for a second platform whose product shape is
known to differ — is speculative generality. But *foreclosing* KMP would be a real loss.

## Decision

1. **Native Android: Kotlin, Jetpack Compose for UI, Gradle (Kotlin DSL), version catalog.**
   Minimum SDK 26 (Android 8.0); target the current stable SDK and keep it current, since
   the foreground-service and permission rules that this app depends on are tied to target
   SDK.
2. **A multi-module Gradle build** split into `:core:*` (logic), `:native:*` (JNI),
   `:feature:*` (Android services and screens) and `:app` (assembly). The full module map,
   with the desktop module each one mirrors, is in `docs/mobile/architecture.md`.
3. **The `:core:*` modules are pure-Kotlin JVM modules** (`kotlin("jvm")`, *not*
   `com.android.library`) and must not import `android.*`. Consequences, all deliberate:
   - they are unit-testable on the JVM with no emulator, no device, no mic — the same
     property that makes the desktop suite runnable in 15 s and is the single biggest
     lever on contributor throughput;
   - they are exactly the code the golden contract vectors ([[adr-mob-008]]) validate;
   - converting them to KMP `commonMain` for the Apple wave is a build-file change, not a
     rewrite. **This is the KMP option, bought at near-zero cost and exercised later.**
   Anything needing `Context`, `AudioRecord`, `SharedPreferences` or the manifest lives in
   `:feature:*` behind an interface that `:core:*` declares — the same
   pure-logic/thin-shell split the desktop uses for the tray (`tray/menu.py` +
   `tray/controller.py` + `platform/linux/tray.py`).
4. **No dependency-injection framework, no reactive-stream framework beyond coroutines +
   `Flow`.** Constructor injection and a hand-written app container. Rationale: every
   framework is a thing a drive-by contributor must learn before their first PR.
5. **Dependency budget.** Additions to `:core:*` need an ADR-level justification; the
   `:app`/`:feature:*` budget is AndroidX + Compose + `kotlinx.serialization` +
   `kotlinx.coroutines` + WorkManager + DataStore. **No Firebase, no Crashlytics, no
   analytics SDK of any kind, ever** — [[adr-011]] forbids it and F-Droid would reject it
   ([[adr-mob-009]]).

## Consequences

- One language for the whole app tree; the only C/C++ is behind `:native:*` ([[adr-mob-005]]).
- The JVM-testable core means the contribution ladder starts at "write a pure function and
  a JUnit test", which needs no Android device — see `docs/mobile/contributing.md`.
- `:core:*` modules cannot take Android conveniences, which will occasionally feel
  bureaucratic (e.g. logging must go through a `Logger` interface). That is the price of
  the KMP option and the emulator-free test suite, and it is worth it.
- Compose means a modern UI with little code, but an IME's key view has real latency
  requirements; if profiling shows Compose is too slow inside the keyboard window, the
  keyboard view specifically may fall back to Views. That is an implementation decision
  reserved to the `:feature:ime` steward, not a re-litigation of this ADR.
- Target-SDK currency is now a maintenance obligation with a deadline attached (Play
  enforces it annually, and FGS/permission behaviour changes with it).

## Rejected

- **Chaquopy / Kivy / BeeWare (run the Python daemon on Android).** Cannot implement an
  IME or a `RecognitionService`; no CTranslate2 for Android so faster-whisper is
  unavailable anyway; large APK; poor battery behaviour; incompatible with F-Droid
  packaging. The Python tree stays the *specification* via [[adr-mob-008]].
- **Flutter / React Native.** The product is OS integration; both would still require
  native IME, native `RecognitionService`, native foreground service and a JNI STT bridge —
  i.e. all of the hard parts — plus a second runtime, a second toolchain for contributors,
  and a harder F-Droid build. Zero shared code with the existing Python desktop, so the
  usual "write once" argument does not even apply here.
- **KMP from day one.** Deferred, not rejected on the merits: the pure-Kotlin `:core:*`
  rule keeps the door open and [[adr-mob-010]] is where it gets decided, with the contract
  already proven by two implementations.
- **Java.** No.
- **A WebView/PWA front end.** No mic-to-any-app path exists on Android for a web app.
