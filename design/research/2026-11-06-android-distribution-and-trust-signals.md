# Research: privacy-safe Android distribution and trust signals

**Issue:** [#810](https://github.com/MSKazemi/yazses/issues/810) (NEXT-MOBILE-05), parent epic [#789](https://github.com/MSKazemi/yazses/issues/789), implementation epic [#81](https://github.com/MSKazemi/yazses/issues/81); existing owner issue [#96](https://github.com/MSKazemi/yazses/issues/96) (F-Droid: a reproducible, fully source-built foss flavour, and the submission)

**Snapshot:** YazSes `main` at `8a72bbc6`, inspected 2026-11-06; external pages read 2026-11-06

**Status:** Research draft, review pending. Not a decision. ADR-030 freeze unchanged. No ADR edited.

**Scope:** documentation research only. No `android/` change, no APK, no submission, no account created, no device measured. Android is not an installable product (`android/README.md:3-11`), so every "go" below is a go *to prepare*, never a go to publish.

Companion notes from the same research epic, not repeated here:

- [API levels and OEM IME/microphone rules (#807)](2026-11-05-android-api-levels-and-oem-ime-microphone-restrictions.md)
- [ADR traceability matrix (#812)](2026-11-06-android-adr-traceability-matrix.md) — its row 8 deferred distribution trust signals to this note
- [First-use journey and model provisioning UX (#806, #809)](2026-11-06-android-first-use-journey-and-model-provisioning-ux.md) — its §"Recovery" asked #810 for a per-channel install guide and an "unknown sources" device test (answered in §6, T-D5)
- [On-device ASR measurement protocol (#808)](2026-11-06-android-on-device-asr-measurement-protocol.md)

## Evidence labels

- **[Primary]** stated on the upstream's own documentation page (key `S#`, §9).
- **[Press]** secondary tech press; treated as a claim, not a fact.
- **[Repo]** read in this checkout at `8a72bbc6`, cited `file:line`.
- **[Assumption]** my inference, stated so it can be challenged.
- **[Unknown]** not answered by what was read.

**Method caveat.** The fetch tool returns a model-written summary of each page, not the raw page. Quotations below are as the tool returned them. Page revision dates are given only where the page printed them (S5 prints per-answer "Last updated" dates). The Accrescent requirements page returned HTTP 404 (§9, S10), so every Accrescent statement here is unverified.

## 1. What the repo already commits to  [Repo]

| Item | Where | State at `8a72bbc6` |
|---|---|---|
| Channel order: signed GitHub APK (M1) → F-Droid + Accrescent (M2) → Play (M3+) | `docs/mobile/adr/adr-mob-009-distribution-and-signing.md:52-54` | Accepted 2026-08-07, design only (`:7`) |
| `foss` (default) and `full` flavours, same privacy posture | ADR-MOB-009 `:42-51` | **Not in the build**: `android/app/build.gradle.kts:7-23` has no `flavorDimensions`/`productFlavors` |
| Dedicated release keystore, maintainer-held, offline backup; v2+v3 signing; reproducible settings "from the first release" | ADR-MOB-009 `:59-65` | No `signingConfig` in `android/app/build.gradle.kts`; no reproducibility settings found by grep |
| Listing text bound by honesty rules; offline claim stated with its one exception | ADR-MOB-009 `:70-72` | No listing exists |
| Annual target-SDK treadmill acknowledged | ADR-MOB-009 `:84-86` | `targetSdk = "34"` (`android/gradle/libs.versions.toml:13`) |
| No weights in APK; in-APK signed catalogue with SHA-256 + licence + pinned URL | ADR-MOB-006 `:32-33`, `:53-58`; `android/app/src/main/assets/models.json` (`_schema` field) | Catalogue present; URLs pinned to a Hugging Face commit per its `_schema` text |
| Only `:model` may hold `INTERNET` | ADR-MOB-006 `:39-41`; `android/gradle/privacy.gradle.kts:116-119` (`networkArtefacts`), allowed set `:model` | Gate present |
| Analytics/crash SDKs banned at any depth | `android/gradle/privacy.gradle.kts:122-127` | Gate present (Firebase Analytics/Crashlytics, Sentry, Amplitude, Mixpanel, AppsFlyer, Facebook core) |
| Merged-manifest golden file | `android/privacy/manifest-golden.txt:5` | One permission today: `RECORD_AUDIO` |
| Gradle wrapper | `android/gradle/wrapper/gradle-wrapper.properties` | Gradle 8.10.2; **no `distributionSha256Sum`**; `gradle-wrapper.jar` committed |
| Gradle dependency verification | `android/gradle/` | **No `verification-metadata.xml`** |

Three findings fall out of this table before any external source is read:

- **G1 — The "no Google library" rule is not enforced.** ADR-MOB-009 `:38-41` says no Google library may enter the dependency allow-list, but `bannedArtefacts` (`privacy.gradle.kts:122-127`) names only two Firebase artefacts, and `com.google.firebase` appears otherwise only in `networkArtefacts` (`:118`), which blocks it from modules *other than* `:model`. `com.google.android.gms` (Play Services) is not named anywhere. A Play Services library would therefore pass today's gate in any module, and Firebase would pass in `:model`. F-Droid rejects both (S1). [Repo + Primary]
- **G2 — Reproducibility is promised but has no build hook yet.** Nothing to fix before an APK exists, but each of the items in §4 is a one-time setting that is cheaper to add with the first `assembleRelease` than to retrofit. [Repo]
- **G3 — `targetSdk 34` is already below Play's floor.** See §2, row "Play". Irrelevant until M3 under ADR-MOB-009, but it means the "Play later" step now starts with a two-level bump (34 → 36), each level carrying behaviour changes the #807 note tracks. [Repo + Primary]

## 2. Distribution decision matrix

Rows are channels; the last column is the go/no-go **for preparation work**. Publishing on any channel stays an owner action (AGENTS.md, global rules) and stays blocked while there is no app.

| Channel | Upstream rule that binds YazSes | Trust signal it can carry | Cost / risk to the privacy claim | Go/no-go to prepare |
|---|---|---|---|---|
| **GitHub Releases APK** (M1, ADR-MOB-009 `:52`) | None from GitHub. From Android: on certified devices, **unregistered** apps install only via ADB or after the user enables the one-time "advanced flow" (developer mode, coaching check, restart, 24-hour wait, biometric/PIN), and updates to unregistered apps fail once the flow is disabled (S5, answers dated 2026-03-23/25). Enforcement starts 2026-09-30 only for *participating stores* in Brazil, Indonesia, Singapore, Thailand; sideloads are not yet affected; global expansion "in 2027" (S4, S5 answer dated 2026-07-15). [Primary] | Release-asset SHA-256 + signing-certificate fingerprint published in the release notes and in-repo; build provenance attestation from the release workflow [Assumption: mirrors the desktop release practice; not checked here]; reproducible-build claim once §4 holds | Lowest process cost. **New risk not in ADR-MOB-009:** from 2027 an unregistered GitHub APK puts every non-ADB user through a 24-hour friction flow. Registration requires identity verification (government ID for a full account, $25 fee for a Full Distribution ADC account; S5) — a personal-data decision for the owner | **Go** (prepare signing, checksums, reproducibility). **Owner decision O1** on registration before the first public APK, see §7 |
| **F-Droid main repo** (M2) | FLOSS licence; 100% FLOSS toolchain; dependencies built from source or from a trusted Maven repo (Maven Central, Google Maven, …); proprietary ad/tracking SDKs, Firebase, Crashlytics, Play Services banned; "must not download additional executable binary files" without explicit opt-in consent (S1) | Built from source by F-Droid; anti-feature labels shown to users (S2); with reproducible builds, F-Droid can publish the **developer-signed** APK only after its rebuild matches (`Binaries:` + `AllowedAPKSigningKeys`), so one signing key exists across GitHub and F-Droid (S3) | Model download: S1 does not address data files fetched at runtime [Unknown]; weights are not executables, but whether reviewers apply **NonFreeAssets** or **NonFreeNetworkServices**/**TetheredNetworkServices** (S2) to an upstream-hosted model is a reviewer call. ADR-MOB-006 sideload path (`:45-49`) is the strongest counter: the app works with no YazSes-chosen host | **Go** for #96 preparation (recipe draft, scanner dry run on a fork) once a `foss` flavour and native build exist; **no-go** for submission until M2 and a device-tested M1 |
| **IzzyOnDroid** | [Unknown] — not read in this pass | Reproducible-build badge [Press/Unknown] | Same APK as GitHub | **Defer**; read its inclusion rules before M2 |
| **Accrescent** (M2) | [Unknown] — requirements page returned 404 on 2026-11-06 (S10) | ADR-MOB-009 `:28-29` cites Accrescent as a neighbour's channel; not verified here | [Unknown] | **Defer**; re-read when M2 is planned |
| **Google Play** (M3+) | New apps/updates must target **API 36** from 2026-08-31 (extension to 2026-11-01 on request); existing apps must target 35 to stay visible to new users on newer Android (S6). Data safety form mandatory, privacy-policy link mandatory; data "only processed locally on the user's device and not sent off device" is not "collected"; "Voice or sound recordings" is an audio data type (S8). Play adds encrypted dependency metadata to the signing block unless disabled (S7) | Data safety "No data collected"; Play App Signing auto-registers the package for developer verification (S5) | Highest process cost; keyboard + `RECORD_AUDIO` scrutiny (ADR-MOB-009 `:26-27`); a Play-only build artefact (dependency block, Play App Signing key) diverges from the F-Droid byte-for-byte story unless kept in the `full` flavour only | **No-go** until M3 (unchanged). G3 recorded |
| **OEM stores, Huawei/Galaxy, Aptoide** | Not researched | — | — | Out of scope |

## 3. Dependency and licence audit checklist (for every Android PR that adds a dependency, and before each release)

Items marked **[gate]** can be automated in `privacy.gradle.kts`; the rest are review items.

1. **[gate] Banned namespaces in the `foss` flavour, at any depth:** `com.google.android.gms`, `com.google.firebase`, `com.google.android.play` (Play Core/feature delivery), `com.google.mlkit` [Assumption: ML Kit pulls Play Services], plus the existing analytics list (`privacy.gradle.kts:122-127`). Closes G1. Proposal only, see §8.
2. **[gate] Source of every artefact** is Maven Central or Google Maven (S1's trusted list); a `flatDir`/local `.aar`/`.jar`/`.so` in the `foss` graph fails. ADR-MOB-009 `:92-93` already rejects prebuilt `.so`/AAR in the default build.
3. **[gate] Network containment** unchanged (`privacy.gradle.kts:116-119`): network clients only in `:model`.
4. **Licence** of each new artefact recorded (SPDX id) and compatible with Apache-2.0 distribution; any non-FLOSS licence blocks the `foss` flavour (S1).
5. **Native code** (whisper.cpp under ADR-MOB-005): built from a pinned source revision in-tree or as a submodule; NDK version pinned exactly (S3 lists NDK version as a reproducibility factor).
6. **Model catalogue entries** (`models.json`): SPDX licence, upstream URL pinned to a commit, SHA-256 — already required by its `_schema`. Add: is the licence open-weights (ADR-MOB-006 `:53-54`)? Is the host a third party the listing must name (S2 TetheredNet risk)?
7. **Gradle wrapper**: add `distributionSha256Sum` to `gradle-wrapper.properties` [Assumption: standard Gradle wrapper property; source not read in this pass] and validate `gradle-wrapper.jar` in CI. [Unknown: whether fdroidserver's scanner accepts a committed wrapper jar; check before #96 submission.]
8. **Dependency verification** (`gradle/verification-metadata.xml`): Google recommends it when adding dependencies (S7 note). Decide in #96 whether the maintenance cost is acceptable for a volunteer project.
9. **Play dependency-info block** disabled in `foss` (`dependenciesInfo { includeInApk = false; includeInBundle = false }`, S7): it is data "encrypted by a Google Play signing key" that no F-Droid reviewer or user can read, and it changes the signing block. [Assumption: F-Droid asks for this to be disabled; S3 as summarised does not mention it — confirm on the F-Droid docs before relying on it.]

## 4. Release evidence policy (proposal)

A release note for `android-vX.Y.Z` (tag scheme per ADR-MOB-009 `:55-58`) states, for each claim, which evidence class backs it. Nothing is claimed above its class.

| Claim in a listing or release note | Minimum evidence | Class |
|---|---|---|
| "Builds from source with no proprietary dependency" | `foss` dependency graph gate green on the tagged commit (§3.1-3.3) | CI-only |
| "Reproducible" | Two independent clean builds of the tag (different machine or container, same toolchain pins) produce byte-identical unsigned APKs, *and* signature copying (`apksigcopier`-style, S3) verifies; record both build environments | CI-only, plus one independent rebuild |
| "Signed by YazSes" | Certificate SHA-256 fingerprint printed in the release note and in a tracked file; same fingerprint as previous releases | Release artefact |
| "No network access except the model download you start" | Manifest golden diff (`android/privacy/manifest-golden.txt`) unchanged except the reviewed `INTERNET` line for `:model`; airplane-mode round trip (ADR-MOB-009 `:66-69`) | CI emulator (instrumented) |
| "Works with network access revoked" | ADR-MOB-006 `:48-49` automated test on emulator, **and** one physical device | Verified-on-device |
| "Dictation works in app X / on Android N / OEM Y" | Device report naming build, device, OS build, date | Verified-on-device only |
| "Accessible with TalkBack" | Device session with TalkBack; never inferred from lint | Verified-on-device only (see #811) |
| "Collects no data" (Play Data safety) | Same evidence as the network row; S8's definition of "collected" | CI + review |

Words a listing must not use without the matching row: "secure", "private by design" as an unqualified superlative, "verified", "audited", "works on all Android phones". "Offline" is always followed by its one exception (ADR-MOB-009 `:71-72`).

Build settings that make the "Reproducible" row reachable, from S3's list of common causes: no embedded timestamps; pinned JDK and NDK; consistent build path or `-ffile-prefix-map` and `--build-id=none` for native code; deal with `baseline.prof`/`baseline.profm` variance; build from a clean, tagged tree (VCS info); note that `apksigner` from build-tools 35.0.0-rc1 on can produce APKs `apksigcopier` cannot verify (S3) — so the signing tool version is a pinned release input, not "latest".

## 5. Go/no-go summary

- **Now (pre-M1):** go on G1 gate hardening and §3 checklist adoption in docs (owners #96 / the Android CI issue); everything else waits for a `foss` flavour and a native build. **No submission, no account, no listing.**
- **M1 GitHub APK:** go only after O1 (§7) is decided and the §4 rows "Signed", "No network", "Works with network revoked" hold. A device-test row with no device report is shown as "not yet tested", not omitted.
- **M2 F-Droid:** go after the reproducible row holds for at least one tag and #96's recipe builds on F-Droid's tooling in a fork dry run.
- **M3 Play:** unchanged no-go; first task is the 34 → 36 bump with the #807 behaviour-change pass.

## 6. Resource-light evaluation plan

CI-only checks need no device; device checks are listed so nobody claims them from CI.

| ID | Check | Needs | Class |
|---|---|---|---|
| T-D1 | Inject `com.google.android.gms:play-services-base` into a throwaway `:core:*` module; the gate must fail with the fix text | Gradle, no device | CI-only (after G1 fix) |
| T-D2 | Build the release tag twice in two clean containers; `diffoscope`/byte compare unsigned APKs | Two runners | CI-only |
| T-D3 | `fdroid build` / scanner dry run of a draft recipe on a fork | fdroidserver container | CI-only |
| T-D4 | Verify release-note fingerprint matches `apksigner verify --print-certs` on the published asset | One runner | CI-only |
| T-D5 | Install the GitHub APK on one certified device per supported Android major with "install unknown apps" off, then on; record every dialog; after 2027 enforcement, also with the advanced flow off (registered vs unregistered) | Devices or emulator images with Play services | **Device** — answers the #806/#809 note's open question |
| T-D6 | Airplane-mode round trip after the model is present | Emulator | CI emulator |

Edge cases to cover: upgrade across a signing-key mismatch (F-Droid-signed vs developer-signed installs cannot update each other — S3's developer-signed mode avoids that split); an expired or pulled model URL (ADR-MOB-006 `:71-74`); an F-Droid reviewer applying an anti-feature after submission (listing text must tolerate it).

Costs: none of T-D1–T-D4 records audio or needs a model download. T-D5 needs Play-certified hardware; no private dictation is involved.

## 7. Owner decisions surfaced (not taken here)

- **O1 — Developer verification registration.** From 2027, on certified devices, an unregistered GitHub/F-Droid APK installs only via ADB or the advanced flow (S5). Options: (a) register `com.yazses.android` (`android/app/build.gradle.kts:12`) and the release key through the Android Developer Console (full account: ID verification, $25; S5); (b) stay unregistered and document the advanced flow and ADB as the install path; (c) decide at M2. The ADC "lets you add and verify multiple signing keys for a single package" (S5), which would also cover an F-Droid-signed build; a reproducible developer-signed F-Droid listing avoids needing a second key at all. Registration discloses the developer's identity to Google but, per S5, "does not collect information about the app content or functionality" — it does not add a network call to the app. This is the owner's personal-data and policy decision.
- **O2 — Signing-key custody.** ADR-MOB-009 `:59-65` already decides; S5 adds that a lost key also means "you won't be able to register your packages". No change, reinforcement only.

## 8. Link to #81 work and proposed ADR note

- **#96** (F-Droid, OPEN): takes §3 items 1-2, 5, 7-9, §4 reproducibility settings, T-D2/T-D3.
- **#81** epic: §4 is a candidate release-evidence checklist for its M1 exit criteria.
- **#806/#809 note**: T-D5 answers its "propose adding one to #810" request.
- **#812 matrix** row 8: this note supplies the "trust signals" it deferred; its verdict "Supported, no change to the decision" still holds for channel order.

**Proposed ADR-MOB-009 amendment (Proposed, not accepted; maintainer decides):** add to *Consequences*: "Android developer verification (S4, S5) applies to certified devices running Android 7+, enforced first for participating stores in four countries from 2026-09-30 and globally from 2027. Before the first public APK the maintainer decides whether to register the package and release key (§7 O1 of the 2026-11-06 distribution note). Reproducible, developer-signed F-Droid publication is preferred because it keeps one signing key across channels." Backward compatible: it adds a pre-release decision and does not change channel order, flavours or signing.

**Proposed gate change (code, not in this note's scope):** extend `bannedArtefacts` in `android/gradle/privacy.gradle.kts:122-127` for the `foss` flavour as in §3.1, with T-D1 as its test. Needs the flavour to exist first.

## 9. Sources (all read 2026-11-06)

- S1 F-Droid Inclusion Policy — https://f-droid.org/docs/Inclusion_Policy/ [Primary]
- S2 F-Droid Anti-Features — https://f-droid.org/docs/Anti-Features/ [Primary]
- S3 F-Droid Reproducible Builds — https://f-droid.org/docs/Reproducible_Builds/ [Primary]
- S4 Android developer verification overview — https://developer.android.com/developer-verification [Primary]
- S5 Android developer verification FAQ — https://developer.android.com/developer-verification/guides/faq [Primary; per-answer dates 2025-09-03 to 2026-09-30 as printed]
- S6 Meet Google Play's target API level requirement — https://developer.android.com/google/play/requirements/target-sdk [Primary]
- S7 Add build dependencies, "Dependency information for Play Console" — https://developer.android.com/build/dependencies#dependency-info-play [Primary]
- S8 Play Console Help, Data safety section — https://support.google.com/googleplay/android-developer/answer/10787469 [Primary]
- S9 Press coverage of the verification timeline (androidauthority.com, gsmarena.com, 9to5google.com; found by search, not read in full) [Press; used only to cross-check S4/S5]
- S10 Accrescent requirements — https://accrescent.app/docs/guide/publish/requirements.html returned HTTP 404 [no content]

Issue states checked with `gh issue view` on 2026-11-06: #810, #96, #81, #789 OPEN. Issue bodies were read as task descriptions only.
