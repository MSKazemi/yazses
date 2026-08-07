# ADR-MOB-006 — Models are downloaded, verified and user-owned; never bundled, never silent

**Status:** Accepted (2026-08-07) · design only, no code yet
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-mob-005]] (engines), [[adr-mob-007]] (privacy/permissions),
[[adr-mob-009]] (distribution), [[adr-011]] (offline default, open weights)

---

## Context

A dictation app is useless without weights and the weights are 40–500 MB. Four facts fix
the design:

- Play imposes a base APK/AAB size limit far below a bundled `small.en`, and F-Droid's main
  repo does not want large opaque binary blobs in-tree.
- The user must be able to choose a model — `tiny.en` on an old phone, `small.en` on a
  flagship, a multilingual model for a non-English user — so a single bundled model is
  wrong even when it fits.
- The download is **the only time the app touches the network**, and that single fact is
  the most important thing to be honest about, because the whole product claim is
  "offline".
- Users who never want the app to touch the network at all (air-gapped, high-threat, or
  simply not trusting the claim) must have a supported path.

## Decision

1. **No model weights ship inside the APK.** The APK contains code and a signed *catalogue*
   of models (id, display name, engine, size, SHA-256, licence, source URL).
2. **First-run model chooser.** Onboarding shows the catalogue with size, expected
   device-class suitability and licence, and asks the user to pick. Nothing is downloaded
   before an explicit tap. The screen states, verbatim in spirit: *this is the only network
   request YazSes ever makes; after it completes you can disable network access for this
   app entirely and dictation will keep working.*
3. **Download is a WorkManager job in `:model`, the single module with the `INTERNET`
   permission** ([[adr-mob-007]]). Requirements: resumable, cancellable, Wi-Fi-only by
   default, HTTPS only (`cleartextTrafficPermitted=false`), **SHA-256 verified against the
   in-APK catalogue before the file is made visible**, atomic rename into place, and a
   readable failure state. A checksum mismatch deletes the file and reports it loudly — a
   corrupted or substituted model is a security event, not a retry.
4. **Sideload path, first-class and documented:** the user may import a model file from
   local storage (SAF) or `adb push` it, and the app verifies it against the catalogue
   checksum when the model is known, or accepts it with an explicit "unverified, you
   supplied this" marker when it is not. **The app is fully functional with network access
   permanently denied**, and this is covered by an automated test, not just a claim.
5. **Models are stored in app-private storage** (`filesDir`/`noBackupFilesDir`), excluded
   from cloud backup (`android:allowBackup` handling and backup rules), and listed in a
   Storage screen that shows size and offers deletion. Removing YazSes removes the weights.
6. **Open weights only, licence shown before download** ([[adr-011]] §5). Each catalogue
   entry carries its licence and its upstream URL, and the download screen shows both.
7. **The catalogue is versioned in-repo** (`android/app/src/main/assets/models.json`), so a
   model addition is a reviewable PR with a checksum in the diff — not a server-side
   change. There is **no remote catalogue endpoint**: the app never asks a YazSes-operated
   server anything, because there is no YazSes-operated server ([[adr-011]] §1).
8. **A quantisation/size matrix per engine** is maintained from `:bench` device reports
   rather than asserted; the chooser's "recommended for your device" hint is derived from
   RAM and SoC class and is presented as a hint, with all options selectable.

## Consequences

- The APK stays small (single-digit MB plus native libs), which helps Play, F-Droid and
  users on metered connections.
- First run has a real cost (a several-hundred-MB download) that must be communicated
  before it starts, including on mobile data.
- Model files are user-visible and deletable, so "how much space is this taking" has an
  in-app answer — a common uninstall trigger removed.
- Hosting is upstream (e.g. the model publisher's repository) rather than a YazSes CDN.
  Upstream URLs rot; the catalogue therefore needs a maintenance obligation and a mirror
  policy, and a broken URL must produce a clear error with a sideload suggestion, never a
  hang. This is a named risk with an owner.
- Because the checksum is in the APK and the APK is signed, a compromised mirror cannot
  substitute weights — a genuinely meaningful supply-chain property for an app whose whole
  point is trust.

## Rejected

- **Bundling `tiny.en` "so it works immediately".** Tempting for onboarding, but it sets
  the accuracy expectation at the worst model the project can ship, adds ~75 MB to every
  install including for users who will immediately download something better, and starts
  an argument with F-Droid about in-tree blobs. Revisit only if onboarding drop-off data
  (from user reports, not telemetry — [[adr-011]] §1) shows it is the deciding factor.
- **A play-asset-delivery / dynamic-feature module for weights.** Ties the mechanism to
  Play; F-Droid and GitHub APKs would need the download path anyway, so this would mean
  two mechanisms instead of one.
- **A YazSes-operated model server or catalogue endpoint.** Creates the exact telemetry
  surface [[adr-011]] forbids (download logs are usage data), plus an operating cost and a
  single point of failure.
- **Downloading silently in the background on first launch.** Violates the spirit of the
  offline claim, surprises metered-connection users, and would make the network permission
  feel like a lie.
