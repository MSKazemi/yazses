# Spec: Biosignal Validation Protocol — Measuring Phantom Activations and Hit Rate on Real Hardware

| Field | Value |
|---|---|
| **ID** | spec-biosignal-validation-protocol |
| **Status** | Proposed |
| **Date** | 2026-10-30 |
| **Modules** | `yazses.biosignal.fieldtest` (guided in-situ session and `FieldTestAggregate`), `yazses.biosignal.evaluate` (interval maths shared with the offline harness), `yazses.biosignal.fprate` (the live ledger) |
| **Related** | ADR-v2-152 ("Falsifiable acceptance criteria", "Kill criteria"), ADR-v2-153, `design/specs/biosignal-pipeline.md`, ADR-v2-150 (research consent), ADR-011, ADR-019 |
| **Research** | `docs/research/muscle-brain-control.md` (open question 1: measured false-activation rates) |
| **User page** | `docs/how-to/biosignal-switch.md` ("Measure your own rate") |

## Goal

Every number in `yazses.biosignal` (detector thresholds, quality-gate limits, the budget, the governor
schedule) is a design choice validated on synthetic signal only (ADR-v2-152, "Evidence and what it does
not show"). This protocol is how that changes. It specifies how a person with real hardware measures, on
their own machine, **how often the switch fires when they did not mean it** and **how often it fires when
they did**, how those measurements are combined across people and boards without moving any raw signal,
and how much evidence is needed before anyone may say anything about them.

It produces upper bounds and lower bounds with their method stated. It does not produce an "accuracy".

## Non-goals

- not a clinical study, a medical evaluation, or a claim about any person's health or condition; YazSes
  is not a medical device, and nothing here is reviewed by an ethics board;
- not a way to collect raw signal, recordings, calibration profiles or thresholds (those never leave the
  machine; see "Reporting back");
- not a tuning loop: the protocol measures a frozen configuration, it does not search for one;
- not a replacement for `yazses biosignal evaluate` on a labelled recording, which scores the detectors
  offline; this protocol measures the whole chain, live, in the activities where mistakes actually happen;
- not an identity, emotion, fatigue or health measurement of any kind.

## Definitions

These are used identically in the field-test output, in the ADR gates and in the user pages. They
follow `yazses.biosignal.fieldtest`, which is the authority for how each number is computed.

| Term | Definition |
|---|---|
| **Activation** | An event the runner would act on: anything except `SQUEEZE_OFF`, which closes a hold rather than starting one (the ledger's rule, ADR-v2-153 section 1). |
| **Trigger kinds** | The activations the field test counts as phantoms. A single `BLINK` is **not** counted by default: a natural blink is unmapped and is not a commit signal (spec, event semantics). The per-kind counts, single blinks included, are still listed in the report. |
| **Usable exposure** | Signal time in which the pipeline reported usable quality and was not suspended, minus the first few seconds of each phase (the design default is 3 s, because reading the next prompt is itself a head movement). Time the quality gate suppressed is excluded from the denominator, so a bad signal cannot flatter the rate by looking like silence. |
| **Phase** | A prompted activity with a fixed purpose (table below). Every second of exposure is labelled with its phase. A phase with less than the minimum usable signal (design default 30 s) is *inconclusive* and is left out of every pooled number. |
| **Phantom activation** | A trigger-kind activation during a phase in which the participant is *not* trying to trigger anything. Ground truth is the prompt, not the participant's memory, so the cancel-signal proxy of the live ledger is not involved. |
| **Cue / hit / miss / void** | In a gesture phase the tool schedules cues. A cue is a *hit* when an expected event kind is accepted inside the cue's response window (design default 3 s), a *miss* otherwise, and *voided* (neither) when its window overlaps unusable signal. Activations outside any window in that phase are reported as extra. |
| **Phantom rate** | Phantom activations per usable hour, per phase, with a one-sided 95% Poisson upper bound (a cube-root approximation, the same as `evaluate_idle`; about `3 / hours` when none was seen). |
| **Hit rate** | Hits over scored cues, with a two-sided 95% Wilson interval (`fprate.wilson_interval`). Cue-to-event latency includes the participant's reaction time and is **not** the detector's own latency. |
| **Stuck-mic event** | The microphone (or the command key) held open by the switch longer than the max-hold watchdog plus one polling interval, or still held after a pause, suspend, stop or source error. A single one is a failure. The field test does not drive the microphone (nothing is typed or acted on), so this is observed in the stress list and in ordinary use, not in `field-test`. |
| **Frozen configuration** | The `[biosignal]` section, the calibration profile and the yazses version, fixed before the evaluation round begins and written down by the participant (they are **not** in the report file; see "Reporting back"). |

## Who and what hardware

- **Participants** are adults using their own hardware on their own machine, who have read the consent
  text below. Intended users of the feature (people who cannot press or hold a key reliably, or whose
  hands are busy) are the population that matters most and are asked for specifically, but are never
  asked for health information; the protocol records none.
- **Hardware recorded** (written by hand beside the shared file, free text, no photographs): board and
  BrainFlow id (or "serial YESP sensor"), electrode type, placement in words (for example "left
  forearm, flexor side"), sampling rate, the `mains_hz` setting, operating system, the yazses version, and
  which of squeeze, double blink and jaw clench were enabled (the standard session cues all three gestures; a switch that was off cannot fire and its row is to be ignored). The report file does not carry these.
- **A configuration is a unit of evidence.** The same person on a different board, a different electrode
  site or a re-seated electrode (with a fresh calibration) is a different configuration, and results are
  never pooled across configurations without also being reported per configuration.
- **Minimum for the ADR gates:** see ADR-v2-152, "Falsifiable acceptance criteria" (participant and
  configuration counts are set there, not here, so the numbers live in one place).

## Preconditions

1. `yazses biosignal doctor` reports no failing check for the source, and its closing `Verdict:` line is
   read before starting. A failing doctor is a result in its own right: record it, do not run phases
   through it.
2. A calibration profile made for this configuration exists (`yazses biosignal calibrate`). The wall-clock
   time from starting `calibrate` to a written profile, the number of attempts, and whether it succeeded
   are noted by the participant (gate A3). The command does not time the person, only the data.
3. Defaults are the defaults. A participant may run with their own `[biosignal]` values, but then the
   result describes those values.
4. For the evaluation rounds the participant does not edit thresholds, the budget or the mapping. A
   retune is allowed only between *rounds* (see "Tuning rounds").

## Phases

`yazses biosignal field-test` walks the participant through these in order, prompting on screen. The
tool advances on **signal** seconds, not on wall time, so a stream with gaps simply takes longer. The
no-intent phases come first and the gestures last, so a tired participant still gives the phantom
evidence that matters most. Durations are the tool's **design defaults**, sized for a short session;
they are not derived from any measured variance, and `--minutes` stretches or shrinks the whole
sequence proportionally.

| Phase (report name) | The participant | Purpose | Default length |
|---|---|---|---|
| `rest` | Sits still, looks at the screen, does nothing on purpose | The floor: spurious firing from noise, drift, mains, posture | 120 s |
| `speech` | Reads aloud or talks as in a call | The jaw and face confound the speech guard exists for | 90 s |
| `chew` | Chews gum or a snack throughout | The confound the speech guard does not cover (ADR-v2-152, known limits) | 60 s |
| `hands_busy` | Types and uses the mouse as in normal work | Arm and hand muscle use on or near the electrode, desk vibration | 120 s |
| `movement` | Looks around, turns the head, shifts, stretches | Posture, cable motion, electrode shift | 60 s |
| `gesture_squeeze`, `gesture_double_blink`, `gesture_jaw_clench` | Makes the named gesture on cue (default 8 cues, 3 s response window) | Hit rate and cue-to-event latency per switch | 45 s each |

A default run is about 7.5 minutes of no-intent phases plus 45 seconds per gesture (about ten minutes for all three). The weights
the tool applies to build its *workday estimate* (rest 0.20, speech 0.25, chew 0.05, hands busy 0.35,
movement 0.15) are an illustrative activity mix for a desk-bound day, **not data**; the per-phase numbers
are the evidence and the weighted figure is a convenience.

Phases that do not apply to a configuration are still run and are simply uninformative (a forearm
electrode with no jaw channel makes `speech` and `chew` informative mostly for the squeeze; a headband
makes them central). The jaw-clench switch is off by default and is measured only when the participant
turns it on; running it once with the speech guard on and once off measures the unguarded rate the guard is
meant to remove. `rest` is deliberately first, before the participant has watched the live monitor, so
that watching the signal does not change how they sit.

### The tool's own verdict is not the ADR gate

The command ends with a verdict: `usable`, `promising`, `needs_tuning`, `do_not_enable` or
`inconclusive`. It is a per-person advisory rung, built from the weighted pooled phantom bound, with
hit rate judged on the point estimate (at least 80% of cues) because with the default eight cues a Wilson
lower bound above 80% is unattainable (eight of eight gives about 68%). It exists to help one person
decide whether to leave a switch on. **The ADR gates are stricter and are read on the per-phase
numbers and the conservative interval ends**; a `usable` verdict from one session is neither sufficient
nor necessary for a gate. The standard session cues every gesture whether or not that switch is on, and the verdict looks at
every conclusive gesture phase, so a switch that was off (and so could not fire) can drag the headline
toward `do_not_enable`; in that case read the per-phase rows of the switches that were on, not the
headline.

## Tuning rounds

Threshold changes are the easiest way to produce a good-looking result that means nothing. The rules:

- A **round** is one or more complete field-test sessions on a frozen configuration.
- Between rounds a maintainer or participant may change thresholds, the budget or the mapping, and must
  write down what changed and why.
- **Never evaluate on the data used to choose the change.** A configuration is judged only on a round that
  ran *after* it was frozen. A result from a round whose configuration was chosen by looking at that
  round's own counts is discarded from the aggregate.
- The ADR's kill criteria count rounds: a limited number of retuning rounds per configuration is allowed
  before it is recorded as failing.

## Aggregation: `FieldTestAggregate`

A session produces a report (`report_to_dict`, schema 1): per phase the usable and excluded seconds, the
phantom count and per-kind counts, the cues scored, voided and hit, the extra activations and the
cue-to-event latencies (to 0.1 s); plus the verdict, its reasons, the budget, the workday figures and the
caveat. `FieldTestAggregate` (with `report_from_dict`, which recomputes every derived number from the
counts so a stored file cannot disagree with itself) merges reports. What it does, and what anyone
aggregating by hand must also do:

1. **Counts and seconds add; rates and bounds are recomputed.** Never average per-session rates. A pooled
   rate is total phantoms over total usable exposure, with the bound computed on the totals. An
   inconclusive phase in every session can become conclusive once its usable seconds add up.
2. **Like with like.** Phases are matched by name. Reports that counted different trigger kinds are
   refused, and so is a phase that is a gesture phase in one report and not in another.
3. **The aggregate has no notion of participant, configuration or session identity.** It does not
   deduplicate (adding the same file twice counts it twice) and it cannot show a per-participant row.
   Whoever merges must therefore: build **one aggregate per participant per configuration** and report
   those rows beside the pooled one; add each file once; and report the worst participant next to the
   pool. A pooled bound can hide one participant for whom the switch is unusable, and a pooled pass with
   a failing individual is read as "not yet" for any claim about people.
4. **Configurations stay separate in the report.** A cross-configuration pool is an additional row, never
   a replacement for the per-configuration ones.
5. **Exposure is the denominator.** A session in which the switch was mostly gated or suspended
   contributes little usable time and so a wide bound; it is not discarded and not up-weighted.
6. **The bound's method is stated, every time:** one-sided 95% Poisson upper bound on frozen thresholds,
   not an accuracy. The workday figure additionally applies a Bonferroni split across the phases used.

## Minimum evidence for a claim

| What you want to say | Minimum evidence | What you may not say |
|---|---|---|
| "This setup produced N phantom activations in H usable hours of `rest`." | One session. State N, H and the phase. | That the switch "has a low false-positive rate". |
| "The phantom rate for phase P is below X per hour for this configuration." | Pooled usable exposure in P of at least `3 / X` hours with no phantom (rule of three), more if any were seen (the report prints the extra hours needed), from at least three sessions on different days so one good afternoon does not stand for the setup. For `X = 6` that is half an hour of usable signal in that phase; a default session gives about one minute of `chew`, so this takes many sessions or stretched ones (`--minutes`). | Anything about another board or electrode site. |
| "...for people" or "...for this board" | The previous row for at least the participant and configuration counts the ADR gate names, with no individual failing the same bound by a wide margin (rule 3 above). | "Works", "accurate" or "reliable" without the bound and the exposure beside it. |
| "The hit rate for a switch is at least Y." | A Wilson **lower** bound of at least Y from pooled scored cues. With no misses the lower bound is about `n / (n + 3.84)`: a 90% floor needs 35 scored cues with none missed (more with any miss), an 80% floor needs 16. A default session scores 8. | A point estimate on its own. |
| "The cancelled-activation proxy tracks real phantoms." | Sessions where both the field-test phantom counts and the live ledger's cancelled counts were recorded over the same period, shown side by side. | Anything about the proxy from synthetic data. |
| "The stuck-mic safeguard holds." | The full stress list below passes on the exact code under test, and ordinary use records no stuck-mic event. | That a stuck mic is impossible: zero events in finite runs bound the rate, they do not eliminate it. |

Claims are about the **configuration and the code revision measured**. A later change to a detector, the
quality gate or the governor invalidates the evidence for the changed behaviour until it is re-run.

## Reporting back without raw signal

`yazses biosignal field-test --json` prints, and `--out <file>` also writes (owner-only, never
overwriting an existing file), the session report. It contains counts, whole-second durations, interval
bounds, the verdict and its reasons, the phase labels and the cue-to-event latencies. It contains **no
sample values, no recordings, no amplitudes, no thresholds, no profile contents and no event
timestamps**. It also contains no board, placement or version information: those are written by the
participant beside it.

- The participant reads the file before sharing. It is a small JSON document meant to be read.
- Sharing is a deliberate act by the participant: attaching the file to an issue or a discussion by hand.
  The command never sends anything, and no yazses component reads the file back from a network location.
- Do not attach a recording, a profile or a screenshot of the live signal. If a maintainer needs to see
  signal to understand a failure, that is a separate, explicit, opt-in contribution governed by the
  research-consent rules in ADR-v2-150, not part of this protocol.
- Maintainers publish only aggregates: pooled rows, and per-participant rows under pseudonyms (P1, P2,
  ...), and only when there are enough participants (the ADR gate's count) that a row does not identify a
  person. Free-text hardware notes are edited to remove names and anything about health.
- A participant can withdraw at any time before publication by asking for their file to be removed from
  the aggregate. After publication only the pooled numbers remain, which cannot be separated.

### Consent text (shown by the command before it starts)

The command narrates, before the first prompt, that nothing is typed or acted on, that no signal is saved,
and that only counts of false activations are reported. The fuller statement for anyone running this as
part of a collection effort: what is counted (activations by activity, exposure, hits); what is not stored
(signal); that nothing leaves the machine unless the participant shares the JSON by hand; that this is not
a medical test and says nothing about their health; that they can stop at any time (Ctrl-C ends the
session and reports what was gathered, marked as stopped early) and that stopping early produces a smaller
sample, not an error.

## Stress tests

Field time cannot cover failure modes that happen once a month. Each of these is injected on purpose,
once with the synthetic source or a replay (cheap, repeatable, required) and, for the ones that need it,
once on real hardware (required before the ADR's stuck-mic gate can be called met). The pass condition is
always the **safe** behaviour, and for every case a hold, if one is open, is closed exactly once.

| Case | How it is injected | Expected safe behaviour |
|---|---|---|
| Cable pull / electrode lift-off | Synthetic dropout or flatline on one channel; on hardware, lift the electrode mid-session | The channel goes untrusted; no event from it; any open hold is closed; status names the reason; recovery needs the signal to be trusted again, with no event on the way back. |
| Electrode pop | Synthetic step that decays; on hardware, tap the electrode | No blink, squeeze or clench from the transient; if a hold was open it is not extended by it. |
| DC step | Synthetic baseline step (electrode shifted) | No activation from the step itself; the baseline is not poisoned (a long step does not make the next real squeeze impossible, and does not end an open hold early without cause). |
| Saturation | Synthetic clipping or gain that rails the ADC | Channel untrusted, no event. |
| Mains burst | Synthetic 50 or 60 Hz burst, or switching a nearby appliance on | Gate marks interference, no event during it; no event on the burst's trailing edge. |
| Dropped packets | Gap in the source clock | An open squeeze is closed, filters restart without a transient trigger, a forward gap is reported as a link problem. |
| USB unplug mid-squeeze | Unplug the board during a hold | The source stops delivering; the watchdog and the runner's error path close the hold exactly once; the daemon keeps running; plugging back in does not resume the old hold. |
| Source returns nothing forever / raises | Fake source | Runner survives, hold closed, no busy loop, status shows the source as stale. |
| Daemon restart mid-hold | Kill the daemon (including `SIGKILL`) while a hold is open, then start it | The dictation turn ends with the process; nothing restarts a hold on startup; with the hands-free global stop on the switch starts paused; the ledger loses at most one autosave interval. |
| Global pause / resume mid-hold | `yazses handsfree pause` during a squeeze, then resume | The turn ends once at the pause; squeezes while paused do nothing; after resume nothing starts until the signal has relaxed. |
| Governor suspension mid-hold | Drive the governor to suspend with a hold open | The hold is closed in the same step; the switch is silent until release or its timer; release is one action. |
| Speech guard failure | A guard source that raises or sticks at "speaking" | A raising source counts as speaking (no clench); a stuck source is ignored after the watchdog so the switch is not locked out. |
| Corrupt state files | Truncated, oversized, hostile or wrong-schema profile and ledger | Loaders return "none" and the feature degrades (no profile means the squeeze stays off), never a crash and never a guess. |
| Profile for a different montage | Profile made for other channels or sampling rate | Refused with a reason; squeeze stays off until recalibrated. |
| Suspend and resume of the laptop | Sleep the machine mid-session | Treated as a gap; the hold is closed; no activation from the first blocks after wake. |

A stress run **fails** on any stuck-mic event, any activation emitted from an untrusted window, or any
exception that reaches the daemon. A fix restarts the whole list on the new code.

## What the existing suite pins, and what it cannot

The synthetic test suite (`tests/test_biosignal_*.py`) is the regression net for the logic; it does not
substitute for any row above on real hardware. Which rows it covers at the logic level is tracked in
`design/specs/biosignal-pipeline.md` ("Test checklist: what the suite pins, and what remains").

## Open questions

1. Is a default session (about two minutes of `rest`, one of `chew`) a useful unit at all for a rare-event
   process? Reaching an upper bound of 6 per hour in one phase takes about half an hour of usable signal
   in it, so the evidence comes from many sessions or stretched ones (`--minutes`). The first reports
   decide whether a longer default or a per-phase length option is needed; the CLI has no protocol-file
   option today, only `protocol_from_dict` in Python.
2. Should the aggregate carry a participant and a configuration key so that per-participant rows and
   de-duplication stop being the merger's job? Today they are, and a mistake there is silent.
3. Is a prompted `speech` phase representative of speech during real dictation, when the speaker is also
   holding the switch? Likely not entirely; the live ledger over many days is the cross-check.
4. The field test acts on nothing, so it cannot observe a stuck microphone. Is the stress list plus the
   live status enough, or does the protocol need an instrumented dictation phase?
5. How many participants with the intended-user profile can be reached, given that the protocol asks for
   no health information and so cannot confirm who they are? Self-description in the issue is the only
   route, and it is voluntary.
