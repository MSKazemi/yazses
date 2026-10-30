# EEG/EOG feasibility protocol (research only)

Status: proposed protocol dated 2026-10-28; **no data has been collected, no analysis has been
run and this document contains no results**. Part of epic #692 / issue #696 (Stage C, gated).
Documentation only: no daemon code, no runtime adapter, no hosted collection, no classification
service.

**This is not a product plan.** EEG/EOG here means one narrow research question about a coarse
intentional activation signal. It is not thought decoding, mind reading, emotion or attention
inference, or a medical or diagnostic measurement, and nothing in this protocol may be described as
any of those. A runtime adapter would need its own approved ADR and evidence from real users.

## 1. Question

Can EEG or EOG provide a **coarse, deliberate activation candidate** (a switch-like event) whose
false-activation behaviour is comparable to the switches YazSes already studies (face gesture, EMG
hold)? "Comparable" is defined by thresholds frozen before any human data exists, not after.

The protocol is staged so that each stage is cheap and reversible, and the next stage cannot start
until the previous one reports.

## 2. Stages

| Stage | Data | What it can establish | What it cannot |
|---|---|---|---|
| P0: synthetic baseline | BrainFlow's synthetic board (`SYNTHETIC_BOARD_ID = -1` in `src/yazses/platform/emg/brainflow_source.py`) and generated signals | That the replay, timing, windowing and analysis plumbing is correct and reproducible, with no device | Anything about whether EEG works. A generated signal is not physiology. |
| P1: injected artifacts | P0 signals with blink, clench and speech-like artifact templates injected at known times | That the pipeline separates a known injected event from background, and measures its own false triggers against ground truth | That a real blink or clench looks like the template |
| P2: human hardware pilot | Real volunteers, a real device | The actual question | Nothing, until it is separately approved |

This document specifies P0 and P1 in detail. **P2 is out of scope here** and sits behind the gate
in section 9.

## 3. P0 and P1 design

1. **Source.** A synthetic board stream and generated test signals with fixed seeds, so every run
   is byte-reproducible. No device and no network.
2. **Independent offline analysis.** Windowing, filtering and feature extraction live in analysis
   scripts outside `src/yazses/`. The tools named in the issue (MNE, `pylsl`, scikit-learn, and
   MOABB where its datasets and licences permit) are **development-only, optional** dependencies
   for the research scripts and never join YazSes' base or optional-extra dependency sets
   (`AGENTS.md`, rule 3; the dependency-budget guard).
3. **Signal classes kept separate.** Every analysed segment is tagged as one of: neural activity,
   ocular artifact (blink, saccade), muscle artifact (clench, jaw, speech), or rest. The injected
   ground truth in P1 carries the same tags.
4. **Controls that must fire no activation.** Rest, reading-like quiet, speaking, deliberate
   blinks, jaw clench and head movement, each as its own labelled block. A candidate that fires on
   a control is a false activation, and it is counted, not discarded.
5. **Activation candidate.** The only output is a timestamped record with a kind, a confidence, an
   age, a signal-quality value and an explicit abstain. It drives **no real system action**: it is
   written to the analysis report and, at most, replayed through the synthetic resolver in
   `examples/hci-hf-lab/` as a labelled synthetic input. Field names follow the fixture contract in
   #699 and the existing activation seam (#137, vectors in #139); this protocol does not define a
   second schema.

## 4. Metrics

