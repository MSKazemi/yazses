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
`docs/research/muscle-brain-control.md`, spec: `design/specs/biosignal-pipeline.md`, field protocol:
`design/specs/biosignal-validation-protocol.md`

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
action (ADR-v2-153). The pipeline keeps running while the global state is paused (only the
daemon-side effects are gated), but the daemon pauses the runner's exposure accounting
(`pause_accounting()` / `resume_accounting()`) on the gate's transitions, so a paused period does not
accrue as ledger exposure and cannot dilute the measured rate.

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
- **Commands to record, evaluate, field-test, inspect profiles and boards** sit beside the first five
  (`doctor`, `calibrate`, `monitor`, `replay`, `report`); see the spec for the current command set.
  A suspended switch is released by the global `yazses handsfree resume`; there is no
  `yazses biosignal resume`. A table of known boards (`boards.py`) is
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
- **Per-person adaptation is only as good as the calibration the person could produce.** The blink
  and jaw-clench detectors take calibration values and a sensitivity scale, and the pipeline refuses
  a stale or mismatched profile, but all of that is validated on synthetic signal only; whether
  the intended users can perform the calibration gestures is unmeasured. A blink-detector warm-up
  defect found in review is fixed (see the spec).
- **Hardware coverage.** Only the synthetic source runs without hardware. BrainFlow boards are
  reached through BrainFlow's own support and are not individually verified here.
- **Time-of-day, fatigue and electrode drift** over a workday are not modelled; a re-seated
  electrode needs a new calibration.

## Evidence and what it does not show

This ADR rests on reasoning and on a small amount of published literature, all of it recorded on the
research page (`docs/research/muscle-brain-control.md`, which grades each reference *measured*, *vendor*
or *secondary*). The figures below are quoted as that page records them; this ADR did not re-derive them
from the primary papers. What each one supports, and what it does not:

