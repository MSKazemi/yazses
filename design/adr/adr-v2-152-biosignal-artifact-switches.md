# ADR-v2-152 — Biosignal switches: artifact-grade EEG/EMG/EOG events under a measured false-positive budget

**Status:** Proposed (2026-10-29)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-v2-129-killer-features-10x]] (the "Rejected" paragraph this ADR narrows and
clarifies, and the activation-source seam it built), [[adr-v04-003-emg-serial]] (the serial EMG
source), [[adr-v2-135-face-gesture-switch]] and [[adr-v2-147-face-switch-intent]] (the same
"detector emits an abstract event, never an action" boundary), [[adr-005]] (`InputBackend`
Protocol), [[adr-011]] (zero telemetry), [[adr-019-egress-inventory-and-escalation]] (egress),
[[adr-021-invest-in-error-cost]] (rule 9: a guard is judged on how rarely it fires),
[[adr-v2-148-hands-free-composition]] (the one global pause/kill state this source must obey),
[[adr-v2-153-biosignal-false-positive-governor]] (the governor mechanism in detail), research:
`docs/research/muscle-brain-control.md`, spec: `design/specs/biosignal-pipeline.md`

## Context

Three pieces of EMG/EEG plumbing already exist, and none of them is a pipeline:

- `EMGBackend` (YESP over serial) is a finished `HotkeyBackend` duck-type, but the device does the
  signal processing. The daemon sees only `HOLD_START` / `HOLD_END` and cannot measure, tune or
  gate the signal behind them (`design/emg-protocol.md`).
- `platform/emg/brainflow_source.py` reads BrainFlow boards (OpenBCI, Muse and others) and feeds
  graded squeeze logic (`platform/emg/pressure.py`). It is one source, one detector, and no
  signal-quality gate.
- The activation seam (ADR-v2-129) and the intent path (`activation/intent.py`) accept any
  non-keyboard trigger, but only a source that already speaks "start / end / label" can use them.

Raw electrodes have a harder problem than the keyboard they replace. The research page
(`docs/research/muscle-brain-control.md`) records it: the only reliable switches a consumer EEG
headset yields, blink and jaw clench, are **eye and muscle artifacts**, not brain signals; the best
measured blink switch is 99.5% accurate at 0.10 false positives per minute, which is about 50
phantom activations in a workday; and a jaw clench is confounded by chewing and by *talking*, which
is fatal in a dictation tool. A dedicated EMG electrode on the muscle measures the same activity
directly and strictly dominates on signal-to-noise, with a false-activation rate you can tune. The
same page also notes that Meta's *Nature* paper reports no false-activation rate at all, and that
the rate is the number that decides whether a trigger is livable.

So the question is not "can an electrode produce a trigger" (it can) but "can we ship one whose
false-activation rate is *measured, bounded and enforced* on the user's own machine".

ADR-v2-129's Rejected paragraph reads: consumer-EEG "thought" triggers are rejected, "artifact-grade
only; ~0.10 FP/min best case ≈ dozens of phantom mic-openings a day — strictly dominated by the EMG
electrode". That sentence is easy to over-read as "no EEG hardware, ever". This ADR keeps its
intent and states the boundary precisely.

## Decision

Add an opt-in `yazses.biosignal` package, `[biosignal] enabled = false`, that turns multichannel
electrode samples into a **small closed set of artifact-grade events**, behind the existing
activation seam, and that holds itself to an explicit, measured false-positive budget.

### 1. Scope: artifact-grade switches only

The package may report exactly these events (`EventKind`): squeeze on/off (graded light/hard),
blink, double blink, jaw clench. Each is a *large, physical, deliberate-or-detectable artifact*:
a muscle burst, an eye closure, a clenched jaw. It may read them from EMG, EOG or the frontal
channels of an EEG headset, and it says which signal kind a channel is (`SignalKind`).

**This ADR does not reverse ADR-v2-129.** It narrows and clarifies it:

| Still rejected | In scope here |
|---|---|
| Decoding thought or intent from brain activity | Detecting a muscle burst, a blink or a jaw clench |
| Motor imagery, SSVEP, P300, any evoked-potential or cortical decoder | Energy and timing of the artifact itself |
| Any classifier whose output depends on what the user is *thinking* | Thresholds on a signal the user *did* with a muscle |
| Silent-speech or open-vocabulary decoding from sEMG | (unchanged: not in this package) |

