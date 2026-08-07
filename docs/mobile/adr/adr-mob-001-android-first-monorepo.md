# ADR-MOB-001 — Mobile is a first-class port, Android first, in this repository

**Status:** Accepted (2026-08-07) · design only, no code yet
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-011]] (zero telemetry, offline-default), [[adr-mob-002]] (native stack),
[[adr-mob-008]] (cross-platform contract), [[adr-mob-010]] (Apple second wave),
program docs: `docs/mobile/`

---

## Context

YazSes is a desktop daemon (Linux/macOS/Windows). Both the README and `docs/roadmap.md`
state plainly: *"Desktop-only. There is no mobile or web version."* That is the single
most-requested missing platform, and it is also where the project's thesis — **dictation
that never leaves the device** — has its sharpest competitive edge: on a phone, the
default dictation path is Google's or Apple's cloud/on-device service that the user
cannot audit, and the confidential-meeting / regulated-profession users YazSes targets
(lawyers, clinicians, journalists) carry a phone into exactly the rooms where a desktop
never goes.

Three structural facts shape the decision:

1. **Android can reproduce the desktop interaction model faithfully; iOS cannot.**
   Android's `InputMethodService` lets a third-party keyboard hold the microphone and
   commit text into *any* app via `InputConnection`, with no root and no accessibility
   grant. On iOS, **no app extension — including a custom keyboard — may access the
   microphone**; this has been a hard Apple restriction since iOS 8, which is why every
   iOS competitor (Wispr Flow, Spokenly, Willow) routes through an app switch. So
   "Android first" is a technical ordering, not a preference. (See [[adr-mob-010]].)
2. **macOS is already shipped.** The user-facing ask "…and Mac" is satisfied today by the
   desktop app; the Apple work that remains is *iOS/iPadOS*, and it is a different product
   shape, not a port of this one.
3. **None of the desktop runtime is reusable.** faster-whisper depends on CTranslate2,
   which has no Android build; the daemon model (long-lived process + Unix socket) fights
   Android's lifecycle; a Python-on-Android runtime cannot implement an IME. The port
   shares *behaviour*, not code — which is precisely why the behaviour must be written
   down as a testable contract before anyone writes Kotlin ([[adr-mob-008]]).

The community question is equally structural. A mobile port is a 6–12 month effort that
the maintainer cannot execute alone alongside the desktop line. It only happens if it is
**contributor-shaped from day one**: parallelisable modules, a machine-checkable
definition of "correct", and tasks that a new contributor can finish in a weekend.

## Decision

1. **Mobile is a first-class, ADR-governed port**, not an experiment. It is governed by
   the `adr-mob-*` series, and it inherits every v1/v2 invariant unchanged — most
   importantly [[adr-011]] (zero telemetry, offline by default, no cloud fallback) and
   the project rule that **new features ship off by default**.
2. **Android is wave 1. Apple (iOS/iPadOS) is wave 2**, and wave 2 starts only after
   Android reaches M2 (see `docs/mobile/index.md` for the milestone ladder), so the
   shared contract has been proven by a second implementation before a third begins.
3. **The Android app lives in this repository**, under a top-level `android/` directory
   with its own Gradle build and its own CI workflow — *not* in a separate
   `yazses-android` repo.
4. **The desktop Python tree and the Android tree are peers**, both conforming to a
   language-neutral contract in a new top-level `contract/` directory ([[adr-mob-008]]).
   Neither imports the other; neither is "the reference implementation" informally — the
   contract is the reference.
5. **Scope of wave 1 is dictation, not the whole desktop feature set.** The Android app
   ships when hold-to-talk dictation into any app is reliable; file transcription and
   Meeting Mode are M3+; the v2 cognitive layer (gaze, EMG, LSP context, remote
   injection) is explicitly out of scope for wave 1.

## Consequences

**Monorepo, positive:**
- One community, one star count, one issue tracker, one CONTRIBUTING — critical for a
  project whose current bottleneck is contributor supply, not code.
- The contract and its golden vectors sit beside *both* implementations, so a CI job can
  fail a desktop PR that silently changes behaviour the Android port depends on. In two
  repos that guarantee degrades to a version-pinned copy that drifts.
- Cross-platform issues ("disfluency filter drops a word") are one issue, not two.
- F-Droid and Play both build fine from a subdirectory of a larger repo.

**Monorepo, negative / mitigations:**
- Python contributors see Kotlin they don't care about, and vice versa → mitigated by
  path-filtered CI (`android/**` triggers the Gradle workflow only), separate module
  stewards, and a `mobile` label on every mobile issue.
- A `git clone` gets bigger → the Android tree carries no model weights and no prebuilt
  binaries ([[adr-mob-006]]), so the growth is source only.
- Release tagging must not imply that a `v2.x` desktop tag ships an APK → Android uses its
  own tag prefix `android-v*` with its own workflow ([[adr-mob-009]]).

**Programme-level:**
- Wave 1 will not have feature parity with the desktop, and saying so plainly is a
  requirement, not a caveat: the README's honesty rules apply to the Android page too
  (nothing is listed as working until it is wired and tested).
- The maintainer's role on mobile is architecture, review and contract ownership; module
  implementation is delegated to the Mobile Working Group (`docs/mobile/contributing.md`).

## Rejected

- **A separate `MSKazemi/yazses-android` repository.** Splits an already-small community
  across two trackers, duplicates CONTRIBUTING/CI/labels, and makes the contract a
  cross-repo dependency that will drift. Revisit only if the Android tree grows its own
  distinct maintainer team.
- **Waiting for the desktop v2 line to stabilise first.** The v2 line is a permanent
  research frontier; "later" means never. The contract work ([[adr-mob-008]]) also pays
  the desktop back immediately by pinning post-processing behaviour that is currently
  only implicitly specified by its tests.
- **iOS first, or both at once.** The microphone restriction on iOS app extensions means
  an iOS wave-1 would ship a different, worse interaction model (app-switch dictation)
  and would teach the project nothing transferable about the IME-centred design.
- **A thin "remote control" app** (phone as a microphone for the desktop) *as the mobile
  product.* It is a good feature and is kept as a deferred item in
  `docs/mobile/portability.md`, but it requires a desktop on the same LAN and so
  does not serve the phone-only user who is the reason to do this at all.
