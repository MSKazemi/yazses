# Research: emergency stop, recovery and unintended activation — a threat model for hands-free input

**Status:** Research note (not a decision). ADR-030 freeze unchanged.
**Issue:** [#816](https://github.com/MSKazemi/yazses/issues/816), parent epic [#790](https://github.com/MSKazemi/yazses/issues/790). Sibling questions (not duplicated here): #813 task inventory, #814 co-design/ethics gates, #815 multimodal arbitration, #817 fatigue/accuracy study design, #818 Wayland limits, #819 go/no-go. Delivery stays under #102 and #692; safety stop was #417 (closed).
**Snapshot:** YazSes `main` at `a241a77b6c59d65fb9265a0475d42f1a97fdfe6a`, read 2026-11-05. **Class:** RESEARCH. No `src/` change, no new feature, no study authorised.

Tags on every statement: **[Verified-in-code]** read in this snapshot; **[Verified-primary-source]** read at the cited public page (the fetch tool returns a text summary of the page, not the page; "not read in full" is stated per source); **[Upstream-claim]** a vendor or standards-body statement I could not read in full; **[Assumption]**; **[Unknown]**.

## 1. Question

Can a user with no usable hands always pause or kill input after device loss, a runaway pointer, stale samples, a false switch activation, or an ambiguous destructive command, and how quickly? [#816] This note maps threats to existing mitigations and tests, ranks the gaps, and proposes synthetic tests. It does not answer "is it safe enough to recommend"; the evidence does not allow that (sections 6 and 11).

## 2. Method and sources

1. Read `handsfree/safety.py`, `handsfree/stopword.py`, `handsfree/preset.py`, `handsfree/recovery.py`, `facegesture/switches.py`, `facegesture/backend.py`, `cmdsafety/classify.py`, the stop/pause/shutdown paths in `core/daemon.py`, `audio/recorder.py`, and the config defaults. [Verified-in-code]
2. Read ADR-v2-148, `design/eye-control/RISK_REGISTER.md`, `TEST_PLAN.md`, `generated/validation-coverage.md`, and the closing comment on #417. [Verified-in-code]
3. Named test files were opened (docstring and test-name list); I did **not** run them (only the gates named in the hand-off were run). A test name is therefore evidence of intent, not of a pass.
4. External comparators, read 2026-11-05:
   - W3C, WCAG 2.2 Understanding SC 2.5.2 Pointer Cancellation, https://www.w3.org/WAI/WCAG22/Understanding/pointer-cancellation.html (summary; not read in full). [Verified-primary-source]: criterion aims to "prevent accidental or erroneous pointer input" and offers abort/undo.
   - W3C, WCAG 2.2 Understanding SC 2.1.4 Character Key Shortcuts, https://www.w3.org/WAI/WCAG22/Understanding/character-key-shortcuts.html (summary; not read in full). [Verified-primary-source]: dictated text can fire single-key shortcuts, "disastrous for speech users".
   - Apple, Voice Control commands, https://support.apple.com/guide/mac-help/use-voice-control-commands-mh40719/mac (summary; not read in full). [Verified-primary-source]: "Stop listening" pauses; "Start listening" resumes **by voice**. The page did not document "Go to sleep"/"Wake up".
   - Microsoft, Voice access command list, https://support.microsoft.com/en-us/topic/voice-access-command-list-dac0f091-87ce-454d-8d57-bef38d3d8563 (summary; not read in full). [Verified-primary-source]: "Voice access sleep"/"Mute" and "Voice access wake up"/"Unmute"; "Turn off microphone". No microphone keyboard shortcut was listed on that page (a search snippet mentioned Alt+Shift+C; not verified).
   - ISO 13850:2015 *Safety of machinery — Emergency stop function — Principles for design*, https://www.iso.org/standard/59970.html: **the ISO page returned HTTP 403; not read.** Scope text came only from standards-body listings in a search result (e.g. https://www.evs.ee/en/iso-13850-2015). [Upstream-claim]: it specifies functional requirements for the emergency stop function on machinery. The normative text is paywalled and I did not read it, so I borrow only the vocabulary (a stop function distinct from a reset) and make **no** conformance claim; YazSes is not machinery.
   - Jacob, "What you look at is what you get" (CHI 1990), the "Midas touch" source. The ACM page returned 403; only a search-result summary was seen. [Upstream-claim] (every look can trigger a command). Identifier not verified here.

Not read: IEC 60204-1, IEC 60812 (FMEA), ISO 14971, any clinical or ISO accessibility standard. [Unknown] whether they add requirements.

## 3. Scope, assets, actors

**In scope:** the existing voice, face-switch, Head-Pointer, chord, biosignal-switch and command-safety paths when `[handsfree_safety]` / the hands-free preset is on. **Out of scope:** new capabilities, thresholds as recommendations, human studies, Wayland semantics (#818), arbitration design (#815).

- **Assets:** the user's document and open windows (integrity); files and shell state (destructive commands); the microphone and camera streams (privacy, ADR-011/019); the user's ability to keep using the computer (availability).
- **Actors:** the user, who may be unable to reach keyboard or pointer; a bystander or TV speaking near the mic; a second person assisting recovery; the OS (device unplug, suspend); the model (misrecognition); contributors changing the code.
- **Trust assumption:** the local machine is not hostile. Adversarial voice injection is not modelled. [Assumption]

## 4. How the stop works today (what the code guarantees)

- **One gate, three states.** ACTIVE / PAUSED / FAULTED; each camera source asks `HandsFreeSafety.gate()` before acting; no fourth "killed" state; shutdown is terminal PAUSED. `safety.py:15-19, 198-221, 337-349`. [Verified-in-code]
- **Fail-closed start.** Every source starts disarmed with no sample; `resume()` refuses a source with no fresh signal or an open fault. `safety.py:212-216, 351-390`. [Verified-in-code]
- **No replay.** An aged-out source is denied until a new sample arrives; recovery bumps an epoch so the next `gate()` returns `clear_pending=True` once. `safety.py:21-25, 42-47, 244-273`. [Verified-in-code]
- **Pause is lock-protected and idempotent, callable from any thread.** `safety.py:320-335`. [Verified-in-code]
- **Staleness window 500 ms, explicitly "not a measured value".** `safety.py:49-57`, `config.py:1559`. [Verified-in-code]
- **Opt-in auto re-arm only for hold-only face switches, only after a *staleness* disarm**, 1 s unbroken fresh signal; pause, fault and shutdown still need explicit resume. `safety.py:27-34, 275-298`, `facegesture/switches.py:90`, `daemon.py:2731-2734`. [Verified-in-code]
- **Stop paths with no pointer:** `yazses handsfree pause` (IPC `_handle_handsfree`, takes no position) `daemon.py:9167-9255`; spoken stop phrase `stopword.py:107-116` + `daemon.py:7676-7725`, evaluated ahead of every typing handler `daemon.py:4531-4536`; face-switch `pause_pointer`, allowed even while the gate is closed (`switches.py:124`, wiring `daemon.py:2689-2696`); chord `brow_raise+shake` (`preset.py:80`, `gesture/runtime.py:378`); the settings page Pause button with Alt+P (`panel.py:611-623`, needs the window open). [Verified-in-code]
- **Voice stop is whole-utterance equality**, 2-6 words, NFKC/case-fold/hyphen tolerant, pause-only (no resume phrase). `stopword.py:14-29, 53-57, 107-116`. [Verified-in-code]
- **Shutdown suppresses first**, before any backend closes. `daemon.py:1765-1779`. [Verified-in-code]
- **Safety floor in the preset** (`protected=True`): global stop, command-safety confirm, gaze `confirm_destructive`, `refuse_destructive_fallback`; a weaker user value makes the preset refuse as a whole. `preset.py:182,187,203,208`. [Verified-in-code]
- **Tray:** no hands-free item (`src/yazses/tray/` has no `handsfree` reference; `stopword.py:28-29` says the same). Tray Quit sends `shutdown` over IPC `tray/app.py:380-387`, which ends the daemon, not a pause. [Verified-in-code]

## 5. Threat table

Evidence level: **ST** synthetic test, **CI** runs in CI, **HW** hardware, **RU** real-user, **none**. All tests below are fake-clock or fake-backend; "HW"/"RU" never apply except where stated.

| # | Threat | Existing mitigation (file:line) | Test evidence present | Level |
|---|---|---|---|---|
| T1 | Stuck-on recording: face switch cannot release | `max_hold_s` stuck-open guard, **default 0 = off** `config.py:693`; refusal at calibrate/doctor/panel `facegesture/restcheck.py`; blind frames close hold `backend.py:441-446`; gate closing releases holds `switches.py:289-320` | `test_facegesture_stuck_open.py`, `test_facegesture_detector_edges.py`, `test_facegesture_shared_camera.py` | ST, CI |
| T2 | Stuck-on recording: recorder never ends | `max_record_seconds` 300 s `config.py:202`, but the cap only **drops samples**, the stream stays open `recorder.py:193`; stray release types nothing `daemon.py:4066-4079` | `test_stray_hold_release_types_nothing.py`; none found for the cap itself (no cap test in `test_recorder.py`) | ST (release only) |
| T3 | False activation from ambient speech/noise | Whole-utterance stop only; hold-to-talk needs a deliberate gesture; mouth-open vs talking is R-13 (open) | `test_handsfree_stopword.py` (prose corpus never fires), `test_face_switch_replay*.py` (synthetic traces) | ST |
| T4 | False activation from blink / natural face motion | Eyes-closed hold floor 0.8 s *of time* (provisional) ; `confidence_floor`, hysteresis, refractory; blink never default (R-14) | `test_facegesture_eyes_closed_wall_time.py`, `test_face_switch_replay_robustness.py` | ST; one maintainer live run 2026-10-18 found a phantom re-type (fixed) |
| T5 | Cannot stop with no hands | Stop routes listed in panel from saved config `panel.py:627-672`; voice, face, chord, CLI | `test_handsfree_panel_stop_routes.py`, `test_handsfree_stop_from_faulted.py`, `test_daemon_handsfree_ipc.py` | ST |
| T6 | Stop path itself fails (faulted camera, mic closed, bad ASR) | Pause works from FAULTED; stop word consumed even if pause fails `daemon.py:7688-7725`; `pause_pointer` bypasses the gate `switches.py:124` | `test_handsfree_stop_from_faulted.py`, `test_handsfree_stopword.py` (mocked `_handle_handsfree`) | ST. ASR recognition of the phrase: **none** |
| T7 | Wrong window gets text or a destructive action | Fallback never raises consequence `recovery.py:1-30`; destructive needs explicit target; `confirm_destructive` default True `config.py:608`, `refuse_destructive_fallback` default **False** outside the preset `config.py:618` | `test_handsfree_recovery.py`, `test_cmdsafety_*` | ST |
| T8 | Ambiguous destructive shell command dictated | `assess_command` patterns, hold until spoken confirm; `[cmdsafety]` **off by default** `config.py:1676`; no timeout (implicit cancel on next utterance, `daemon.py:6014-6024`) | `test_cmdsafety_daemon.py`, `test_cmdsafety_patterns_can_fire.py`, `test_cmdsafety_sees_the_typed_text.py` | ST |
| T9 | Runaway streaming partials | Streaming **off by default** `config.py:350`; commands never stream `daemon.py:3957`; voice stop calls `stream_injector.cancel()` (backspaces) `daemon.py:4532-4534`, `inject/streaming.py:84-91` | `test_streaming_stop_leak.py`, `test_streaming_injector.py` | ST |
| T10 | Camera/gaze mis-targets | Per-source containment; stale source disarmed; wrong-target rate is R-01 (open) | `test_handsfree_safety.py`, `test_handsfree_e2e_fake_scenario.py` | ST; no HW |
| T11 | Device loss mid-hold | Stream death flagged, take filed `device_lost` (`bc60f88c`); camera blindness closes hold | `test_recorder_device_change_mid_recording.py` (mocked sounddevice, not measured) | ST |
| T12 | Battery / fatigue lockout | None found for camera sources; `grep -ril fatigue src/yazses` hits only config/voicehealth/biosignal comments (vocal-strain guard is separate). R-11, R-18 open | none | none |
| T13 | Shutdown races an activation | `shutdown()` first, terminal `daemon.py:1765-1779`, `safety.py:337` | `test_handsfree_safety.py::test_shutdown_suppresses_first_and_cannot_be_rearmed` | ST |

Mapping to the existing register (`design/eye-control/RISK_REGISTER.md`) [Verified-in-code]:

- T1, T2, T6 -> R-05 (cannot stop; Critical) and R-24 (recovery triggers an action).
- T3, T4 -> R-03, R-13, R-14 (false activation, talking, blink).
- T10 -> R-01 and R-06 (wrong target; stale pose).
- T12 -> R-11 and R-18 (CPU/battery; fatigue).
- R-05 and R-24 are listed as **release blockers** for the hands-free bundle; the register states they stay blockers "even if unit tests are green".

## 6. Gaps, ranked

Rank = severity for a no-hands user x likelihood of mattering x how little is known.

1. **G1 — The voice stop is untimed and unmeasured end to end.** It fires only after a hold-to-talk burst ends **and** Whisper decodes it, then equality-matches. No stop-to-suppress latency bound exists; recognition of "pause hands free" is explicitly unmeasured (`stopword.py:31-34`). A misrecognition ("paws hands free") is typed as text. [Verified-in-code]; real-world miss rate [Unknown]. Pointer-side pause itself is instantaneous once called (same lock) [Verified-in-code]; the delay is in reaching it.
2. **G2 — Stop is final for a no-hands user; resume has no hands-free route.** By design there is no spoken resume (`stopword.py:26-29`, `daemon.py:7710-7713`), the tray has no item, and resume is CLI or Settings page. After a *false* stop, a user who cannot type or point is locked out until someone helps. Apple documents voice resume ("Start listening") and Microsoft documents "Voice access wake up"/"Unmute" [Verified-primary-source], so the design differs from both comparators on purpose; whether the trade-off is right for this user group is [Unknown] and is a maintainer/co-design question (#814).
3. **G3 — A held microphone can outlive its cause.** `max_record_seconds` drops audio but the stream stays open (`recorder.py:193`), `max_hold_s` defaults to 0, and the own-capture loop leaves a hold held when a frame raises (`backend.py:571`). The gate watchdog runs only when a consumer calls `gate()`/`sample()`; the daemon does not tick it for the face switch (it calls `gate.status()` for display only; biosignal has its own watchdog thread, `biosignal/runner.py:14`). A camera read that **hangs** (not returns) would feed no frames, so no release. [Verified-in-code] for each fragment; the hang scenario is [Assumption], untested.
4. **G4 — Every threshold on the stop path is a placeholder.** 500 ms staleness, 1 s re-arm, 0.8 s eyes-closed floor, 0.5 confidence floor, default stop phrase: all labelled provisional/unmeasured in source. [Verified-in-code] A too-short window trips FAULTED and costs the user their input (`safety.py:55-57`).
5. **G5 — No hardware or user evidence.** `validation-coverage.md`: 16 cells registered, 16 PLANNED, 0 reported, 0 independent hosts. [Verified-in-code] RISK_REGISTER lists R-03/R-04/R-18 measurement as recommendation blockers. The only live evidence is single-maintainer anecdote (stray re-type 2026-10-18; stale-every-glance, ADR amendment). RU for target users: none.
6. **G6 — Non-hold re-arm is an open decision.** Who may re-arm select/confirm switches and chords is "pinned as an open decision" (#417 closing comment; `test_handsfree_safety_semantics.py`). [Upstream-claim: #417 closing comment; the pinned test was not opened]
7. **G7 — Command safety is shell-pattern text only, off outside the preset, no timeout.** A confirm word is accepted from whatever the mic hears; whether any speaker check applies here is [Unknown]. GUI-destructive actions rely on deixis confirm, a different gate.
8. **G8 — No fatigue or battery lockout** (T12). Camera sources run until paused. [Verified-in-code by grep] Effect on a fatigued user is [Unknown].
9. **G9 — Streaming + stop phrase** types partials then backspaces; correctness depends on the target app honouring backspaces (`config.py:336-338` warns shift+Left deletes in some apps). Off by default.

## 7. What the safety floor guarantees, and does not

**Guarantees (under the stated test fakes) [Verified-in-code]:** with the gate enabled, a pause denies every registered camera source on the next `gate()` call; stale or faulted sources never act on old data; recovery is explicit (except opt-in hold-only staleness); half-made gestures are dropped at stop/re-arm; open face-switch holds are released when the gate closes and a frame arrives; destructive gaze actions are not redirected to a stand-in window when the preset floor is on; shutdown is terminal.

**Does not guarantee:** that a stop is *reachable* (needs camera, an open mic path, a window, or a terminal, each of which can be the thing that failed); any latency bound; that the gate is on (`[handsfree_safety]` and `[cmdsafety]` default to off; only the preset turns them on, `preset.py:182,187`); that a stop word is recognised; that the microphone closes when the recorder cap is hit; that keyboard hold-to-talk (a separate path, `daemon.py:3891`) is governed by the camera gate; that `pause` stops speech dictation by design (ADR-v2-148: "losing face tracking should not disable speech"). [Verified-in-code]

## 8. Recovery paths for a user with no hands

| Situation | Route available | Needs | Evidence |
|---|---|---|---|
| Pointer running away | Voice stop (if hold works), face `pause_pointer`, chord, `yazses handsfree pause`, panel Pause | mic path / camera / terminal / window | ST |
| Camera lost (FAULTED) | Voice stop; CLI | mic path; terminal | ST (`test_handsfree_stop_from_faulted.py`) |
| Mic lost | Face switch or chord pause (camera-based); CLI | camera or terminal | ST (mocked) |
| False stop, want to continue | `yazses handsfree resume` or Settings Resume/Recover (Alt+R) | **hands or an assistant** | ST |
| Dictation hold stuck open | Release gesture; `max_hold_s` if set; `yazses stop`; tray Quit | pointer for tray; terminal for stop | ST for guard only |
| Everything failed | Another person, power/OS-level control | outside YazSes | none |

[Assumption] Each route is only as available as its dependency. Screen-reader/switch-scan reachability of the panel is **not tested** by this note (see non-claims).

## 9. Proposed synthetic tests (not implemented, not authorised to implement under the freeze)

All numeric or string fixtures; no audio, face, or participant data; fake clocks.

- **S1 Reachability matrix.** From a saved config, derive each stop route's dependency set {camera, mic-open, pointer, keyboard, window, terminal}; assert at least one route avoids both camera and pointer, and report configs where none exists. Pure over `stop_routes` inputs. Closes G1/G2 visibility.
- **S2 Stop-latency budget replay.** Fake clock + fake engine returning a scripted decode time; assert pause-called-to-all-denied is 0 ticks and report release-to-pause time as a function of decode time. Gives a *model*, not a measurement. Closes G1.
- **S3 Stop-phrase confusion set.** A hand-written list of plausible mis-transcriptions ("paws hands free", "pause hand free"); assert each is typed, not consumed, and that none matches by accident. Documents the miss mode without audio. Closes G1.
- **S4 Stuck-hold characterisation.** Recorder fed samples past `max_record_seconds` with no release; assert and document current behaviour (stream open, samples dropped). Follow with a maintainer decision (Q2). Closes G3.
- **S5 Frozen-capture replay.** Own-capture loop with a `cap.read()` that raises on every call, and one that blocks past a deadline; assert whether an open hold is released. Expect a failure for the exception case (`backend.py:571`). Closes G3.
- **S6 False-stop lockout model.** Enumerate gate states after a voice stop and the resume routes each one admits; assert the set contains no route that avoids hands and report it. Frames Q1 for #814.
- **S7 Streaming stop-phrase replay.** Scripted partials ("pause", "pause hands", "pause hands free") through `StreamingInjector` then cancel; assert net injected characters is 0 with a fake injector, and that a backspace-ignoring fake leaves residue. Closes G9.
- **S8 Confirm-word contamination.** Held `rm -rf` followed by scripted ambient strings; assert only exact confirm words release it and that a held command survives an unrelated utterance policy (document implicit cancel). Closes G7.

## 9a. Draft stop/recovery acceptance model (a proposal for discussion, not a requirement)

Numbers are deliberately left as parameters: no measurement exists to fill them ([Unknown]).

| Invariant | Statement | Checkable by |
|---|---|---|
| I1 No-action-after-stop | After `pause()` returns, no source's `gate()` returns `allowed` until an explicit `resume()` succeeds (hold-only staleness re-arm excepted) | S2, existing `test_handsfree_safety*.py` |
| I2 No replay | The first decision after any suppression or re-arm carries `clear_pending`; no pose, switch or gaze value from before it is acted on | existing `test_handsfree_safety_clean_rearm.py` |
| I3 Bounded hold | A microphone hold opened by any hands-free source ends within T_hold of its cause ending or the gate closing, T_hold a stated parameter | S4, S5 |
| I4 Reachable stop | For every enabled configuration at least one stop route exists whose dependencies exclude every component that can be the failed one | S1 |
| I5 Stop latency | Release of the stop utterance to all-sources-denied is below T_stop, T_stop a stated parameter, reported as a distribution not a mean | S2 (model); real value needs hardware and consent gates |
| I6 Recoverable | After any stop, at least one documented resume route exists that the same user can perform, or the config says explicitly that an assistant is required | S6 |
| I7 No destructive action on a stand-in target | A destructive action never runs on a target the user did not choose | existing `test_handsfree_recovery.py` |

## 9b. What would falsify this note's conclusions

- A reproduced case where a source acts after `pause()` returned, which would falsify I1 and the "Guarantees" paragraph.
- A frozen own-capture read that leaves a microphone open past T_hold (S5 failing), which would confirm G3 rather than leave it an assumption.
- A measured stop-phrase miss rate low enough across accents and rooms to make G1 negligible, or high enough to make the voice route unreliable. Neither measurement exists.
- A user group for whom a spoken resume causes more harm than a locked-out stop (against G2); only co-design (#814) can show this.
- Any comparator page, read in full, contradicting the summaries recorded in section 2.

## 10. Open questions for the maintainer

- **Q1:** Is "no spoken resume" a settled rule for a user with no hands, or should #814 test a guarded spoken resume? Apple and Microsoft resume by voice.
- **Q2:** Should the recorder cap close the stream, and should `max_hold_s` have a non-zero default when the gate is on? Both change defaults, so outside this note's authority.
- **Q3:** Should the gate be ticked by the daemon so a hung capture thread cannot hold a microphone open?
- **Q4:** Is a tray Pause item wanted given ADR-v2-148 lists tray/menu as a stop example but none ships?
- **Q5:** Which of the 16 PLANNED validation cells, if any, should ever cover a stop-latency or false-stop session, and under whose review (#425/#427)?
- **Q6:** ADR-v2-148 is still `Proposed (2026-09-22)` while the code relies on it. Intentional?

## 11. Non-claims

No user study. No hardware validation (0 cells reported; none run here). No screen-reader, switch-scanning or assistive-technology testing. No measurement of ASR accuracy, stop latency, false-activation rate or staleness distribution. No recruitment, recording, or sensor upload occurred. No ISO 13850, IEC or WCAG conformance claim; ISO text was not read. Tests named above were not re-run for this note. The comparator pages were read as tool-produced summaries. This note is not an ADR amendment and does not lift the ADR-030 freeze.
