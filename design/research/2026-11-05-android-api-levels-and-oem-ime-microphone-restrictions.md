# Research: Android API levels, OEM variation and microphone rules for an offline dictation IME

**Issue:** [#807](https://github.com/MSKazemi/yazses/issues/807), parent epic [#789](https://github.com/MSKazemi/yazses/issues/789), implementation epic [#81](https://github.com/MSKazemi/yazses/issues/81)  
**Snapshot:** YazSes `main` at `a241a77b6c59d65fb9265a0475d42f1a97fdfe6a`, inspected 2026-11-05; external pages read 2026-11-05  
**Status:** Research note (not a decision). ADR-030 freeze unchanged.  
**Scope:** documentation research only. No `android/` change, no APK, no ADR edited, no device measured, no claim about any device. Distribution policy beyond a one-line note belongs to [#810](https://github.com/MSKazemi/yazses/issues/810).

## Evidence labels

- **[Verified-primary-source]** stated on a developer.android.com / source.android.com / Google Play Help page (key `S#`, section 8).
- **[Upstream-claim]** third-party or aggregator assertion; not accepted as fact here.
- **[Verified-in-repo]** read in this checkout at the snapshot above.
- **[Assumption]** my inference; stated so it can be challenged.
- **[Unknown]** not answered by what was read; needs a source or a device.

**Method caveat.** The fetch tool returns a text summary made by a small model, not the raw page. Every `S#` is therefore "read as summarised", not "read in full". Two reference pages were cut off by the tool: S6 (first 100,000 of 361,215 characters) and S16 (first 100,000 of 221,880). Page revision dates were not exposed, so only the read date is recorded.

## 1. What the repo already commits to  [Verified-in-repo]

| Item | Where | Value |
|---|---|---|
| `minSdk` / `compileSdk` / `targetSdk` | `android/gradle/libs.versions.toml` | 26 / 34 / 34; AGP 8.7.2; Kotlin 2.0.21 |
| Rationale for 26 | same file | "the floor where the IME APIs and the audio behaviour this app depends on are consistent" (no source cited) |
| Manifest permissions today | `android/platform/audio/src/main/AndroidManifest.xml` | `RECORD_AUDIO` only |
| Permission budget | [ADR-MOB-007](../../docs/mobile/adr/adr-mob-007-privacy-permissions-lifecycle.md) §A | `RECORD_AUDIO`, `INTERNET` (`:model` only), `POST_NOTIFICATIONS`, `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_MICROPHONE`, `SYSTEM_ALERT_WINDOW` (bubble) |
| Hold-to-talk needs no FGS because the IME window is visible | ADR-MOB-003 consequences, ADR-MOB-004 | assumption about "in use" status; see Q4 |
| Meeting Mode = user-started `microphone` FGS | ADR-MOB-007 §D, spike [#97](https://github.com/MSKazemi/yazses/issues/97) | open risk, no measurements |
| Native engines | `android/README.md`, [index](../../docs/mobile/index.md) | placeholders; NDK "not yet"; `:platform:audio` capture "written but never run" |
| Device-only tasks | [#674](https://github.com/MSKazemi/yazses/issues/674) (API 26 + 33), [#686](https://github.com/MSKazemi/yazses/issues/686) (API 26 + 34), [#88](https://github.com/MSKazemi/yazses/issues/88) | all open, all need an emulator or phone |

Nothing in `android/` has run on a phone. Every device statement below is therefore a source claim, not an observation.

## 2. Answers, question by question

**Q1. minSdk/targetSdk and IME lifecycle.**
IME lifecycle callbacks (`onCreateInputView`, `onStartInput`, `onStartInputView`, `onFinishInputView`, `onFinishInput`) and `InputConnection.commitText` are documented without per-API-level caveats for 26-36 in the pages read [Verified-primary-source, S5, S6]. S6 gives only "class added in API level 3". The repo's claim that 26 is where "IME APIs ... are consistent" is [Unknown]: no read source marks 26 as a boundary for the IME APIs. The boundaries that *are* documented fall elsewhere: audio capture (API 28/29), mic UI (31), FGS typing (34), see section 3. The doc says to release large allocations soon after the IME window hides, and to bring the UI up quickly by preloading [Verified-primary-source, S5]; these pull against each other for a model-backed IME (Q7).

**Q2. RECORD_AUDIO and the privacy UI (Android 12+).**
Runtime permission since API 23; the request API takes an `Activity` [Verified-primary-source, S12], so an `InputMethodService` cannot show the dialog itself and needs an onboarding activity [Assumption: inferred from the signature]. Two denials mean permanent denial ("don't ask again") [S12]. Android 11 adds "Only this time": access continues while an activity is visible, briefly in the background, and while a FGS started from a visible activity runs; revocation kills the process [S12]. Unused-app auto-reset applies to apps targeting 30+ [S12]. From Android 12: status-bar mic indicator, Privacy Dashboard, and a device-wide mic toggle "on supported devices" that makes the app **receive silent audio, not an error** [Verified-primary-source, S13, S14]. Support is queryable with `SensorPrivacyManager.supportsSensorToggle` [S13]. Which devices support the toggle is [Unknown].

**Q3. Background mic and the `microphone` FGS type.**
Camera/microphone FGS needs `foregroundServiceType` when targeting 30+ [S25]. From Android 14 (target 34) a type and its `FOREGROUND_SERVICE_<TYPE>` permission are mandatory, `microphone` requires a granted `RECORD_AUDIO`, and creating a `microphone` FGS while in the background throws [Verified-primary-source, S2, S1, S7]. Capture from a `BOOT_COMPLETED` receiver is blocked for `microphone` since Android 14 [S8]. Exemptions that allow starting from the background include a user action on a bubble, notification, widget or activity, and "your app is the device's current input method" [S1]. The `SYSTEM_ALERT_WINDOW` exemption narrowed for target 35 to "permission **and** a visible overlay window" [S8]. FGS notification display may be delayed 10 s on Android 12+ [S14]. Without `POST_NOTIFICATIONS` (API 33), an FGS still starts but its notification is hidden from the drawer and shown only in the Task Manager [S26].

**Q4. IME-specific microphone behaviour.**
Documented: capture is allowed to foreground apps or apps with a FGS; since Android 9 an app without either "continued running but received silence" [Verified-primary-source, S4]. Documented: the current IME may start FGSs from the background [S1], and S6 says an IME "could have no input area ... but instead listen to audio" [S6, summarised]. **Not found in any source read:** a statement that an IME may record *only while its window is shown*, nor that a hidden IME is silenced, nor how the capture policy classifies an IME process. A search for an AOSP rule on this returned nothing usable [Unknown]. ADR-MOB-003's "IME window is visible, so the app is foreground" is therefore plausible, [Assumption], and the exemption in S1 does not prove it. This is the highest-value device test (section 7).

**Q5. SpeechRecognizer / RecognitionService.**
`createOnDeviceSpeechRecognizer` and `isOnDeviceRecognitionAvailable` are API 31; `checkRecognitionSupport` and `triggerModelDownload` API 33; the download-listener overload API 34 [Verified-primary-source, S15]. The base class doc says the default implementation "is likely to stream audio to remote servers" and is "not intended ... for continuous recognition" [S15]. A client picks the system default service unless it names a component [S15]; API 30+ clients need a `<queries>` entry for `android.speech.RecognitionService` [S15]. `RecognitionService` has `onStartListening/onStopListening/onCancel`, `onCheckRecognitionSupport` and `onTriggerModelDownload` [S16, per-method API levels not shown]. Where a user changes the default recogniser, and what any OEM's picker shows, is [Unknown]; ADR-MOB-003 already says it "varies by OEM". Who owns the microphone while a third-party service recognises, and whether it counts as foreground, is [Unknown].

**Q6. Battery, Doze, standby buckets.**
Doze (API 23): unplugged, stationary, screen off; wake locks ignored, network suspended, jobs deferred [Verified-primary-source, S17]. Whether a `microphone` FGS keeps CPU inference running through Doze is not stated in the text read [Unknown]. Standby buckets (API 28+): *Active* while an activity launches or a long-running FGS runs; "if an app doesn't have a launcher activity, it might never be promoted to the active bucket"; "every manufacturer can set their own criteria" [S18]. Restricted bucket: API 31, auto-entry after 8 days without interaction on 33+ (45 on 31/32), one 10-minute job session per day [S18, S14]. Android 16 adds job runtime quotas by bucket and for jobs concurrent with an FGS (all apps) [S10]. Play prohibits asking for battery-optimisation exemption unless the core function breaks [S17]. Whether an IME-only app (it has a launcher/settings activity only if we add one) is promoted by keyboard use is [Unknown].

**Q7. Memory.**
Per-app Dalvik heap hard limit varies by device RAM; query `getMemoryClass()` [Verified-primary-source, S19]. `largeHeap` "doesn't guarantee a fixed increase" and applies to the Dalvik heap [S20]. Unmodified mmapped files can be paged out; modified memory stays resident [S19]. Cached processes can be killed at any time; lmkd ranks by `oom_adj` and OEMs tune it per device via `ro.lmk.*` [S19, S21]. Native model memory is not the Dalvik heap, so `largeHeap` probably does not govern whisper.cpp allocations [Assumption]. No source gives a per-device model-size budget [Unknown].

**Q8. 16 KB page size.**
Android 15 supports 16 KB devices; apps with NDK code must be rebuilt. AGP >= 8.5.1 and NDK >= r28 produce aligned libraries by default; NDK <= r27 needs `-Wl,-z,max-page-size=16384`; prebuilts must be rebuilt; `zipalign -P 16` and `check_elf_alignment.sh` verify [Verified-primary-source, S11]. Play: apps targeting 35+ must support 16 KB on 64-bit devices; the page says updates that do not "won't be able to release" them from **February 1, 2027** [S11]. Android 16 adds a compat mode with a user dialog for 4 KB-aligned apps [S10]. Repo AGP 8.7.2 meets the AGP bar [Verified-in-repo]; NDK is unpinned [Verified-in-repo].

**Q9. Play policy on mic / accessibility (note only, #810 owns the rest).**
Play requires a Console FGS-type declaration for target 34+, with a video per type; `microphone` maps to "Background Audio Access" ("Show the user initiate the microphone actively recording") [Verified-primary-source, S24]. The AccessibilityService policy restricts the API and requires a prominent in-app disclosure for non-accessibility tools [S23, page undated]. ADR-MOB-003's rejection of `AccessibilityService` is consistent. Sideload / F-Droid rules: not researched here.

**Q10. OEM variation.** See section 5.

## 3. Constraint table

| # | Constraint | API | Source | Consequence for the M0-M3 plan | Status |
|---|---|---|---|---|---|
| C1 | One ordinary app captures at a time; pre-10 `startRecording` errors if busy | <29 | S4 | #88 "mic stolen -> clean stop" has two shapes by API level | known |
| C2 | Background app without FGS gets silence | 28+ | S4 | Hold-to-talk correctness depends on Q4 | known; IME case unknown |
| C3 | Priority scheme: silenced, not stopped; `AudioRecordingCallback` must be registered **before** capture | 29+ | S4 | #88 must treat `isClientSilenced` as the "stolen" signal; a silent buffer is not an error | known |
| C4 | Mic toggle -> silent audio; mic indicator always shown | 31+ | S13, S14 | RMS gate would say "nothing heard"; UI should distinguish toggle-off/silenced from quiet room | known; support per device unknown |
| C5 | `RECORD_AUDIO` needs an Activity to request; double-deny is permanent; one-time grant ends with process kill | 23 / 30 | S12 | Onboarding (#91) must launch an activity and handle "revoked mid-session" | known |
| C6 | Auto-reset of unused permissions (targets 30+) | 30+ | S12 | Mic permission may vanish for a rarely used keyboard; recheck every burst | known |
| C7 | FGS type + `FOREGROUND_SERVICE_MICROPHONE` mandatory; `microphone` FGS cannot be created from background | 34 | S2, S1, S7 | `targetSdk=34` already in force: ADR-MOB-007 table matches; start Meeting Mode only from visible UI | known |
| C8 | Current IME, notification, bubble, widget, activity tap are start-from-background exemptions | 31+ | S1 | Quick Settings tile start is not named among S1's listed exemptions in the text read | known; tile path unknown |
| C9 | FGS time limits: only `dataSync`, `mediaProcessing`, `shortService` documented | 35 | S3, S2 | ADR-MOB-007 says "several types"; `microphone` has none in the text read; #97 still must measure | known; real-device unknown |
| C10 | `POST_NOTIFICATIONS`: FGS starts without it, notification only in Task Manager when denied | 33 | S26 | ADR-MOB-007 "permanent notification" may be invisible; indicator remains | known |
| C11 | Audio-focus requests need top app or FGS | 35 (target) | S8 | #88 audio-focus handling untested for an IME; whether IME counts as "top" unknown | unknown |
| C12 | Doze / buckets / restricted bucket; bucket criteria set by OEM | 23 / 28 / 31 | S17, S18 | #90 download job may be deferred; make download user-initiated and foreground | known; OEM values unknown |
| C13 | Android 16 job quotas by bucket and with FGS | 36 (all apps) | S10 | Any WorkManager use (download, import) must tolerate stops | known |
| C14 | Heap limit per device; `largeHeap` not guaranteed; cached processes killable; lmkd OEM-tuned | all | S19, S20, S21 | ADR-MOB-005 needs a measured peak RSS per model (#92), no assumed budget | unknown numbers |
| C15 | Release large allocations after the IME hides | all | S5 | Conflicts with keeping a model hot; load-on-first-burst vs keep policy is undecided | known; policy open |
| C16 | 16 KB alignment for all `.so`; Play block from 2027-02-01 for targets 35+ | 35 / 15+ devices | S11 | Pin NDK >= r28 when `:native:*` arrive; verify with `zipalign -P 16`; `full` flavour prebuilts need audit | known; builds do not exist |
| C17 | Play target API: new apps and updates must target 36 from 2026-08-31 (extension to 2026-11-01); existing apps >= 35 | 36 | S22 | Repo `targetSdk=34` is below the Play bar (GitHub/F-Droid unaffected); ADR-MOB-009 "Play later" implies a target bump with a test pass | known |
| C18 | Target 35: edge-to-edge forced; target 36: opt-out removed, predictive back default, `KEYCODE_BACK` not dispatched | 35 / 36 | S8, S9 | Settings/onboarding UI and the IME back handling need a pass at bump time; IME window effect not documented in text read | partly unknown |
| C19 | On-device recogniser API for clients | 31 / 33 / 34 | S15 | #93 `RecognitionService` serves clients regardless of level, but clients on <31 cannot ask for on-device | known |
| C20 | Play FGS declaration + video; AccessibilityService policy | target 34 | S24, S23 | Plan Meeting Mode demo video for a Play listing; no AccessibilityService stays consistent | known |

## 4. Lowest-supported-API view (not a recommendation to change anything)

- Moving the floor 26 -> 29 removes the "one app at a time" capture shape (C1) and gives one stolen-mic semantic. Cost: unknown, no install-share figure was read (the Android version dashboard was not fetched) [Unknown].
- Moving to 31 would make indicators/toggle (C4), on-device recogniser API (C19) and FGS start restrictions uniform. Same unknown cost.
- Nothing read argues for raising `minSdk`; nothing read justifies 26 over 24 or 28 either [Assumption]. The cheapest evidence is #674 and #686 on API 26, 29, 31, 34 images, which are already planned.

## 5. OEM variation: what is source and what is claim

**[Verified-primary-source] statements that variation exists:**
- Standby-bucket criteria are manufacturer-defined; do not try to steer them (S18).
- lmkd is tuned per device through `ro.lmk.*` and `ro.config.low_ram` (S21).
- The mic/camera toggle and Privacy Dashboard exist on "supported devices" only (S13).
- The Doze exemption list is user-configurable under Settings > Battery > Battery Optimization; Play restricts apps asking for it (S17).

**[Upstream-claim] (not used as fact):**
- dontkillmyapp.com asserts that vendors "prefer battery life over proper functionality of your apps" and ranks vendors. Run by a third party (the Urbandroid team per the page); the landing page states no methodology and no date. Per-vendor pages were **not read**. Treat as a pointer to *what to test*, not evidence of what happens.
- Issue #97 states that Samsung, Xiaomi and Huawei kill background work "aggressively, independently of what AOSP allows". Same status: [Upstream-claim] in the repo, no primary source attached.

**[Unknown] (no source found, device needed):** OEM keyboard-switcher behaviour, custom IME pickers, whether OEM skins re-label or hide the mic indicator, per-vendor "app lock/auto-start" lists, and whether an OEM silences a hidden IME.

## 6. ADR items to check (ADRs not edited)

1. **MOB-003/004 "IME visible, so no FGS needed":** unverified; S1 lists the IME as an FGS-start exemption but no source states the capture rule (Q4).
2. **MOB-007 "Android 15+ applies time limits to several FGS types":** the docs read name `dataSync`, `mediaProcessing`, `shortService`, not `microphone` (C9). Wording may need narrowing; #97 stays valid as an empirical check.
3. **MOB-007 §D "permanent notification":** depends on `POST_NOTIFICATIONS`; denial hides it from the drawer (C10).
4. **MOB-007 §D "another app taking the mic":** on API 29+ delivered as silencing via callback, not an error (C3); #88 acceptance text should say so.
5. **MOB-007 §A table:** has no `POST_NOTIFICATIONS` runtime rationale, no `foregroundServiceType` manifest note, no Play declaration (C7, C20).
6. **MOB-005 JNI/model lifecycle:** reconcile with "release large allocations after hide" (C15); a native crash takes the IME process (ADR already notes it). Running the engine in a separate process (`android:process`) was **not researched** [Unknown].
7. **MOB-009 "annual target-SDK obligation":** concrete date and level now readable on S22 (C17); repo `targetSdk=34`.
8. **MOB-002 / toml comment "26 is the floor ... consistent":** no cited source; see section 4.
9. **MOB-003 §5 bubble + `SYSTEM_ALERT_WINDOW`:** FGS exemption needs a *visible overlay* at target 35+ (C8).
10. **ADR-030:** a *proposed* amendment is not justified by this note. Items 2-4 are wording corrections for #81's owners, not scope changes.

## 7. Device-test checklist (what only real devices can answer; no results here)

Record for every run: model, SoC, Android version and patch level, OEM skin version, install source, battery-optimisation state, bucket (`adb shell am get-standby-bucket`).

- [ ] **T1 hidden-IME capture (Q4):** hold-to-talk with window shown; then try capture after the window hides or after switching IMEs; does `AudioRecord` return audio or silence? Which API levels differ?
- [ ] **T2 stolen mic (C1, C3):** start capture, then start a call/voice recorder/assistant; observe `isClientSilenced`, errors and `onRecordingConfigChanged`, on API <29 and >=29 (#88).
- [ ] **T3 toggle and indicator (C4):** device-wide mic toggle off, then dictate; check `supportsSensorToggle`, silent buffer, UI wording; check indicator appears on every OEM tested.
- [ ] **T4 permission paths (C5, C6):** deny twice, "Only this time", revoke mid-burst, auto-reset after idle; does the IME survive each; where does the onboarding activity open.
- [ ] **T5 Meeting Mode FGS (C7-C10, #97):** 60 and 90 minutes, screen off, unplugged, on >=2 devices including one non-Pixel skin; start from tile, shortcut, in-app button; with `POST_NOTIFICATIONS` denied; record kill/throttle/timeout behaviour and whether audio saved.
- [ ] **T6 Doze and buckets (C12):** `dumpsys deviceidle force-idle` during a Meeting run; force `restricted` bucket; does the model download job still finish.
- [ ] **T7 memory (C14, C15):** peak RSS and PSS for each candidate model (#92), under `stressapptest`-style pressure; lmkd kills while IME hidden; cold-start latency of first burst after kill.
- [ ] **T8 16 KB (C16):** once libraries exist, boot a 16 KB emulator/device (`adb shell getconf PAGE_SIZE` = 16384), run `zipalign -c -P 16 -v 4`, load engine, decode a fixture.
- [ ] **T9 recogniser (Q5, #93):** `isOnDeviceRecognitionAvailable`, `checkRecognitionSupport` on API 31/33/34; can the user select YazSes as default on each OEM; who holds the mic.
- [ ] **T10 audio focus and back (C11, C18):** request focus from the IME at target 35+; back gesture inside the IME at target 36.
- [ ] **T11 keyboard switch (OEM):** switch away and back via picker, globe key and `switchToNextInputMethod` on each skin; does capture state reset.
- [ ] **T12 regex and SHA (#674, #686):** run the planned emulator checks on API 26, 29, 31, 34 images.

Privacy rule for all of the above: synthetic or consented own-voice audio only; no real dictation, no third-party SDK installed to measure.

## 8. Sources (all read 2026-11-05 as tool summaries; revision dates not exposed)

- S1 https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start
- S2 https://developer.android.com/develop/background-work/services/fgs/service-types
- S3 https://developer.android.com/develop/background-work/services/fgs/timeout
- S4 https://developer.android.com/media/platform/sharing-audio-input
- S5 https://developer.android.com/develop/ui/views/touch-and-input/creating-input-method
- S6 https://developer.android.com/reference/android/inputmethodservice/InputMethodService (partial)
- S7 https://developer.android.com/about/versions/14/behavior-changes-14
- S8 https://developer.android.com/about/versions/15/behavior-changes-15
- S9 https://developer.android.com/about/versions/16/behavior-changes-16
- S10 https://developer.android.com/about/versions/16/behavior-changes-all
- S11 https://developer.android.com/guide/practices/page-sizes
- S12 https://developer.android.com/training/permissions/requesting
- S13 https://developer.android.com/training/permissions/explaining-access
- S14 https://developer.android.com/about/versions/12/behavior-changes-all
- S15 https://developer.android.com/reference/android/speech/SpeechRecognizer
- S16 https://developer.android.com/reference/android/speech/RecognitionService (partial)
- S17 https://developer.android.com/training/monitoring-device-state/doze-standby
- S18 https://developer.android.com/topic/performance/appstandby
- S19 https://developer.android.com/topic/performance/memory-overview
- S20 https://developer.android.com/guide/topics/manifest/application-element
- S21 https://source.android.com/docs/core/perf/lmkd
- S22 https://developer.android.com/google/play/requirements/target-sdk
- S23 https://support.google.com/googleplay/android-developer/answer/10964491
- S24 https://support.google.com/googleplay/android-developer/answer/13392821
- S25 https://developer.android.com/about/versions/11/privacy/foreground-services
- S26 https://developer.android.com/develop/ui/views/notifications/notification-permission
- U1 (upstream claim, landing page only) https://dontkillmyapp.com/

Not read: Android version dashboard, per-vendor dontkillmyapp pages, AOSP source for the capture policy, `Service` reference, WorkManager docs, Play user-data and permissions policies beyond S23/S24.

Related: [ADR-030](../adr/adr-030-agent-era-direction.md), [milestone policy](../milestone-policy.md), [mobile programme](../../docs/mobile/index.md).
