# Multimodal HCI Lab — Hugging Face integration roadmap

**Status:** proposed research/documentation track (2026-10-27), **not a new product release wave**. [Programme epic #692](https://github.com/MSKazemi/yazses/issues/692). Follow `AGENTS.md`, `design/milestone-policy.md`, ADR-011, ADR-019 and the shipping freeze in ADR-030.

## Decision and scope

Maintain an **offline product / optional public research surface** boundary. The website advertises prospective studies, not an implemented HF integration or a proven BCI. Neither real sensor streams nor users' raw camera/microphone/EEG data go to Hugging Face. The existing camera owner `src/yazses/perception/` and EMG `src/yazses/platform/emg/` remain canonical. No feature registry entry, model download or config flag is added by this documentation programme.

## Tracked epic and delivery tasks

**Parent:** [Epic #692 — Hugging Face × multimodal HCI](https://github.com/MSKazemi/yazses/issues/692). Delivery children span **three existing milestones** (#7 Speech accuracy, #9 Contributor experience, #10 Hands-free). The epic has **no milestone**, by policy. *Delivery* is the [milestone-policy](../milestone-policy.md) class (each child carries one milestone), not a commitment to ship: under the ADR-030 freeze these are research and documentation tasks, none adds a daemon capability, and a proposal beyond them stops at a *Proposed* ADR or an `evergreen:research` issue. The issue descriptions cross-link the parent; **native GitHub sub-issue association must be completed separately in the Issues UI** before the traceability audit can verify parentage.

| Stage | Issue | Outcome / blocking condition | Milestone |
|---|---|---|---|
| A | [#698 — HCI-HF-005](https://github.com/MSKazemi/yazses/issues/698) | HF publishing/ownership and model, dataset, Space card drafts; no account actions | #9 |
| A | [#694 — HCI-HF-002](https://github.com/MSKazemi/yazses/issues/694) | Versioned model/license/hash inventory, air-gap proof; coordinate Android #683 | #7 |
| A | [#699 — HCI-HF-006](https://github.com/MSKazemi/yazses/issues/699) | Synthetic fixture schema and offline validator used by Space and replay | #10 |
| A | [#693 — HCI-HF-001](https://github.com/MSKazemi/yazses/issues/693) | Static, synthetic-only interactive Space source; review after #699 for final fixtures | #9 |
| A | [#701 — HCI-HF-008](https://github.com/MSKazemi/yazses/issues/701) | Independent privacy/license/egress prepublication gate; needs #693, #694, #698 | #9 |
| B | [#700 — HCI-HF-007](https://github.com/MSKazemi/yazses/issues/700) | Pure local replay for target grounding, abstention and confirmation; blocked by #699 | #10 |
| B | [#695 — HCI-HF-003](https://github.com/MSKazemi/yazses/issues/695) | Camera/gaze evaluation protocol on shared source; existing eye-control gates #414–#420 | #10 |
| C | [#696 — HCI-HF-004](https://github.com/MSKazemi/yazses/issues/696) | EEG/EOG synthetic-board feasibility; hardware/ethics gated | #10 |

**#700 acceptance audit (2026-11-06, synthetic fixtures only, Linux + Node 24).** Each criterion in the issue maps to a named passing test. `replay.test.js` runs under `node --test` and is wrapped by `tests/test_hci_hf_lab.py::test_replay_eval_tests_and_cli_pass_under_node`. These tests regression-check a pure resolver. They measure no device and no person.

| #700 criterion | Test(s) |
|---|---|
| No action on stale / low-confidence / contradictory signals | `eval/replay.test.js` "#700 C1"; rule-level: `resolver.test.js` "stale or low-confidence activation abstains", "conflicting gaze and voice targets abstain", "low voice confidence abstains" |
| High-risk action never accepted without confirmation | `eval/replay.test.js` "#700 C2" (every shipped scenario × every destructive intent); `resolver.test.js` "destructive intents always ask for confirmation" |
| Emergency stop always wins | `eval/replay.test.js` "#700 C3" (emergency stop and voice "stop" over every shipped scenario); `resolver.test.js` "stop wins over a fully valid accept" |
| Missing EEG/EMG/camera adapters do not interrupt the voice path | `eval/replay.test.js` "#700 C4" |
| Deterministic JSON/Markdown metrics, synthetic warning | `eval/replay.test.js` "the report is deterministic", "the synthetic-data warning is in both outputs…", "#700 C5/C7"; `test_replay_eval_tests_and_cli_pass_under_node` (two CLI runs byte-identical) |
| No daemon feature, OS injection, cloud endpoint or weights | `test_eval_files_are_offline_and_deterministic`, `test_700_the_lab_ships_only_static_web_files_and_no_weights`, `test_700_the_product_does_not_import_or_reference_the_lab` |
| Separation from participant validation (#419) | `eval/replay.test.js` "#700 C5/C7" |

Each new test was checked against a mutation of a scratch copy of the code, and each one fails on its own mutation. For three criteria, no earlier test failed: the stop check made conditional on a valid activation (C3), the voice path made to require a gaze stream (C4), and the #419 sentence removed from the notice (C5/C7). Those three criteria were therefore untested before this audit. Earlier tests already failed on the C1 mutation (gaze staleness ignored) and the C2 mutation (destructive intents accepted). **Open limit:** the lab models no keyboard or hotkey activation. With camera, EMG and EEG *all* absent, the activation is `none`, and a voice command therefore abstains. C4 holds only while at least one activation source remains. In the product, the hold-to-talk hotkey sits outside this lab. Closing the gap would change `resolver.js` and the fixture schema, so it needs its own issue. The native sub-issue link to #692 and the #693 UI integration are still open.

**Ready-to-scope sequence:** #698/#694/#699 can proceed independently; #693 then #701 for a publication-ready *synthetic* demo; #700 after #699; #695 and #696 remain evidence-gated. Completing this research programme does **not** require approving live EEG or camera changes.

## Dependencies and phases

| Phase | Priority | Deliverable | Gate | Responsibility |
|---|---|---|---|---|
| 0. Inventory and policies | Now | Map existing camera/voice/EMG seams, licenses, HF costs and egress hazards | No duplicate existing work; #692 and docs linked | Research/documentation |
| 1. Public synthetic Space | Next, no daemon changes | Minimal static HTML/JS fake-desktop demo + fixtures and reproducible source; optional owner-controlled HF Space | No live sensor input, remote processing, or paid resource | Web/research contributor |
| 2. Offline model provenance | Next, aligned with existing work | Read-only inventory table: model ID/revision/license/hash/inference/runtime and Android pinning reference #683 | No startup network, no unsupported model license | ML + platform reviewer |
| 3. Camera/gaze evaluation | Gated | Replicable device matrix, calibration, abstention and latency reports reusing existing FaceLandmarker | #419 user evaluation; #414 permissions; #418 Wayland; real hardware | HCI/accessibility contributors |
| 4. EMG and EEG feasibility | Research only | Synthetic BrainFlow board + optional local EEG recording replay using MNE/LSL and reproducible classifiers | Consent/ethics, artifact controls, accidental activation bound, no medical or thought-decoding claims | Biosignal researcher |
| 5. Product decision | After ADR-030 constraints change | Maintainer ADR on whether a measured new adapter is worth maintaining | External-user demand; isolation, tests, fallback, support matrix | Maintainers |

## Proposed code boundaries (only if later approved)

- A **standalone examples/research** tree is preferred for prototypes, e.g. `examples/hci-hf-lab/`; never import HF or torch from core daemon startup.
- Existing `PerceptionSample` maps to a narrow numeric `Observation` envelope through an adapter. For experimental EEG, a local BrainFlow/LSL adapter emits `ActivationCandidate` with monotonic time, quality and confidence; interaction policy consumes it only after gating.
- Device-specific models run in an optional local worker with timeout, bounded queue and explicit stop. A disconnected worker must not break ordinary dictation.
- Pure inference-independent fusion logic and synthetic fixtures test abstention, stale signals, false double-activations, and accidental target selection.
- All runtime/network changes need privacy and ADR review; do not change `src/`, `pyproject.toml` or generated docs just to prototype a Space.

## Prototype acceptance tests

1. Static Space works in a browser without microphone/camera permission, account login, tokens or backend.
2. Network inspector shows no uploads for local UI interaction; third-party embeds, telemetry and webfonts are absent.
3. Synthetic scenarios cover a correct gaze+speech combination, low confidence, stale data, contradictory modalities, intentional muscle switch, accidental blink, failed confirmation, and emergency stop.
4. Actions are displayed as **proposals only**, not sent to real desktop. The model may abstain. All synthetic metrics are unmistakably labeled.
5. CI lints static assets and validates schema; link checks and strict MkDocs build pass.
6. The optional research worker uses local data and can be disabled/uninstalled without changing the base app.

## Evaluation design

- **Voice:** WER/CER, CPU cost, language coverage and end-to-end dictation latency on licensed public/locally approved fixtures.
- **Camera:** angular error distribution, target correctness, abstention, lighting/head-motion sensitivity, resource use and error recovery.
- **Muscle/brain:** event precision/recall, onset/end offset, false activations/hour, between-session stability, fatigue/user effort (non-diagnostic), reproducibility by device. Separate EEG neural decoding from EOG/EMG artifacts. No claims of thought reading.
- **Fusion:** wrong-target rate, confirmation burden, time-on-task, recoverability and end-to-end safety; report negative cases.
- **Human participant work:** separate ethics review, consent, retention/deletion plan and accessible opt-out. Do not publish participants' data by default.

## Mapping to existing work

- [Eye programme](../eye-control/ROADMAP.md): shared camera, permissions, validation and real Wayland/OS work; #102, #104, #414–#420.
- [EMG #103](https://github.com/MSKazemi/yazses/issues/103): closed; extend only by measurable research.
- [Intent #137](https://github.com/MSKazemi/yazses/issues/137), [activation contract #139](https://github.com/MSKazemi/yazses/issues/139): extension seams, not second contracts.
- [Android model pin #683](https://github.com/MSKazemi/yazses/issues/683): reuse in model-provenance planning.
- [Public research page](../../docs/research/huggingface-multimodal-hci.md).

## Explicit non-goals

No hosted live inference, no always-on camera by default, no identity/emotion/attention inference, no EEG thought transcription, no automatic app submission, no paid Hugging Face space, no model training on private user corpus, and no direct browser-to-OS actuation.
