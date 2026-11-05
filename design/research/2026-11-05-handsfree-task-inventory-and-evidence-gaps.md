# Hands-free task inventory and evidence gaps

**Date:** 2026-11-05 · **Baseline:** `main` at `a241a77b` (v2.48.1 line) · **Issue:** [#813](https://github.com/MSKazemi/yazses/issues/813) (NEXT-A11Y-01), epic [#790](https://github.com/MSKazemi/yazses/issues/790)
**Status:** Research note (not a decision). ADR-030 freeze unchanged.
**Scope:** read-only audit of this repository. No `src/` change, no new capability, no participant, no recording, no external source (none was needed).
**Siblings:** [#814](https://github.com/MSKazemi/yazses/issues/814) co-design gates · [#815](https://github.com/MSKazemi/yazses/issues/815) arbitration · [#816](https://github.com/MSKazemi/yazses/issues/816) stop/unintended-activation threat model · [#817](https://github.com/MSKazemi/yazses/issues/817) measurement · [#818](https://github.com/MSKazemi/yazses/issues/818) Wayland/AT limits · [#819](https://github.com/MSKazemi/yazses/issues/819) go/no-go proposal. Delivery stays in [#102](https://github.com/MSKazemi/yazses/issues/102) / [#692](https://github.com/MSKazemi/yazses/issues/692).

## 1. Question and answer in one paragraph

Open question of #813: can a person complete editing, app navigation, dialog response and stop/recovery workflows with existing voice/gaze/head/switch capabilities? **Answer from the repository alone: not demonstrated, and for four task families demonstrably not complete.** [Verified-in-code] Most single capabilities exist and have synthetic tests. [Verified-in-docs] No hands-free capability has a hardware record or a user study in the validation registry. [Verified-in-code] Several complete tasks have a first step that needs a keyboard, a pointer or a terminal, and the way back from a pause or a restart has no hands-free route at all.

## 2. Method, labels and evidence scale

Read: `AGENTS.md`, `docs/roadmap.md`, `docs/validation-matrix.md`, `docs/features.md` (generated registry), `docs/how-to/hands-free-setup.md`, `hands-free-voice-stop.md`, `gaze-look-to-pane.md`, `design/eye-control/*` (README, VALIDATION_MATRIX, EVALUATION, RISK_REGISTER, `validation-slots.json`, `generated/validation-coverage.md`), ADR-v2-148, and `src/yazses/{handsfree,gaze,facegesture,headpointer,gesture,mousegrid,pilot,windowctl,commands,eyeeval}`. Nothing was run on a camera or a desktop.

Labels: **[Verified-in-code]** read in `src/` or `tests/` (or absence found by `grep`; a grep absence is not proof of absence). **[Verified-in-docs]** stated in a repository document, not independently re-checked. **[Assumption]** my inference. **[Unknown]** not determinable from the repository.

Evidence level per task (highest present): `none` < `synthetic` (named test file; runs in CI on the OS matrix, [Verified-in-docs] E20 in `docs/validation-matrix.md`) < `hardware record` < `real-user study`. A synthetic test proves a rule on fabricated input; it cannot show that anything was seen, heard or reachable on a real desktop ([Verified-in-docs] `design/eye-control/EVALUATION.md`, E0 versus E3-E7). **No row below reaches `hardware record`.**

Tier words are those of `docs/features.md`: core, recommended (on by default), recommended, optional, experimental, planned (not wired). [Verified-in-docs]

## 3. Inventory of complete hands-free tasks

"Hands-free entry" asks whether the *first step* of the task can be taken by a person with no keyboard and no mouse. `NO` means that step needs a key, a pointer or a terminal. `CAM` means it depends on a working camera. `BURST` means it needs a dictation burst to have been started first (task 3).

| # | Task | Implementing capability (module / slug / tier) | Hands-free entry | Evidence present |
|---|---|---|---|---|
| 1 | Set up hands-free (enable preset, packages, calibrate, restart, arm) | `handsfree/preset.py` / `handsfree` / experimental (needs `--force`). [Verified-in-docs] | **NO.** Terminal (`yazses handsfree enable --force`, `restart`, `resume`) or Settings window; both calibrations are terminal-only. [Verified-in-docs] | synthetic: `test_handsfree_preset.py`, `test_handsfree_cli.py`, `test_handsfree_setup_doc.py`, `test_settingsui_handsfree_apply_and_routes.py` |
| 2 | Start the daemon (first time, then every login) | `platform/linux/autostart.py`, `cli.py start`; `tray` / recommended (on by default). [Verified-in-code] | First start: **NO** (`yazses start`). Later logins: yes, via the login service. [Verified-in-code] `test_cli_start_autostart.py` | synthetic: `test_autostart.py`, `test_cli_start_autostart.py`, `test_tray_daemon_recovery.py`. Hardware: matrix "Start / restart / stop" is UNVERIFIED on Linux, **Failed (HW)** on Windows Scoop 2.36.0 (E12). [Verified-in-docs] |
| 3 | Start / stop dictation | Core hold-to-talk is a **keyboard key** (`HotkeyConfig.key`, default right_alt/right_option/right_ctrl). [Verified-in-code] Hands-free: `facegesture/` / `facegesture` / experimental (jaw-open default, eyes-closed opt-in); `biosignal` / experimental; `autostop` / optional is a hotkey *tap*; `wakeword` is **planned, unwired**. [Verified-in-docs] | **CAM only** (face switch) or biosignal hardware. No voice-only start exists. [Verified-in-code] | synthetic: `test_facegesture_*.py` (many), `test_face_switch_replay.py`, `test_facegesture_stuck_open.py`, `test_stray_hold_release_types_nothing.py`. Informal maintainer live observation 2026-10-18 (ADR-v2-148 amendment); not a registry record. [Verified-in-docs] |
| 4 | Correct a mistake | Re-dictate; `undo` "scratch that" (`commands/revise.py`, recommended on by default); `spoken-edit` (optional, "change X to Y"); `reask` (optional). [Verified-in-docs] | BURST. Spoken-edit is "command-key gated"; the config says single-key mode auto-detects commands on the dictation key. [Verified-in-code] Whether a face-switch burst qualifies: [Unknown] | synthetic: `test_revise.py`, `test_scratch_that_ordering.py`, `test_spoken_edit_does_not_match_a_word_ending_in_words.py` |
| 5 | Undo | `commands` "undo" (ctrl+z via `commands/dispatch.py`); `timeline` / recommended ("undo the last sentence"). [Verified-in-code] | BURST | synthetic: `test_timeline_sentence_undo.py`, `test_scratch_that_ordering.py`. In-app effect of ctrl+z per OS: matrix injection cells UNVERIFIED except Linux X11 "Reported". [Verified-in-docs] |
| 6 | Navigate / select text | Key-level voice commands: select all, go up/down/left/right, page up/down, home/end, tab, escape (`commands/grammars/en.py`, `dispatch.py`). `findreplace`, `jump` (Neovim only), both optional. `hatselect` (structural selection) is **planned, unwired**. [Verified-in-code/docs] Selecting an arbitrary word or range: no command found in the dispatch table. [Verified-in-code, grep] | BURST | synthetic: `test_grammar_classifier.py`, `test_grammar_punctuation_and_keys.py`, `test_cli_jump.py`. Cross-app effect: none |
| 7 | Click / activate a control | `headpointer` + dwell-click (optional); face-switch `select` action (not bound by the preset); `pilot` (optional, Linux AT-SPI, "click Save"); `mousegrid` (experimental, X11/macOS); `mouthswitch`, `vocaljoystick` (experimental). [Verified-in-code/docs] | Pointer: CAM. Pilot/grid: BURST. Dwell **clicks only while the overlay is shown**, and the overlay is not launched on native Wayland, so nothing clicks there. [Verified-in-docs] | synthetic: `test_headpointer_state_matrix.py`, `test_headpointer_reachability.py`, `test_pilot_wiring.py`, `test_mousegrid_wiring.py`, `test_overlay_dwell_ring.py`. Wrong-target rate: none |
| 8 | Switch window / app | `windowctl` (optional, **X11 only**, focus by name and layout verbs); `gaze` / experimental routes *dictation* to the looked-at window on X11 but does not focus it. [Verified-in-docs] No alt-tab or app-launch command found. [Verified-in-code, grep] | BURST (voice) or CAM (pointer on a taskbar) | synthetic: `test_windowctl_actions.py`, `test_windowctl_focus.py`, `test_windowctl_promises.py`, `test_gaze_route.py`, `test_gaze_glance_type_end_to_end.py`. Wayland/Windows/macOS: no voice route |
| 9 | Handle an unexpected dialog (not YazSes's own) | No dialog detector found. [Verified-in-code, grep; Assumption that it is exhaustive] Reachable only through generic means: voice "press enter / escape", `pilot` label click, `mousegrid`, dwell. YazSes's *own* confirmations (`cmdsafety` "confirm", pilot hold) are handled. | BURST or CAM | synthetic: `test_cmdsafety_daemon.py`, `test_pilot_confirm_recheck*.py`, `test_command_mode_target_guard.py`. Unexpected-dialog scenario: **none** |
| 10 | Pause | Voice stop phrase (`handsfree/stopword.py`, preset role); chord brow-raise+shake (`gesture`, optional); face switch bound to `pause_pointer` (not bound by the preset); `handsfree pause`; panel Pause button. [Verified-in-docs] | Voice phrase: BURST, so it depends on the face switch still running. Chord: CAM. CLI/panel: **NO**. | synthetic: `test_handsfree_stopword.py`, `test_handsfree_stop_from_faulted.py`, `test_handsfree_safety.py`, `test_handsfree_panel_stop_routes.py`. Phrase recognition rate: unmeasured. [Verified-in-docs] |
| 11 | Stop everything (daemon, camera) | `yazses stop` (`cli.py`), tray Quit. Pause leaves sensing on; `handsfree disable` + `restart` releases the camera. [Verified-in-docs] No spoken or gestural quit found. [Verified-in-code, grep] | **NO** | synthetic: `test_stop_closes_the_tray.py`, `test_tray_stop_and_messages.py` |
| 12 | Recover from a stuck state (runaway pointer, camera lost, mic held open) | `handsfree/safety.py` (ACTIVE/PAUSED/FAULTED, stale watchdog 500 ms placeholder), `handsfree/recovery.py`, `facegesture/restcheck.py`, `audio.max_record_seconds` 300 s cap. [Verified-in-code] Hold-only face switch re-arms by itself 1 s after the face returns; everything else needs explicit Resume. [Verified-in-code] | Auto-rearm: CAM. Resume: **NO** (CLI or panel). | synthetic: `test_handsfree_safety_auto_rearm.py`, `test_handsfree_safety_clean_rearm.py`, `test_handsfree_e2e_fake_scenario.py`, `test_facegesture_stuck_open.py`, `test_headpointer_hostile_inputs.py` |
| 13 | Change a setting | Settings window (Qt), `config.toml`, CLI. No spoken settings command found. [Verified-in-code, grep] | **NO** (keyboard or pointer; the Hands-free page is reachable by Tab, [Verified-in-docs]) | synthetic: `test_settingsui_keyboard_access.py`, `test_settingsui_handsfree_accessibility.py` (Qt offscreen, contrast formula; no real screen reader) |
| 14 | Update YazSes | `update-check` (optional, notification only), `yazses update`, tray "Install update". [Verified-in-docs] | **NO** | synthetic: `test_updater.py`, `test_cli_update.py`, `test_tray_update_click_acts.py`. After an update the daemon restarts (task 15) |
| 15 | Recover after reboot / lock / suspend | Login service restarts the daemon (task 2). Hands-free **starts PAUSED after every start** and needs an explicit Resume. [Verified-in-docs] No lock-screen or suspend handler found in `core/daemon.py`; camera stall timer uses a clock that does not advance in suspend. [Verified-in-code, grep] What the gate does with a pre-suspend sample after wake: [Unknown] | Daemon back: yes. Resume: **NO** | synthetic: `test_handsfree_e2e_fake_scenario.py` (startup PAUSED, camera dark, re-arm). Lock/suspend: **none** |

## 4. Reachability by platform

[Verified-in-docs] unless marked. `Y` shipped, `-` not available, `?` not established.

| Need | Linux X11 | Linux native Wayland | macOS | Windows |
|---|---|---|---|---|
| Head pointer moves | Y | portal pointer only if the injector holds a portal session [Verified-in-code, `platform/linux/__init__.py`] | Y (Accessibility grant; tested only against a simulated layer) | Y (`platform/windows/pointer.py` exists; unrun on hardware) |
| Dwell click (needs overlay) | Y | `-` (overlay not launched by default) | ? | ? |
| Gaze routing | Y | `-` | `-` | `-` |
| Click by label (`pilot`) | Y | ? | `-` | `-` |
| Voice mouse grid | Y | `-` | Y | `-` |
| Voice window focus | Y | `-` | `-` | `-` |

[Assumption] On Windows and macOS the only documented commit is dwell, and its overlay precondition on those OSes is not stated in the hands-free setup page; I did not trace it.

## 5. Gaps ranked by "user stranded" severity

Severity = how long a person without keyboard and mouse is left without any way to proceed, and whether anything tells them.

1. **No hands-free resume (tasks 10, 12, 14, 15).** [Verified-in-docs] Resume is only `yazses handsfree resume` or the Settings page; there is deliberately no resume phrase and no resume gesture action (`facegesture/switches.py` `ACTIONS` has none). Every pause, every daemon restart, every update and every reboot ends in PAUSED. [Verified-in-code] Only a hold-only face switch re-arms itself, and only after a *stale-signal* disarm, not after a user pause or restart. Stranded until a second person or a physical key helps.
2. **Opening the microphone has one hands-free path, and it is the camera (task 3).** [Verified-in-code] If the camera is lost or the face switch is paused or FAULTED, the user cannot start a burst; `wakeword` is unwired, `autostop` needs a hotkey tap. [Verified-in-docs] The voice stop phrase and every voice command (tasks 4-9) inherit that dependency: "once hands-free is paused the face switch no longer starts a burst".
3. **Click commit is missing where the overlay is not drawn (task 7).** [Verified-in-docs] On native Wayland (GNOME default) the pointer may move but nothing clicks; the preset binds no `select`/`confirm`/`cancel`. The documented precision fallback (`mousegrid`) is experimental and X11/macOS only.
4. **Setup, calibration and updates have no hands-free entry (tasks 1, 13, 14).** [Verified-in-docs] The documents say so for calibration but do not mark the whole path as assisted setup. [Assumption] Acceptable for a caregiver-assisted first install; it is a stranding risk for self-service updates and setting changes.
5. **No window/app switching off X11 (task 8).** [Verified-in-docs] No voice route on Wayland, Windows, macOS; the user depends on the pointer reaching a taskbar.
6. **Unexpected dialogs are unmodelled (task 9).** [Verified-in-code, grep] Only generic routes exist; no scenario, no wrong-target measure.
7. **Stop-everything and camera-off are not hands-free (task 11).** [Verified-in-docs] Pause keeps the camera pipeline available; the user may believe it is off. Privacy expectation, not a stranding risk.
8. **Lock/suspend behaviour unknown (task 15).** [Unknown] Not found in the daemon; could be benign (stale gate) or could re-arm on a stale pose.
9. **Zero hardware or participant evidence for any of the above.** [Verified-in-docs] See section 6.

### 5a. Workflow map: where each task's chain depends on another

```text
install / enable / calibrate / restart / resume (tasks 1, 2)   <- keyboard, pointer or terminal
        |
        v
camera healthy + face switch ARMED (task 3)  <-- single hands-free root for every spoken task
        |-- burst --> dictate (3) --> correct (4) --> undo (5) --> navigate (6)
        |-- burst --> window (8) / dialog keys (9) / pilot, grid click (7) / stop phrase (10)
        '-- camera --> head pointer (7, 8) / chord stop (10)
camera lost / pause / restart / update / reboot  --> PAUSED or FAULTED (10, 12, 14, 15)
        '-- resume: terminal or Settings page only      <- the exit edge needs hands
```

[Verified-in-code/docs] for each edge individually; the single-root picture is my synthesis. [Assumption] A user with a physical switch or a biosignal board (`biosignal`, experimental) has a second root; that route has its own open evidence plan ([ThinkGear note](2026-11-03-thinkgear-first-device-evidence.md)) and is not analysed here.

## 6. Coverage by existing validation slots

[Verified-in-code] `design/eye-control/validation-slots.json` (schema 2) holds 16 cells; `generated/validation-coverage.md` reports **16 PLANNED, 0 READY, 0 with any report, 0 independent hosts, 3 of 8 packs registered**.

| Pack | Registered cells | Maps to inventory task | Note |
|---|---|---|---|
| T0 install / camera lifecycle / privacy | WIN, MAC, GNOME, KDE, X11, each A+B (#428-#435, #438, #439) | 2, 3, 11 (camera release) | All PLANNED, blocked on runtime reachability |
| T1 coarse gaze 4-target | X11 A+B (no issue yet), HIDPI-A, ANY repeat x3 (#437) | 8 (gaze routing only) | PLANNED; X11 slots have no issue opened |
| T5 display topology | HIDPI A+B (#436, #440) | none directly | Calibration validity, not a task |
| T2 head pointer, T3 face switch, T4 safety/recovery, T6 grounding, T7 workflow | **no cell** | 3, 7, 10, 12, 15 | The coverage page states these are unregistered; they are exactly the stranding-critical tasks |

Not covered by any pack, slot or fake scenario: tasks 1, 4, 5, 6, 9, 13, 14 and the lock/suspend half of 15. [Verified-in-docs] `docs/validation-matrix.md` is a platform/install matrix (dictation, injection, start/stop) and contains **no hands-free row**.

## 7. Proposed next evidence

### 7a. Synthetic, participant-independent (no hardware; repository-only; each needs maintainer approval under the ADR-030 freeze, because test code is not `src/` but a new scenario harness is scope)

| ID | Scenario | Closes | Pass criterion (acceptance model) |
|---|---|---|---|
| S1 | Resume-route census: for every stop route in `panel.stop_routes`, derive from the registry which modalities can resume | gap 1 | The test records the answer; it is expected to show "terminal/panel only". It documents, it does not fix |
| S2 | Cold start: fake daemon restart, assert PAUSED, no pointer motion, no stale click, first frame observes only | gaps 1, 8 | Extends `test_handsfree_e2e_fake_scenario.py`; no action before explicit arm |
| S3 | Camera dark with no keyboard: fake FAULTED face switch, list every remaining route that can open a burst | gap 2 | Expected empty set; documents the dependency |
| S4 | Suspend/lock clock jump through `HandsFreeSafety` and the camera stall timer | gap 8 | No action on the first post-wake sample |
| S5 | Entry-point census: derive from `features.py` + config which first steps need key/pointer/terminal; compare with this note | gap 4 | Machine-derived, not a hand-written set (house rule: a hand-written set is the defect) |
| S6 | Fake AT-SPI dialog: decoy buttons, destructive label, missing tree; measure grounded-correct / ambiguous / abstained | gap 6 | Zero wrong-target clicks on the fixture; abstention is a pass |
| S7 | Per-session capability matrix test (move/click/focus/label-click) | gaps 3, 5 | Matches section 4; fails when docs and code diverge |
| S8 | Face-switch false-activation replay on *synthetic* traces (`eyeeval.switch_replay`) | gap 2 | Phantom actions/hour reported with exposure; says nothing about real faces |

### 7b. Human gates (cannot be closed by Claude or CI; no recruitment, recording or upload is authorized by this note)

- **H1** Hardware T0/T2/T3/T4/T7 runs on each OS/session (community QA, [#428](https://github.com/MSKazemi/yazses/issues/428) family; T2-T4 and T7 need cells registered first).
- **H2** Independent check that the stop phrase and the face switch behave on real voices and faces, with false activations per hour and exposure reported (R-03, R-13, R-23). [Verified-in-docs] Risk register rows.
- **H3** Co-design and consent review before any participant study ([#814](https://github.com/MSKazemi/yazses/issues/814), [#419](https://github.com/MSKazemi/yazses/issues/419)); separate community QA from publishable human-participant research ([#813](https://github.com/MSKazemi/yazses/issues/813) boundary text).
- **H4** Fatigue, precision and task-completion measurement with people who actually cannot use a keyboard or mouse ([#817](https://github.com/MSKazemi/yazses/issues/817)).
- **H5** Real screen-reader / assistive-technology pass on the Hands-free page (current tests use Qt's offscreen platform).
- **H6** Maintainer decision on whether an inventory finding becomes a *proposed* ADR amendment ([#819](https://github.com/MSKazemi/yazses/issues/819)); nothing here authorizes implementation.

### 7c. Proposed stop/recovery acceptance model (for #816/#817 to adopt or reject)

A task row would count as "complete hands-free" only if all of the following held in a recorded run. Each is a proposal, not an existing gate.

1. **Entry:** the first and every later step is taken by a modality the user can produce; the run log names it.
2. **Independent stop:** at least one stop route works with the camera lost and the pointer misbehaving (ADR-v2-148 already requires one independent of the pointer; the synthetic proof is `test_handsfree_stop_from_faulted.py`). [Verified-in-code]
3. **Explicit, hands-free re-arm:** the way back from PAUSED/FAULTED needs no key, pointer or terminal, and its first frame never acts ([Assumption] today only the second half is tested; I did not read every safety test).
4. **No replay:** after any interruption no earlier pose, switch event or gaze target fires.
5. **Unintended actions** are counted per hour of exposure with the exposure stated; zero in a short run is reported as an upper bound, not as zero.
6. **Intervention count:** any keyboard, mouse or terminal use during the run is recorded and makes the task "assisted".

Failure modes to look for: a stop route that needs the failed sensor; a resume that fires a held gesture; a guard that fires so often it is switched off (AGENTS.md rule 9); a fallback that raises consequence (`handsfree/recovery.py` forbids it, [Verified-in-code]).

Alternative approaches the evidence does not yet separate: voice-only always-listening start (privacy and false-wake cost, `wakeword` unwired); a physical or biosignal switch as the root; a caregiver-assisted setup path declared as such; leaving resume manual on purpose because an automatic one is itself a risk (ADR-v2-148 recovery hierarchy item 5, voice-stop page). [Verified-in-docs] The last is a deliberate design position, so gap 1 is a tension to weigh in #819, not an oversight to patch.

### 7d. Privacy and review notes for any later human study

[Verified-in-docs] The hands-free pipeline keeps frames in memory and reports only states, names and ages (`handsfree/observability.py`). A study that records faces, voices or biosignals is a separate data transfer governed by `design/eye-control/DATA_SHARING.md`, `GOVERNANCE.md` and `AGENTS.md` (no real user audio or voiceprints to a third-party coding agent). Community QA reports and research participation must stay separate. Unintended-action risk to the participant (a stuck click or open microphone) needs a stop condition written before the first session. None of this is started here.

### 7e. Falsifying evidence for the answer in section 1

The "not demonstrated" conclusion is falsified by a registry record showing a person completing tasks 3, 10 and 15 on a stated OS/session and version without a key, pointer or terminal. Nothing of that kind exists today. [Verified-in-docs]

## 8. Explicit non-claims

- This note reports **no user study**, no participant data and no measurement of any person.
- It makes **no clinical claim** and **no accessibility-compliance claim** (no WCAG, Section 508, EN 301 549 or similar statement). The one contrast-ratio test it cites checks a formula on rendered pixels, not conformance.
- It does not say any capability works or fails for a real user; it says what the repository shows and does not show.
- Synthetic tests and CI are not hardware evidence and are not counted as such.
- Statements labelled [Assumption] or [Unknown] must not be quoted as findings.
- The freeze is unchanged: no feature, ADR acceptance, release or roadmap commitment follows from this note.