Every rate is reported with its numerator and denominator, and an hourly rate only when the scored
exposure time reaches a minimum frozen before the run (the same rule as the camera protocol, with the
repository's provisional `DEFAULT_MIN_EXPOSURE_S` in `yazses.eyeeval.analysis` as the starting point).
Below the minimum, report the count and the exposure. The P0/P1 replay script never prints an hourly
rate at all: its bursts are injected at a fixed pace, so any rate would be invented.

| Metric | Definition |
|---|---|
| False activations per hour | Activations on control blocks and idle time, divided by scored exposure time |
| Missed switches | Intended events (injected in P1, cued in P2) with no activation, over intended events |
| Latency | Event onset to activation candidate, p50 and p95, with the sampling rate and window length stated |
| Artifact separation | For each artifact class, the fraction wrongly passed as an activation, over the artifacts of that class |
| Calibration burden | Steps and time required before the detector is usable |
| Session drift | Change in false-activation and miss counts across time blocks and across sessions |
| CPU and memory | Process utilisation and RSS delta per host; never averaged across unlike machines |
| Negatives | Every configuration that failed, reported next to the ones that worked |

P2 adds fatigue and accessibility (who can and cannot use the signal, and discomfort) as reported
outcomes, not as inferences from the signal.

## 5. Data and privacy

- **Public data is synthetic only.** No volunteer biosignal, voice, personal metadata or camera
  footage is published, uploaded to the Hub or committed.
- **Real biosignals are treated like raw sensor data** (the programme's Class D): not collected
  centrally, not attached to issues, and not shared without a separate risk and ethics decision,
  protocol, retention plan and explicit consent (`design/eye-control/DATA_SHARING.md`).
- P0 and P1 involve no people and no personal data.

## 6. Accessibility and safety

- **No flickering stimulus** (including SSVEP-style paradigms) is used in any stage until a specific
  photosensitivity review sets limits. The first human pilot, if approved, uses no flicker.
- Any human pilot needs a safety fallback that always wins over the signal, a way for the
  participant to stop at any time, and an observer who can stop the session.
- The signal must be able to abstain, and an abstain is never retried silently.

## 7. Claims allowed and disallowed

| Allowed | Not allowed |
|---|---|
| "On synthetic signals the pipeline separated injected artifacts with these counts" | "EEG can control a computer" |
| "The detector fired on N of M control segments" | Any statement about reading, decoding or inferring thoughts, intent beyond a deliberate activation, emotion or attention |
| A negative or inconclusive result | Medical, diagnostic or therapeutic effectiveness |
| A device-independent baseline | A claim that P0 or P1 numbers predict real-human behaviour |

## 8. Done when (mapped to the issue)

| Issue requirement | Where it is met |
|---|---|
| Protocol | This document |
| Synthetic schema | Not defined here; reuse the canonical schema from #699 |
| Evaluation scripts and tests | P0 and P1 are implemented in `scripts/hci_eegeog_replay.py` with tests in `tests/test_hci_eegeog_replay.py`: seeded synthetic signals, a naive and an artifact-aware detector, scoring against injected ground truth with denominators. All output is synthetic and says so; P2 has no code |
| Documented non-goals | Sections 1, 5, 6 and 7 |
| Device-independent baseline | P0 |

## 9. Gate

- P2 needs independent ethics review, informed consent, a privacy and retention plan, owner
  approval, and a safety fallback, each approved separately from this document.
- A runtime adapter needs a separate approved ADR and evidence from real users. Completing P0 and
  P1 is not that evidence.
- Product priorities stay as set in ADR-030; this work does not change them.

## 10. Open questions for the maintainer

1. Whether to keep the repository's provisional minimum exposure for an hourly rate (600 s,
   `yazses.eyeeval.analysis`) for the pilot; it must be frozen before P2.
2. The "comparable to existing switches" thresholds to freeze before P2 (none are proposed here
   because any number chosen now would be arbitrary).
3. Where the research scripts live. They are outside `src/` (`scripts/hci_eegeog_replay.py`) and
   nothing in the daemon imports them; whether they should move to a separate repository is open.
4. Which ethics body would review a P2 pilot.

Cross-references: epic #692; #699 (synthetic fixtures); #103 and #137 and #139 (existing activation
seams); #693 (synthetic resolver demo, draft PR #703); #700 (replay report); #701 and #698
(publication gate and playbook); `design/eye-control/DATA_SHARING.md`; ADR-030.