If a future change wants a decoder from the left column, it needs its own ADR and its own evidence,
and it does not get to cite this one.

### 2. The false-positive budget is part of the feature, not a metric beside it

Following ADR-021 rule 9 ("hold only on a specific, checkable signal, never a heuristic"), the
package ships four defences against its own mistakes:

1. **A signal-quality gate suppresses events.** Flatline, saturation, mains interference, baseline
   drift and sample dropout each mark a window "not trustworthy", and no event is emitted from an
   untrustworthy window. A detached electrode must produce silence, never a trigger.
2. **Detectors are conservative by construction.** Double-threshold onset/offset with a frozen
   baseline, a max-hold watchdog that ends a hold which never releases, and a refractory period.
   The jaw-clench detector has a **speech guard** because talking is the confound the research page
   names; the package does not pretend to solve it, it declines to fire when speech is present.
   The guard is a suppressor: it may miss a clench, never invent one, and a guard that fails
   (raises) is treated as "speaking". The guard is a callable the integrator supplies. The daemon
   passes the dictation state (no clench while a turn is being recorded); `speechguard.py`
   combines several such sources (recording, VAD, text-to-speech playback) with a hangover tail and
   a stuck-source watchdog, so a flag wedged at "speaking" cannot lock the switch out for ever. All
   of it reads *audio-side* state. A test on the electrode signal itself (spectral shape of the
   jaw channel) is not part of this decision (see "Known limits").
3. **An activation ledger measures the cost.** Every activation is recorded locally. An activation
   the user explicitly cancels or undoes within a short grace window (design default 3 s)
   counts as *cancelled*; an activation that is merely not followed by anything is **not** counted,
   because silence is just as likely a correct, uneventful activation. The cancelled fraction is a
   proxy for false positives and is reported with a Wilson confidence interval so a small sample
   is not read as a result. It is a **proxy**, not ground truth; the docs say so wherever it is
   shown. Rates are per *active* exposure time, so a paused, gated or suspended period never
   dilutes them.
4. **A budget governor acts on the ledger.** `max_cancelled_per_hour` bounds cancelled activations.
   Over budget (judged on a conservative lower bound of the cancelled *rate*, with a minimum
   amount of evidence, not on the displayed fraction), the governor first *desensitizes* (raises
   thresholds), and only if that is not enough *suspends* the source and says so. Suspension
   recovers by itself after a timer that grows on repeats, into the desensitized state, and ends
   at once on a single user action. A switch that keeps misfiring ends up off, loudly, rather than
   quietly annoying, and never off for good. The mechanism, states and alternatives are in
   [[adr-v2-153-biosignal-false-positive-governor]]; the wording "desensitize, then suspend" always
   means that escalation order.

The numeric thresholds, budget default and desensitization steps are **design choices to be set at
implementation and then measured**; this ADR fixes the structure, not the numbers, and no value may
be called recommended until the field measurement the research page asks for exists. Values in
code (for example the default budget of 6 cancelled activations an hour, which is the best
published blink switch, 0.10 false positives a minute, expressed per hour) are placeholders of
that kind.

### 3. The detector emits events, never actions

Same boundary as ADR-v2-147: a `StreamDetector` consumes `SampleBlock`s and returns `BioEvent`s. It
imports no daemon, injector, pointer or window code. A thin runner maps events onto the *existing*
seams: `on_mode_start` / `on_mode_end` (the callbacks `EMGBackend` and `BrainFlowSource` already
feed) and **labels-only** intents through `activation/intent.py`. Because intents go through the
ordinary command grammar and its confidence-times-consequence gate, nothing here can run an
irreversible action without the confirmation a spoken command would need. Unmapped events do
nothing.

### 4. Everything is local, optional and lazily imported

`numpy` is the only hard requirement of the pure modules (filters, detectors, quality gate,
ledger). BrainFlow stays behind the existing `emg-band` extra and is imported only inside the
source that needs it, so a base install imports and runs unchanged (AGENTS.md rule 3). Pure logic
sits beside injected backends (rule 5): detectors are tested on synthetic and replayed signals with
no hardware. Hardware sources degrade to a logged no-op when the device or library is absent, as
the serial and BrainFlow paths do today.

### 5. Per-person calibration drives the detectors; it is not optional

