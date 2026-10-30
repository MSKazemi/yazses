# DRAFT - not for upload until #699/#701 approve

This is draft text for a dataset card. It must not be uploaded anywhere, and the schema it
describes is provisional, until issue #699 (canonical schema) and issue #701 approve.

---
license: apache-2.0
pretty_name: YazSes Multimodal HCI Lab Scenarios (synthetic)
tags:
  - synthetic
  - human-computer-interaction
  - accessibility
size_categories:
  - n<1K
---

# YazSes Multimodal HCI Lab Scenarios (synthetic)

## Summary

Sixteen hand-authored scenarios for a decision-layer prototype that combines gaze, voice
intent and a deliberate activation. Each scenario holds simulated inputs, the decision a
reference resolver should reach, and relative timestamps. The set includes negative examples
(accidental and false activations), not only successes.

## Explicit statements

- synthetic=true for the whole dataset and for every scenario.
- It contains no human biometric data, no private data and no user data: no gaze trace, EMG or
  EEG/EOG recording, face image, audio, transcript, voiceprint or participant identity.
- All numbers (confidences, signal ages, hold durations, timestamps) are SIMULATED and
  illustrative. They are not measurements and not a device benchmark.
- EEG/EOG entries are an experimental research proposal. They model a coarse activation
  event only. Nothing here reads thoughts or supports a medical claim.

## Schema and version

- `schema_version`: `0.1-prototype`. Provisional. Issue #699 owns the canonical schema and this
  data must migrate to it before any upload.
- Machine-readable description: `fixtures.schema.json`. Source of truth: `fixtures.js`
  (`window.HCI_FIXTURES = <JSON>;`).
- Top level: `schema_version`, `synthetic`, `license`, `provenance`, `generator`, `thresholds`,
  `desktop`, `intents`, `activation_kinds`, `scenarios`.
- Scenario: `id`, `title`, `description`, `synthetic`, `negative_example`, `modality`
  (subset of `voice_intent`, `gaze`, `face`, `emg`, `eeg_eog_experimental`), `inputs`,
  `intended_target`, `expected` (`decision`, optional `target`), `decision_at_ms`, `timeline`
  (integer relative milliseconds, non-decreasing), `simulated_conditions`.
- Decisions: `accept`, `ask_confirmation`, `abstain`, `stop`.

## Provenance and generation

Hand-authored; no random seed. No external dataset, recording or model was used.

## Intended use

Teaching and reviewing decision rules for multimodal input: when to act, when to ask and when
to refuse. It is not a training set for a gaze, voice, EMG or EEG model and must not be used
to estimate real-world accuracy.

## Splits

None. The set is too small and too artificial to split. All 16 scenarios are one evaluation
set, used only to check that a resolver reproduces the expected decisions.

## Limitations

- Sixteen scenarios cover the rules, not the variety of real signals, users or environments.
- Thresholds are illustrative defaults, not tuned or validated values.
- The `lighting` and `device` notes are descriptive labels only; no such conditions were measured.
- The schema is provisional and will change.

## Licence

Apache-2.0 for the fixtures and the code.
