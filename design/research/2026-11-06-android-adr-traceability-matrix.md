# Research: traceability matrix, Android research findings vs ADR-MOB-001..010

**Issue:** [#812](https://github.com/MSKazemi/yazses/issues/812) (parent [#789](https://github.com/MSKazemi/yazses/issues/789); epic [#81](https://github.com/MSKazemi/yazses/issues/81); relates to the M0 design review [#98](https://github.com/MSKazemi/yazses/issues/98) and to [#807](https://github.com/MSKazemi/yazses/issues/807))  
**Snapshot:** YazSes `main` at `1698395d`, inspected 2026-11-06. Issue states checked with `gh issue view` on the same day (section 6).  
**Status:** Research note, not a decision. ADR-030 freeze unchanged. Evergreen research per the [milestone policy](../milestone-policy.md) (no milestone).  
**Scope:** documentation only. No `android/` change, no ADR edited, no APK, **no device was used and no device result is claimed**. Every "verified" label below means "the ADR text was read at the cited line" or "the #807 note states it from a primary source as summarised by a fetch tool"; none means "observed on a phone".

The only input evidence is the single landed research note, [#807](2026-11-05-android-api-levels-and-oem-ime-microphone-restrictions.md) (called "the #807 note"; its `S#` are numbered sources, `C#` constraints, `Q#` questions, `T#` device tests). Its own caveat applies to everything here: its sources were read as tool summaries, two were truncated.

## 1. Labels

| Label | Meaning in the matrix |
|---|---|
| **Supported** | The #807 note cites a primary source (S#) consistent with the ADR claim. |
| **Contradicted-in-wording** | A primary source in the note differs from the ADR's wording; the design intent may still be sound. |
| **Unverified** | The ADR asserts it; the #807 note found no source and says so (`[Unknown]`/`[Assumption]`). |
| **No evidence** | The #807 note did not examine this decision. This is not a finding of correctness. |

Recommendation vocabulary: **No change**, **Small change to an M1 issue** (#87-#92 acceptance text), **Amend ADR (PROPOSED)** (wording drafted in section 4; nothing applied), **Device test first**.

## 2. Matrix

ADR citations are `file:line` under `docs/mobile/adr/`. Alternatives are what the ADR itself rejects, or, where marked, what the evidence newly suggests.

| # | ADR decision (file:line) | #807 evidence | Label | Alternatives | Backward compatibility | Recommendation |
|---|---|---|---|---|---|---|
| 1 | **MOB-003:25, :81-83** and **MOB-007:75-76**, **MOB-004:28-31**: a visible IME window makes the app "in use", so hold-to-talk needs no microphone foreground service | Q4: no source states that an IME may record only while its window is shown, nor how capture policy classifies an IME process; S1 lists "current input method" as an FGS-start exemption, which does not prove the capture rule; S4: background app without FGS or foreground gets silence since Android 9. Section 6 item 1 of the #807 note. | **Unverified** (core premise of M1) | (a) Keep as is and test (T1). (b) Run a short `microphone` FGS only around a hold, started while the IME is the current input method (S1 exemption). (c) Detect silence and surface "mic unavailable". None adopted here. | An FGS adds `FOREGROUND_SERVICE_MICROPHONE` to the `:feature:ime` path and a notification during holds; MOB-007:44 already budgets the permission for `:feature:meeting`, so no new permission, but a new module owner. Removing the FGS later is source-compatible. | **Device test first (T1), then decide.** Proposed ADR note A1 (section 4). Until T1 reports, #89 and #88 must not claim the premise as fact. |
| 2 | MOB-004:57-59 / MOB-007:77-80: Meeting Mode is a user-started `microphone` FGS from a Quick Settings tile, shortcut or in-app button | C7: type and permission mandatory on target 34, creation from background throws (S2, S1, S7). C8: S1's exemption list as read names bubble, notification, widget, activity tap and current IME; a Quick Settings tile start is not named. | **Supported** for the in-app button and shortcut path (as far as an activity is visible); **Unverified** for the tile | Start the FGS only from an activity the tile launches (visible UI first). | No data or API compat issue; a design pre-M3. | **Small change** to Meeting Mode issue text and #97: the tile path must be tested (T5) and may need to route through an activity. No ADR amendment. |
| 3 | MOB-007:28-30: "Android 15+ applies time limits to several FGS types" | C9: S3/S2 document time limits for `dataSync`, `mediaProcessing`, `shortService`, not `microphone`. | **Contradicted-in-wording** (the claim of an applicable limit for the type that matters is not supported by the text read) | None needed; it is a wording issue. #97 remains the empirical check. | Wording only. | **Amend ADR (PROPOSED)**, A2. Keep #97 open (needs devices). |
| 4 | MOB-007:78-80: Meeting Mode "permanent notification" with elapsed time and stop action | C10, S26: FGS starts without `POST_NOTIFICATIONS`; notification then appears only in the Task Manager, not the drawer. FGS notification display may be delayed 10 s (S14). | **Contradicted-in-wording** (permanence depends on a runtime grant) | Make the grant part of the Meeting Mode start flow; refuse to start without it, or start with a non-notification indicator. Design choice, not made here. | Wording only; behaviour change is additive. | **Amend ADR (PROPOSED)**, A3, and **small change** to onboarding #91 (request `POST_NOTIFICATIONS` before first Meeting Mode, handle denial). |
| 5 | MOB-007:83-84 and #88 acceptance "Mic stolen by another app -> clean stop": capture stops on "another app taking the mic" | C1/C3, S4: on API 29+ the app is **silenced, not stopped or errored**; `AudioRecordingCallback` must be registered **before** capture; pre-29 `startRecording` errors if the mic is busy. | **Contradicted-in-wording** (the signal differs by API level and is not an error) | Treat `isClientSilenced` as the stolen-mic signal on 29+, the start error on <29. | #88 is open; the change is to acceptance text, not shipped behaviour. | **Small change to #88** (A4 wording). No ADR amendment strictly needed; MOB-007:83 may be narrowed in the same edit as A2/A3. |
| 6 | MOB-007:39-45 permission table (the manifest is a reviewed artefact) | C7, C10, C20: no `POST_NOTIFICATIONS` runtime rationale, no `foregroundServiceType` manifest note, no Play FGS declaration (S24). | **Supported** (the permissions listed are the right ones); table is **incomplete** (notes only) | Add a notes column; do not add permissions. | Additive documentation; MOB-007:50 requires the table to change with any manifest PR. | **Amend ADR (PROPOSED)**, A5 (notes only). |
| 7 | MOB-002:44-46: minSdk 26, "target the current stable SDK and keep it current" (and the toml comment that 26 is where IME APIs are "consistent") | Q1, section 4: no read source marks 26 as an IME-API boundary; documented boundaries are audio (28/29), mic UI (31), FGS typing (34). C17/S22: Play requires target 36 for new apps and updates from 2026-08-31 (extension to 2026-11-01); repo `targetSdk` is 34. No install-share figure was read. | minSdk rationale **Unverified**; "keep target current" **Supported**; current target is **below the Play bar** (irrelevant to GitHub/F-Droid per C17) | Floor 29 or 31 (#807 section 4): unknown cost, no evidence to move. | Raising minSdk drops devices; not recommended on this evidence. A target bump changes FGS/permission behaviour (MOB-009:84-86). | **No change to minSdk.** **Small change**: reword the toml comment to drop the uncited claim (a code-owner edit, outside this note); schedule a target-bump test pass before any Play work. |
| 8 | MOB-009:36-39, :84-86: F-Droid-shaped, GitHub APK first, Play later; annual target-SDK obligation | C17 gives the concrete date and level; C20: Play FGS declaration with video, AccessibilityService policy (S24, S23). Distribution trust signals are #810 (not researched). | **Supported** | Play-first is already rejected (MOB-009:90). | Nothing shipped. | **No change** to the decision. Note the Play facts in the Play-readiness work when that starts; #810 owns the rest. |
| 9 | MOB-003:26, :30: `RecognitionService` second; overlay bubble with `SYSTEM_ALERT_WINDOW` | Q5/C19, S15/S16: on-device recogniser API levels 31/33/34; default impl "likely to stream audio to remote servers"; user-selected default varies by OEM (`[Unknown]`). C8, S8: at target 35 the overlay exemption requires permission **and** a visible overlay window. | **Supported** (levels); OEM picker **Unverified**; bubble exemption **Contradicted-in-wording** at target 35+ | None needed. | Bubble is M3 and opt-in; wording only. | **Amend ADR (PROPOSED)**, A6 (bubble clause only). Device test T9 for the picker. |
| 10 | MOB-005:94-97: two JNI bridges; handles behind `Closeable`; no native call on the main thread; crash takes the IME process | C14/C15: S5 says release large allocations soon after the IME window hides, which pulls against keeping a model hot; `largeHeap` likely does not govern native allocations (`[Assumption]`); no per-device model budget in any source. Separate `android:process` for the engine **not researched**. | Lifecycle policy **Unverified**; the `Closeable` rule is **No evidence** against | Load on first burst vs keep warm vs separate process (open; needs T7). | Policy choice is internal; no data format affected. | **Small change to #92 and #87**: record peak RSS and PSS per model, and measure first-burst latency after the process is killed (T7). No ADR amendment until numbers exist. |
| 11 | MOB-006:39-45: model download is a WorkManager job, Wi-Fi only by default, user-initiated | C12/C13: Doze and buckets may defer jobs; bucket criteria are OEM-defined; Android 16 job quotas (S10, S17, S18). | **Supported** with a caveat | Keep it a foreground, user-visible download (already "nothing downloads before an explicit tap", MOB-006:35-36). | Compatible. | **Small change to #90**: acceptance should require resume after process death and deferral, with the user-visible progress path. No ADR change. |
| 12 | MOB-007:26 and MOB-003 onboarding duty: honest keyboard privacy explainer; `RECORD_AUDIO` request | C5/C6, S12: request API needs an `Activity`, so an IME needs an onboarding activity; two denials are permanent; "only this time" ends with process kill; unused-app auto-reset (target 30+) can revoke the grant. C4: mic toggle yields silent audio, not an error. | **Supported** (consistent), constraints **new to the issues** | n/a | Compatible. | **Small change to #91 and #89**: handle revoked-mid-session, permanent denial, and distinguish "toggle off or silenced" from "quiet room" in the UI wording. |
| 13 | MOB-001 (Android-first, in-repo; Decision at `adr-mob-001-android-first-monorepo.md:49`) | None | **No evidence** | n/a | n/a | No change. |
| 14 | MOB-008 (cross-platform contract, `adr-mob-008-cross-platform-contract.md:39`) | None | **No evidence** | n/a | n/a | No change. |
| 15 | MOB-010 (Apple wave after Android M2, `adr-mob-010-apple-second-wave.md:47`) | None | **No evidence** | n/a | n/a | No change. |
| 16 | 16 KB page size (no ADR line owns it; MOB-005 owns the JNI bridges) | C16, S11: all `.so` must be 16 KB aligned for targets 35+ on 64-bit; Play block from 2027-02-01 for non-compliant updates; AGP >= 8.5.1 met by repo AGP 8.7.2; NDK unpinned. | **Supported**; gap, **not an ADR contradiction** | Pin NDK >= r28 when `:native:*` land. | None yet; no native build exists (per the #807 note section 1). | **Small change to #87** (NDK pin and `zipalign -P 16` check, T8). |

Rows 13-15 are placeholders for completeness: the note examined none of them, and the gap itself is a finding.

## 3. The unverified premise, stated plainly

**Assumption under test.** "Because the IME window is visible while recording, the app is 'in use' for the while-in-use `RECORD_AUDIO` rule and needs no microphone foreground service for hold-to-talk" ([MOB-003:81-83](../../docs/mobile/adr/adr-mob-003-text-delivery-surfaces.md); restated at [MOB-003:25](../../docs/mobile/adr/adr-mob-003-text-delivery-surfaces.md), [MOB-007:75-76](../../docs/mobile/adr/adr-mob-007-privacy-permissions-lifecycle.md) and, as a constraint, [MOB-004:28-31](../../docs/mobile/adr/adr-mob-004-activation-model.md)).

**What is established.** The platform documents that a foreground app, or an app with an FGS, may capture, and that other apps receive silence (S4). The current input method may start FGSs from the background (S1). The `InputMethodService` reference (S6, partial) says an IME "could have no input area ... but instead listen to audio". **What is not established:** that an IME process is classified as foreground for capture while its window is shown, that a hidden IME is silenced, and whether this differs by API level or OEM (Q4, Unknown). The note's search for an AOSP rule returned nothing usable.

**Why it matters.** It is the product's primary path (MOB-004 decision 1). If wrong, hold-to-talk would capture silence on some builds, and the symptom (a quiet buffer) is indistinguishable from a quiet room unless the UI separates them (row 12). No code depends on it yet: `:platform:audio` capture is "written but never run" (#807 section 1).

**Proposed device test (no result exists).** Extends #807's T1 into a runnable procedure. Use synthetic or consented own-voice audio only, install nothing that measures through a third-party SDK.

| Step | Do | Record |
|---|---|---|
| 1 | Build a minimal IME whose mic key opens `AudioRecord` (16 kHz mono PCM16) on key-down and logs RMS per 100 ms until key-up. No FGS. | Device model, SoC, Android version and patch, OEM skin, install source |
| 2 | Hold with the keyboard window shown, in a plain app, a browser field, and a field in a second window (split screen). | RMS non-zero vs zero; `AudioRecordingCallback` `isClientSilenced` |
| 3 | Hold, then hide the window mid-hold (back, home, switch IME), keep the key state. | Does audio continue, go silent, or error; time to change |
| 4 | Repeat 2-3 with the mic toggle on and off (C4) and after revoking the permission (C5). | Distinguish silenced vs permission vs toggle |
| 5 | Repeat 2-3 with a short `microphone` FGS (started while the IME is current) around the hold. | Whether (3) changes; notification visibility with `POST_NOTIFICATIONS` denied (C10) |
| 6 | API levels: at minimum 26, 29, 31, 34 images (aligns with #674 and #686), then one non-Pixel OEM skin. | Per-cell result table |

**Decision rule (proposal).** If step 2 and 3 show continuous audio on every tested cell, relabel the premise "Verified on <devices>, not on others" and keep the ADRs. If any cell silences or errors, adopt alternative (b) from row 1 and amend MOB-003, -004 and -007 together. The result must name the devices; "works on Android" is not a result.

## 4. Draft ADR amendments (PROPOSED, not applied)

Nothing below edits `docs/mobile/adr/`. Each is wording a maintainer may adopt in a separate L3 change. None changes scope or ADR-030.

- **A1 (MOB-003, MOB-004, MOB-007).** Replace the flat assertion with: "Hold-to-talk is expected not to need a microphone foreground service because the IME window is visible. This is **unverified** (see the 2026-11-06 traceability note); [#89] must not ship on this premise until device test T1 passes on the tested set, and a fallback of a short `microphone` FGS started while YazSes is the current input method is specified." Backward compatible: it only adds a condition.
- **A2 (MOB-007:28-30).** Replace "Android 15+ applies time limits to several FGS types" with "Android 15+ applies time limits to some FGS types; the documentation read names `dataSync`, `mediaProcessing` and `shortService`, and no limit for `microphone` was found. #97 measures it."
- **A3 (MOB-007:78-80).** Add: "The ongoing notification is visible in the drawer only when `POST_NOTIFICATIONS` is granted; the start flow requests it and handles denial."
- **A4 (MOB-007:83-84, and #88 acceptance, which is an issue edit not an ADR edit).** "Another app taking the mic" becomes: "on API 29+ the app is silenced and notified through `AudioRecordingCallback` (registered before capture); on API <29 `startRecording` errors if the mic is busy. A silent buffer is not by itself an error."
- **A5 (MOB-007 table at :39-45).** Add a Notes column: `POST_NOTIFICATIONS` runtime grant; `foregroundServiceType="microphone"` on the service; Play Console FGS declaration and demo video for a Play listing.
- **A6 (MOB-003 bubble).** Add: "From target 35 the background-start exemption needs the overlay permission **and** a visible overlay window."

Alternatives to amending: leave the ADRs and track A1-A6 only in the M1 issues. This is cheaper but leaves the ADRs, which contributors treat as binding, stating a premise the project has not verified; the review in #98 is the natural venue to decide.

## 5. Priorities for epic #81

Ranked by cost of being wrong times closeness to the first shipped behaviour. This is a recommendation, not a plan commitment; ordering across contributors is the maintainer's call.

1. **T1 hidden/visible-IME capture test** (row 1). Blocks the confidence of #88 and #89 and decides whether MOB-003/-004/-007 change. Needs one device or emulator image plus a few OEM devices; no project code beyond a spike.
2. **#88 acceptance rewording** (row 5, A4) and **#91 onboarding handling** (rows 4, 12). Text-only, near-zero cost, prevents building the wrong stolen-mic and permission paths.
3. **#92 peak-memory and cold-start measurement** (row 10, T7). Needed before a model recommendation is made in #90 and before the load policy is chosen.
4. **#90 job deferral acceptance** (row 11) and **#87 NDK pin and 16 KB check** (row 16). Cheap now, expensive once native builds exist.
5. **#97 90-minute Meeting Mode spike** (rows 2, 3, 4). Device-heavy, and Meeting Mode is later than hold-to-talk. Wording fixes A2-A3 do not need to wait.
6. **Wording amendments A2-A6** in one batch, after #98 feedback. **Defer** any minSdk or target change; no evidence argues for either now.

## 6. Verification record

`gh issue view <n> --json number,state,title` on 2026-11-06, all returned OPEN: #81 (Epic: YazSes for Android), #789 (Android adoption and mobile voice UX), #98 (Design review of the ten mobile ADRs), #807 (Audit Android API level and OEM IME/microphone restrictions), #812 (Map Android research results to M0-M3 ADRs and decision gates), #97 (Spike: 90-minute microphone foreground service on Android 15/16), #88 (`:core:audio` + `:core:vad` + `:platform:audio`), #87, #89, #90, #91, #92, #93, #810, #674, #686. #807 remains open: this note does not close its device-test checklist and #812 stays open until a maintainer accepts or amends.

ADR line citations were read in this worktree at the snapshot above. The #88 acceptance quotes ("Mic stolen by another app -> clean stop, no crash, user told") come from the issue body read on the same date.

**Limits.** No device, emulator, Gradle build or Android test was run. The #807 sources were summaries, two truncated. Rows 13-15 rest on absence of evidence. Row 7's Play dates are from S22 as summarised, and should be re-read from the primary page before anyone schedules a bump.

Related: [#807 note](2026-11-05-android-api-levels-and-oem-ime-microphone-restrictions.md), [ADR-030](../adr/adr-030-agent-era-direction.md), [milestone policy](../milestone-policy.md), [mobile programme](../../docs/mobile/index.md).