Fixed microvolt thresholds are meaningless across people, placements and days. The calibration
session (`calibration.py`) derives reference levels from the user's own relaxed baseline and
contractions and writes a local profile with no raw samples. The EMG switch is **off** until a
profile with a maximum-contraction reference exists: it is refused rather than guessed. Blink and
jaw-clench detectors adapt to a per-person reference only through hooks that the calibration
exposes (a constructor from calibration values, and a runtime sensitivity scale that the governor
turns up and back down). Where a detector does not yet take calibration values, it runs on its own
conservative, self-estimated baseline and the docs say so.

### 6. The source obeys the global pause, and the governor's release is one action

Hands-free composition (ADR-v2-148) has one global ACTIVE / PAUSED / FAULTED state. A biosignal
source is one more hands-free input: while the global state is not ACTIVE the daemon ignores the
source's squeezes and intents, and a squeeze already held when a pause arrives is released at once
and latched off until the signal relaxes, so the pause cannot be followed by a stale hold. The
source reports a heartbeat to the gate while blocks arrive, so a device that goes quiet ages out
of the global state like a camera that goes blind. This is enforced at the daemon seam, in the
adapter callbacks; the package stays free of daemon imports. The runner exposes a small public
API (`ledger`, `pipeline`, `note_cancelled`, `governor_release`, `save_ledger`, `status`) so the
daemon never reaches into private attributes. An explicit Resume of the global state also releases
the governor: the governor's release is one
action (ADR-v2-153). Today the pipeline and ledger keep running while the global state is paused
(only the daemon-side effects are gated), so a paused period still accrues exposure time; that is
a known limit.

### 7. Measurement is built in: the ledger survives a crash, and an evaluation harness scores the detectors

- **The ledger is persisted as it goes**, not only on a clean shutdown (`[biosignal]
  ledger_autosave_seconds`), as aggregate counters only (sessions, active seconds, activations and
  cancellations per event kind; no raw signal, no per-event record). Each save adds only what
  changed since the previous save to what the file holds at that moment, so repeating it neither
  double counts nor overwrites totals written by another process. A daemon that is killed loses at
  most one interval of the measurement the feature exists to produce.
- **An evaluation harness** (`evaluate.py`) scores a detector or pipeline against a recording with
  scripted events (recall, precision, latency) and counts phantom activations per hour on a stream
  with nothing happening, with Wilson and Poisson intervals. Its report states on every run that
  synthetic results prove the logic and not real-world accuracy.
- **Commands to record, evaluate, inspect profiles and boards, and resume a suspended switch** sit
  beside the first five (`doctor`, `calibrate`, `monitor`, `replay`, `report`); see the spec for
  the current command set and which of them exist yet. A table of known boards (`boards.py`) is
  advice for choosing a `source` string, built only from ids read from the installed BrainFlow
  package; it opens nothing.

## Alternatives rejected

- **Reverse ADR-v2-129 and ship "EEG control".** No measured number in the repository supports a
  livable false-activation rate for thought decoding on consumer hardware; BCI inefficiency (some
  users never produce usable patterns) makes it a feature that silently does not work for part of
  its audience. Rejected again, on the same evidence.
- **Keep one detector per source and no shared pipeline.** That is what exists. It cannot gate on
  signal quality, share calibration, or measure a false-positive rate across sources, and each new
  board would re-implement a threshold.
- **Do the processing on the microcontroller (YESP only).** Right for the DIY serial device and
  still supported, but it leaves the daemon blind: no quality gate, no ledger, no budget. The new
  pipeline covers the raw-sample case; YESP is unchanged.
- **A trained classifier for blink/clench.** More accuracy on a lab set, but it needs a training
  corpus we do not have, hides the failure mode, and cannot be explained to a user whose switch
  misfired. Thresholds on interpretable features can be.
- **Fire first, report the false-positive rate later.** ADR-021's lesson: a guard that fires too
  often teaches users to dismiss it. The budget must act on the user's machine, not sit in a paper.
- **Upload recordings to tune detectors centrally.** Excluded by ADR-011 and ADR-019; see below.

## Consequences

- EMG/EOG/EEG-artifact switches become measurable on the user's own machine: the proxy rate, its
  interval and the budget state are visible (`yazses biosignal report`, `monitor`).
