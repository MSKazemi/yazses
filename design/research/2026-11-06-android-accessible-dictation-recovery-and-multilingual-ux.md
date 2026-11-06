# Research: accessible mobile dictation, recovery flows and multilingual keyboard UX

**Issue:** [#811](https://github.com/MSKazemi/yazses/issues/811) (NEXT-MOBILE-06), parent [#789](https://github.com/MSKazemi/yazses/issues/789); feeds [#89](https://github.com/MSKazemi/yazses/issues/89) (`:feature:ime`) and [#95](https://github.com/MSKazemi/yazses/issues/95) (`:feature:settings` + diagnostics), epic [#81](https://github.com/MSKazemi/yazses/issues/81)
**Snapshot:** YazSes `main` at `8a72bbc6`, inspected 2026-11-06. External pages read 2026-11-06.
**Status:** Research note and design proposal, not a decision. ADR-030 freeze unchanged. Evergreen research (no milestone).
**Scope:** documentation only. No `android/` change, no ADR edited, no APK, no emulator or device run, **no user testing, no participant data, no screen-reader session**. Nothing here says a step works on a phone or that YazSes supports Android accessibility. Wireframes are text sketches of what the ADRs already commit to, not designs that someone has validated.

**Builds on, and does not repeat:**
[#807 note](2026-11-05-android-api-levels-and-oem-ime-microphone-restrictions.md) (constraints `C#`, device tests `T#`),
[#812 traceability matrix](2026-11-06-android-adr-traceability-matrix.md) (rows and proposed amendments `A#`),
[#806/#809 first-use and model-provisioning note](2026-11-06-android-first-use-journey-and-model-provisioning-ux.md) (onboarding and model errors),
[#808 measurement protocol](2026-11-06-android-on-device-asr-measurement-protocol.md) (device tiers).
Distribution ([#810](https://github.com/MSKazemi/yazses/issues/810)) is out of scope.

## 1. Labels

- **[Code]** read at the cited `file:line` in this checkout. Android code is pure, JVM-tested Kotlin; none of it is wired to a view yet (`android/feature/ime/src/main/kotlin/com/yazses/feature/ime/Placeholder.kt` is the whole IME module).
- **[ADR]** stated by a mobile ADR at the cited line. A design commitment, not an observation.
- **[Primary]** stated on a developer.android.com, W3C or Google Help page, read 2026-11-06 through a fetch tool that returns a model-made summary (verbatim quotes where marked). Two pages were longer than one fetch; the parts used are named in section 9.
- **[Assumption]** my inference, stated so it can be challenged.
- **[Unknown]** needs a device; tagged with the proposed device test `U#` (section 6).

## 2. Answer to the issue question

Question (#811): how do touch target sizes, talk/release feedback, composing text, editing mistakes, non-Latin scripts and screen-reader use affect M1/M2 usability?

1. **Screen-reader users probably cannot use hold mode at all, so toggle mode is their path, not a fallback.** Under TalkBack a "long press" is the gesture *double-tap and hold* [Primary, S4], and touch exploration means a finger landing on the mic key is first an exploration, not a key-down [Assumption]. Hold-to-talk built on raw `ACTION_DOWN`/`ACTION_UP` (ADR-MOB-004:75-78) would then not start, or start late. Toggle mode already exists in code with a hard cap [Code, `ActivationSource.kt:80-109`] and is an M1 requirement [ADR, MOB-004:46-49]. **Proposal:** when touch exploration is on, the mic key should behave as a toggle and say so, with the user's hold/toggle choice still respected if set explicitly. Unverified: U1.
2. **A spoken announcement can be dictated into the user's own text.** If TalkBack says "recording" after capture starts, the phone's speaker output can reach the microphone and be transcribed [Assumption, by mechanism; no measurement]. **Proposal:** announce *before* `SessionEffect.StartCapture` and signal the start of capture with haptics or a visual-only change, not speech. Unverified: U2.
3. **The minimum touch target is 48dp x 48dp** [Primary, S2]. A five-key bar (mic, backspace, enter, undo, switch) fits that on a 360dp-wide phone in portrait. The mic key should be the largest target; the destructive keys (backspace, undo) should not sit right next to it [Assumption].
4. **`commitText` replaces any composing text left in the field** [Primary, S1, verbatim: "removes the contents of the currently composing text and replaces it with the passed CharSequence"]. If the previous keyboard left a composing span (a half-typed word with underline) and the user switches to YazSes and dictates, the half word could be overwritten [Assumption about what other IMEs leave behind]. **Proposal for #89:** if `onUpdateSelection` reports a composing range (`candidatesStart != -1`) [Primary, S3], call `finishComposingText()` before the first `commitText`. Unverified: U4.
5. **Undo is the safety net for misrecognitions, and today it records only a length.** `UndoLastInsert.Insert` holds `id` and `length` in UTF-16 code units [Code, `UndoLastInsert.kt:10-14`], which matches `deleteSurroundingText` ("lengths are supplied in Java chars") [Primary, S1]. That is correct for surrogate pairs and Persian ZWNJ, but **it cannot tell whether the text before the cursor is still the text it inserted.** The class tells the caller to invalidate on typing or cursor moves [Code, `:26-29`], but an editor that reformats or autocorrects after commit (for example a chat app turning `:)` into an emoji) changes the length without a cursor move from YazSes [Assumption]. **Proposal:** store the inserted string too and verify it with `getTextBeforeCursor(len)` before deleting; refuse with a visible reason when it differs, rather than deleting the wrong characters. `getTextBeforeCursor` can return null or fewer characters [Primary, S1]; treat that as "cannot verify" and refuse. Pure-Kotlin change in `:core:session`, testable without a device.
6. **Non-Latin dictation is not possible in M1, whatever the UI does.** The only pinned models are `tiny.en` and `base.en` [#808 note section 1, from `android/app/src/main/assets/models.json`]. Persian, the project's first-class test language for text [`docs/mobile/contract.md:91-92`], can only be tested today in post-processing (contract vectors) and in the editing path (undo, spacing), not in recognition. The UI must not suggest otherwise (section 5, R9).
7. **No ADR amendment is needed for these findings.** One existing inconsistency should be resolved by the owner: the toggle cap is 120 s in ADR-MOB-004:47-48 and in #89's body, but the ADR's own erratum (MOB-004:8-9) and the code (`ActivationSource.kt:88-91`, default 300 s from `[audio] max_record_seconds`) say 300 s. A *proposed* wording fix is in section 7.

## 3. What the code already guarantees [Code]

| Concern | Where | What holds |
|---|---|---|
| Hold vs toggle are interchangeable sources | `ActivationSource.kt:1-12`, `:43-55`; `ActivationDriver.kt:1-26` | Same session, same debounce rules, same secure abort. A toggle requires `debounceMs = 0` (`ActivationDriver.kt:22-26`), so a TalkBack double-tap is not swallowed by the 500 ms hold debounce. |
| The UI can say *why* the mic closed | `ActivationSource.kt:24-37` | `KEY_UP`, `SECOND_ACTIVATION`, `CAP_REACHED`, `SECURE_ABORT`. Recovery messages (section 5) can be keyed on this. |
| Every refusal carries a reason | `DeliveryGuard.kt:10-36` | `NOT_DECODING`, `SECURE_FIELD`, `BLANK_TEXT`, checked in that order. |
| Effects the UI must render | `HoldSession.kt:39-63` | `StartCapture`, `StopCapture`, `Decode`, `Deliver`, `NothingHeard`, `DecodeFailed`, `Refused(reason)`. |
| States for the key-bar indicator | `HoldSession.kt:20-36` | `Idle`, `Holding`, `Capturing`, `Decoding`, `Delivering`. #89 asks for idle / recording / decoding / no-target / error; "no-target" and "error" are effects, not states, so the view needs a short-lived overlay state for them [Assumption]. |
| Single undo, UTF-16 lengths | `UndoLastInsert.kt:4-36` | One undo, then nothing; a newer insert replaces the older one. |
| Script-aware continuation spacing | `android/core/postprocess/.../Spacing.kt:8-30` | Persian closing marks and Unicode `Cf` characters (ZWNJ, bidi controls) are handled when deciding the space between bursts. |

**Gaps [Code]:** there is no clipboard-fallback model, no message catalogue and no announcement policy in `:core:*`; all three would be invented inside `:feature:ime`, where they are harder to test. Section 8 proposes moving the decisions into pure code.

## 4. Wireframes (text sketches, unvalidated)

Portrait, about 360dp wide. Each key at least 48dp x 48dp [S2]; the mic key wider. LTR shown; in an RTL locale the bar mirrors and backspace/enter use auto-mirrored icons [Assumption: standard `supportsRtl` behaviour; verify U6].

```
Idle                 [ ⌨ prev ] [  🎤  Hold to talk  ] [ ↶ undo ] [ ⌫ ] [ ⏎ ]
Holding (<500 ms)    [ ⌨ prev ] [  🎤  keep holding… ] [ ↶ undo ] [ ⌫ ] [ ⏎ ]
Capturing            [ ⌨ prev ] [ ● REC ▁▃▅▃▁ 0:07   ] [ ↶ undo ] [ ⌫ ] [ ⏎ ]
Decoding             [ ⌨ prev ] [  ⋯  Writing…       ] [ ↶ undo ] [ ⌫ ] [ ⏎ ]
Notice (3-5 s, then Idle; stays until dismissed if it needs an action)
                     [ ⌨ prev ] [ ⚠ Copied to clipboard — paste it   ✕ ] [ ⌫ ] [ ⏎ ]
Secure field         [ ⌨ prev ] [ 🔒 Mic off in password fields     ] [ ⌫ ] [ ⏎ ]
Toggle mode, capturing
                     [ ⌨ prev ] [ ● REC 0:42 / 5:00  Tap to stop   ] [ ⌫ ] [ ⏎ ]
```

Rules behind the sketch:

- **Recording is never colour-only:** the dot, the text "REC", the timer and the level meter change together, so the state is visible in greyscale and to colour-blind users. Text contrast at least 4.5:1 below 18sp [Primary, S2].
- **The mic key label changes with the mode** ("Hold to talk" vs "Tap to start"), and its accessibility description is the action, not the icon (S2: "describe the purpose and result of the interaction, not the visual details").
- **Toggle mode shows the cap** (`0:42 / 5:00`), because a session left running is the risk toggle mode adds back [ADR, MOB-004:79-81].
- **The undo key is disabled, with a reason, when there is nothing to undo or the text cannot be verified** (finding 5), instead of silently doing nothing.
- **Switch key:** `switchToPreviousInputMethod()` and `shouldOfferSwitchingToNextInputMethod()` are **API 28** [Primary, S3], but `minSdk` is 26 [#807 note section 1]. On API 26-27 the switch key needs a different call or must be hidden with a reason [Assumption: the pre-28 path is the deprecated `InputMethodManager.switchToLastInputMethod(IBinder)`, not re-read for this note]. Device test U5.
- **Landscape:** the default `onEvaluateFullscreenMode()` selects fullscreen with an extract editor in landscape [Primary, S3]. A five-key bar does not need it; overriding it to `false` keeps the host app visible [Assumption; verify U6].

## 5. Recovery flows

Every path ends with the user's words either in the field, on the clipboard with a message, or explicitly discarded with a reason. Nothing disappears silently (ADR-MOB-003:57-61; #89 table).

| # | Trigger (code signal) | What the user sees / hears | Recovery action | Notes |
|---|---|---|---|---|
| R1 | `commitText` returns `false` (connection no longer valid) [S1] or no `InputConnection` | "Copied to clipboard — paste it" notice, persistent until dismissed | Paste; the notice offers nothing else | ADR-MOB-003:57-61. Announce as a polite live-region notice, after capture has stopped (finding 2). |
| R2 | `Refused(SECURE_FIELD)` at press | "Mic off in password fields" | None needed | Already refused before capture [Code, `HoldSession.kt:110-115`, `DeliveryGuard.kt:20-21`]. The text must not be copied to the clipboard either: nothing was recorded. |
| R3 | `SECURE_ABORT` mid-burst (focus moved to a password field) | "Stopped: password field — nothing was kept" | None | `ActivationSource.kt:35-36`: audio discarded. |
| R4 | `NothingHeard` | "Microphone muted or unavailable — hold and speak" | Retry | #807 C4: with the Android 12+ privacy toggle off, the mic delivers silence, which an RMS gate reports as nothing heard. The message should add "Check the microphone toggle" when the level meter never moved above floor [Assumption on how to tell them apart; U3]. |
| R5 | `Refused(BLANK_TEXT)` | Same text as R4 | Retry | A blank decode looks the same to the user as silence; one message, not two. |
| R6 | `DecodeFailed` / model missing | "Speech model missing — open YazSes to download" with a button that opens the app | Opens onboarding / model screen | Error names the fix (#89). Model-state wording belongs to the #806/#809 note. |
| R7 | `CAP_REACHED` (toggle) | "Stopped at 5:00 — your text was added" | None | The burst is decoded, not lost: the end edge passes the captured audio to `session.onRelease` (`ActivationDriver.kt:147-152`), and `ActivationDriverTest.kt:45` ("the cap force-stops at exactly the cap and decodes the audio captured so far") proves it. |
| R8 | Misrecognition | User taps undo | Verified undo (finding 5); if verification fails: "Can't undo — the text was changed" | WCAG 2.5.2 allows completion on the up-event when the result can be undone [Primary, S5]; undo is what makes hold-to-talk meet that option. |
| R9 | Field or app language is not English (only `.en` models pinned) | Nothing is blocked; a one-time hint "English only for now" in the key bar | Settings link | Do not guess the field's language. Honest limitation, not an error. |
| R10 | Mic permission revoked or auto-reset (#807 C5, C6) | "Microphone permission needed — open YazSes" | Opens the onboarding activity | An IME cannot request the permission itself (#807 C5). The capture layer already reports this case as `CaptureStopReason.PERMISSION_LOST` (`MicrophoneCapture.kt:20`, raised at `:125`), the signal the #806/#809 note relies on. |

## 6. Accessibility acceptance tests

"CI" means a JVM or Robolectric-style test that needs no device; "Device" means a phone or emulator with TalkBack. None of these has been run.

| # | Test | Where | Pass condition |
|---|---|---|---|
| A1 | Toggle start/stop with `debounceMs = 0` survives a double-tap timing (two taps at most 300 ms apart start and stop) | CI, `:core:session` | Exists in part: the driver rejects a toggle with non-zero debounce (`ActivationDriver.kt:22-26`). The first-tap start and second-tap stop are already tested (`ActivationDriverTest.kt:23`, `:29`); add only a test that a second tap less than 300 ms after the first still stops and decodes. |
| A2 | Every `SessionEffect` and `EndCause` maps to exactly one message id and announcement policy | CI, proposed pure `KeyBarMessages` (section 8) | Exhaustive `when`; a new enum value fails compilation. |
| A3 | No announcement is scheduled between `StartCapture` and `StopCapture` | CI, same | Policy returns "announce before" or "announce after" only. |
| A4 | Verified undo refuses when text before cursor differs, is shorter, or is null | CI, `:core:session` | Covers the Persian/emoji corpus below. |
| A5 | All key-bar targets at least 48dp x 48dp, every key has a non-empty, unique description | CI (UI test) | S2 thresholds. |
| A6 | Contrast of key-bar text at least 4.5:1 in light and dark | CI | S2. |
| U1 | TalkBack on: mic key with hold mode selected; then toggle | Device | Record what event sequence the view receives; decide the TalkBack default from it. |
| U2 | TalkBack on, speaker output: does an announcement made during capture appear in the transcript? | Device | Measured with synthetic speech only, no real dictation. |
| U3 | Privacy mic toggle off: level meter and `NothingHeard` message | Device, API 31+ | Message distinguishes the two cases, or the note's assumption is dropped. |
| U4 | Previous IME leaves a composing span; switch to YazSes; dictate | Device, with two other keyboards | No user text overwritten. |
| U5 | Switch-to-previous key on API 26, 27, 28+ | Emulator images | Key works or is hidden with a reason. |
| U6 | RTL locale (Persian) and landscape: bar mirrors, no fullscreen extract view | Emulator | Visual check, screenshot attached. |
| U7 | Switch Access (one switch, auto-scan) can start and stop toggle mode | Device | Reachable without a touch. |
| U8 | Large font and display size (largest settings): labels not clipped, no key under 48dp | Emulator | Screenshot. |

### Synthetic Unicode / RTL corpus for A4 and the spacing path

Synthetic strings only, no real dictation. Each row is input to undo verification and to continuation spacing (`Spacing.kt`), with UTF-16 length noted because `deleteSurroundingText` counts Java chars [S1].

| Case | Example (escaped) | Why |
|---|---|---|
| Persian with ZWNJ | `می‌خواهم` | ZWNJ is a `Cf` character inside a word; must count and must not trigger spacing rules. |
| Persian comma after Latin | `OK،` | Script-aware closing mark (`Spacing.kt:8-12`). |
| Mixed LTR/RTL | `سلام YazSes 2.49` | Bidi run boundaries. |
| Extended Arabic-Indic digits | `۱۴۰۵` | Not ASCII digits. |
| Emoji (surrogate pair) | `ok 👍` | Length 5 in UTF-16, 4 in code points; undo must not split the pair (S1 warns IME authors about half pairs). |
| ZWJ emoji sequence | `👩‍💻` | One glyph, five code units. |
| Combining mark | `é` | One glyph, two code units. |
| CJK unspaced | `你好` | Unspaced script path (`Cjk.kt:59-72`). |
| Editor autocorrect | inserted `:)`, field now shows `☺` | Verification must refuse (A4). |

## 7. Feedback to #89 and #95 (prioritised), and the ADR question

**To #89 (`:feature:ime`), highest first:**

1. Add acceptance rows: "TalkBack on: mic key operable (toggle path)" (U1) and "no announcement during capture" (A3/U2).
2. Add "commit does not overwrite another keyboard's composing text" (finding 4, U4).
3. Make undo verified (finding 5, A4) and add "undo cannot delete text the user did not dictate" to the non-negotiable table.
4. Switch key on API 26-27 (U5): decide work-around or hide.
5. Resolve the cap figure: #89 says 120 s; code and the MOB-004 erratum say 300 s (`[audio] max_record_seconds`).

**To #95 (`:feature:settings`):** the hold/toggle switch and "English only for now" belong on the settings screen with the reason shown; the diagnostics screen should include "touch exploration on/off" and "mic toggle state, if readable" next to the permission rows, so a bug report from a screen-reader user carries the mode. #95 already lists "TalkBack-usable" as an acceptance item; U1 and U8 give it a concrete procedure.

**ADR question.** No ADR change is justified by this note: MOB-004 already makes toggle an M1 accessibility requirement, MOB-003 already requires the clipboard fallback. The one *proposed* wording fix (for the owner; nothing applied):

> MOB-004 §2: replace "(`max_burst_seconds`, default 120 s)" with "(the shared `[audio] max_record_seconds`, desktop default 300 s; see the erratum above)".

The TalkBack default (finding 1) should wait for U1 before any ADR text says how hold mode behaves under a screen reader.

## 8. Proposed pure-code seams (for #89, not implemented)

Following the house pattern (pure logic beside a heavy backend):

- `:core:session` **`VerifiedUndo`**: `decide(insert: String, before: CharSequence?) -> Delete(n) | Refuse(reason)`. Pure, covers A4 and the corpus.
- `:core:session` **`KeyBarMessages`**: maps `SessionEffect`, `EndCause`, `Refusal` and a delivery failure to `(messageId, persistence, announceWhen)`. Exhaustive over the enums (A2, A3). The IME only renders it.
- Neither changes a public interface; both are additions inside an Android module with JVM tests.

## 9. Sources (all read 2026-11-06 via a fetch tool that summarises pages)

- **S1** Android `InputConnection` reference, https://developer.android.com/reference/android/view/inputmethod/InputConnection (characters 0-100,000 of 118,371 read; `setComposingText` detail was beyond that part).
- **S2** Make apps more accessible, https://developer.android.com/guide/topics/ui/accessibility/apps (48dp x 48dp, 4.5:1 / 3:1 contrast, content descriptions).
- **S3** Android `InputMethodService` reference, https://developer.android.com/reference/android/inputmethodservice/InputMethodService (read in parts; `switchToPreviousInputMethod` and `shouldOfferSwitchingToNextInputMethod` "Added in API level 28"; `onUpdateSelection` API 3; fullscreen default in landscape).
- **S4** TalkBack gestures, Android Accessibility Help, https://support.google.com/accessibility/android/answer/6151827 ("Double-tap" activates; "Double-tap and hold" long-presses; pass-through is a 4-finger double tap and hold). The page does not describe on-screen keyboard typing behaviour.
- **S5** W3C, Understanding SC 2.5.2 Pointer Cancellation (WCAG 2.2), https://www.w3.org/WAI/WCAG22/Understanding/pointer-cancellation.html (four options: no down-event, abort or undo, up reversal, essential). It does not mention push-to-talk; mapping hold-to-talk onto "abort or undo" is my reading [Assumption].
