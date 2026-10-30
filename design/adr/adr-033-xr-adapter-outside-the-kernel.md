# ADR-033 — An XR adapter that sits outside the kernel: rays in, `TargetSnapshot` out

**Status:** Proposed (2026-10-30)
**Decision required:** the owner decides; nothing here is accepted until he says so.
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-025-grounded-interaction-kernel]] (cites the four gates, which are written in the
[research note](../../docs/research/interaction-kernel.md), §"Decision rule for the next five
years"; OpenXR "belongs outside the kernel as an adapter"), [[adr-v2-013-glasses-desktop-bridge]],
[[adr-v2-011-semg-modality-router]], [[adr-v2-010-gaze-routed-dictation]],
[[adr-v2-151-grounded-target-resolution]], [[adr-v2-149-gaze-calibration-coordinate-space]],
[[adr-v2-150-evaluation-evidence-and-research-consent]],
[[adr-019-egress-inventory-and-escalation]],
[[adr-021-invest-in-error-cost]],
[AR/VR & wearable SoA note](../research/waves/03-ar-wearables.md).

Evidence labels: **[M]** measured in this worktree (`feat/xr-adapter`, on top of `main`
`4fda3403`, the `src/yazses/xr/` files still uncommitted) · **[R]** stated by a note in this
repository (the note's own sources were not re-verified here) · **[O]** engineering judgement ·
**[U]** not verified.

---

## Context

ADR-025 proposes a Grounded Interaction Kernel and says plainly what it does *not* approve:
"OpenXR or OpenUSD" (§"What this ADR explicitly does not decide"), and that a spatial
integration "should adapt into the kernel rather than define it" (alternative E). The research
note repeats the constraint: OpenXR support, "if ever added, belongs outside the kernel as an
adapter" (§9), and "the kernel itself should know nothing about those dependencies".

The SoA note [R] names the gap this adapter is aimed at: spatial OSes solved gaze-targeting of
windows, desktops route to focus; point-and-speak exists only in cloud AR assistants; and
there is no privacy-first local bridge from a wearable's gaze/hand input to a desktop. The same
note records the negative result that matters for scope: gaze+voice *sub*selection is disliked
(CHI'26, as summarised there), so voice should carry content and gaze/pinch the targeting.

This ADR records the decision to **build, and keep, the adapter as a separate, pure,
dormant package** — `src/yazses/xr/` — and to judge it by the four gates in the research note
that ADR-025 cites (they are not written in ADR-025 itself), instead of by how much of it
already exists. It exists as code now. Measured on 2026-10-30 [M]: `src/yazses/xr/` holds 15
modules plus `__init__.py` (4,000 lines in all, by `wc -l`), with 15 test files
`tests/test_xr_*.py` and one fuzz target; the passing-test count is given under Gate 3. These
counts describe that day's tree and will go stale; re-measure rather than copy them.

## What was built (the facts the gates are judged against)

Pure standard-library Python; the only imports from outside the package are from
`yazses.grounding.contracts`, in `xr/grounded.py` and `xr/session.py` [M].

| Concern | Module |
|---|---|
| Value contracts: `Vec3`, `Ray`, `RaySource` (head/eye/hand/controller), `XrSample`, `GestureEvent`, `Panel`, `PanelHit`; metres, radians, right-handed +Y up −Z forward; every constructor refuses NaN/inf | `types.py`, `geometry.py` |
| Untrusted companion → desktop frames: one bounded UTF-8 JSON object, all fields required, unknown keys, duplicates, NaN and oversize refused; for any frame content only `WireError` escapes (a bad `max_bytes` argument is a caller error, `ValueError`); `ClockMap` maps device time onto the desktop clock, with offset movement bounded in both directions by rate (up by `max_drift`; down from a `jitter_s` credit refilled at `max_drift`) and a clock step refused | `wire.py` |
| Engine/runtime convention conversion (OpenXR, Unity, Unreal, Android XR, visionOS) at the seam | `conventions.py` |
| Ray/panel intersection → `(u, v)` panel coordinates | `raycast.py` |
| One-Euro ray stabiliser, dwell read-out | `smoothing.py` |
| Spoken "this/that/here" → panel, from pointing history near word onset, weighted by held time; needs `min_samples` 3 and `min_coverage_s` 0.05 so a single stray sample never binds; returns BOUND / AMBIGUOUS / NONE, never guesses | `binding.py` |
| When a ray-chosen target must be confirmed (ambiguous, target changed mid-utterance, destructive, low confidence/margin) | `confirm.py` |
| Hand/controller gesture → hold-to-talk START/STOP/CANCEL edges, debounce, flicker grace, forced STOP on a stuck gesture, `max_future_s` bound on forged stamps | `ptt.py` |
| Bounded panel registry with expiry (ids restricted to `[A-Za-z0-9._:-]{1,128}`); sticky dictation pin that lapses if its panel is re-posed; spoken labels quoted and sanitised | `anchors.py` |
| Observation → `TargetSnapshot(source=TargetSource.XR_RAY)`; panel space `xr-panel:<id>` with a version the caller supplies | `grounded.py` |
| Bounded sample retention (refuses future stamps, pickling, copying), log redaction, persistence policy, empty `EGRESS` | `privacy.py` |
| Static device capability table (unknown is `None`, never `False`) | `devices.py` |
| `XrSession`: the pure composition of all of the above (wire → clock map → filters → retention / registry / PTT → binding → confirm → snapshot); no thread, no socket, no clock; the host calls `feed_frame` and `tick`, and `reset()`s after `COMPANION_MISBEHAVING` | `session.py` |
| Seeded synthetic trajectories and scenarios | `synth.py` |

**Not built, and the ADR does not pretend otherwise [M]:** nothing outside `xr/` imports it;
there is no `[xr]` config section (`grep -n -i xr src/yazses/config.py` finds only an unrelated
comment), so the package docstring's "off by default; nothing runs until `[xr] enabled`" is
today true only because nothing runs it at all. There is no CLI command, no daemon hook and no
companion app. The only edit outside the package is one line in
`src/yazses/grounding/contracts.py`: `TargetSource.XR_RAY = "xr_ray"`. And the
`src/yazses/bridge/` package that ADR-v2-013 describes contains a pure pairing state machine
and audio framing only; I found no socket transport and no consumer of `[bridge] listen_port`
other than a `doctor` message. The XR wire format is therefore not carried by anything yet, and
`XrSession`, which would consume it, has no caller.

## Decision (proposed)

1. Keep the XR adapter in its own package, `src/yazses/xr/`, dependency-free, observations in
   and a `TargetSnapshot` out. No OpenXR, Unity, Unreal, visionOS or Android XR SDK is ever
   imported by YazSes; a *companion app* on the device (none exists) would sample rays and send numbers.
2. The kernel-side contract gains exactly one name, `TargetSource.XR_RAY`, so provenance is
   not lost (see rejected alternative D). It gains no XR type and no XR behaviour.
3. Ship nothing user-visible until the gates below are met by evidence. Landing the package
   as dormant, tested library code is the whole of this proposal; wiring it into the daemon,
   adding `[xr]` config, a CLI surface or a companion is **not** part of it and needs its own
   decision after Gate 1 has real evidence.

## The four gates

ADR-025's rule: a futuristic integration is considered only if it passes all four. Judged
honestly:

### Gate 1 — Problem: *weakly met, arguably not met*

*Is a measured user/HCI problem being solved, rather than protocol novelty?*

No real-user XR problem has been measured by this project. No headset session, no headset
user, no recorded ray trace and no interview exists in the repository that I found [M]. The
evidence for the need is (a) the SoA note's gap list and its point-and-speak / modality-split
findings [R], which come from the literature, not from our users, and carry the note's own
caveat that its citations "have not been re-verified" against `research/verify_refs.py`; and
(b) synthetic scenarios from `synth.py`, which prove the code does what it was written to do
and say nothing about whether anyone needs it. The same note warns that voice is weak for
repetitive selection [R] — a risk to the premise, not support for it.

This gate is the reason the status is Proposed. **What would have to be true to proceed past
dormant code:** at least one real person with a headset or glasses who dictates to a desktop
and has a stated targeting problem ("it types into the wrong window"), observed or logged
under ADR-v2-150's consent rules; ideally a recorded (consented) ray+word trace that the
binder can be run against. Without that, the package is an option we hold, not a feature.

### Gate 2 — Boundary: *met*

*Can it enter through observations without weakening offline and safety invariants?*

- Observations in: `XrSample` / `GestureEvent` / `Panel` frames, validated at `wire.py`.
- Out: `to_target_snapshot` returns the kernel's existing `TargetSnapshot` with
  `source=TargetSource.XR_RAY`, a point in a named panel space (`xr-panel:<id>`, whose version is
  supplied by the caller per ADR-v2-149: `snapshot_series` takes a `versions` mapping
  defaulting to 0, and `XrSession` bumps a panel's version whenever its pose or size changes,
  so a moved panel invalidates an older snapshot), the sample's confidence
  **unchanged** (a hit adds none), and no point at all when the ray hit nothing — so the
  existing `TargetResolver` answers `UNRESOLVED` rather than being handed an invented
  location. A semantic source publishing in any other space makes the resolver abstain
  (`SEMANTIC_SPACE_MISMATCH`), per the module docstring [R-code; not re-run against a
  resolver here beyond the package's own tests].
- The kernel knows nothing about OpenXR: the grep for imports in `src/yazses/xr/` shows
  `math`, `json`, `re`, `random`, `unicodedata`, `collections`, `dataclasses`, `enum`,
  `typing`, the package's own modules and `yazses.grounding.contracts` only [M]. The one trace on the kernel side is an enum member's *name*.
- Caveat the gate does not hide: ADR-025's `src/yazses/interaction/` package does not exist
  (`ls src/yazses/interaction` fails [M]) and ADR-025 is itself still Proposed. The contract
  this adapter actually targets is `yazses.grounding` (ADR-v2-151). If ADR-025 is rejected or
  reshaped, the adapter's output contract is `TargetSnapshot`, which stands on its own.

### Gate 3 — Evaluation: *partly met; the part that matters is not*

*Can success and failure be measured, including abstention and error cost?*

Can be measured now, on synthetic data only: binder outcome (BOUND / AMBIGUOUS / NONE)
against the target the generator knows it aimed at; the confirm policy's firing rate via
`expected_prompt_rate`; PTT safety invariants (mic never left open, tested); wire-layer
robustness on hostile frames (tested; `tests/test_xr_*.py` → 954 passed (exit 0, 367 s, on 2026-10-30) [M]). The abstention path is
first-class: `AMBIGUOUS` and `NONE` are results, and `confirm.decide` holds on destructive,
ambiguous and changed targets (ADR-021).

Cannot be measured yet, and the synthetic numbers must not be quoted as if they were:
real tracker noise and dropout (the generator's Rayleigh noise model is our own invention);
real pointing-to-speech timing (so `lead_s`/`lag_s`); the real confirmation burden (the
"under 5 %" the tests assert is a property of the defaults *on invented data*, as
`confirm.expected_prompt_rate`'s docstring itself says); wrong-action rate, unsafe-action
rate, unnecessary-clarification rate, time-to-action and cost-weighted error — i.e. most of
ADR-025's required metric list — all need real sessions. **What would have to be true:** a
small consented capture protocol and a scoring script that reports ADR-025's metrics, written
before the daemon is wired, not after.

### Gate 4 — Complexity: *weakly met*

*Does it compose existing special cases rather than multiply independent paths?*

It composes in intent: its output feeds the existing resolver; `confirm.py` mirrors
`gaze.route.needs_confirm` (same destructive-and-ray-routed rule) and `binding.py` is the
spatial sibling of `gaze/deixis.py` [M, by reading]; `ptt.py` emits the same START/STOP edges
the keyboard hold path produces; `devices.py` names the `modality.router` presets rather than
inventing roles (and a test checks the names against the real table).

It **adds** more than it removes. It reuses none of that code — the package imports nothing
from `gaze/`, `modality/`, `bridge/` or `remote/`; the parallels are re-implementations that a
test or a review must keep in step [M]. 4,000 lines (measured 2026-10-30) and a second deixis binder, a second
confirm policy and a second hold state machine exist now, and no existing special case has
been deleted or simplified. That is exactly the failure mode ADR-025 names ("increases the
number of independent runtime paths rather than collapsing them"). **What would have to be
true:** when (if) wired, the XR binder and the gaze deixis path share a single confirm policy
and the XR PTT enters through the one daemon hold path with no second code path in
`core/daemon.py`; otherwise the right outcome is to reject this ADR and delete the package.

### Summary

| Gate | Verdict | Blocking? |
|---|---|---|
| 1 Problem | Weak: literature only, no measured user | **Yes** for wiring or release |
| 2 Boundary | Met | No |
| 3 Evaluation | Partial: synthetic only | **Yes** for any accuracy or burden claim |
| 4 Complexity | Weak: parallel re-implementations | **Yes** for wiring |

Two gates are met only weakly. The proposal is therefore *keep it dormant and bounded*, not
*build it out*.

## Alternatives considered and rejected

**A. Depend on OpenXR / a Unity or Unreal SDK inside the daemon.** Rejected. It would put a
large, platform-specific, frequently-changing runtime and a graphics/engine stack under a CPU
dictation daemon, break "a fresh install with no extras must import and run" (AGENTS.md rule
3), and contradict ADR-025 and the research note (§9) directly. A companion on the device that
sends already-sampled numbers keeps every SDK on the device side of the wire.

**B. Use a cloud AR assistant (voice+gaze deixis as a service).** Rejected. It sends gaze,
head and hand data and speech off the machine, which is what the project exists not to do
(AGENTS.md rule 1; ADR-011, ADR-019), and the SoA note's own gap is that this capability exists
only in cloud assistants [R]. Where it ever leaves the machine it would be a new SEND row.

**C. Build our own VR/AR application.** Rejected. It turns a dictation tool into a spatial-app
vendor, needs per-platform store, signing and review work no one has been funded or staffed
for, and the SoA note itself flags closed glasses hardware as the near-term constraint, with
phone-as-mic as the only path that works now [R]. The desktop side stays the product.

**D. Map XR rays onto `TargetSource.GAZE`.** Rejected. `TargetSource` is closed on purpose so
that provenance is not lost (its docstring). A headset ray is a different instrument from a
webcam gaze estimate: different noise, different coordinate space, different failure modes. A
policy that treats coarse webcam gaze more cautiously than a deliberate input would silently be
unable to tell them apart. The cost is a one-line diff to a reviewed enum, which is the review
the enum asks for.

## Privacy stance

Eye, head and hand rays are sensitive: a gaze trace can reveal attention and identity, and the
research note ("Open research questions", item 7) already asks which observations are safe to retain "for a few seconds"
[R; the phrase is in the note, not in ADR-025's text; the current `xr/privacy.py` docstring
attributes it to the note correctly]. The adapter's stance, and where it is
enforced:

- **Zero egress.** `xr/privacy.py` exports `EGRESS = frozenset()`, and a test scans the
  package's source by AST for network and process primitives, in the style of
  `tests/test_egress_inventory.py` [M]. The adapter sends nothing; it is designed only to receive numbers.
- **Bounded retention.** `SampleRetention` keeps at most 2.0 s and 240 samples by default,
  evicts oldest first, refuses a sample stamped more than `max_future_s` (5 s) ahead of the
  reference clock, refuses pickling and copying, and its `repr` shows no coordinates.
  **`XrSession` configures it to 8.0 s and 720 samples**, so the rays at a word's onset are
  still held when the (post-utterance) transcript arrives; see the open privacy decision under
  Consequences. `PanelRegistry` is bounded (64) and
  expires panels (30 s) so a departed surface stops receiving text. These are defaults, not
  validated values, and they bind only once something uses them: **nothing does yet.**
- **Redacted logs.** `redact_for_log` is the only intended log form of a sample (confidence
  bucketed, no direction).
- **Consent-only persistence.** `may_persist` returns true only for the literal
  `research_consent is True` under `RESEARCH_CONSENT_ONLY`; the default is never. This is the
  hook for ADR-v2-150's research-consent boundary; it does not replace that ADR's process.

**Tie to ADR-019.** The egress count must not change. Verified by running, not asserted:
`uv run python -m pytest tests/test_egress_inventory.py tests/test_xr_privacy.py` → 232 passed (exit 0)
in this worktree on 2026-10-30. The inventory test walks `SRC.rglob("*.py")` and so covered
`src/yazses/xr/`, which is on disk but untracked; ADR-019's table, the `FETCH`/`SEND` registries
and the "nine paths, two send" count were not edited [M]. That is the limit of the claim: the
scan guards our code, not a dependency, and it cannot see a *future* transport. The unresolved
piece is how the companion's frames reach the desktop. The bridge's transport does not exist
yet; when it does, it is either an inbound listener — which sits awkwardly with the stance,
quoted in ADR-032 from ADR-020 §2 and not re-read here [U], that a daemon holding a live
microphone does not listen on a port — or it rides the existing SSH tunnel, which already has
its ADR-019 SEND row. Either choice needs its own decision and, if it adds an outbound or
listening path, its own ADR-019 row first. This ADR does not make that choice.

## Consequences

**Good.** The spatial question is answered at the boundary instead of leaking into the kernel;
the dormant package costs a fresh install nothing (no dependency, no import at startup); the
failure direction is safe by construction (unknown stays unknown, ambiguity is a result, the
mic closes on a stuck gesture); hostile companion input is contained to one exception type.

**Accepted costs.**
- **Unwired.** No user can reach any of this. It is tested library code with no entry point.
  The project already carries a large inventory of designed-but-unreachable capabilities; this
  adds to it until wired.
- **Tuning defaults are unvalidated starting points, not findings.** One-Euro `min_cutoff_hz`
  1.0 / `beta` 0.007 / `d_cutoff_hz` 1.0 (the filter paper's starting values, per the module,
  not tuned for any tracker); binder `lead_s` 0.4 / `lag_s` 0.2 / `min_share` 0.6 /
  `min_confidence` 0.3 / `max_gap_s` 0.1 / `min_samples` 3 / `min_coverage_s` 0.05
  (`min_mass` defaults to 0 and is superseded by the last two); confirm `min_confidence`
  0.35 / `min_margin` 0.25; PTT `debounce_s` 0.05 / `release_grace_s` 0.12 / `max_hold_s` 120 /
  `min_confidence` 0.5 / `max_future_s` 5; `ClockMap` `max_jump_s` 0.5 / `max_drift` 0.001 /
  `jitter_s` 0.02; retention 2.0 s / 240 samples (`SampleRetention` default) and 8.0 s / 720
  (`XrSession`). None has met a real headset. No accuracy figure for the binder is claimed. A guard is judged on how rarely it fires
  (AGENTS.md rule 9), and the confirm firing rate on real sessions is unmeasured.
- **OPEN PRIVACY DECISION (owner): how long may pointing rays be held in memory?**
  `XrSession` retains rays for 8.0 s (720 samples). That is longer than `SampleRetention`'s own
  2.0 s default and longer than the "few seconds" framing of the research note (open question
  7). The reason is mechanical: a sentence is recognised after it ends, the binder needs the
  rays around the *word's onset*, and a long sentence outlasts 2 s. The rays are held in memory
  only, are never persisted without research consent, and never leave the machine, but the
  figure has been neither measured nor approved. Options: accept 8.0 s; shorten it and accept
  that long sentences bind less often (refusal, not a wrong target); or bind per word as
  the transcript streams so a shorter window suffices. Until the owner decides, 8.0 s / 720 is
  provisional, and nothing is wired, so no real person's rays are held yet.
- **Unverified device assumptions.** `conventions.py` treats Android XR and visionOS as
  OpenXR-aligned (right-handed, +Y up, −Z forward, metres) and says so as an *assumption*; I
  have not verified either against the vendors' documentation [U], and visionOS in particular
  is not an OpenXR platform, so the label describes a convention, not a runtime. `devices.py`
  sets only what the repo's research note states and leaves the rest `None`: eye tracking is
  unknown for every profile (phone companion included), the Android XR and Vision Pro rows set
  hand tracking `True` on OS-level quotes ("fuses gaze+hand+voice+visual"; "Vision Pro
  gaze-target + pinch") that say nothing about what an app can read, and both leave
  "desktop-readable mic stream" unknown. With these values `suggest_preset` returns `balanced`
  for those two and `voice-only` for the rest; no profile yields `hands-free`. The note's device claims are
  themselves from a 2026-07-02 snapshot with unverified citations [R].
- **Parallel logic to keep in step** with `gaze/` (Gate 4).
- **A closed-enum edit** in `grounding/contracts.py` that every downstream `match` on
  `TargetSource` must handle; this ADR did not audit consumers for exhaustiveness [U].

**Main failure mode.** The package grows (more gestures, more devices, more presets) ahead of
any user, becoming the umbrella ADR-025 warns about.

## What would make us reject this ADR

Reject or supersede, and delete `src/yazses/xr/`, if: (1) no real XR user or trace has
appeared by the time the maintainers next review the direction (a review point the owner sets), i.e. Gate
1 never moves; (2) wiring requires a second hold/confirm/deixis path in the daemon (Gate 4);
(3) measured binder accuracy on real traces does not beat "route to keyboard focus"; (4) the
confirmation burden on real sessions is high enough that users would dismiss it; (5) the only
workable transport requires a new listening or outbound path the owner will not accept.

## What this ADR does not decide

It does not approve: wiring into the daemon, an `[xr]` config section, a CLI surface, a
companion app, any transport for the wire format, any change to ADR-019's inventory, OpenUSD /
digital-twin entity identity (research-note §9 ("Spatial/digital-twin identity")), eye-tracker access beyond what a companion
sends, or the `PHYSICAL` consequence class. It does not mark ADR-025 accepted; if ADR-025 is
rejected, this adapter's output remains the existing `TargetSnapshot`.

## Order of work if the owner accepts it

1. Finish aligning source comments with the unwired state: the attribution comment in
   `xr/privacy.py` and the package docstring's "off by default" wording have been corrected, but
   the `EGRESS` comment in `xr/privacy.py` and the `xr/__init__.py` docstring still describe
   frames arriving "over the existing paired bridge" in the present tense, though that
   transport does not exist.
2. Decide the transport (see Privacy stance) and write the ADR-019 row if one is needed.
3. Write the consented-capture protocol and the scoring script (Gate 3) before any wiring.
4. Collect real traces; re-tune the starting defaults against them and publish the numbers.
5. Only then wire one path (head/eye ray + pinch hold + "this" binding) behind `[xr] enabled =
   false`, sharing the confirm policy with the gaze path (Gate 4).
