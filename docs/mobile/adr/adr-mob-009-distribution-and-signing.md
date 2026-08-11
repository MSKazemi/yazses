# ADR-MOB-009 — Distribution: F-Droid-shaped by default, GitHub APK first, Play later

**Status:** Accepted (2026-08-07) · design only, no code yet
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-mob-005]] (engines), [[adr-mob-006]] (models),
[[adr-mob-007]] (privacy gate), [[adr-011]], desktop analogue: `adr-008` (packaging),
the internal distribution-status note

---

## Context

The desktop line learned that distribution is not a last step: the APT/PPA/Snap channels
each imposed constraints that had to be designed for, and the strictly-confined snap still
cannot do hold-to-talk. The Android channels impose their own, and they conflict:

- **F-Droid** builds everything from source, does not accept prebuilt binaries (including
  convenience AARs and prebuilt `.so` files), rejects proprietary dependencies outright
  (no Play Services, no Firebase), and rewards reproducible builds. It is also where the
  privacy-focused Android audience actually looks, which is exactly YazSes' audience.
- **Google Play** reaches everyone else, costs a one-off developer fee, requires an
  accurate Data Safety declaration ([[adr-mob-007]] F), applies extra scrutiny to keyboards
  and to `RECORD_AUDIO`, and forces an annual target-SDK treadmill.
- **Accrescent** and direct **GitHub Releases APKs** are fast, unmediated channels; the
  closest FOSS neighbour (Transcribro) ships via Accrescent and GitHub.

The engine choice interacts directly: whisper.cpp is a small CMake project that an F-Droid
recipe can realistically build from source, whereas sherpa-onnx's practical Android path is
a prebuilt AAR over ONNX Runtime — convenient everywhere except the one channel that
matters most ([[adr-mob-005]]).

## Decision

1. **F-Droid compatibility is a design constraint from M0, not a later port.** Every choice
   in the dictation path must be buildable from source with no proprietary dependency. This
   is why whisper.cpp is the default engine and why no Google library may enter the
   dependency allow-list.
2. **Two product flavours, one codebase:**
   - `foss` — the default and the F-Droid/Accrescent/GitHub build. Dictation path only from
     source-built native code. sherpa-onnx-dependent capabilities (diarization, Silero VAD,
     Parakeet) are either built from source in the recipe if that proves feasible, or are
     **absent and honestly reported as absent** by the feature registry (the desktop's
     `system/backends.py` distinction between "install the extra" and "this build cannot
     supply it" ports directly).
   - `full` — the GitHub/Play build, which may use upstream-published binary artefacts for
     the optional engines. Never differs in privacy posture: same permission table, same CI
     privacy gate, no analytics in either.
3. **Release order:** M1 → signed GitHub Releases APK (`android-v0.1.0`). M2 → F-Droid
   submission + Accrescent. M3+ → Play, only once Meeting Mode and file import are stable
   enough to survive Play review and the keyboard-policy questions.
4. **Independent versioning and tags.** Android releases use `android-vX.Y.Z` tags and an
   `android-release.yml` workflow; desktop `v*` tags must not build or publish an APK, and
   the Android workflow must not fire on desktop tags. The Android About screen shows both
   its own version and the contract version it satisfies ([[adr-mob-008]] §6).
5. **Signing.** A dedicated Android release keystore, held only by the maintainer, backed up
   offline, never in the repo and never in a workflow that a fork can trigger; the CI secret
   is scoped to tag-triggered release runs. `apksigner` v2+v3 signing. Reproducible-build
   settings are enabled from the first release so an F-Droid reproducible listing stays
   possible later. **Key rotation on Android is effectively impossible for sideloaded
   users**, so this is treated with the same seriousness as the APT signing key (whose loss
   already cost this project a re-key — see the APT repo history).
6. **CI.** A path-filtered `android-test.yml` (Gradle: assemble, unit tests including the
   contract vectors, lint, the manifest/dependency privacy gates) runs on `android/**` and
   `contract/**` changes; an instrumented job runs the airplane-mode round-trip on an
   emulator. Desktop CI is untouched.
7. **Store listing text is bound by the honesty rules.** No feature is listed as working
   until it is wired and tested on a device; the "offline" claim is stated with its one
   exception (the user-initiated model download) in the listing itself, not only in the FAQ.

## Consequences

- The default build is the most restricted one, so the project cannot accidentally take a
  dependency that locks it out of F-Droid — the failure mode is caught at M0 rather than at
  submission.
- Feature availability differs by flavour, which is a documentation burden and a support
  burden; the feature screen must show it plainly, per-build, at runtime.
- Play arrives late, which costs reach early. Accepted: the early audience is the
  privacy-motivated one, and a rushed Play listing for a keyboard with `RECORD_AUDIO` and a
  half-built Meeting Mode is a rejection risk with reputational cost.
- An annual target-SDK obligation now exists for the Play build, and target-SDK bumps
  change FGS/permission behaviour ([[adr-mob-007]]) — so the bump is a scheduled task with
  a test pass, not a one-line diff.

## Rejected

- **Play-first.** Reaches the wrong audience first, imposes the heaviest process on the
  least-mature build, and would tempt Play-only conveniences into the codebase.
- **Prebuilt `.so`/AAR in the default build.** Blocks F-Droid's main repo and weakens the
  supply-chain story for an app whose selling point is trust.
- **A separate "YazSes Pro" paid build.** Out of scope; the project is Apache-2.0 and
  community-built, and a paid tier would poison the contribution model.
- **Publishing the APK from the same tag as the desktop release.** Couples two release
  cadences that have nothing to do with each other, and would make every desktop patch
  release look like a mobile release.
