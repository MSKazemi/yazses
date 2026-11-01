# ADR-v2-153 — The biosignal false-positive governor: measure a proxy, desensitize first, suspend only on evidence, release in one action

**Status:** Proposed (2026-10-29)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-v2-152-biosignal-artifact-switches]] (the package this governs; its section 2
names the budget, this ADR records the mechanism), [[adr-021-invest-in-error-cost]] (rule 9: a guard
is judged on how rarely it fires), [[adr-v2-148-hands-free-composition]] (one global safety state;
the governor is a per-source guard beneath it, not a replacement), [[adr-v2-129-killer-features-10x]]
(the activation seam), research: `docs/research/muscle-brain-control.md`, spec:
`design/specs/biosignal-pipeline.md`, field protocol: `design/specs/biosignal-validation-protocol.md`

## Context

ADR-v2-152 commits the `yazses.biosignal` package to a *measured, bounded, enforced*
false-activation rate. Three facts shape how that can be done:

1. **A running system cannot see false positives directly.** It can see what the user did next.
   The only observable is that the user cancelled or undid an activation shortly after it fired.
   That is a **proxy**: a user may cancel a correct activation (changed their mind), or leave a
   wrong one uncorrected (did not notice). Ground truth needs a labelled session, which is an
   evaluation job, not a daemon job.
2. **Small samples lie.** Three cancellations out of three activations is three samples, not
   "100%". A governor that acts on a point estimate will fire on the first unlucky quarter hour.
3. **A guard that fires too often is worse than no guard** (ADR-021, AGENTS.md rule 9). It
   interrupts the user, teaches them to dismiss it, and then catches nothing. A guard that cannot
   be dismissed in one move teaches them to turn the whole feature off.

The research page records the published ceiling this is measured against: the best published blink
switch reaches 0.10 false positives per minute, about 50 phantom activations in a workday, and one
paper reports no false-activation rate at all. A switch worse than that is not livable, and a switch
nobody can measure cannot be tuned.

## Decision

Add a budget governor to the biosignal package (`biosignal/fprate.py`), driven by a local
activation ledger, with these rules. Every numeric value below is a **design choice** with its
rationale stated, not a measured operating point; the budget structure is the decision, the numbers
are to be changed with data.

### 1. Measure a cancelled-fraction proxy, and report its uncertainty

- The ledger counts each *activating* event (everything except `SQUEEZE_OFF`, which is a release,
  not a new activation) and counts it as **cancelled** when the integrator reports an undo or
  cancel of the latest switch-initiated action inside a short grace window (design default 3 s).
  An undo later than that is the user editing, not the trigger misfiring.
- The cancelled fraction is shown with a **Wilson score interval**, which behaves at small n and
  at the 0 and 1 edges where the normal interval collapses. Every place that prints the number
  also carries the proxy caveat (`PROXY_NOTE`).
- Rates use **active exposure time** as the denominator, not wall time. Time is accrued only while
  the trigger is live: a laptop left open overnight, a paused session, a period where the quality
  gate suppressed the detectors and a period where the governor itself suspended the source add
  nothing. Wall time would flatter the trigger.
- The ledger is local. What is persisted is aggregate counters only (sessions, active seconds,
  activations and cancellations per event kind); no raw signal, no per-event record.

### 2. The governor acts on evidence, not on the point estimate

The governor does **not** act on the displayed fraction. It compares a conservative **lower
confidence bound of the cancelled rate per active hour** (a one-sided bound, design default about
90%) against the budget `max_cancelled_per_hour` (design default 6 an hour, the best published blink
switch expressed per hour). It acts only when there is enough evidence for the signal to mean
anything: a minimum of active minutes and a minimum number of cancellations since the last change of
state (design defaults 5 min and 3). Below that there is no signal, only noise, and the governor
stays out of the way.

### 3. Desensitize first, then suspend

States: `OK`, `DESENSITIZE`, `SUSPEND`. "Desensitize then suspend" is the escalation order, and it
means exactly this:

| Transition | When | Effect |
|---|---|---|
| `OK` to `DESENSITIZE` | the rate's lower bound is credibly over budget | thresholds are multiplied by a factor (design default 1.5): the pipeline raises its confidence floor and tells any detector that exposes a sensitivity scale to rescale. The switch still works; it is harder to trigger. |
| `DESENSITIZE` to `SUSPEND` | after fresh evidence in the desensitized state, the lower bound is still credibly over a multiple of the budget (design default twice) | the source stops emitting events, any held squeeze is closed, and the user is told why and how to resume. |
| `SUSPEND` to `DESENSITIZE` | a timer (see 4) | the source resumes, still desensitized, with a fresh evidence window. It cannot suspend again until new cancellations accumulate. |
| `DESENSITIZE` to `OK` | the recent rate is below a fraction of the budget (hysteresis, design default 0.5) for a minimum dwell (design default 20 min) | the scale returns to exactly 1.0. |

