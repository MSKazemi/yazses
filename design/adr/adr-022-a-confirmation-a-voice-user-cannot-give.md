# ADR-022 — A confirmation a voice user cannot give

**Status:** Proposed (2026-08-16) · needs a decision on option A vs B before implementation
**Context links:** [[adr-v2-010-gaze-routing]] (`needs_confirm`), [[adr-021-invest-in-error-cost]]
(the one-release-phrase rule), [[adr-v2-065-command-safety]] (`ConfirmGate`),
`design/accessibility-and-throughput-spec.md` (Spec 1, whose baseline this is)

## Context

Spec 1's metric is *daemon-initiated states with no voice-only exit, target zero*. Counted
on 2026-08-16 the baseline is **2**. Of eleven notification sites in `core/daemon.py`, nine
pass `actions=False` and are informational; two wait for an answer and neither can be
answered by voice:

| State | Asks | Voice exit |
|---|---|---|
| Mic-change guard, `daemon.py::_notify_mic` | Re-calibrate / Pin this mic / Ignore | none |
| Destructive gaze deixis, `daemon.py::_confirm_deixis` | "Close it" / "Keep it" | none |

The second is the one that matters. Gaze targeting exists so that someone who cannot use a
pointer can choose a window by looking at it; its safety confirmation then requires a
pointer. The code says so plainly — *"confirm with the button"* — and where actionable
notifications are unsupported the action is dropped rather than offered another way.

That is problem A3 from the problem space (hands-free treated as a checkbox rather than a
working mode) occurring **inside the feature built to answer it**.

The pattern to copy is two files away. `ConfirmGate` holds a destructive dictated command
until a spoken *confirm*, and `checkdigit` deliberately reuses the same held slot and the
same release word so the user learns **one** phrase rather than one per guard.

## The decision that is actually needed

Not *whether* — that is settled by Spec 1. The open question is where the held state lives,
and it matters because the slot in question is the one holding `rm -rf`.

**Option A — extend `ConfirmGate.hold()` with an `on_confirm` callback.** One slot, one
release word, exactly as the existing rule intends. `confirm()` runs the callback and
returns the held text, which is empty for an action-only hold.

- *For:* preserves the single-slot invariant that the one-phrase rule depends on.
- *Against:* changes the semantics of the shared safety gate to serve an
  off-by-default experimental feature. A defect here releases a destructive command
  wrongly. The gate is currently pure and trivially testable; a callback makes it
  stateful in a way that can fail.

**Option B — a separate pending-deixis slot in the daemon, released by the same word,
checked strictly after `cmdsafety.pending`.**

- *For:* the safety gate is not touched at all.
- *Against:* two pending things can exist at once, which is the ambiguity the shared-slot
  design was built to avoid. "Confirm" would need a defined precedence, and a user with
  both pending has no way to see which one they just released.

**Recommendation: A, with the callback invoked *after* the held text is released and any
exception from it contained**, so a failing window action cannot leave the gate stuck. B
trades a rare ambiguity for a permanent second code path, and the one-phrase rule is the
property most worth protecting.

## Why this is Proposed and not Accepted

Neither path can be exercised where this was written: the gaze path needs X11, a webcam and
a calibration, and the guard it modifies is the one thing in the pipeline that must not
regress. Option A's blast radius reaches `cmdsafety` and `checkdigit`, both of which are
on by default, to fix a feature that is off by default.

The measurement is done and the options are written down; shipping a change to a safety
gate on the strength of unit tests alone is the step that needs a human who can run it.

## Consequences

The baseline moves from 2 to 1 when either option lands. The mic-change guard is the
remaining one, and it is easier — its three actions map to commands that already exist
(`recalibrate_mic`, `pin_mic` over IPC) and it holds nothing dangerous, so it can be done
without touching `ConfirmGate` under either option.
