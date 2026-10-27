# Multimodal HCI Lab — Hugging Face integration roadmap

**Status:** proposed research/documentation track (2026-10-27), **not a new product release wave**. Coordination [#692](https://github.com/MSKazemi/yazses/issues/692). Follow `AGENTS.md`, `design/milestone-policy.md`, ADR-011, ADR-019 and the shipping freeze in ADR-030.

## Decision and scope

Maintain an **offline product / optional public research surface** boundary. The website advertises prospective studies, not an implemented HF integration or a proven BCI. Neither real sensor streams nor users' raw camera/microphone/EEG data go to Hugging Face. The existing camera owner `src/yazses/perception/` and EMG `src/yazses/platform/emg/` remain canonical. No feature registry entry, model download or config flag is added by this documentation programme.

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