Desensitizing is the gentle fix and is always tried first. Suspension is a stop, not a degradation
to a quieter detector that keeps firing. The desensitize scale resets to 1.0 when the state returns
to `OK`; leaving a stale scale in force after recovery would silently make the switch permanently
harder to use.

### 4. Auto-recovery with backoff

A suspension ends by itself after a timer (design default 5 min), longer by a backoff factor on each
repeat (design default 2x) and capped (design default 1 h), and it recovers into `DESENSITIZE`, not
straight to `OK`. A switch that suspends repeatedly therefore stays off for longer each time, while
a one-off bad patch heals without anyone touching it. The timer exists so that the feature cannot be
left dead for good by a single bad hour.

### 5. One-action release, bound by the integrator

`release()` returns the governor to `OK` at any state, immediately, and starts a fresh evidence
window so it cannot re-fire until enough new cancellations have been seen. The governor module only
exposes `release()` and the text that tells the user how to invoke it; **binding it to a single
word, button or gesture is the integrator's job**, and the release must be one action (ADR-021:
the release is one word). A suspended switch whose release needs a settings visit is a defect.
The release path must not depend on the suspended source itself, because the source is the thing
that is off.

A release also arms a one-shot hold: the next evaluation only refreshes the rate numbers and applies no
transition. The recent rate is an exponentially weighted average that still contains the cancellations
the user just dismissed, so without the hold a release followed by one more cancel could be judged on the
old evidence and suspend the switch again at once. After that one evaluation the fresh evidence window
and the existing hysteresis do the rest. A stream gap, reconnect or recalibration does **not** release
the governor (`pipeline.reset(keep_governor_state=True)`, the default): a dropout is not evidence that the
false-positive problem went away. Only an explicit release, or `keep_governor_state=False`, does. Paused
time (the global hands-free pause) does not accrue as exposure, because the daemon calls the runner's
`pause_accounting()` while the gate refuses.

### 6. The governor is conservative about when it fires, because the cost of firing is borne by the user

- It fires only on a specific, checkable signal (a credibly high cancelled *rate* with enough
  evidence), never on a heuristic.
- It is **off in the module by default** (`FalsePositiveBudget.enabled = False` reports `OK` and the
  ledger still measures), so the numbers exist before anything is allowed to change behaviour. In
  the package it is armed only when `[biosignal] max_cancelled_per_hour` is greater than 0; `0`
  means "count, never act".
- It is explicable: `explain()` returns one or two plain sentences stating what is happening, why,
  and how to undo it.
- Its firing rate is itself a measurement the evaluation harness should report (how often it
  desensitizes or suspends on a clean synthetic stream, which should be never, and on a noisy one).
  A governor that fires on a clean stream is broken.

## Alternatives rejected

- **Fixed refractory period only.** A refractory period stops one burst being counted twice; it
  says nothing about a switch that fires spuriously once every ten minutes. It is kept as a
  detector property (ADR-v2-152) and is not a substitute for a budget.
- **No governor; report the rate and let the user decide.** This is "fire first, report later". The
  report is kept (`yazses biosignal report`), but a user who is being interrupted every few minutes
  should not need to open a report to stop it.
- **Act on the displayed cancelled fraction.** Fires on small samples, and the fraction has no
  exposure-time denominator, so it cannot be compared with a per-hour budget.
- **Suspend immediately over budget.** Skips the cheap, reversible step. Many over-budget cases are
  a threshold slightly too low for today's electrode contact, which a modest desensitization fixes
  while keeping the switch usable.
- **Suspend forever until the user re-enables.** Teaches users to disable the feature and never
  turn it on again; the auto-recovery timer with backoff is the compromise.
- **A trained classifier that rejects "likely false" activations (ML post-filter).** Needs a labelled
  corpus of real false positives that does not exist, would train on exactly the proxy this ADR
  calls unreliable, hides the failure mode, and cannot be explained to a user whose switch
  misfired. Revisit only with measured data and its own ADR.

## Consequences

- A misbehaving switch ends up quieter, and if that is not enough, off, with a plain-language
  reason and a one-action way back.
- The cancelled signal must be wired by the integrator. If nothing reports a cancel, the governor
  sees zero cancellations and never acts; that is a safe failure (the switch is just ungoverned),
  but it makes the budget a no-op, and `doctor` / `report` should say so rather than imply
  protection.
- The proxy can punish a user who cancels for reasons unrelated to the switch, and can miss false
  positives the user never notices. Both are accepted and documented; neither is solvable without
  ground truth.
- No new data leaves the machine. The ledger holds counts, not signals (ADR-011, ADR-019).

## Evidence and what it does not show

- **The published reference point.** The budget default of 6 cancelled activations an hour is the best
  published blink switch (0.10 false positives per minute; Li et al., *Neurocomputing* 2018, as
  recorded on the research page) expressed per hour. That figure comes from a different detector and
  setup, and counts false positives by the study's own definition. It is a yardstick for "no worse than
  the best published artifact switch", not an estimate of what this package will do and not a
  statement that 6 an hour is acceptable to a user.
