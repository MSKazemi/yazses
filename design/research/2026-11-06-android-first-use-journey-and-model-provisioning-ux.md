# Research: Android first-use journey and model-provisioning UX

**Issues:** [#806](https://github.com/MSKazemi/yazses/issues/806) (first-use journey) and [#809](https://github.com/MSKazemi/yazses/issues/809) (model download, sideload and provenance UX), parent [#789](https://github.com/MSKazemi/yazses/issues/789); feeds the implementation issues [#91](https://github.com/MSKazemi/yazses/issues/91) (onboarding), [#90](https://github.com/MSKazemi/yazses/issues/90) (`:model`) and [#89](https://github.com/MSKazemi/yazses/issues/89) (`:feature:ime`), epic [#81](https://github.com/MSKazemi/yazses/issues/81)  
**Snapshot:** YazSes `main` at `4695e49a`, inspected 2026-11-06. Issue states checked with `gh issue view` the same day (section 8).  
**Status:** Research note, not a decision. ADR-030 freeze unchanged. Evergreen research (no milestone).  
**Scope:** documentation only. No `android/` change, no ADR edited, no APK, no emulator or device run, **no user testing and no participant data**. Nothing here says a step works on a phone. It describes what the code and ADRs already commit to, where the journey can fail, and how a later test could measure that.

This note does not repeat the ADR-by-ADR findings of the [traceability matrix](2026-11-06-android-adr-traceability-matrix.md) (#812) or the platform constraints of the [#807 note](2026-11-05-android-api-levels-and-oem-ime-microphone-restrictions.md). It cites their row, constraint (`C#`) and device-test (`T#`) numbers instead.

## 1. Labels

- **[Code]** read at the cited `file:line` in this checkout. "Code" means JVM-tested pure Kotlin unless stated; none of it is wired to a UI, a WorkManager job or a network client yet.
- **[ADR]** stated by an Accepted mobile ADR at the cited line. A design commitment, not an observation.
- **[#807] / [#812]** taken from those notes, with their own caveats (sources read as tool summaries; no devices).
- **[Gap]** the ADR or issue asks for something that no code or catalogue field provides today.
- **[Assumption]** my inference, stated so it can be challenged.
- **[Unknown]** needs a source or a device; marked with the device test that would answer it.

## 2. What exists today [Code]

| Piece | Where | State |
|---|---|---|
| Catalogue schema and validation (id slug, unique ids and digests, 64-hex SHA-256, positive size, `https://` with a DNS host, non-blank licence) | `android/core/model/src/main/kotlin/com/yazses/core/model/ModelCatalogue.kt:15-26`, `:108-135`, `:143-162` | Pure, tested (28 `@Test` in `ModelCatalogueTest.kt`) |
| Catalogue data: two entries, `tiny.en` and `base.en`, MIT, URLs pinned to a Hugging Face commit | `android/app/src/main/assets/models.json:2`, `:5-22` | In repo; pinning closed [#683](https://github.com/MSKazemi/yazses/issues/683), checksums closed [#675](https://github.com/MSKazemi/yazses/issues/675) |
| Download decision: refuse / wait / start | `.../core/model/DownloadPolicy.kt:71-90` | Pure, tested (20) |
| Install ordering: temp name, verify, then rename | `.../core/model/InstallPlan.kt:3-6`, `:75-139` | Pure, tested (18) |
| Resume planning from a partial file | `.../core/model/ResumePlan.kt:31-41` | Pure, tested (10) |
| SHA-256 verification, sideload classification, acknowledgement label | `.../core/model/ModelVerifier.kt:50-53`, `:113-136` | Pure, tested (17); on-device run is open [#674](https://github.com/MSKazemi/yazses/issues/674) (API 26-33, no `HexFormat`, see `:77-78`) |
| `:model` module (the download job, the only `INTERNET` holder per MOB-007) | `android/model/src/main/kotlin/com/yazses/model/Placeholder.kt:3`, `android/model/src/main/AndroidManifest.xml:2` | **Placeholder**; its manifest is empty, so `INTERNET` is **not declared yet** |
| Merged-permission golden file | `android/privacy/manifest-golden.txt:5` | Lists `RECORD_AUDIO (:platform:audio)` only |
| Network containment gate | `android/gradle/privacy.gradle.kts:130` (`networkAllowedModules = setOf(":model")`) | Build-time gate exists |
| Capture stop reasons (`REQUESTED`, `PERMISSION_LOST`, `PREEMPTED`, `ERROR`) | `android/platform/audio/src/main/kotlin/com/yazses/platform/audio/MicrophoneCapture.kt:15-28` | Compiles; never run on a device (`android/README.md:87-88`) |
| Delivery refusals (`NOT_DECODING`, `SECURE_FIELD`, `BLANK_TEXT`) | `android/core/session/src/main/kotlin/com/yazses/core/session/DeliveryGuard.kt:16-25`, `:31-36` | Pure, tested |
| Onboarding, IME, settings, storage screen | `android/feature/{ime,settings}/.../Placeholder.kt`, `android/app/.../Placeholder.kt` | **None exist** (`android/README.md:79`: "There is still no app.") |

So the journey below is a specification against real pure logic and ADR text; every UI step is still to be built in #89, #90 and #91.

## 3. Annotated first-use journey

Each step lists the commitment, the measurable failure (what an observer or test can count), and the recovery path. "Measure" names a signal a synthetic run can record without capturing any speech content.

### J0. Install (sideloaded APK or F-Droid; Play later per MOB-009)

- **Commitment:** the APK carries code and the catalogue, no weights [ADR, MOB-006:32-33]. `minSdk` 26, `targetSdk` 34 [Code, `android/gradle/libs.versions.toml:12-13`].
- **Failure, measurable:** install refused (unknown-sources not allowed, signature conflict with an older build, API < 26). Measure: installer outcome and the screen the user stops on.
- **Recovery:** install guide per channel (owned by MOB-009 / [#810](https://github.com/MSKazemi/yazses/issues/810), not researched here).
- **Unverified:** OEM installer wording and "unknown sources" flow by API level [Unknown; no device test exists for it in T1-T12; propose adding one to #810].

### J1. First launch and the honest-limits screen

- **Commitment:** state the limits before the user is disappointed: phone-class model, English-first, a model download is needed [#91 body, "What to build" item 4]. The two catalogue models are both `.en` [Code, `models.json:6`, `:15`], so "English-first" is literally true of the catalogue today.
- **Failure:** user leaves before J2. Measure: drop-off at this screen in the scripted run (section 5); TalkBack reads every element (#91 acceptance).
- **Recovery:** none needed beyond a clear "Continue"; the claim set must match the ADRs line by line (#91 acceptance).

### J2. Enable the keyboard (two system Settings screens) and answer the warning

- **Commitment:** two-step enable-then-select; address the system "may collect all the text you type" warning truthfully: no typing surface, no network permission on the recognition path, source public [ADR, MOB-003:76-81]. The recognition path's lack of network is build-enforced [ADR, MOB-007:52-57; Code, `privacy.gradle.kts:130`].
- **Failure:** (a) user does not return from Settings; (b) returns with the keyboard enabled but not selected; (c) abandons at the warning dialog. Measure: which of (a)-(c), and the time from leaving to returning. Detecting "enabled" and "selected" is an #91 deliverable ("detect when it worked").
- **Recovery:** re-entry card that says which of the two steps is missing and deep-links back.
- **Copy caution [Assumption]:** "no network permission in the recognition path" is true of the build gate; the *app* will hold `INTERNET` (in `:model`) once #90 lands. The explainer must say "the app can reach the network only to download the model you choose", not "this app has no internet access", or it fails #91's "every claim true today" rule.
- **Unverified:** Settings paths and picker differ by version and OEM [#807 section 5; T11].

### J3. Microphone permission, requested in context

- **Commitment:** each permission at the moment it is first needed, never all at launch [ADR, MOB-007:123-124]. `RECORD_AUDIO` needs an `Activity` to request, so the IME must hand off to an onboarding activity [#807 C5].
- **Failure:** denied once; denied twice (permanent); "only this time" grant later expiring; auto-reset after disuse; the device-wide mic toggle off, which yields **silent audio, not an error** [#807 C4-C6]. Measure: grant state after the step, and whether a later burst reports `PERMISSION_LOST` versus silence.
- **Recovery:** permanent denial needs an "Open app settings" path, not a re-prompt. A silent burst must read "microphone muted or unavailable", not "didn't catch that" [#812 row 12]. `CaptureStopReason.PERMISSION_LOST` already separates revocation from a fault [Code, `MicrophoneCapture.kt:10-21`]; there is no reason yet for "toggle off" or "silenced" [Gap; #812 row 5 for the API 29+ silencing signal].
- **Unverified:** whether hold-to-talk from a visible IME captures audio at all without a foreground service [#812 row 1, section 3; T1]. This is the premise the whole journey stands on.

### J4. Model choice and consent to one download

- **Commitment [ADR, MOB-006:34-38]:** the chooser shows size, device-class suitability and licence; nothing downloads before an explicit tap; the screen says this is the only network request and network can be disabled afterwards. Licence and upstream URL shown before download [MOB-006:53-54].
- **What the code enforces [Code]:** a download stays at `Wait(NEEDS_CONFIRMATION)` until the caller passes `userConfirmed = true`, which must never be inferred from a settings switch (`DownloadPolicy.kt:61-65`, `:83`); refusals come first and no setting overrides them (`:59-60`, `:80-82`).
- **Storage estimate, from the catalogue [Code, `models.json:9`, `:17`]:**

  | Model | `sizeBytes` | Shown as (SI) | (binary) |
  |---|---|---|---|
  | `tiny.en` | 77,704,715 | 77.7 MB | 74.1 MiB |
  | `base.en` | 147,964,211 | 148.0 MB | 141.1 MiB |

  Peak extra space during an install is about one `sizeBytes`, because the bytes go to `<id>.<sha12>.part` and are renamed into place (`InstallPlan.kt:95-96`, `:3-6`) [Assumption: the temp file is on the same filesystem as the final file, so the rename does not copy]. Replacing a model keeps the old one until the new one is installed, so two models coexist briefly [Assumption about #90's design]. Pick one unit system for the UI and use it everywhere; the catalogue's integer bytes are the source.
- **Gaps:**
  - **Device-class suitability:** `ModelEntry` has no RAM/SoC field (`ModelCatalogue.kt:15-26`); MOB-006:59-61 says the hint comes from `:bench` reports, which do not exist yet ([#92](https://github.com/MSKazemi/yazses/issues/92)). Until then the chooser can show size only, and must not invent a recommendation.
  - **Licence notice:** the catalogue carries a licence *identifier* (`"MIT"`, `models.json:11`), not the licence text or a link to it. The About screen (#91 item 5) needs the text; where it comes from is undecided.
  - **No free-space check:** `DownloadPolicy.decide` takes network and battery but not available storage (`DownloadPolicy.kt:71-79`), so "not enough space" has no decision today.
- **Failure, measurable:** user cannot tell which model to pick; user taps without having seen the size (a defect by MOB-006:35-36); user on mobile data is surprised. Measure: time on screen, whether size/licence/source were on screen at the tap (UI test assertion), and decision on `METERED` with default settings (`WAITING_FOR_WIFI`, `DownloadPolicy.kt:87`; Wi-Fi-only default `:14-16`).
- **Recovery:** "Use mobile data for this download" as an explicit, size-stating action; "Import a file instead" (J6) always visible.

### J5. Download, verify, install

- **Commitment [ADR, MOB-006:39-44]:** resumable, cancellable, Wi-Fi-only by default, HTTPS only, SHA-256 verified before the file becomes visible, atomic rename, readable failure state; a mismatch deletes the file and is reported loudly, never retried.
- **What the code enforces [Code]:** `InstallPlan` yields `Installed` only from a `Verified` result for the same entry (`InstallPlan.kt:109-124`, `:131-139`); a result for another model is `WrongModel` (`:115-118`). The temp name embeds 12 digest characters, so a catalogue that changes a digest under the same id never resumes stale bytes into the new model (`:89-96`). `ResumePlan` resumes only when the server supports ranges, restarts otherwise, and calls an over-long partial `Corrupt` (`ResumePlan.kt:31-41`). URLs are pinned to a commit (`models.json:2`), which is what makes byte-range resume against an unchanged file safe [Assumption: a pinned Hugging Face `resolve/<commit>` URL serves identical bytes over time].
- **Failure states and what the user should see:**

  | Decision / outcome | Source | User-facing meaning | Recovery |
  |---|---|---|---|
  | `Wait(NO_NETWORK)` | `DownloadPolicy.kt:85` | "Waiting for a connection" | Auto-resume when connected; "Import a file instead" |
  | `Wait(WAITING_FOR_WIFI)` | `:86` | "Waiting for Wi-Fi (148 MB)" | Explicit mobile-data opt-in |
  | `Wait(BATTERY_LOW)` | `:87` (default is an inference, `:9-12`) | "Paused: battery low" | Charge, or explicit override |
  | `Refuse(UnsafeSource)` / `Refuse(NotInCatalogue)` | `:80-81` | Programming or packaging error | Report a bug; sideload |
  | `Refuse(PREVIOUS_MISMATCH)` | `:82`, `:45-50` | "The last download of this model did not match its checksum" | **Gap:** clearing the id needs "a deliberate user action, which this module does not model" (`:47-48`). Spec it: a separate "Try again from scratch" tap that deletes the partial, plus sideload |
  | `Rejected.Mismatch` | `InstallPlan.kt:46-47` | Security event | Delete, report, no auto-retry (MOB-006:43-44) |
  | `ResumePlan.Corrupt` | `ResumePlan.kt:22-23` | Partial file is wrong | Discard partial, restart on the user's tap |
  | Dead upstream URL (HTTP error, DNS failure) | not modelled in `:core:model` | "Source unavailable" with a sideload suggestion, never a hang | #90 acceptance; MOB-006:71-74 |

- **A UX trap in the resume path [Assumption, from the code shape]:** resumed bytes are not checked until the whole file is hashed. A partial damaged by an interrupted write ends as `Mismatch`, which the ADR treats as a security event with no retry. On a flaky connection the user could see a "substituted model" warning for what was a storage glitch. The wording should state the fact ("the file did not match its expected checksum and was deleted") without asserting tampering, and offer the deliberate restart above. This keeps MOB-006's no-automatic-retry rule intact.
- **Platform caveats [#807, #812]:** Doze, standby buckets and Android 16 job quotas may defer or stop a WorkManager job (C12, C13); #812 row 11 already asks #90 to require resume after process death with visible progress. Not re-argued here.

### J6. Air-gapped sideload (first-class alternative to J4-J5)

- **Commitment [ADR, MOB-006:45-49]:** import via SAF or `adb push`; verified against the catalogue when known, accepted with an explicit "unverified, you supplied this" marker when not; the app is fully functional with network permanently denied, proven by an automated test.
- **What the code enforces [Code]:** a sideload with no expected entry is `Verified` if its digest is in the catalogue, else `UnknownSideload` only when an `UnverifiedAcknowledgement` is passed, else `UnverifiedRefused` (`ModelVerifier.kt:130-135`). A malformed digest fails closed before anything else (`:119`). The words the user must have accepted are fixed: `"unverified — you supplied this"` (`:50-53`). `InstallPlan` refuses to treat a download result as a sideload (`InstallPlan.kt:119-120`).
- **Storage:** an SAF import copies the file into app-private storage (MOB-006:50-51), so the device briefly holds the user's copy plus the app's [Assumption about #90's import design]. Same `sizeBytes` table as J4 for catalogue models; unknown files have no declared size.
- **Failure, measurable:** user cannot find the file in the SAF picker; file is a catalogue model with a wrong digest (`Verified` cannot happen, the result is `UnverifiedRefused` or, if acknowledged, an unverified install of corrupt bytes [Gap: for a *known-name* file the UI should say "this does not match <model>", but the verifier is digest-only by design]); user does not understand the unverified label. Measure: picker abandonment, and whether the acknowledgement screen showed the exact label before the tap (UI assertion).
- **Recovery:** show the computed SHA-256 so a careful user can compare it with the upstream page; link to the catalogue entry list.

### J7. Revoking network after the download

- **Commitment:** after the download the user "can disable network access for this app entirely and dictation will keep working" [ADR, MOB-006:36-38]; an airplane-mode round trip is a CI gate [ADR, MOB-007:67-69]; #90 acceptance: airplane mode plus a sideloaded model works end to end.
- **Unverified [Unknown]:** whether a given device offers a per-app "deny all network" control is not established by any source this note or the #807 note read. Airplane mode is the portable test. The onboarding copy should say how to do it on the device in front of the user, or fall back to airplane mode, instead of implying a control that might not exist. This is a copy point for #90/#91, not a design change.
- **Measure:** decode a fixture with networking off (MOB-007:67-69) and confirm no model operation needs the network after `Installed`. Nothing in `:core:model` touches the network (`DownloadPolicy.kt:53`, `ModelVerifier.kt:55-58`), so verification of an installed file can be repeated offline.

### J8. First hold-to-talk

- **Commitment:** press-and-hold the mic key, release to decode and deliver; hold/toggle switch defaulting to hold [ADR, MOB-004:41-47].
- **Failure, measurable:** stray tap below the hold threshold (no burst, by design); finger slides off (MOB-004:75); silent buffer (J3); decode produces nothing (`BLANK_TEXT`, `DeliveryGuard.kt:23-24`). Measure: burst started yes/no, stop reason (`MicrophoneCapture.kt:15-28`), delivery decision.
- **Recovery:** a visible "hold to talk" hint after a too-short tap; distinct messages for permission, muted mic, and "nothing recognised".
- **Unverified:** the visible-IME capture premise [#812 row 1; T1]; first-burst latency after a cold start [#812 row 10; T7].

### J9. Choosing (and losing) a text target

- **Commitment [ADR, MOB-003:57-61, :84-88]:** delivery by `InputConnection.commitText`; with no `InputConnection` or a failed commit the transcript goes to the clipboard and the user is told, never dropped; password fields disable the mic and say why.
- **What the code enforces [Code]:** secure fields are refused before blank text (`DeliveryGuard.kt:31-36`). There is **no "no target" refusal** in `DeliveryGuard` (`:16-25`) [Gap or layering choice: the clipboard fallback may belong in `:feature:ime` (#89)]. Either way, the journey needs an observable outcome for it.
- **Failure, measurable:** text inserted into the wrong field (focus moved during decode); no field focused; secure field. Measure: delivery outcome per synthetic target app (plain field, browser field, password field, no focus).
- **Recovery:** clipboard plus a toast naming what happened; for secure fields, the mic key disabled with a reason before the user speaks.

## 4. Threat-model notes for model provenance (#809)

| Threat | Control in code or ADR | Residual |
|---|---|---|
| Upstream file replaced | Commit-pinned URL (`models.json:2`) and in-APK SHA-256 (`ModelVerifier.kt:120-128`) | APK signing protects the digest (MOB-006:75-77); a compromised build pipeline is out of scope here |
| Catalogue edited to point elsewhere | `https` + DNS host, no userinfo, no localhost or IP literal (`ModelCatalogue.kt:143-162`); additions are reviewed PRs (MOB-006:55-58) | Review quality |
| Partial bytes from an old digest resumed into a new model | Digest prefix in the temp name (`InstallPlan.kt:89-96`) | None found |
| Unknown file accepted silently | Requires `UnverifiedAcknowledgement` (`ModelVerifier.kt:46-53`, `:133-134`) | The user can still accept a malicious file; the label is the control |
| Malformed digest treated as a match | Fails closed (`ModelVerifier.kt:119`) | None found |
| `Verified` forged by a caller | `InstallOutcome` constructors are `internal`; documented as *not* a hard boundary (`InstallPlan.kt:28-33`) | Accepted in-code; a review point for #90 |
| Download as usage telemetry | No YazSes server; upstream host only (MOB-006:55-58, :89-91) | The upstream host sees the request; the store declaration must say so (MOB-007:97-99) |

## 5. Synthetic usability script (no participant data)

**Purpose.** A repeatable walkthrough that a contributor runs alone on an emulator, to find dead ends and missing recovery paths before any real user sees the app. It is a cognitive walkthrough with fault injection, not a user study, and its results must be reported as such.

**Rules.** No real dictation and no recordings of anyone's voice: use synthetic audio fixtures (generated speech, or the project's existing contract fixtures) fed through the test audio path, or silence. No analytics or third-party SDK installed to measure anything. Record only metadata: step, timestamps, decision/outcome names, screen identifiers. Nothing is uploaded.

**Setup per run.** Record: emulator image API level (26, 29, 31, 34 at minimum, matching #807 section 4 and #674/#686), whether the run is emulator or device, the app commit, and which faults are injected.

| # | Task given to the walker | Inject | Pass signal | Failure to count |
|---|---|---|---|---|
| S1 | "Install and open the app" | none / API 25 image | Reaches J1 | Install refused, no explanation |
| S2 | "Turn on the YazSes keyboard" | Return from Settings without selecting | Re-entry card names the missing step | Stuck, or "done" shown while not selected |
| S3 | "Allow the microphone" | Deny twice; then "only this time"; then mic toggle off | Correct message per case | Re-prompt after permanent denial; silence reported as "nothing heard" |
| S4 | "Pick a model and download it" | Metered network; airplane mode; low battery | `WAITING_FOR_WIFI` / `NO_NETWORK` / `BATTERY_LOW` shown in words with size | Download starts without a tap; size/licence/source not on screen at the tap |
| S5 | "Finish the download" | Kill the process at 50 %; server without range support; truncate the partial; flip one byte | Resume or restart as `ResumePlan` decides; mismatch deletes and reports | Hang; half-usable model; automatic retry after mismatch |
| S6 | "Download again after a failed check" | Previous mismatch recorded | Deliberate restart path exists | Dead end (today's gap in J5) |
| S7 | "Install a model from a file with no internet" | Catalogue file; unknown file; malformed file | Verified / acknowledgement screen with exact label / refusal | Unknown file installed without the label |
| S8 | "Turn off internet and dictate" | Airplane mode after install | Fixture decodes and delivers | Any network-dependent error |
| S9 | "Dictate a sentence into a note" | Too-short tap; finger slide-off | Burst outcome and hint | No feedback |
| S10 | "Dictate into a password box / with nothing selected" | Secure field; no focus | Mic disabled with reason / clipboard plus notice | Text dropped silently |

**Metrics.** Per task: completed yes/no, time, number of screens visited, the failure row reached, and whether a recovery path existed and was found. Aggregate as counts per step; with one walker there is no statistic, and the write-up must not imply one.

**What CI can already cover today [Code].** S4-S7's decisions are pure functions: a table-driven JVM test could assert each fault's decision (`DownloadPolicy`, `ResumePlan`, `InstallPlan`, `ModelVerifier`). Most of those cases already have tests (section 2 counts). Everything involving a screen, Settings, WorkManager, SAF or audio needs the app and is emulator- or device-only.

## 6. What remains unverified

- Every UI step: nothing in `:feature:*`, `:app` or `:model` exists beyond placeholders (section 2).
- The visible-IME capture premise behind J3/J8 [#812 row 1; T1].
- OEM variation in the keyboard-enable flow, the IME picker, mic indicator wording and installer prompts [#807 section 5; T11].
- Behaviour on API 26-33 for the SHA-256 path (no `HexFormat`; [#674](https://github.com/MSKazemi/yazses/issues/674) open) and on 26/29/31/34 images generally (#686).
- Download job deferral under Doze, buckets and Android 16 quotas [#807 C12-C13; T6].
- Whether a device offers a per-app network kill switch (J7).
- Device-class suitability: no measurements exist (#92).

## 7. Proposals (none applied)

For the owning issues; none is an ADR change, and nothing here is labelled accepted.

1. **#90:** add a pure free-space decision beside `DownloadPolicy` (J4); model the deliberate "clear previous mismatch" action (J5, `DownloadPolicy.kt:47-48`); map each `WaitReason`/`RefuseReason`/`Rejected` to one user message using the table in J5; word a mismatch as a checksum fact, not an accusation.
2. **#90 / #91:** decide where licence *text* comes from (J4) and how the About screen shows it.
3. **#91:** copy rules from J2 ("network only for the model download you choose") and J7 (name the device's control or fall back to airplane mode).
4. **#89:** state where the no-`InputConnection` clipboard fallback lives and give it an observable outcome (J9).
5. **#92 → #90:** no "recommended for your device" hint until `:bench` data exists (J4).
6. **ADR amendment:** not justified by this note. The one wording question, MOB-006:36-38's "disable network access for this app entirely", is a copy issue for #91 unless T-style evidence shows no device offers such a control; if a maintainer prefers ADR wording, it should go into the #98 review batch with #812's A1-A6.

## 8. Verification record

Read in this worktree at `4695e49a`: the `:core:model` sources and test files cited, `models.json`, the `:model`, `:app`, `:feature:ime`, `:feature:settings` and `:platform:audio` manifests, `android/privacy/manifest-golden.txt`, `android/gradle/privacy.gradle.kts`, `android/gradle/libs.versions.toml`, `DeliveryGuard.kt`, `MicrophoneCapture.kt`, `android/README.md`, ADR-MOB-003, -004, -006 and -007, the #807 note and the #812 matrix. `@Test` counts from `grep -c "@Test"` on the five `:core:model` test files. Sizes converted from the catalogue's integer bytes.

`gh issue view` on 2026-11-06: #806, #809, #91, #90, #89, #674 and #694 OPEN; #675 and #683 CLOSED. Issue bodies were read as task descriptions only.

**Limits.** No Gradle build, Android test, emulator or device was run for this note. No user was observed. All Android platform behaviour is cited from the #807 note, whose sources were tool summaries.

Related: [#807 note](2026-11-05-android-api-levels-and-oem-ime-microphone-restrictions.md), [#812 traceability matrix](2026-11-06-android-adr-traceability-matrix.md), [ADR-MOB-006](../../docs/mobile/adr/adr-mob-006-model-distribution.md), [ADR-MOB-007](../../docs/mobile/adr/adr-mob-007-privacy-permissions-lifecycle.md), [mobile programme](../../docs/mobile/index.md), [ADR-030](../adr/adr-030-agent-era-direction.md).