| What is cited | What it supports | What it does **not** show |
|---|---|---|
| An EOG blink switch at 99.5% accuracy, 1.3 s response and **0.10 false positives per minute** (Li et al., *Neurocomputing* 2018; *measured*) | That an artifact-grade switch can be accurate, and that the **best published** false-positive rate for a blink switch is of this order, about 50 phantom activations in a workday | That our detector reaches it; that it holds on a headband rather than the study's electrodes; that it holds over a workday of talking and typing; that 0.10/min is *livable* (the research page calls it a fatal problem without extra safeguards). It is a ceiling to beat, not a result we have. |
| A breath-hold PPG toggle at **0.02 false operations per minute** (Han et al., *Sensors* 2020; *measured*) | That a different physiological channel can be five times quieter than a blink switch | Anything about EMG or EOG. It motivates choosing the channel where the action is loudest; it supplies no number for ours. |
| Meta's *Nature* 2025 sEMG wristband (Kaifosh et al.; *measured*): large-scale offline gesture decoding on held-out users | That surface EMG gestures generalise across many people in an offline evaluation | A false-activation rate. As the research page records, the paper reports **no false-activation rate**, which is the number that decides whether a trigger is livable. Its hardware is also not available to this project (no raw EMG, no Linux, ADR-v2-129). |
| "Jaw clench about 90%, sub-second possible" (a row of the research page's table) | Nothing citable: that row carries no reference on the page | Do not quote it as evidence. The same table names the real problem, chewing and talking, and no cited source measures the rate under them. |
| BCI inefficiency (Tibrewal et al.; *measured*) | Why thought decoding stays out of scope: some users never produce usable patterns | Anything about artifact switches. |
| **This repository's own results** | That the code does what the spec says: the quality gate suppresses, the watchdog closes holds, the governor escalates in order, the ledger counts correctly. Synthetic and replayed signals only. | Anything about a human body: no phantom-activation rate, no hit rate, no latency, no calibration time, and no behaviour on any board has been measured on a real person. However large the synthetic test suite is, it is evidence about the logic, not about physiology. |

Taken together: **the literature establishes that the idea is not absurd and that the false-positive rate
is the number that matters; it does not establish that this implementation meets any rate, and the
repository has no real-signal evidence at all.** The structure this ADR decides (gate, budget, ledger,
measurement) is the response to that gap. It is not a claim that the gap is closed.

Further unknowns that no cited source settles: how the cancelled-activation proxy relates to labelled
phantom activations (never compared); how far a person's rate varies day to day and electrode re-seat to
re-seat; whether the speech guard, which reads audio-side state, is enough in real dictation; and whether
the intended users, who matter most, can produce the gesture the calibration asks for as reliably as the
volunteers any first study will be able to find.

## Falsifiable acceptance criteria

The status stays **Proposed** until a real-hardware field test, run under
`design/specs/biosignal-validation-protocol.md`, meets the gates below. They are **design choices**, set
before any data exists so they cannot be bent to fit data; they are not derived from a clinical or
usability standard, and they can be changed only by a recorded amendment made *before* the run they
govern. Moving the status is a maintainer decision recorded as a dated amendment to this ADR; passing the
gates makes the move permitted, not automatic.

Common conditions for every gate: thresholds, budget and mapping frozen before the evaluation round (no
tuning on the data being judged); each participant calibrated for their own configuration; bounds
computed as the protocol states (a one-sided 95% Poisson upper bound for rates per usable hour, a
two-sided 95% Wilson interval for proportions, read at the **conservative** end); results reported per
configuration and per participant beside the pool.

**Tier 1: Proposed to Accepted.**

| # | Gate | Pass condition |
|---|---|---|
| A0 | Sample | At least 5 participants, using at least 2 distinct board or electrode-site configurations, each configuration with at least 2 participants. |
| A1 | Phantom activations | In each of the phases `rest`, `hands_busy` (typing), `speech` and `chew` of the field test, the pooled one-sided 95% upper bound on phantom activations per usable hour, over all trigger kinds the configuration enabled, is at most **6 per hour**. With no phantom seen that needs about half an hour of pooled usable signal in the phase (rule of three), more if any were seen; the report prints the extra hours needed. The 6 per hour is the best published blink switch (0.10 per minute) expressed per hour, which makes the gate "no worse than the best published artifact switch", a floor and not a statement that 6 an hour is pleasant. The per-kind counts are reported beside it. |
| A2 | Hit rate | The two-sided 95% Wilson **lower** bound on deliberate-gesture hits (pooled scored cues of the `gesture_*` phases) is at least **90% for the squeeze** and at least **80% for the double blink**, which with no misses needs about 35 and 16 scored cues respectively (a default session scores 8 per switch). This is stricter than the tool's own advisory `usable` verdict, which judges the hit rate on the point estimate. |
| A3 | Calibration time | At least 80% of participants reach a written profile within **5 minutes of wall-clock time and 3 attempts** from the start of `yazses biosignal calibrate`, electrode seating included. (The guided phases themselves are about half a minute of recorded data at the default timings in `CalibrationConfig`; the ceiling is for the person, not the code.) Participant counts are small, so the proportion is reported with its interval and read on the point estimate. |
| A4 | Safety | **Zero stuck-mic events** in the full stress list of the protocol on real hardware (cable pull, USB unplug mid-squeeze, daemon restart mid-hold, pause mid-hold, governor suspension mid-hold) and in all of the participants' live use (the field-test command itself drives nothing, so it cannot see a stuck microphone). One event fails the gate; the fix restarts the list. |
| A5 | Governor behaviour | Judged in live use, because the field test acts on nothing and reports no cancels, so it cannot move the governor: in the participants' own days with the daemon and ledger on, the governor does not leave `OK` for those who meet A1; in one deliberately noisy live session it escalates in order (desensitize, then suspend); and a single release returns it to `OK` from each state, every time it is tried. Details: ADR-v2-153, "Falsifiable acceptance criteria". |
| A6 | Privacy | The shared field-test JSON contains no signal, no recording, no profile and no per-event timestamps, confirmed by reading the schema and a sample file. |

**Jaw clench (separate, optional).** It is off by default and stays off unless it meets A1 and A2 in
`speech` and `chew`, with the speech guard on. Chewing is itself a clench, so failing is a plausible
outcome and is not a failure of the rest of the feature: the squeeze can reach Accepted while the jaw
clench is documented as unsupported.

**Tier 2: leaving "experimental".** The feature stays labelled experimental on every page until all of
Tier 1 holds **and**: at least 10 participants on at least 3 configurations, including intended users of
the feature (people for whom a key press is difficult), who take part voluntarily and are asked for no
health information; a phantom upper bound of at most **2 per usable hour** in `rest` and `hands_busy`; at
least 5 days of each of several participants' own use with the live ledger on (the cancelled-activation
proxy, shown against the labelled field-test counts); and no gate regression after the last code change
to a detector, the quality gate or the governor. Leaving "experimental" removes a label. It does not make
the feature default-on: AGENTS.md rule 2 (new features ship off by default) is not relaxed by a field
test.