- A new optional section, a new `biosignal` command group and a new package. All dormant by
  default; an existing install is unchanged (AGENTS.md rule 2). Config keys and the CLI surface are
  public interfaces and so are L3 work: the generated reference docs are regenerated with them.
- **Biometric-adjacent data.** Raw recordings and calibration profiles describe a person's
  physiology. They are classified accordingly in the spec: stored locally, profile file mode 0600,
  never transmitted, never part of a diagnostics bundle by default.
- **Honest limitation, carried into every user-facing page:** blink and jaw clench are artifacts.
  Talking confounds the jaw clench. Thresholds are per person and per electrode placement, so
  calibration is mandatory and a re-seated electrode needs a new one. The shipped structure is
  reasoned; the numbers are unmeasured until community reports exist.
- The package gives the research page's open question 1 ("measured false-activation rates") a way
  to be answered with real data rather than anecdotes.
- Cost: a polling loop and a few filters while the source runs. Off means zero cost.

## Egress

**No new egress path exists.** The package opens no socket and makes no network call. Sources are
a local serial port, a local BrainFlow device (USB/Bluetooth to the machine, not the network), a
file the user names, or a synthetic generator. Recordings, profiles and the ledger are written to
local disk only. Nothing is added to the nine registered egress paths of ADR-019, and
`tests/test_egress_inventory.py` must continue to pass with no new registration. If a BrainFlow
board type that streams over a network socket is ever supported, that is a new egress decision
under ADR-019 and needs its own review. (BrainFlow's synthetic board and the in-package synthetic
source need no hardware.)

## Open questions / known limits

What is still unmeasured or unproven, stated plainly so no page overstates it:

- **Thresholds are untuned on real recordings.** Every number in the detectors, the quality gate,
  the calibration and the governor is a design choice validated on synthetic signals. None is a
  measured operating point, and none may be called recommended.
- **Validation is synthetic only.** The test and evaluation signals are generated. They show that
  the logic does what it says; they do not show real-world sensitivity, false-positive rate or
  latency on a person with a real board in a real room.
- **The cancelled fraction is a proxy.** It undercounts false positives the user does not notice
  and overcounts cancellations that have nothing to do with the switch. It is shown with an
  interval and a caveat; it is not an error rate.
- **The governor needs the integrator to report cancels.** If no undo or cancel is reported, the
  budget never acts. That fails safe but is a no-op that must be visible.
- **Speech suppression reads audio-side state only.** The speech guard fires on the dictation
  state, a voice-activity flag and playback, not on the jaw electrode itself. If those sources are
  absent or late, a clench during speech can still pass.
- **Blink and jaw-clench detectors may not yet take calibration values**, so their per-person
  adaptation can be weaker than the EMG switch's, and the governor reaches them only through the
  pipeline's confidence floor unless they expose a sensitivity scale. A blink-detector warm-up
  defect was found in review and its fix is tracked in the spec's checklist.
- **Hardware coverage.** Only the synthetic source runs without hardware. BrainFlow boards are
  reached through BrainFlow's own support and are not individually verified here.
- **Time-of-day, fatigue and electrode drift** over a workday are not modelled; a re-seated
  electrode needs a new calibration.

## Implementation status

Verified against the tree when this ADR was last updated. The status line stays "Proposed" until
field measurement exists; an item here can be present in code and still be unmeasured.

| Item | State |
|---|---|
| Package, quality gate, detectors, calibration session and profile, sources, pipeline, runner, daemon wiring, ledger, governor, `doctor` / `calibrate` / `monitor` / `replay` / `report` | present |
| Speech guard combiner (`speechguard.py`, used by the daemon, config `speech_guard`), evaluation harness (`evaluate.py`), global-pause handling in the daemon adapter, public runner API, periodic ledger autosave (`ledger_autosave_seconds`), board table (`boards.py`), commands `record` / `evaluate` / `boards` / `resume` / `profile` | present |
| Calibrated blink/clench detectors with a runtime sensitivity scale, and the blink warm-up fix | present (synthetic-signal validation only); the spec's "Round-2 status" table is the authority |

## Not decided here

- Default thresholds, budget and desensitization schedule (measure first).
- Whether a graded third squeeze level is learnable (research page, open question 2).
- Additional boards beyond what BrainFlow already supports.
- Any silent-speech or label-emitting decoder; the intent path carries labels, this package emits
  only the fixed event set above.
