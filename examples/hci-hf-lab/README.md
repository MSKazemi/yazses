---
title: YazSes Multimodal HCI Lab (synthetic)
emoji: 🧭
colorFrom: blue
colorTo: gray
sdk: static
pinned: false
license: apache-2.0
short_description: Synthetic multimodal interaction simulator (no sensors)
---

# YazSes Multimodal HCI Lab (synthetic)

A static, browser-only simulator for studying how a decision layer could combine gaze, voice
intent and a deliberate activation (blink, face gesture, EMG hold, experimental EEG/EOG)
without acting on weak or contradictory signals. It is research and documentation material
for [issue #693](https://github.com/MSKazemi/yazses/issues/693), related to
[#692](https://github.com/MSKazemi/yazses/issues/692) and
[#699](https://github.com/MSKazemi/yazses/issues/699).

**Everything here is synthetic.** The scenarios are hand-authored; every confidence, age and
duration is a simulated, illustrative number. Nothing here measures a device or a person.

## What it is not

- It uses no camera, no microphone and no sensor of any kind, and asks for no permission.
- It has no uploads and makes no network request after the page loads. Nothing leaves your browser.
- It performs no OS action. Every outcome is a preview and ends with
  "Preview only - nothing was executed."
- It is not a YazSes product feature and is not wired into the daemon.
- EEG/EOG is an experimental research proposal only: coarse activation, never mind-reading,
  and no medical or diagnostic claim of any kind. The resolver never auto-accepts it.
- The summary counts in the replay table are illustrative outputs of hand-written scenarios,
  not accuracy rates and not a device benchmark.

## Run it locally

```sh
python3 -m http.server -d examples/hci-hf-lab 8000
# open http://localhost:8000
```

Opening `index.html` directly (`file://`) also works: there is no framework, no bundler, no
module import and no CDN. Run the unit tests with
`node --test examples/hci-hf-lab/resolver.test.js` (Node 18 or newer) and the repository guard
with `uv run python -m pytest tests/test_hci_hf_lab.py`.

## Files

| File | Role |
|---|---|
| `index.html`, `style.css`, `app.js` | The page. `app.js` only wires the DOM. |
| `resolver.js` | Pure decision logic. No DOM, clock or randomness. |
| `fixtures.js` | The single source of truth: `window.HCI_FIXTURES = <JSON>;`. |
| `fixtures.schema.json` | Documentation-grade JSON Schema for the fixtures. |
| `resolver.test.js` | `node:test` unit tests, including every fixture scenario. |
| `eval/replay.js` | Deterministic replay report: decision counts, wrong actions, abstention, confirmation burden, simulated latency. `node eval/replay.js [--json]`. |
| `eval/replay.test.js` | `node:test` tests for the report, including cases that force each counter. |
| `DATASET_CARD.draft.md` | Draft dataset card. Not for upload yet. |

## Resolver rules

The first rule that fires decides. Thresholds live in `fixtures.js` under `thresholds`.

1. A stop intent or the emergency stop gives **stop**. Stop always wins; the Escape key triggers it.
2. No activation gives **abstain**.
3. An invalid activation gives **abstain** with the specific reason: low confidence, a stale
   sample, an EMG hold shorter than `emg_min_hold_ms`, or a repeated blink inside
   `blink_refractory_ms`.
4. Target resolution. If voice names a target and gaze is unusable (disconnected, low
   confidence or stale), the named target is used. If gaze is usable and voice names a
   different window, the modalities conflict: **abstain**. With no named target, unusable
   gaze or a gaze point on no window gives **abstain** and suggests the keyboard or voice.
   Otherwise the gazed window is the target.
5. Low voice confidence gives **abstain**.
6. Risk. Destructive intents (delete, send) and any EEG/EOG activation always give
   **ask_confirmation**.
7. Otherwise **accept**, which is a proposal only.

### The 16 scenarios

| Scenario | Expected | Why |
|---|---|---|
| `correct_target` | accept | Confident gaze on Notes, valid blink. |
| `low_confidence` | abstain | Gaze 0.35 < 0.6 and no named target. |
| `stale_sensor` | abstain | Gaze sample 900 ms old, limit 500 ms. |
| `conflicting_modalities` | abstain | Gaze on Terminal, voice says Mail. |
| `muscle_hold_release` | abstain | EMG hold 120 ms < 250 ms (negative example). |
| `accidental_blink` | abstain | Second blink 180 ms after the first, inside 400 ms (negative example). |
| `confirmation_required` | ask_confirmation | "Send" is destructive. |
| `emergency_stop` | stop | Stop latched; wins over valid inputs. |
| `voice_only` | accept | No gaze; voice names Terminal; valid EMG hold. |
| `gaze_plus_voice` | accept | Gaze and voice name the same window. |
| `face_gesture_activation` | accept | Face gesture at 0.82 >= 0.7. |
| `emg_switch_activation` | accept | EMG hold 380 ms at 0.92 confidence. |
| `eeg_eog_experimental` | ask_confirmation | Experimental activation never auto-accepts. |
| `incorrect_target_selection` | ask_confirmation | Drifted gaze picks Terminal; "delete" is destructive, so the user sees the target and can cancel. Not a wrong-target accept. |
| `sensor_disconnection` | abstain | Gaze lost, no named target. |
| `false_activation` | abstain | EMG twitch at 0.55 < 0.8 (negative example). |

A wrong-target result is counted only when the resolver accepted a window other than the
intended one. The shipped fixtures contain none; a unit test builds one to prove the counter works.

## Replay report and what it is not

`node examples/hci-hf-lab/eval/replay.js` replays every fixture and prints counts with their
denominators. It is a regression check on the resolver, not a benchmark: the scenarios are
hand-written, so "16 / 16 match" says the resolver does what the fixture author expected and
nothing about any device or person. It does not report a false-activation rate per hour, because
the scenarios cover about 16 simulated seconds and an hourly figure would be invented. Real
participant validation is a separate study (issue
[#419](https://github.com/MSKazemi/yazses/issues/419)).

## Status labels

| Capability | Status |
|---|---|
| Gaze, voice and activation resolver, replay table, emergency stop | implemented in this prototype (synthetic) |
| Real gaze, face, EMG or EEG/EOG input | proposed; not implemented, not planned as a product feature here |
| Canonical fixture schema | proposed; owned by issue #699 |
| Hugging Face Space and dataset publication | proposed; see below |

## Schema status

`schema_version: "0.1-prototype"` is provisional and is **not** an official schema. Issue
[#699](https://github.com/MSKazemi/yazses/issues/699) will own the canonical schema, and
`fixtures.js` and `fixtures.schema.json` must then migrate to it.

## Publication

Publishing this folder to the Hugging Face Hub, as a Space or a dataset, is a separate,
owner-controlled step. Nothing in this directory publishes anything. The front matter above
only prepares the folder to be a static Space; the dataset card is a draft.

Licence: Apache-2.0 for the code and the synthetic fixtures.
