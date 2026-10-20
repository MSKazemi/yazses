# Face-switch traces — format, nuisance fixtures and the field report

**Status:** harness delivered (EYE-BENCH-001, #409); no field study run  
**Date:** 2026-10-20  
**Related:** [EVALUATION.md](EVALUATION.md) (E2), [METRICS.md](METRICS.md),
[DATA_SHARING.md](DATA_SHARING.md), [ROADMAP.md](ROADMAP.md) P5.4,
[face-switch spec](../specs/eye-face-switch.md)

A facial switch is judged by how rarely it fires when nobody meant it to, not by classifier
accuracy (AGENTS.md rule 9). This page describes the numeric trace the false-activation harness
replays, the nuisance traces it ships with, how to measure a different detector over the same
traces, and the report a volunteer could later send.

```sh
uv run python scripts/replay_face_switch_trace.py            # print the report
uv run python scripts/replay_face_switch_trace.py --check     # CI drift gate
uv run python scripts/replay_face_switch_trace.py --trace my-trace.json --no-sweep
```

## Synthetic traces do not justify defaults

Every checked-in trace is **invented**. The nuisance traces are shaped after commonly reported
properties (blinks of roughly 100–400 ms and about 15–20 a minute at rest, a yawn of several
seconds, the upper lid lowering with downward gaze), but the scores are not measured from any
camera or any person. A number computed on them shows what a detector does *to that shape*. It
does not show what it does to people, and it can never make a threshold, a debounce or a gesture
"recommended". Every report carries this in its `no_threshold_notice` field. Recommending a face
switch needs false-activation evidence from real volunteer sessions across people
([ROADMAP.md](ROADMAP.md) P5.4).

## The trace format (schema 1.1)

One JSON object per trace. The validator is `src/yazses/eyeeval/switch_trace.py`; it refuses
anything below rather than half-reading it.

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | `"1.1"`; any `1.x` is read, another major is refused |
| `trace_id` | yes | lowercase slug, unique within a set, `[a-z0-9._-]`, up to 80 characters |
| `study_mode` | yes | `synthetic`, `ci` or `community_qa`; `research` is refused (no consent field) |
| `gesture` | yes | one of the detector's gestures, e.g. `jaw_open`, `eyes_closed` |
| `sample_rate_hz` | yes | 0.1–1000; sample *i* is at *i / sample_rate_hz* seconds |
| `scores` | yes | one number in 0..1 per sample for that one gesture, or `null` for no reading |
| `segments` | yes | run-length labels `{"context": ..., "samples": n}` covering every sample |
| `confidences` | no | landmarker confidence per sample, same length as `scores` |
| `baseline` | no | `{"level": x}`, the resting level in force when the trace was taken |
| `description` | no | up to 280 characters; never copied into a report |

**Contexts** label what the person was doing: `deliberate` (the gesture was meant — the only
intended context), `rest`, `speech`, `head_movement`, `smile`, `blink`, `yawn`, `look_down` and
`other`. `blink`, `yawn` and `look_down` arrived in 1.1, so a report can say which involuntary
movement fired the switch; every 1.0 trace is a valid 1.1 trace. Two `deliberate` segments may
not touch (put the release between them).

**There is no clock.** A document with a `timestamp`/`time_s`-style column is refused: resample
onto a uniform grid and write each dropped frame as `null`. There is also no field for an image,
frame, mesh, landmark, blendshape vector, person or session. A document that adds one at any
depth is refused, and renaming it does not get it through.

```json
{
  "schema_version": "1.1",
  "trace_id": "my-desk-morning",
  "study_mode": "community_qa",
  "gesture": "jaw_open",
  "sample_rate_hz": 15,
  "segments": [{"context": "rest", "samples": 4}, {"context": "deliberate", "samples": 3},
               {"context": "rest", "samples": 2}],
  "scores": [0.03, 0.04, null, 0.05, 0.71, 0.82, 0.80, 0.30, 0.04]
}
```

## What the report counts

Per trace and pooled per gesture: `intended_activations` (deliberate segments), `detections`,
`misses`, `false_activations` (switch starts outside every deliberate window, one per action),
`duration_s`, and `false_activations_per_hour` over the non-deliberate time, with exact
one-sided 95% Poisson `_lower_95`/`_upper_95` limits and `per_hour_extrapolated` when that time
is under an hour. A `by_context` block splits phantoms by the context they began in. A figure
with no denominator is `{"value": null, "reason": ...}`, never `0`: no deliberate gesture leaves
`recall` and latency missing, and no non-deliberate time leaves the rate missing
([METRICS.md](METRICS.md) "Missing data"). An empty trace or trace set is refused.

## The nuisance traces and what the shipped detector does

All five run at 15 Hz (the `[facegesture] fps` default). They use the shipped `GestureSwitch`
at its constructor defaults (hold 0.5, release 0.35, 3-sample debounce). The figures come from
`tests/fixtures/face_switch_replay_report.json`, which `--check` keeps current.

| Trace | Gesture | What it is | False activations (non-deliberate s) | Misses |
|---|---|---|---|---|
| `natural-blinks` | `eyes_closed` | 34 blinks in 2 min plus 3 deliberate 1.2 s closures | 6, all `blink` (116.4 s) | 0 of 3 |
| `look-down-glances` | `eyes_closed` | 6 glances of 1.5–4 s plus short blinks plus 2 closures | 5, all `look_down` (78.3 s) | 0 of 2 |
| `animated-talking` | `jaw_open` | 70 s of lively speech, emphatic vowels at most 2 samples long | 0 (90 s) | none intended |
| `yawns` | `jaw_open` | 3 yawns of 6 s plus 2 deliberate 1.4 s jaw opens | 3, all `yawn` (91.3 s) | 0 of 2 |
| `blinks-on-jaw-open` | `jaw_open` | 17 blinks watched by a jaw switch | 0 (60 s) | none intended |

What these shapes show, and only on these shapes:

- **A frame debounce lasts whatever the camera makes it.** Three samples at 15 Hz is 0.2 s, so
  every blink of 5 samples (about 0.33 s) or more fires an `eyes_closed` switch.
- **A longer hold fixes blinks, not glances down.** In the test suite a candidate with a 0.8 s
  timed hold removes all six blink phantoms and keeps all three deliberate closures. Four
  glances down still fire it, because a glance holds the lids low for longer than the hold.
- **No threshold or debounce separates a yawn from `jaw_open`.** A yawn is wider and longer than
  the deliberate gesture. All three yawns fire at hold 0.35, 0.5 and 0.6, and with a 15-sample
  debounce too.
- Lively talking stays clear of the default only because its emphatic vowels are shorter than
  the debounce. The same trace at hold 0.35 fires twice.

## Measuring another detector over the same traces

The harness owns the traces, labels and scoring, not the activation policy. Pass a `Detector`
(a name for the report plus a factory that builds a fresh detector per trace from the
configuration, the gesture and the baseline) to `replay_trace` / `replay_traces`:

```python
from yazses.eyeeval.switch_replay import CURRENT_DETECTOR, Detector, replay_traces

def build(config, gesture, baseline):
    return MyCandidate(config.hold_threshold, config.release_threshold, gesture=gesture)

report = replay_traces(traces, detector=Detector("my-candidate", build))
```

The default, `CURRENT_DETECTOR`, builds `GestureSwitch` with the same keyword arguments as
`facegesture/backend.py`. A test fails if the backend starts passing one the harness does not,
so the committed report keeps measuring the detector that ships. A detector that returns an
event other than `start`/`end`, ends a hold it never opened, or reports an unknown frame status
is refused. The harness never ignores it, because an ignored event would read as a switch that
never misfires.

## A volunteer field report (later)

The format already accepts `study_mode: community_qa`, and such a report says
`"evidence_class": "includes_community_qa"`. No YazSes command records a trace yet, so the
following is the template for when one exists. It is not something to do by hand today.

1. Record locally, at the switch's own frame rate, the one gesture score being tested. Never
   record frames, video, landmarks or the full blendshape vector.
2. Label the segments while recording: which stretches were deliberate, and which were rest,
   talking, blinking, yawning or looking down.
3. Run `uv run python scripts/replay_face_switch_trace.py --trace my-trace.json --no-sweep`
   on your own machine.
4. Share the **report**. It holds counts, rates and the trace id, and no sample. Keep the trace
   file itself unless a maintainer asks for it under [DATA_SHARING.md](DATA_SHARING.md). A
   public issue is Class B community QA, never research data.
5. Say what the report cannot: the camera, the lighting, how long the session was, and that one
   person's session is not "people".