- **Nothing published validates a cancelled-activation proxy.** Using "the user undid it within a
  grace window" as a stand-in for a false positive is a design choice made here because it is the only
  observable a running daemon has. The repository has never compared it with labelled phantom
  activations on a real person. Its two known failure directions (cancels unrelated to the switch;
  false positives never noticed) are argued, not measured.
- **The statistics are textbook; their fit is untested.** A Wilson interval for a proportion and a lower
  confidence bound on a Poisson rate are standard tools and are tested against known values. Whether
  cancellations behave like a Poisson process (they will cluster: a bad electrode contact produces
  bursts) is an assumption. Clustering makes the lower bound less conservative than it looks.
- **Every governor number is a design choice with no field validation:** the factor, the multiples, the
  dwell, the timer, the backoff, the confidence level, the grace window, the evidence floor. The unit
  tests show the state machine moves as written; they say nothing about whether those values suit any
  person.
- **Our results are synthetic.** That the governor stays quiet on a clean synthetic stream and escalates
  on a scripted noisy one shows the machine works, not that it fires at the right times in a room.

## Falsifiable acceptance criteria

The governor is part of the Tier 1 gates of [[adr-v2-152-biosignal-artifact-switches]] (A5) and is
judged against `design/specs/biosignal-validation-protocol.md`. Note what the field test can and cannot
show here: `yazses biosignal field-test` acts on nothing and reports no cancels, so the governor cannot
move during it. The governor is therefore judged in **live use** (a participant's own days with the daemon
running and the ledger on, read through `yazses biosignal report` and the status block) plus one
deliberately noisy live session, with thresholds frozen before the round:

1. **It stays out of the way when nothing is wrong.** Over the live-use days of participants whose
   field-test phantom bounds meet the A1 bound of ADR-v2-152, the governor entered `DESENSITIZE` or
   `SUSPEND` **zero** times. (A firing rate on a clean stream is the first measurement of a guard,
   ADR-021; a governor that fires there is broken, not cautious.) A participant who meets A1 but whose
   governor fires anyway is the proxy-versus-phantom disagreement of criterion 5, not a pass.
2. **It acts when it should.** In a deliberately noisy live session (electrode loosened or a source of
   interference added on purpose, with the participant cancelling the resulting mistakes), the governor
   reached `DESENSITIZE` and, if the noise persisted, `SUSPEND`, and the user-facing text said why and how
   to resume. The time to act, in active minutes, is recorded and reported; no latency bound is set
   before data exists.
3. **Release is one action, every time it is tried.** In every state (`DESENSITIZE`, `SUSPEND`) a
   single release returned the switch to normal and it did not re-suspend without fresh evidence.
4. **Recovery works.** A suspension ended by its own timer into `DESENSITIZE`, never straight to `OK`,
   and a switch that suspended repeatedly stayed off longer each time up to the cap.
5. **The proxy is checked.** The live ledger's cancelled counts and the field test's labelled phantom
   counts are reported side by side for the same sessions. There is no numeric gate on their
   agreement before data exists (inventing one would be a guess); a recorded finding that they
   disagree strongly triggers kill criterion 2 below.

## Kill criteria

1. **Unusable fire rate.** If, after two tuning rounds, the governor still fires in the clean `rest`
   and `hands_busy` rounds on a configuration whose labelled phantom rate is within budget, its evidence
   floor and bound are wrong; the shipped default of `max_cancelled_per_hour` becomes `0` (count,
   never act) until a new ADR replaces the mechanism.
2. **The proxy does not track phantoms.** If the field test shows the cancelled-activation proxy is
   uninformative (quiet when labelled phantoms are frequent, loud when there are none), the
   proxy-driven governor is retired: the ledger and the report stay as a measurement, and the
   enforcement is replaced by something that does not depend on a proxy (for example a fixed
   conservative threshold set from the field-test phantom rate) in a new ADR.
3. **Release cannot be made one action.** If the integrator cannot offer a release that does not
   depend on the suspended source, a suspended switch is a lock-out, and the suspend step is removed
   (desensitize only) until it can.
4. **Nobody reports cancels.** If integrators never wire the cancel signal in practice, the budget is
   a no-op everywhere. The governor is then documented as measure-only and the budget key is removed
   rather than left to imply protection.

## Not decided here

- The numbers (budget, factor, multiples, dwell, timer, backoff, confidence level). Measure first.
- Whether the desensitize step should scale thresholds by a fixed factor or by the observed margin
  (spec, open question 3).
- Whether the budget should be per event kind rather than one budget for the whole source. The
  current design is one governor per ledger; per-kind governors are possible by giving each kind its
  own ledger.
- How the integrator should word and bind the release (that is the global hands-free surface,
  ADR-v2-148).