## Kill criteria

A feature that cannot meet its own budget should stop, not drift. These are decisions recorded in
advance; each is a design choice and applies to the **tested hardware and code revision**, not to
electrodes in general.

1. **Budget unreachable on a board.** If a board or electrode-site configuration still exceeds A1 after
   **2 tuning rounds** (each judged on a fresh round after its configuration was frozen), it is recorded
   as failing and removed from the documented hardware. If **every** configuration tested fails A1 for
   the squeeze, the biosignal switch is withdrawn as a user feature: the package is reduced to the
   evaluation harness and the replay tools, and the user pages are rewritten to say so. Blink and jaw
   events are withdrawn first (the likelier to fail), and the squeeze on a dedicated muscle electrode is
   the last thing standing, because it is the case the research page argues for.
2. **Calibration is the barrier.** If fewer than 60% of participants reach a profile within the A3
   ceiling after 2 rounds of calibration-procedure changes, the per-person calibration design is wrong
   and needs a new ADR before any other work; the feature does not proceed on a calibration most people
   cannot complete.
3. **A stuck-mic event that cannot be designed out.** If a stuck-mic event recurs after its fix and the
   cause is a property of the hardware path rather than a defect (for example a driver that reports a
   healthy stream while delivering stale data), the affected source type is removed, not guarded
   further.
4. **The governor's evidence is unusable.** If the field-test shows the cancelled-activation proxy does
   not move with labelled phantom activations (silent when phantoms are frequent, or loud when there are
   none), the proxy-driven governor is retired or replaced with a different mechanism by a new ADR. The
   measurement and the one-action release stay.
5. **No evidence.** If no real-hardware field result exists after **two minor releases** from the first
   release containing the feature, a maintainer reviews the status and either extends with a stated
   reason or withdraws the user-facing pages. A feature nobody can measure is not kept alive on the
   strength of its test suite.
6. **Scope creep.** Any request to turn the feature into a decoder of thought, intent, emotion or health
   is out of scope under section 1 and is not a "next step" of this ADR (it needs its own ADR and
   evidence, and may not cite this one).

## Implementation status

Verified against the tree when this ADR was last updated. The status line stays "Proposed" until
field measurement exists; an item here can be present in code and still be unmeasured.

| Item | State |
|---|---|
| Package, quality gate, detectors, calibration session and profile, sources, pipeline, runner, daemon wiring, ledger, governor, `doctor` / `calibrate` / `monitor` / `replay` / `report` | present |
| Speech guard combiner (`speechguard.py`, used by the daemon, config `speech_guard`), evaluation harness (`evaluate.py`), global-pause handling in the daemon adapter, public runner API, periodic ledger autosave (`ledger_autosave_seconds`), board table (`boards.py`), commands `record` / `evaluate` / `boards` / `profile` / `profile-clear` | present |
| Calibrated blink/clench detectors with a runtime sensitivity scale, and the blink warm-up fix | present (synthetic-signal validation only); the spec's "Round-2 status" table is the authority |
| Round-3 hardening: squeeze artifact blanking and channel agreement; block-size-independent jaw timing and an opt-in chew hold-off; per-hop quality evaluation with lead-off, common-mode and contact score; calibration provenance enforcement (`calibration_max_age_days`); `reset(keep_governor_state=...)`; release survives one evaluation; accounting pause/resume; richer `status()`; `watchdog_seconds` and `min_event_confidence`; daemon status block and ordered shutdown | present (synthetic-signal validation only); the spec's "Round-3 status" table is the authority |
| `fieldtest.py` and `yazses biosignal field-test`, the doctor `Verdict:` line, and the validation protocol | present as tooling and a written protocol. **No field-test result exists.** The gates above are unmet; the status stays Proposed. |

## Not decided here

- Default thresholds, budget and desensitization schedule (measure first).
- Whether a graded third squeeze level is learnable (research page, open question 2).
- Additional boards beyond what BrainFlow already supports.
- Any silent-speech or label-emitting decoder; the intent path carries labels, this package emits
  only the fixed event set above.
