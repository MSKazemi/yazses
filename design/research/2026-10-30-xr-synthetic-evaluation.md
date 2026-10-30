# Synthetic evaluation of XR deixis binding and the confirm policy, and the protocol for the real study

**Date:** 2026-10-30 (rev. 3: decision layer redesigned; section 0.2 is new and supersedes the confirm-policy numbers of rev. 2, which are kept as the "before") ·
**Status:** research input to the `yazses.xr` adapter (branch `feat/xr-adapter`); the protocol in
section 6 is a **draft, not approved or submitted** · **Author:** Mohsen Seyedkazemi Ardebili ·
**Builds on:** [ADR-021](../adr/adr-021-invest-in-error-cost.md),
[ADR-v2-150](../adr/adr-v2-150-evaluation-evidence-and-research-consent.md)

Evidence labels: **[M]** measured by the script in Appendix C on 2026-10-30 ·
**[S]** synthetic by construction (a property of the generator, not of any user) ·
**[O]** engineering judgement · **[U]** not verified.

---

## 0. Read this first

**Everything in sections 1-5 is `study_mode = "synthetic"` (ADR-v2-150).** The trajectories come
from `yazses.xr.synth`, which encodes the same assumptions the binder was written around. These
numbers therefore test **self-consistency and parameter sensitivity**. They say **nothing about how
often a real person's gaze, hand or controller would be bound correctly**, and no sentence in this
document, in a README, a changelog or a paper may be rewritten into a claim about real users.
Real-world accuracy is measured only by the protocol in section 6, which has not been run.

### Correction of the first draft of this document

The first draft reported that **19.3% of trials were bound to the wrong panel** with the defaults, and
called it the headline weakness. **That figure was a labelling artifact in the generator, not a
property of the binder.** `make_scenarios` then labelled the truth as the panel fixated *first* even
when the synthetic eyes had already moved to another panel by the word onset (the generator's default
lead range, 0.2-0.8 s, exceeds its dwell range, 0.3-0.9 s, in about a fifth of trials). The binder
answered with where the eyes were at the word; the label said where they had been; the difference was
scored as a binder error. The generator now separates the *intent* (`truth_panel_id`) from the
*measured gaze at the onset* (`gaze_panel_at_onset`) and has a `look_away_prob` knob (default 0), and
this re-run scores every trial against the intent and reports the look-away trials **as their own
stratum** so the artifact cannot hide inside a pooled number. The corrected results are in section 0.1.
The first draft's other numbers (prompt rates, bias, threshold sweeps) were also produced by the
old binder and are superseded.

### 0.1 What the corrected run shows (rev. 2: the policy BEFORE the redesign)

> Everything in 0.1 and in sections 5.1-5.6 was measured on the rev-2 confirm policy and rev-2 binder. Section 0.2 reproduces these numbers and then shows what the redesign changed. Where the two disagree about a default, 0.2 is current.

All figures [M][S]. "Silent wrong-bind" = the binder returned BOUND to a panel that is not the
intended one **and** `confirm.decide` showed no prompt (the wrong action would run unannounced).
Two conditions: `look_away_prob = 0` (the eyes are on the intended panel when the word is spoken) and
`look_away_prob = 0.2` (20% of trials: the eyes moved on before the word). In the second, the trials
are split by the noise-free generated gaze at the onset into an **aligned** stratum (identical to the
first condition, as it should be) and a **look-away** stratum. n = 500 per cell before stratifying
(about 100 look-away trials per cell; the look-away tables pool the four layouts, about 400 per row).

1. **When the eyes are still on the intended panel (the aligned stratum), the pipeline makes
   essentially no wrong-binds in this model.** With zero-mean noise of up to 2 degrees there were
   **0 wrong-binds in 64,000 scored cell-trials** (16 layout-lead combinations x 4 noise levels x
   smoothing off/on, 500 each, 8,000 distinct scenarios re-scored under the noise and smoothing
   settings), and per-cell 95% Wilson upper limits are 0.8% (n=500). The only wrong-binds in that
   condition were **4 of 80,000** at 4 degrees noise with smoothing on, abutting or adjacent panels,
   lead 0.0-0.2 s, and none was silent (all were prompted). This is the model's best case: the label
   is valid, the noise is Gaussian, there is no bias. It shows self-consistency, not accuracy.
2. **When the eyes have already moved on (the look-away stratum), the pipeline never recovers the
   intent and often binds silently to where the eyes are now.** At defaults, noise 1 degree, pooled
   over layouts, smoothing off: **correct-bound 0.0% in every lead range**, and silent wrong-binds of
   **37.0% [32.5-41.8]** (lead 0.0-0.2 s, n=405), **1.3%** (0.2-0.4 s, n=388; 97.4% of trials refused),
   **20.2% [16.7-24.2]** (0.2-0.8 s, n=436) and **71.7%** (0.6-1.2 s, n=420). A naive "ray at the
   word" resolver is wrong in 100% of these trials by construction, so the binder is better than that
   only when it refuses (prompts), not when it answers. The binder is behaving as designed (it
   weighs pointing around the onset); the point is that **the design cannot recover "the panel I
   meant" once the look is out of the window, and nothing downstream sees the problem**: the eyes are
   steady on the new panel at the onset and at the utterance end, the margin is large, so
   `confirm.decide` is silent.
3. **The prompt rate is far above ADR-021's "rarely fires" goal in this model, and in the aligned
   stratum every prompt is a false alarm.** Aligned, noise 1 degree, smoothing off: **39-52%** of
   trials prompted at lead 0.2-0.4 s (by layout), **73-77%** at 0.2-0.8 s and **98-99.6%** at
   0.6-1.2 s; 100% of them were `TARGET_CHANGED_DURING_UTTERANCE` (with that rule disabled the
   prompt rate is 0.0% in every one of those rows, because no ambiguity or low-confidence ever
   occurs). Since the aligned stratum has no wrong-binds to prevent, these prompts prevented nothing.
   Part of this is a generator artifact: when the fixation must outlast the lead it is stretched to
   `lead + 2/hz`, so the synthetic eyes leave the panel almost at once after the word and the
   0.3 s end check always sees a different panel. [U] How often real users look away within 0.3 s of
   a spoken demonstrative is exactly what the real study must measure. What this run does show is that
   the rule fires on *any* gaze departure, regardless of how confident the bind was.
4. **A constant tracker bias still produces confident wrong-binds, and prompts do not track
   them.** Abutting panels, 1 degree noise on top, look_away_prob 0, leads 0.0-0.4 s: silent
   wrong-binds of **8.6-11.6% at 5 degrees** (wrong-bound 12.2-15.2%), **1.0-2.2% at 3 degrees**,
   and 0 silent at 2 degrees (max 0.4% wrong). Panels with a 2.9 degree gap showed at most 0.4% at 5
   degrees; far and mixed layouts at most 0.2%. In the 5 degree abutting cells the prompt rate was
   7.6-43.0%: the cell that prompts least (7.6%, smoothing on, lead 0.0-0.2 s) has a silent
   wrong-bind rate of 11.0%, and the one that prompts most (43.0%, smoothing off, lead 0.2-0.4 s)
   still has 8.6%.
5. **One-Euro smoothing helps in two ways in this model, only one of which is denoising.**
   It cuts refusals at high noise (lead 0.2-0.4 s, 4 degrees: refused 31.0% to 2.4% in the far
   layout, 41.0% to 3.0% in mixed) and it cuts prompts in the aligned stratum (e.g. 45% to 9%, far
   layout, lead 0.2-0.4 s). It also raises the look-away stratum's correct-bound rate from 0% to
   34-45% at leads 0.0-0.8 s, **at zero noise too**, which is not denoising: the filter's lag keeps the
   ray on the earlier panel for a moment into the window. [O] Inferred, not isolated by a separate
   test. It does not reduce bias-induced errors (abutting, 5 degrees, silent 8.6-8.8% off versus
   11.0-11.6% on).
6. **No tested threshold removes the look-away problem without a cost, and the one that helps most
   matches the generator.** Adjacent layout, 1 degree, lead 0.2-0.8 s, look-away stratum
   (about 96 trials; wide intervals): `lead_s=0.8, lag_s=0.1` gives correct-bound 62.5%
   [52.5-71.5] and silent wrong 7.3% [3.6-14.3], against 0.0% and 21.9% for the defaults, with the
   aligned stratum unchanged (100% correct, 0 silent wrong). That configuration works because 0.8 s
   is the generator's maximum lead, which is circular. Raising `min_share` to 0.9 lowers look-away
   silent wrong to 12.5% but cuts aligned correct-bound to 54.2%; `min_margin` 0.6 only reaches 17.7%.
   **These sweeps show sensitivity; do not use them to choose defaults.**

**Net.** The corrected result is a *narrower* and different warning than the first draft's: the
binder is not noise-fragile in this model, but (a) it is blind to intent once the eyes have moved
on, (b) the confirm policy cannot see that case, (c) it is blind to constant bias, and (d) the
prompt policy's firing rate is untested and, against this generator, is high. Items (a)-(c) are
silent wrong-binds, the error ADR-021 prices highest; (d) is the opposite risk, a guard that fires
until users ignore it.


### 0.2 Rev. 3: the decision layer redesigned, before and after

All figures [M][S]: synthetic trajectories only, never evidence about real users. Evaluation scripts: Appendix F. Raw tables: Appendix E.

**Reproduction first.** The Appendix C script was re-run unchanged on 2026-10-30 (n = 500, seed 20261030). Its tables match Appendix B line for line (a diff of the two, ignoring blank lines, shows only two framing lines of the appendix). The three weaknesses are therefore real in this model: (1) aligned stratum, noise 1 degree, smoothing off: prompt rate **39.4-52.0%** at lead 0.2-0.4 s (by layout), 73-77% at 0.2-0.8 s, 98-99.6% at 0.6-1.2 s; (2) look-away stratum, pooled over layouts: correct-bound 0.0% and silent wrong **37.0%, 1.3%, 20.2%, 71.7%** at leads 0.0-0.2, 0.2-0.4, 0.2-0.8, 0.6-1.2 s; (3) 5 degree constant bias on abutting panels: silent wrong **8.6-11.6%**.

**What changed (confirm.py, binding.py, session.py).** The binder's verdict, margin and confidence are unchanged (a property test pins this). It now also reports checkable evidence, and `confirm.decide` holds on these signals, each a number compared with a published threshold:

| signal (reason) | measured by | default | silent when |
|---|---|---|---|
| ambiguous binding (`ambiguous_panels`) | top-2 share margin, as before | `min_share` 0.6 | unchanged |
| ray near a neighbour (`near_panel_edge`) | evidence-weighted angle from the winning rays to the nearest *other* panel | `error_budget_deg` 3.0 | panels farther apart than the budget, so it cannot fire there |
| gaze just arrived (`recent_panel_switch`) | seconds since the gaze last rested (>= 0.15 s) on another panel, in the 1.5 s before the word | `settle_s` 0.3 | no prior panel, or settled |
| gaze rested elsewhere (`target_changed_during_utterance`) | length of the run on a *different* panel at the utterance end | `min_departure_s` 0.5 | a glance, a return, or no departure |
| thin evidence (`low_confidence`) | top share, margin, confidence | 0.6 / 0.25 / 0.35 | unchanged |

The old rule "the panel under the ray nearest the onset differs from the panel nearest the end" is kept only as the fallback for a caller that supplies no duration. A prompt now carries `candidates`, the one or two panels to offer ("this one, or B?"), so the answer is one word.

**Cost model [O] (engineering judgement, not measured).** A prompt costs 1 (a one-word release); an abstain (keyboard-focus fallback) costs 2; a prompt that does not offer the intended panel costs one more; a silent wrong bind costs W, with W = 5, 10, 20 (find it, undo it, retype; larger when the destination is a terminal or chat). A prompt is the better error than a silent wrong bind exactly when P(wrong | the signal fired) x W > 1, that is, when more than 1/W of the held cases would have been wrong. The synthetic scenarios only supply P(wrong) under assumptions I chose.

**Setup of the final run.** 672 cells, n = 300 trials per cell, 3 seeds that were not used to choose any default (20270101-3; the sweeps that picked 3 degrees, 0.3 s and 0.5 s used seed 20261030, n = 150), 4 layouts, noise 1 degree. Rows below pool the 4 layouts and 3 seeds (3,600 trials per row). Besides the generator scenarios (`aligned`, `look`) there are three added scenarios built from the same primitives, because the generator has no history before the first fixation and no tail after the word: **transit** (the gaze comes from another panel, then the word follows the arrival; intent = the panel reached), **stay** (the gaze stays on the target until 1.0 s after the word) and **leave** (the gaze rests on another panel from 0.1 s to 1.0 s after the word; utterance end 1.0 s). Transit and leave are deliberately harsh for the two new rules: in both, the intent is the bound panel, so every prompt is a false alarm.

**Before / after, smoothing ON (the session default), percent of trials.** Silent wrong carries its 95% Wilson interval where it is not ~0.

| scenario | lead (s) | OLD silent-wrong | OLD prompt | NEW silent-wrong | NEW prompt | NEW abstain |
|---|---|---:|---:|---:|---:|---:|
| eyes on target | 0.2-0.4 | 0.0 | **19.8** | 0.0 | **1.2** | 0.0 |
| eyes on target | 0.2-0.8 | 0.0 | 39.3 | 0.0 | 1.1 | 0.0 |
| eyes on target | 0.6-1.2 | 0.0 | 60.4 | 0.0 | 1.2 | 0.0 |
| look-away | 0.0-0.2 | 0.0 | 84.2 | 0.0 | 53.6 | 14.6 |
| look-away | 0.2-0.4 | 0.0 | 77.7 | 0.0 | 42.6 | 11.1 |
| look-away | 0.2-0.8 | **5.3** [4.6-6.1] | 74.6 | **1.4** [1.0-1.8] | 50.2 | 9.4 |
| look-away | 0.6-1.2 | **41.8** [40.2-43.4] | 50.9 | **29.6** [28.1-31.1] | 53.9 | 3.9 |
| transit (intent = panel reached) | 0.0-0.2 | 6.6 [5.8-7.4] | 82.6 | **21.9** [20.5-23.2] | 72.2 | 5.9 |
| transit | 0.2-0.4 | 0.1 | 48.2 | 0.2 | 79.4 | 0.4 |
| transit | 0.2-0.8 | 0.0 | 17.2 | 0.1 | 30.9 | 1.0 |
| transit | 0.6-1.2 | 0.0 | 0.0 | 0.0 | 1.8 | 0.0 |
| stay on target to +1.0 s | any | 0.0 | 0.0 | 0.0 | 1.2-1.4 | 0.0 |
| leave to another panel | any | 0.0 | 100.0 | 0.0 | **85-86** | 0.0 |

Smoothing OFF (the rev-2 headline setting), pooled over layouts: eyes-on-target prompts 44.3 -> 1.2% (lead 0.2-0.4), 74.7 -> 1.2% (0.2-0.8), 99.1 -> 1.3% (0.6-1.2); look-away silent wrong 28.5 -> 28.4% (0.0-0.2, unchanged: the unsmoothed ray is simply on the new panel), 0.4 -> 0.3%, 19.9 -> 5.3% (0.2-0.8), 75.2 -> 48.4% (0.6-1.2).

**Constant bias (5 degrees, abutting panels, 1 degree noise, eyes on target), smoothing ON:** silent wrong **12.4 -> 0.0%** (lead 0.0-0.2) and **10.7 -> 0.0%** (0.2-0.4); prompts 8.7 -> 32.8% and 28.7 -> 34.1%. At 3 degrees: silent wrong 2.0 -> 0.0% and 1.4 -> 0.0%, prompts about 21%. With no bias the abutting layout prompts 4.8-4.9% (old policy 6-32%); the adjacent and far layouts 0.0%. The rule protects against errors inside the budget: at 5 degrees on the adjacent layout (panels 2.9 degrees apart) 0.6% silent wrong remains at lead 0.0-0.2 s, and it is not zero in general once the error exceeds the budget.

**Accepted prompt rate on the eyes-on-target scenario: 1.2% pooled (0.0% on the far, adjacent and mixed layouts; about 5% on the zero-gap abutting layout), 1.2-1.4% in the stay scenario.** I accept it because (a) every one of those prompts is a `near_panel_edge` hold on abutting panels, where a 3 degree tracker error can flip the choice, so each is specific and checkable; (b) the price is one word in about twenty utterances on the layout that needs it, against a silent wrong rate the old policy let through at 8.6-12.4% under a 5 degree bias; (c) layouts whose panels are farther apart than the budget pay nothing. The number is a property of the 3 degree budget and of the generator's aim points (kept 0.15 of a width away from an edge); real users who dwell near seams will see more.

**Where the redesign does not win, stated plainly.**

1. **Look-away with a settled gaze is still bound silently.** At lead 0.6-1.2 s, 29.6% of look-away trials (smoothing on; 48.4% off) are bound to where the eyes are now with no prompt, because the user had already looked at the new panel for more than 0.3 s. No signal available to a gaze-only decision separates "I looked at A, then B, and I mean A" from "I moved from A to B and I mean B" once the gaze has settled. `settle_s` moves along that trade-off and nothing more: raising it to 0.5 s cuts look-away silent wrong to 4.4% pooled and raises transit prompts from 37% to 54% (Appendix E sweep). The synthetic data cannot say which end real users want; the real study (section 6) must measure how often the intent is the *previous* panel.
2. **Pooled cost does not clearly improve in the look-away / transit mix.** With W = 10 the mixed cost at q = 0.2 look-away is 0.70 (old) versus 0.68 (new), a tie; at q = 0.05 the old policy is cheaper (0.37 vs 0.49); at q = 0.5 the new one is (1.36 vs 1.08); at W = 20, q = 0.2 it is 1.02 vs 0.90. For those two rules the redesign converts silent wrong binds into prompts at about break-even cost when W is 10, and pays when a wrong bind is expensive (W >= 20) or look-away is common. Its large gain is the removal of the false alarms in the aligned scenarios, not the look-away rules.
3. **A regression: speech before the gaze arrives.** Transit at lead 0.0-0.2 s (the word is spoken as the gaze is still leaving the previous panel), smoothing on: silent wrong rose from **6.6% to 21.9%**. The old instantaneous "panel changed after the onset" comparison prompted on 82.6% of these trials; a glance shorter than `min_departure_s` no longer does. The same event is the `leave` scenario with a different intent, which the old rule also prompted on (100%) and the new rule prompts on 85-86%. Gaze alone cannot tell them apart.
4. **The `leave` prompt rate is the largest unknown and it is high.** If users habitually rest their gaze on another panel for 0.5 s or more before the utterance ends, 85-86% of those utterances prompt (old: 100%). `min_departure_s` is the one knob (0.8 s gives 5.7% in this scenario only because the tail I built has runs of about 0.8-0.9 s; that is a property of the tail, not a recommendation). If the real study shows this behaviour is common the rule should be raised or removed: rule 9 says a guard that fires on routine behaviour is worse than none.
5. **Abstain is unchanged.** The look-away rows abstain 3.9-14.6% (smoothing on) before and after: the binder returns NONE (fall back to keyboard focus) when the window holds no usable evidence, and the redesign does not touch that.
6. **Cost.** Rival angles add about 0.17 s per resolution at 64 panels with 54 in-window samples on this laptop under load (the existing ray cast, 0.9 s for 711 rays x 64 panels, dominates); at a handful of panels it is milliseconds. [M, one machine, contended]

**Not tuned to the generator, and what that does and does not show.** The rules use physical quantities (angle to a neighbour, seconds since leaving a panel, seconds of rested gaze), and the defaults were fixed on one seed before the held-out seeds were run. But all scenarios were written by me, so agreement with them is still self-consistency. The hand-built adversarial cases in `tests/test_xr_confirm.py`, `test_xr_binding.py` and `test_xr_session.py` (threshold boundaries, a glance that returns, a gap in a run, a ray exactly on a seam, unmeasured evidence) and the hypothesis properties (more evidence never lowers a hold; a stricter policy never removes one; no silent bind when the top share is under the floor; the rival and prior-panel evidence never change the verdict; order invariance) do not depend on the generator.

---

## 1. What was run, exactly

```sh
cd /home/mohsen/scratch/repos/yazses-xr          # branch feat/xr-adapter, base 4fda3403
PYTHONPATH=src python3 xr_eval.py --n 500 --seed 20261030 --workers 12 --out <dir>
```

- **n = 500 per cell** (the first draft used 1,000; reduced so the larger grid fits in about 12
  minutes). Wall time 11 min 39 s on 12 cores. 320 grid cells (2 look-away settings x 4 layouts x 5
  noise levels x 4 lead ranges x smoothing off/on) + 80 threshold-sensitivity cells + 80 bias cells
  = 480 cells.
- Script: Appendix C (304 lines; kept outside the repo, in the session scratchpad, as `xr_eval.py`;
  sha256 prefix `2b909abbc0e1d04c`). Python 3.12.3, standard library only.
- Seed: base `20261030`. Cell seed = base + 1000 x layout index + lead index, so **every noise level,
  both smoothing settings and (for the grid) both look-away settings of a (layout, lead) group share
  the generator seed**; `make_scenarios` is called twice per cell, once with the cell's noise and once
  with noise 0 and the same seed, to classify each trial into the aligned or look-away stratum by the
  noise-free `gaze_panel_at_onset`.
- Code under test: the **uncommitted** `src/yazses/xr/` of the worktree (all modules last modified
  before 00:47 local time, before the run began). sha256 prefixes: `synth.py 05acd45c7772`,
  `binding.py b6ac57444932`, `confirm.py 45dd2ff4c374`, `raycast.py 8d19eaa02c82`,
  `smoothing.py 5d5bf449a193`, `geometry.py e1e7fcb98ac9`, `types.py 175c5c478652`. A changed module
  may change the numbers; re-run rather than reuse.
- **Cells are not independent.** The 5 noise levels and 2 smoothing settings re-score the same
  scenarios of a (layout, lead) group, so never pool cells into one Wilson interval. The intervals in
  the tables are per row; the look-away headline rows pool *layouts* only (different seeds).

## 2. What the synthetic model assumes, and how it is optimistic

The scenario generator (`synth.make_scenarios`) draws, per trial: a target panel (the intent) and, if
more than one panel exists, a distractor; the gaze lands on the target at `t0` in 0.2-1.0 s; the word
onset is `t0 + lead`. By default the fixation is stretched to outlast the lead and the eyes drift to
the distractor right after it. In a look-away trial (probability `look_away_prob`) the fixation is
at most 0.9 s and at least 0.1 s, a 50 ms eased saccade follows, and the eyes are on a different
panel (or off to the side of a lone panel) at the onset; the lead of such a trial is lifted to about
0.2 s so that is physically possible. Aim points stay within 15-85% of a panel's width and height.
Samples are at 90 Hz with confidence fixed at 1.0. Ways this is **optimistic or simply different
from reality**:

1. **Noise is zero-mean Gaussian per sample, independent across samples** (Rayleigh magnitude, random
   azimuth). Real trackers have **systematic bias** (a per-person, per-session offset), correlated
   error, and error that grows toward the periphery. Section 5.4 adds a constant yaw bias as a
   first probe; it is a single shape, not a model of any device.
2. **No calibration drift** over a session, no headset slippage, no re-calibration events.
3. **No saccadic suppression, blinks, microsaccades or smooth pursuit.** The saccade is a clean 50 ms
   arc; there are no dropouts (the `synth.dropout` generator exists but was not used) and no
   confidence variation (so the confirm rule's `LOW_CONFIDENCE` fires essentially only through margin).
4. **Perfect intent.** The target is the panel the user means, by design; the user never means a
   panel they have not looked at, never points at an occluded or off-panel location, and never
   changes their mind. In the aligned condition the eyes are on the intended panel at the word every
   time, which real speakers need not do.
5. **The eyes leave right after the word.** In the default (aligned) scenario the gaze moves to the
   distractor within a few frames after the onset when the fixation was stretched to the lead. This
   drives the prompt rates in section 5.2. Real users scan, re-fixate and read the destination.
6. **Flat, front-facing panels at one distance (2 m)**, equal size, in a row. No depth occlusion
   (a nearer panel hiding part of a farther one), no head motion, no oblique panels, no world-locked
   versus head-locked difference. "Overlapping in angular terms" is covered only by the abutting
   layout, not by true depth overlap.
7. **Uniform lead** on invented intervals. Real speech-gaze lag has a different shape and depends on
   the task [U]. The look-away fraction (0.2) is also invented; the pooled rate depends on it, which
   is why strata are reported.
8. **Word onset known exactly.** In use it comes from recogniser word timestamps with their own error.
9. **Hand and controller rays** (steadier, but with different failure modes) are not modelled; only
   the `EYE` source is used.
10. **The same author wrote the generator, the binder and this harness.** Agreement between them is
    expected; it is not independent confirmation. The first draft's 19.3% is a concrete example of
    a harness disagreement that looked like a finding.

## 3. Method

**Pipeline per trial** (the real modules, unmodified; mirrors `XrSession.resolve_demonstrative`):
`synth.make_scenarios` -> optional `smoothing.RayFilter` (library defaults, one fresh filter per trial)
-> `raycast.nearest_hit` per sample -> `binding.PanelObservation` -> `binding.bind_demonstrative`
(defaults: `lead_s=0.4`, `lag_s=0.2`, `min_share=0.6`, `min_confidence=0.3`, `max_gap_s=0.1`,
`min_samples=3`, `min_coverage_s=0.05`) -> `confirm.decide` with the binder's `margin` and
`confidence` (defaults: `min_confidence=0.35`, `min_margin=0.25`, `destructive=False`).

**Choices of mine, not in the modules** (they move the prompt rate): the utterance end is the word
onset + 0.3 s; `panel_at_onset` and `panel_at_end` are the panel under the sample nearest the onset
and the end (as in `XrSession._panel_near`), unknown if no sample lies within 0.25 s. To keep the
run affordable only samples within 1.0 s before to 0.6 s after the onset are passed on after
smoothing (the binder window is at most 0.8 s before and 0.4 s after in the sweeps); a check on 600
trials over all four layouts gave identical counts with and without that cut.

**Layouts** (panels 0.6 m x 0.4 m, 2 m ahead, eye height 1.6 m; angles from the eye):

| name | panels | edge gap | angular gap |
|---|---|---|---|
| far | 3 in a row | 1.0 m | ~27 degrees |
| adjacent | 3 in a row | 0.1 m | ~2.9 degrees |
| abutting | 3 in a row | 0 | touching |
| mixed | A, B adjacent (0.1 m gap) plus C, D about 1.05 m beyond their outer edges | as stated | mixed |

**Grid.** noise (mean angular error) 0, 0.5, 1, 2, 4 degrees (converted to radians) x lead ranges
0.0-0.2, 0.2-0.4, 0.2-0.8 (the generator default), 0.6-1.2 s x smoothing off/on x 4 layouts x
`look_away_prob` 0 and 0.2. **Threshold sensitivity:** adjacent and mixed layouts, noise 1 and 2
degrees, lead 0.2-0.8, smoothing off, `look_away_prob` 0.2, one parameter varied at a time (80
cells). **Bias:** every ray yawed by 0-5 degrees toward +x with 1 degree Gaussian noise on top,
leads 0.0-0.2 and 0.2-0.4, smoothing off/on, `look_away_prob` 0 (80 cells).

**Metrics per cell** (95% Wilson interval), always against `truth_panel_id`: *correct-bound*,
**WRONG-bound** (BOUND and not the intent), **silent-wrong** (wrong-bound and no prompt),
*ambiguous*, *none*, *prompt* (`confirm=True`; `NO_TARGET` is silent), *prompt w/o target-changed*
(a diagnostic: the prompt that would remain if the end-of-utterance panel were unknown), and *naive
ray-at-word wrong* (the panel under the last raw ray at or before the onset is not the intent).
`destructive=True` is not swept: it prompts every bound action by design.

---

## 4. Results

**Headline A. look_away_prob = 0 (eyes still on the intended panel): lead-time sweep at 1 degree mean noise.** Percent of trials, silent-wrong with 95% Wilson interval; n=500 per row.

| layout | lead (s) | OFF: WRONG-bound | OFF: silent-wrong [CI] | OFF: correct-bound | OFF: prompt | OFF: prompt w/o target-changed | ON: WRONG-bound | ON: silent-wrong [CI] | ON: correct-bound | ON: prompt | ON: prompt w/o target-changed |
|---|---|---:|---|---:|---:|---:|---:|---|---:|---:|---:|
| far(gap1.0m) | 0.0-0.2 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 8.2 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 99.8 | 0.6 | 0.0 |
| far(gap1.0m) | 0.2-0.4 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 44.8 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 8.8 | 0.0 |
| far(gap1.0m) | 0.2-0.8 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 74.8 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 17.4 | 0.0 |
| far(gap1.0m) | 0.6-1.2 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 98.0 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 23.4 | 0.0 |
| adjacent(gap0.1m) | 0.0-0.2 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 14.6 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 3.2 | 0.0 |
| adjacent(gap0.1m) | 0.2-0.4 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 39.4 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 25.6 | 0.0 |
| adjacent(gap0.1m) | 0.2-0.8 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 75.6 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 50.4 | 0.0 |
| adjacent(gap0.1m) | 0.6-1.2 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 99.4 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 86.6 | 0.0 |
| abutting(gap0m) | 0.0-0.2 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 14.0 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 4.2 | 0.0 |
| abutting(gap0m) | 0.2-0.4 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 52.0 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 31.8 | 0.0 |
| abutting(gap0m) | 0.2-0.8 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 77.4 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 65.4 | 0.0 |
| abutting(gap0m) | 0.6-1.2 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 99.6 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 96.2 | 0.0 |
| mixed(2adj+2far) | 0.0-0.2 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 9.8 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 1.8 | 0.0 |
| mixed(2adj+2far) | 0.2-0.4 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 47.6 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 13.6 | 0.0 |
| mixed(2adj+2far) | 0.2-0.8 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 73.2 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 25.8 | 0.0 |
| mixed(2adj+2far) | 0.6-1.2 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 97.8 | 0.0 | 0.0 | 0.0 [0.0-0.8] | 100.0 | 38.0 | 0.0 |

**Headline B. look_away_prob = 0: noise sweep at lead 0.2-0.4 s.** Refused = ambiguous + none.

| layout | noise (deg) | OFF: silent-wrong [CI] | OFF: correct-bound | OFF: refused | OFF: prompt | ON: silent-wrong [CI] | ON: correct-bound | ON: refused | ON: prompt |
|---|---:|---|---:|---:|---:|---|---:|---:|---:|
| far(gap1.0m) | 0 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 45.4 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 8.8 |
| far(gap1.0m) | 0.5 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 45.2 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 8.8 |
| far(gap1.0m) | 1 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 44.8 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 8.8 |
| far(gap1.0m) | 2 | 0.0 [0.0-0.8] | 98.2 | 1.8 | 38.2 | 0.0 [0.0-0.8] | 99.8 | 0.2 | 8.8 |
| far(gap1.0m) | 4 | 0.0 [0.0-0.8] | 69.0 | 31.0 | 30.4 | 0.0 [0.0-0.8] | 97.6 | 2.4 | 9.0 |
| adjacent(gap0.1m) | 0 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 39.6 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 25.6 |
| adjacent(gap0.1m) | 0.5 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 39.4 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 25.6 |
| adjacent(gap0.1m) | 1 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 39.4 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 25.6 |
| adjacent(gap0.1m) | 2 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 36.2 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 25.2 |
| adjacent(gap0.1m) | 4 | 0.0 [0.0-0.8] | 89.4 | 10.6 | 30.8 | 0.0 [0.0-0.8] | 98.6 | 1.4 | 25.4 |
| abutting(gap0m) | 0 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 52.4 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 31.2 |
| abutting(gap0m) | 0.5 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 52.6 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 31.4 |
| abutting(gap0m) | 1 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 52.0 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 31.8 |
| abutting(gap0m) | 2 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 49.0 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 31.4 |
| abutting(gap0m) | 4 | 0.0 [0.0-0.8] | 89.6 | 10.4 | 42.4 | 0.0 [0.0-0.8] | 98.4 | 1.6 | 30.6 |
| mixed(2adj+2far) | 0 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 47.8 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 13.6 |
| mixed(2adj+2far) | 0.5 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 48.0 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 13.6 |
| mixed(2adj+2far) | 1 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 47.6 | 0.0 [0.0-0.8] | 100.0 | 0.0 | 13.6 |
| mixed(2adj+2far) | 2 | 0.0 [0.0-0.8] | 97.2 | 2.8 | 42.6 | 0.0 [0.0-0.8] | 99.8 | 0.2 | 13.6 |
| mixed(2adj+2far) | 4 | 0.0 [0.0-0.8] | 59.0 | 41.0 | 32.4 | 0.0 [0.0-0.8] | 97.0 | 3.0 | 13.2 |

**Headline C. look_away_prob = 0.2, LOOK-AWAY stratum only (the eyes had moved on before the word), pooled over the four layouts** (layouts use different seeds, so these trials are independent across layouts; n is the pooled count; noise 1 degree). Scored against the intended panel. 'naive' = answering with the panel under the last ray at the word.

| lead (s) | smoothing | n | correct-bound [CI] | WRONG-bound [CI] | silent-wrong [CI] | refused (ambig.+none) | prompt | naive ray-at-word wrong |
|---|---|---:|---|---|---|---:|---:|---:|
| 0.0-0.2 | OFF | 405 | 0.0 [0.0-0.9] | 46.2 [41.4-51.0] | 37.0 [32.5-41.8] | 53.8 | 63.0 | 100.0 |
| 0.0-0.2 | ON | 405 | 34.3 [29.9-39.1] | 0.0 [0.0-0.9] | 0.0 [0.0-0.9] | 65.7 | 87.4 | 100.0 |
| 0.2-0.4 | OFF | 388 | 0.0 [0.0-1.0] | 2.6 [1.4-4.7] | 1.3 [0.6-3.0] | 97.4 | 98.7 | 100.0 |
| 0.2-0.4 | ON | 388 | 45.4 [40.5-50.3] | 0.0 [0.0-1.0] | 0.0 [0.0-1.0] | 54.6 | 74.0 | 100.0 |
| 0.2-0.8 | OFF | 436 | 0.0 [0.0-0.9] | 21.1 [17.5-25.2] | 20.2 [16.7-24.2] | 78.9 | 79.8 | 100.0 |
| 0.2-0.8 | ON | 436 | 39.4 [35.0-44.1] | 6.7 [4.7-9.4] | 6.4 [4.5-9.1] | 53.9 | 77.3 | 100.0 |
| 0.6-1.2 | OFF | 420 | 0.0 [0.0-0.9] | 71.9 [67.4-76.0] | 71.7 [67.2-75.8] | 28.1 | 28.3 | 100.0 |
| 0.6-1.2 | ON | 420 | 14.5 [11.5-18.2] | 41.7 [37.0-46.4] | 40.0 [35.4-44.8] | 43.8 | 53.3 | 100.0 |

**Headline D. same look-away stratum, by noise (lead 0.2-0.8 s, pooled over layouts).**

| noise (deg) | smoothing | n | correct-bound | WRONG-bound [CI] | silent-wrong [CI] | refused | prompt |
|---:|---|---:|---:|---|---|---:|---:|
| 0 | OFF | 436 | 0.0 | 21.8 [18.2-25.9] | 20.4 [16.9-24.4] | 78.2 | 79.6 |
| 0 | ON | 436 | 39.9 | 6.7 [4.7-9.4] | 6.4 [4.5-9.1] | 53.4 | 76.8 |
| 0.5 | OFF | 436 | 0.0 | 21.8 [18.2-25.9] | 20.4 [16.9-24.4] | 78.2 | 79.6 |
| 0.5 | ON | 436 | 39.9 | 6.7 [4.7-9.4] | 6.4 [4.5-9.1] | 53.4 | 76.6 |
| 1 | OFF | 436 | 0.0 | 21.1 [17.5-25.2] | 20.2 [16.7-24.2] | 78.9 | 79.8 |
| 1 | ON | 436 | 39.4 | 6.7 [4.7-9.4] | 6.4 [4.5-9.1] | 53.9 | 77.3 |
| 2 | OFF | 436 | 0.0 | 19.3 [15.8-23.2] | 18.3 [15.0-22.3] | 80.7 | 81.7 |
| 2 | ON | 436 | 39.0 | 6.2 [4.3-8.9] | 6.0 [4.1-8.6] | 54.8 | 77.5 |
| 4 | OFF | 436 | 0.2 | 10.6 [8.0-13.8] | 10.1 [7.6-13.3] | 89.2 | 89.4 |
| 4 | ON | 436 | 37.4 | 6.4 [4.5-9.1] | 6.0 [4.1-8.6] | 56.2 | 76.6 |

**Headline E. look_away_prob = 0.2, ALIGNED stratum (the eyes are on the intended panel), pooled over layouts, noise 1 degree.** Should agree with Headline A.

| lead (s) | smoothing | n | WRONG-bound [CI] | silent-wrong | correct-bound | prompt |
|---|---|---:|---|---:|---:|---:|
| 0.0-0.2 | OFF | 1595 | 0.0 [0.0-0.2] | 0.0 | 100.0 | 11.7 |
| 0.0-0.2 | ON | 1595 | 0.0 [0.0-0.2] | 0.0 | 99.9 | 2.5 |
| 0.2-0.4 | OFF | 1612 | 0.0 [0.0-0.2] | 0.0 | 100.0 | 46.6 |
| 0.2-0.4 | ON | 1612 | 0.0 [0.0-0.2] | 0.0 | 100.0 | 20.5 |
| 0.2-0.8 | OFF | 1564 | 0.0 [0.0-0.2] | 0.0 | 100.0 | 76.2 |
| 0.2-0.8 | ON | 1564 | 0.0 [0.0-0.2] | 0.0 | 100.0 | 39.8 |
| 0.6-1.2 | OFF | 1580 | 0.0 [0.0-0.2] | 0.0 | 100.0 | 98.5 |
| 0.6-1.2 | ON | 1580 | 0.0 [0.0-0.2] | 0.0 | 100.0 | 61.5 |

How to read them: lead 0.0-0.4 s is the model's best case; 0.2-0.8 s is the generator's own default
range; 0.6-1.2 s is deliberately stressful. A "0.0 [0.0-0.8]" row means 0 events in 500 trials, not
zero risk. Headlines C and D pool the four layouts (independent seeds); the per-layout look-away
tables in Appendix B have about 100 trials per row and very wide intervals.

Full tables (all 480 cells, prompt reasons, threshold sensitivity and bias) are in Appendix B.

## 5. What the numbers say

> Sections 5.1-5.6 discuss the rev-2 policy. Section 0.2 supersedes them wherever they describe prompt rates, the bias result or the threshold sweep for the shipped defaults.

### 5.1 The label artifact, and what is left once it is removed

The first draft's 19.3% wrong-bind rate was the look-away stratum scored as if it were the
whole population. With the generator corrected, the aligned stratum shows no wrong-binds at noise up to
2 degrees, and the look-away stratum shows a *different* failure: not a mislabel but a real
limitation of any "weigh the pointing around the word" binder. In a look-away trial the user
looked at the intended panel and then moved on before speaking. Two readings, which this data cannot
separate:

- **(a) The intent is the earlier panel.** The user means it and the binder, which weighs the window
  around the onset with a triangular weight peaking at the word, returns the panel under the eyes now
  (or refuses). Then the binder has a built-in blind spot, and a longer look-back (or a
  dwell-recency rule, or an explicit target highlight before the text lands) would be needed.
- **(b) The intent is where the eyes are now.** A person who has since looked at another panel may
  mean *that* one, and the binder is right and the label is wrong.

The real study cannot afford to guess, so it asks the participant after every trial which panel they
*meant* (section 6.4) and scores the look-away trials separately.

### 5.2 Prompt rate

Aligned stratum, noise 1 degree, smoothing off: 39-52% of trials prompted at lead 0.2-0.4 s, 73-77% at
0.2-0.8 s, 98-99.6% at 0.6-1.2 s; with smoothing on, 9-32%, 17-65%, 23-96% (by layout). All of these
are `TARGET_CHANGED_DURING_UTTERANCE`; with that reason disabled the prompt rate was 0.0% in every
aligned row at 1 degree noise (Headline A). With no wrong-binds in that stratum, none of these prompts
prevented anything. This is mostly the generator: in the aligned scenario the eyes are sent to the
distractor right after the word, so a 0.3 s end check cannot fail to see a change. The finding is not
"the real prompt rate is ~45%"; it is that the **rule that governs most prompts is untested against
any real gaze behaviour and, against this plausible one, would violate ADR-021's own test**. Its
design (any change of panel under the eyes within the utterance) also prompts on a correct, confident
bind. In the look-away stratum the same rule is the only thing standing between the user and a wrong
action, and it does not stand there often enough: prompt rates of 63% (lead 0.0-0.2 s) and 80%
(0.2-0.8 s) left silent wrong rates of 37% and 20%.

### 5.3 One-Euro smoothing on versus off

Paired, same trials. At lead 0.2-0.4 s and 4 degrees noise, smoothing cut refusals (ambiguous+none)
from 31.0% to 2.4% (far), 10.6% to 1.4% (adjacent), 10.4% to 1.6% (abutting) and 41.0% to 3.0%
(mixed), and raised correct-bound from 69.0% to 97.6% (far): the denoising effect the filter was
built for. In the look-away stratum it moves correct-bound from 0% to 34-45% and cuts silent
wrong-binds (e.g. lead 0.2-0.8 s: 20.2% to 6.4%), but the same cut appears at **0 degrees**, so it is
not denoising: it is lag (a 1 Hz minimum cutoff gives a time constant of roughly 0.16 s) keeping the
smoothed ray on the earlier panel into the window. [O] That mechanism is inferred, not isolated. At
long leads the effect is gone: lead 0.6-1.2 s ON still has silent wrong-binds of 40.0% [35.4-44.8].
The filter does not help constant bias (section 5.4). Treat smoothing as helping with jitter and as
untested for everything else.

### 5.4 Systematic bias

Zero-mean noise cannot move the *mean* ray off a panel, so the binder degrades by refusing; a constant
offset changes the mean and does the opposite. The effect appears only when the bias exceeds the
distance from the aim point to the next panel. Abutting panels: silent wrong-binds of 1.0-2.2% at 3
degrees and **8.6-11.6% at 5 degrees** (wrong-bound up to 15.2%), 0 silent at 2 degrees. A 2.9 degree
gap absorbed it up to 3 degrees (0 wrong) and reached at most 0.4% at 5 degrees; far and mixed
layouts at most 0.2%. The binder's `margin` and the confirm policy are blind to a consistent shift
by construction (the share on the wrong panel is near 100%); in the 5 degree abutting cells the prompt rate (7.6-43.0%) did not follow the
silent wrong-bind rate. [O] The design implication is not a threshold: it is a calibration-quality
input to the confirm decision, or a minimum gap between panels, or an explicit target highlight
before the text is placed.

### 5.5 Threshold sensitivity

Adjacent layout, 1 degree, lead 0.2-0.8 s, `look_away_prob` 0.2, smoothing off (the full grid is in
Appendix B). In the **aligned** stratum every `lead_s`/`lag_s`/`min_share`/`min_margin` variant
stayed at 0 silent wrong-binds; the cost is on correct-bound (e.g. `lead_s=0.2`, `lag_s=0.4`: 54.2%;
`min_share=0.9`: 54.2%) and on prompts. In the **look-away** stratum silent-wrong was 21.9% at
defaults, 99.0% at `lead_s=0.2, lag_s=0.2`, 65.6% at 0.4/0.4, 15.6% (correct 53.1%) at
`lead_s=0.6, lag_s=0.1`, 7.3% (correct 62.5%) at `lead_s=0.8, lag_s=0.1`, 12.5% at `min_share=0.9`
and 17.7% at `min_margin=0.6`. A shorter look-back makes the look-away stratum worse (silent-wrong
38.5-100% across the 12 cells with `lead_s=0.2`, against 16.2-21.9% at the defaults). Across all 80 sensitivity cells the aligned stratum had 0 wrong-binds; and
among the cells whose aligned correct-bound stayed at or above 99%, the lowest look-away silent-wrong
rate was 6.0% (mixed layout, 2 degrees, `lead_s=0.8`, `lag_s=0.1`). Look-away n is 96-117 per row, so the intervals are wide (e.g. 7.3% [3.6-14.3]). **These sweeps show how
sensitive the model is to each knob; they must not be used to choose defaults**, least of all
`lead_s=0.8`, which equals the generator's maximum lead.

### 5.6 What these results do and do not support

Supported: the pure modules run end to end, are deterministic at a fixed seed, make no wrong-binds when
the eyes are on the intended panel and the noise is zero-mean up to 2 degrees, and degrade toward
refusal rather than a confident wrong panel under that noise. Not supported: any accuracy,
error-rate or prompt-rate claim for real users, devices or layouts, or that the defaults are
validated. `bind_demonstrative`'s own docstring says the `lead_s`/`lag_s`/`max_gap_s`/`min_samples`/
`min_coverage_s` defaults "are not validated values", and nothing here changes that. The findings to
act on are in section 0.1 items 2-4: the look-away case, the missing bias signal, and the prompt rule.

---

## 6. Protocol for the real study (draft, not yet reviewed or approved)

This is a **proposal**. Nothing in it has been submitted to an ethics body, and no data has
been collected. Under [ADR-v2-150](../adr/adr-v2-150-evaluation-evidence-and-research-consent.md)
Rule 7 the responsible research environment must determine the applicable review process,
and the protocol, measures, exclusions and analysis must be versioned and final **before
recruitment**. Everything below is the content to put in front of that determination, not a
substitute for it.

### 6.1 Evidence class and identifiers

- `study_mode = "research"` (ADR-v2-150 Rule 2) with a protocol identifier of the form
  `xr-deixis-binding-v1`, minted when this protocol is frozen. Until then no result may be
  labelled `research`.
- Sections 1-5 of this document are `study_mode = "synthetic"`. Synthetic and research rows
  never share a table; the analysis script refuses to read both (Rule 6).
- Public hardware reports about XR devices stay `community_qa` and never enter the
  participant analysis (Rule 1, Rule 5).

### 6.2 Participants

- **Who.** Adults (18+) who can give informed consent in the study language, with normal or
  corrected-to-normal vision, recruited by open call and not from project contributors the
  investigator supervises or employs (to avoid undue influence).
- **Not excluded for being hard to track.** Glasses, contact lenses, eye colour, make-up
  and head shape are **recorded as covariates, not exclusion criteria**: excluding the people
  a tracker serves worst would flatter the result. Participants whose device cannot be
  calibrated are counted and reported as "could not calibrate", never silently dropped.
- **Accessibility populations** (people who use hands-free input because of a motor
  impairment) are the intended long-term users, and are **out of scope for this first
  study**. They need their own protocol, with the participants and an accessibility partner
  involved in designing it. Results here must not be described as applying to them.
- **Size.** See 6.6: 10 tuning plus 30 confirmation participants (40 analysed), and a separate pilot of 5.
  Each analysed participant does 40 aligned and 8 look-away scored trials in the primary condition.

### 6.3 Consent, information and withdrawal

- Written participant information stating: what is recorded (6.5), that audio is **not**
  recorded, that gaze and head pose can be sensitive and in rich form can re-identify, where
  data is stored, for how long, who can see it, and how to withdraw.
- Consent is a separate, signed (or recorded-tick) step before the first trial, kept in a
  record that is **stored apart from the measurements** and linked only by a private
  mapping (ADR-v2-150 Rule 5). No GitHub name or e-mail is ever an analysis key.
- A volunteer who earlier filed a public `community_qa` report is not thereby enrolled
  (Rule 3); they enrol through this protocol as anyone else.
- **Withdrawal** is possible until the analysis dataset is frozen; the participant's rows are
  then deleted via the private mapping. After the freeze, rows are already unlinkable and can
  no longer be removed, and the information sheet must say so.
- Open items for the ethics determination, not decided here: retention period, whether
  the de-identified per-trial table may be published (a tentative yes, with the replay
  stream in 6.5 withheld), data-protection basis in the study's jurisdiction, compensation.

### 6.4 Task and design

Within-subject. Each participant sits at a fixed distance from a rendered panel layout
(or the real headset, if the study device is a headset) and performs cued trials:

1. A cue highlights one panel (the **instructed target**: this is the ground-truth label).
2. The participant looks at it and says "type here" (or "put it there") followed by a short
   fixed phrase from a bank, at their own pace. Lead time is **not** instructed; it is
   measured from the recogniser's word timestamps.
3. The system binds and either acts silently or asks. A prompt is answered with the release
   word. After every trial the participant states, on a single key, which panel they
   **meant** (so a stale or mistaken instruction is separable from a binder error: a labelling
   mistake of exactly this kind produced the first draft's 19.3% in section 0).
4. **Look-away trials** (8 of every 48 scored trials, interleaved at random): the instruction is
   to look at the cued panel, then look elsewhere (a second cue appears 100-900 ms later) and
   *then* say the phrase, still meaning the first panel. The remaining 40 are **aligned trials**
   (the participant is told to keep looking at the cued panel while speaking). A trial's stratum
   is decided from the **recorded panel-hit stream** (the panel under the eyes at the word onset
   equals the participant's "meant" panel: aligned; otherwise: look-away), not from the
   instruction, so an instructed look-away that the participant did not perform is analysed as
   aligned. Aligned and look-away trials are **never pooled** in any rate (section 5.1): a pooled
   figure depends on the proportion the experimenter chose.

Conditions, order counterbalanced by Latin square: layout (far / adjacent / abutting /
mixed, as in section 3), and, if hardware allows, ray source (eye / head / hand). The primary
analysis is one pre-named (layout, source) condition; the others are secondary.

Calibration is run per the device vendor's procedure and **recalibration is not allowed
mid-session** unless the participant requests it (it is logged), so drift can happen as it
would in use.

### 6.5 What is recorded, and how it must be stored

Per ADR-v2-150 Rule 4 the study records **derived values only**:

| Recorded | Not recorded |
|---|---|
| random participant id, session id, trial id, `study_mode`, protocol id and version | name, contact details, GitHub identity, device serial |
| device model class, ray source, layout, condition, trial order | raw camera frames, eye images, face mesh |
| the instructed target and the participant's own "meant" label | audio, the dictated text, screenshots |
| word-onset time (recogniser timestamp), utterance end | free-text answers (a closed list only) |
| the **panel-hit stream**: per sample `(t, panel id or none, tracker confidence)`, i.e. exactly the `PanelObservation` the binder consumes | raw ray vectors and head/hand pose, unless the ethics determination approves them separately |
| binder outcome, margin, confirm reason, release word, any correction | |
| task time (cue to correct text in the correct panel) | |
| covariates: glasses/lenses, calibration quality score, self-reported prior XR experience | any medical or diagnostic information |

The panel-hit stream is enough to **replay** the binder and the confirm policy offline under
any candidate threshold (it is the binder's whole input), which is what the tuning rule in
6.8 needs. Angular error is summarised per trial as one scalar (angle from the instructed
target centre at the word onset), which keeps the noise level measurable without keeping the
gaze path.

**Storage.** Measurements: access-controlled, encrypted storage under the investigator's
institution or the project owner's control, never in the public repository, never in a
GitHub issue, never on a hosted LLM service (AGENTS.md: no real user data to a third-party
coding agent). The consent record and the id mapping: a separate store with a separate
access list. Analysis runs on the measurements store only. Retention and deletion follow the
approved protocol.

### 6.6 Outcomes and sample size

**Primary: the silent wrong-bind rate, in two strata.** A trial counts when the binder
returned BOUND, the bound panel is not the participant's "meant" panel, and **no confirmation
was shown**. This is the error ADR-021 prices highest: a confident wrong action. The
denominator is all scored trials of that stratum in the primary condition (a refusal is not a
success but it is not this error).

**Pre-stated tolerances.**
- **P1, aligned trials:** the **upper 95% confidence limit** of the silent wrong-bind rate is
  **<= 1.0%**. One per cent is a judgement, not a finding: roughly one wrongly placed dictation
  in a hundred without warning.
- **P2, look-away trials:** the same limit is **<= 5.0%**. The synthetic run (section 0.1)
  found 20-37% at the defaults, so this tolerance is expected to fail today; it is stated now so
  that failing is a result and not a surprise to be explained away. Whether look-away use is
  common enough to matter is itself a finding to report (the share of such trials among
  unprompted dictation is not estimated by this design).
- The product may claim what each stratum supports and nothing more: a pass on P1 with a fail
  on P2 means "binds correctly when you keep looking at the panel", not "binds to the panel
  you meant".
- The owner may set stricter figures before the protocol is frozen; they may not be loosened
  after data is seen.

**Reported with it, not traded against it:** the **wrong-bind rate before confirmation**
(BOUND and wrong, prompted or not), because a prompt only helps if the participant notices
the prompt is wrong, and because a high figure means the confirm policy is carrying weight
the binder should carry.

**Secondary:** (a) prompt rate (share of trials that held for confirmation; the ADR-021
risk is a guard that fires too often, and `expected_prompt_rate`'s own docstring calls for
exactly this re-measurement); (b) frictionless-success rate (correct, silent); (c) task time,
median and IQR, with prompts included; (d) refusal rate (ambiguous or none); (e)
"could not calibrate" count.

**Sample size.** If no silent wrong binds are seen in `n_eff` independent trials, the
Wilson upper limit is `z^2 / (n_eff + z^2)`, with `z = 1.96`, so reaching <= 1.0% needs
`n_eff >= 380` (the exact Clopper-Pearson bound needs about 367) and reaching <= 5.0% needs
`n_eff >= 73`. Trials within a
participant are correlated, so the number of trials must be inflated by the design effect
`1 + (m - 1) * rho` for `m` trials per participant and intra-class correlation `rho`. The
correlation is unknown (a tracker that is biased for one face is biased for every trial of
that face; section 5.4 shows why this matters) and **must be assumed, not estimated, before
data exists**: with `m = 40` aligned trials per participant and a deliberately pessimistic `rho = 0.05`
the design effect is 2.95 and P1 needs ~1,120 aligned trials, i.e. **28 participants, rounded
up to 30 confirmation participants x 40 = 1,200 aligned trials**. P2 with `m = 8` has a design
effect of 1.35 and needs ~100 trials; 30 x 8 = **240 look-away trials** gives margin. The 10
tuning participants are *in addition*: the confirmation set alone must carry the claim (6.8),
which is why the total is 40, not 30. Both calculations assume zero events; each observed event
raises the needed `n` sharply, so 1,200 aligned trials supports a pass at 0 events and a
"cannot tell" at 2 or more. The pre-stated tolerance is applied to a **cluster-adjusted Wilson
upper limit**: the Wilson interval computed on `n_eff = N / deff`, with `deff` estimated
from the data (ANOVA estimator of `rho`) and **floored at the pre-assumed 0.05**. A participant
bootstrap is not used for the criterion because with zero events every resample is zero and
the interval collapses to a falsely tight [0, 0]; it may be shown as a descriptive extra. If the pilot (6.7) shows `rho` is
larger than 0.05, the sample is increased before the confirmation phase, not after.

This sample proves a *bound for one device, one layout set and one population*. It does not
establish a rate for headsets in general, for other layouts, or for people with impairments.

### 6.7 Pilot

Five participants, not analysed for the confirmation claim. Purpose: check the apparatus
logs what 6.5 lists, estimate `rho` and the actual lead-time distribution, and check the
"meant" key is understood. Anything learned may change the protocol only through a new
version number, before the tuning phase starts.

### 6.8 Pre-registered decision rule for tuning lead/lag and thresholds

Fixed before data collection and filed with the frozen protocol:

1. **Split by participant, not by trial.** Participants 1-10 (by enrolment order) are the
   **tuning set**; participants 11-40 are the **confirmation set**. The confirmation set is
   not opened until step 4. (The tuning set, 400 aligned trials, is too small to *demonstrate*
   a 1.0% bound even at zero events, so step 3 screens on point estimates; only step 4 claims.)
2. **Candidate grid, fixed in advance:** `lead_s` in {0.2, 0.4, 0.6, 0.8}, `lag_s` in {0.1,
   0.2, 0.4}, `min_share` in {0.5, 0.6, 0.75}, `min_margin` in {0.25, 0.4}, smoothing in {off,
   default One-Euro}. No candidate is added after seeing results.
3. **Selection on the tuning set only**, replaying the recorded panel-hit streams: screen to
   candidates whose silent wrong-bind **point estimate** is <= 0.5% on aligned trials and
   <= 2.5% on look-away trials (half of each tolerance); among them pick the one with the lowest
   prompt rate over the 40:8 mix of the design; ties go to the lower task time, then to the one nearest the
   current defaults. If **no** candidate passes the screen, stop: the result is "no candidate in the grid
   meets the screen on this hardware", the feature stays off by default
   (AGENTS.md rule 2), and the report says so as the finding.
4. **One-shot confirmation.** Evaluate the chosen candidate and the **current defaults** on
   the confirmation set. The chosen candidate becomes the shipped default only if its
   cluster-adjusted Wilson upper limits on the confirmation set meet P1 (<= 1.0%); its P2 result
   is reported either way and decides what the documentation may claim (6.6). Otherwise the
   defaults do not change and the study is reported as negative.
5. **No second pass.** If step 4 fails, any further tuning is a new study version with new
   participants. Peeking at confirmation data to adjust the grid, the tolerance or the
   exclusions is a protocol violation and is reported as one.
6. **Everything is reported**: the full tuning-set table for every candidate, not only the
   winner, and every deviation from this rule.

Because the claim rests on the held-out set, selecting from a 144-point grid on the tuning
set does not inflate the confirmation claim; it only costs tuning-set power, which is why the
grid is kept small.

### 6.9 Threats the protocol is built to expose

- **Label problem** (sections 0 and 5.1): the participant's "meant" key, the separate
  aligned and look-away strata, and stratification from the recorded stream, not the instruction.
- **Systematic bias** (section 5.4): per-participant bias is a random effect; it is why the
  analysis is clustered and why calibration quality is a covariate.
- **Order and fatigue:** Latin square, breaks every 20 trials, trial index recorded.
- **Demand effects:** participants know their gaze is measured; the cue never says the
  system "should" prompt, and the prompt appears only through the system.
- **Learning:** the first 5 trials of every condition are practice and excluded; the number is
  fixed here, not chosen later.
- **Experimenter degrees of freedom:** every choice in 6.2-6.8 is frozen before recruitment.

---

## Appendix A. Reproducing the numbers

```sh
git -C /home/mohsen/scratch/repos/yazses-xr rev-parse --short HEAD     # 4fda3403 (xr modules uncommitted)
mkdir -p /tmp/xr_eval_out && cd /home/mohsen/scratch/repos/yazses-xr
# save Appendix C as /tmp/xr_eval.py, then:
PYTHONPATH=src python3 /tmp/xr_eval.py --n 500 --seed 20261030 --workers 12 --out /tmp/xr_eval_out
```

Writes `xr_eval_tables.md` (the tables of Appendix B) and `xr_eval_results.json` (raw counts per
cell and stratum). It uses only the standard library and the `yazses.xr` modules, no network, no
files other than the two outputs, and a private `random.Random` per generator, so the same seed and
the same module sources give the same counts. (`--workers` changes only wall time, about 12 minutes on
12 cores at n=500.) A smoke run: `--n 20 --workers 12` finishes in about a minute. If a `yazses.xr`
module has changed since the hashes in section 1, expect different numbers. The Headline tables of
section 4 were derived from `xr_eval_results.json` by the short post-processing script in Appendix D
(it pools the look-away stratum over layouts); Appendix B holds the unpooled per-layout rows.

## Appendix B. Full tables (generated by the script, unedited)

Columns: *correct-bound*, **WRONG-bound**, *silent-wrong* (wrong-bound with no prompt), *ambiguous*,
*none*, *prompt*, *prompt w/o target-changed* (diagnostic), and *naive ray-at-word wrong*; each is a
percentage with its 95% Wilson interval. All scored against the intended panel.

### Grid: look_away_prob=0 (eyes still on the intended panel at the word)

**far(gap1.0m) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   7.8% [ 5.8- 10.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   8.0% [ 5.9- 10.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   8.2% [ 6.1- 10.9] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |
| 2 | lead0.0-0.2 | 500 |  99.2% [98.0- 99.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |   8.0% [ 5.9- 10.7] |   0.0% [ 0.0-  0.8] |   5.8% [ 4.1-  8.2] |
| 4 | lead0.0-0.2 | 500 |  73.8% [69.8- 77.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |  26.0% [22.3- 30.0] |   4.6% [ 3.1-  6.8] |   0.2% [ 0.0-  1.1] |  27.4% [23.7- 31.5] |
| 0 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  45.4% [41.1- 49.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  45.2% [40.9- 49.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  44.8% [40.5- 49.2] |   0.0% [ 0.0-  0.8] |   1.2% [ 0.6-  2.6] |
| 2 | lead0.2-0.4 | 500 |  98.2% [96.6- 99.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.8% [ 0.9-  3.4] |   0.0% [ 0.0-  0.8] |  38.2% [34.0- 42.5] |   1.8% [ 0.9-  3.4] |   8.6% [ 6.4- 11.4] |
| 4 | lead0.2-0.4 | 500 |  69.0% [64.8- 72.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  15.0% [12.1- 18.4] |  16.0% [13.0- 19.5] |  30.4% [26.5- 34.6] |  15.0% [12.1- 18.4] |  30.0% [26.1- 34.2] |
| 0 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  76.0% [72.1- 79.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  76.0% [72.1- 79.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  74.8% [70.8- 78.4] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |
| 2 | lead0.2-0.8 | 500 |  95.2% [93.0- 96.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   4.8% [ 3.2-  7.0] |   0.0% [ 0.0-  0.8] |  66.0% [61.7- 70.0] |   4.8% [ 3.2-  7.0] |   8.0% [ 5.9- 10.7] |
| 4 | lead0.2-0.8 | 500 |  50.6% [46.2- 55.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  40.0% [35.8- 44.4] |   9.4% [ 7.1- 12.3] |  60.0% [55.6- 64.2] |  40.0% [35.8- 44.4] |  30.2% [26.3- 34.4] |
| 0 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  98.0% [96.4- 98.9] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |
| 2 | lead0.6-1.2 | 500 |  88.2% [85.1- 90.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  11.8% [ 9.3- 14.9] |   0.0% [ 0.0-  0.8] |  89.0% [86.0- 91.5] |  11.8% [ 9.3- 14.9] |   8.4% [ 6.3- 11.2] |
| 4 | lead0.6-1.2 | 500 |  26.4% [22.7- 30.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  72.8% [68.7- 76.5] |   0.8% [ 0.3-  2.0] |  86.8% [83.6- 89.5] |  72.8% [68.7- 76.5] |  30.8% [26.9- 35.0] |

**far(gap1.0m) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.0-0.2 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   0.6% [ 0.2-  1.7] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |
| 2 | lead0.0-0.2 | 500 |  96.2% [94.1- 97.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   3.8% [ 2.4-  5.9] |   0.6% [ 0.2-  1.7] |   0.0% [ 0.0-  0.8] |   5.8% [ 4.1-  8.2] |
| 4 | lead0.0-0.2 | 500 |  87.2% [84.0- 89.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  12.8% [10.2- 16.0] |   0.4% [ 0.1-  1.4] |   0.0% [ 0.0-  0.8] |  27.4% [23.7- 31.5] |
| 0 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   8.8% [ 6.6- 11.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   8.8% [ 6.6- 11.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   8.8% [ 6.6- 11.6] |   0.0% [ 0.0-  0.8] |   1.2% [ 0.6-  2.6] |
| 2 | lead0.2-0.4 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   8.8% [ 6.6- 11.6] |   0.0% [ 0.0-  0.8] |   8.6% [ 6.4- 11.4] |
| 4 | lead0.2-0.4 | 500 |  97.6% [95.9- 98.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   2.2% [ 1.2-  3.9] |   9.0% [ 6.8- 11.8] |   0.2% [ 0.0-  1.1] |  30.0% [26.1- 34.2] |
| 0 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  17.2% [14.1- 20.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  17.4% [14.3- 21.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  17.4% [14.3- 21.0] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |
| 2 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  17.4% [14.3- 21.0] |   0.0% [ 0.0-  0.8] |   8.0% [ 5.9- 10.7] |
| 4 | lead0.2-0.8 | 500 |  98.8% [97.4- 99.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |   0.8% [ 0.3-  2.0] |  17.8% [14.7- 21.4] |   0.4% [ 0.1-  1.4] |  30.2% [26.3- 34.4] |
| 0 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  23.4% [19.9- 27.3] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  23.6% [20.1- 27.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  23.4% [19.9- 27.3] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |
| 2 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  23.2% [19.7- 27.1] |   0.0% [ 0.0-  0.8] |   8.4% [ 6.3- 11.2] |
| 4 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  23.0% [19.5- 26.9] |   0.0% [ 0.0-  0.8] |  30.8% [26.9- 35.0] |

**adjacent(gap0.1m) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  15.0% [12.1- 18.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  14.6% [11.8- 18.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  14.6% [11.8- 18.0] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |
| 2 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  13.0% [10.3- 16.2] |   0.0% [ 0.0-  0.8] |   5.2% [ 3.6-  7.5] |
| 4 | lead0.0-0.2 | 500 |  92.2% [89.5- 94.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   3.0% [ 1.8-  4.9] |   4.8% [ 3.2-  7.0] |  12.2% [ 9.6- 15.4] |   3.0% [ 1.8-  4.9] |  23.2% [19.7- 27.1] |
| 0 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  39.6% [35.4- 44.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  39.4% [35.2- 43.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  39.4% [35.2- 43.7] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |
| 2 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  36.2% [32.1- 40.5] |   0.0% [ 0.0-  0.8] |   2.6% [ 1.5-  4.4] |
| 4 | lead0.2-0.4 | 500 |  89.4% [86.4- 91.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   8.0% [ 5.9- 10.7] |   2.6% [ 1.5-  4.4] |  30.8% [26.9- 35.0] |   8.0% [ 5.9- 10.7] |  21.6% [18.2- 25.4] |
| 0 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  75.8% [71.9- 79.3] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  75.8% [71.9- 79.3] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  75.6% [71.6- 79.2] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |
| 2 | lead0.2-0.8 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   0.0% [ 0.0-  0.8] |  70.2% [66.0- 74.0] |   0.2% [ 0.0-  1.1] |   3.0% [ 1.8-  4.9] |
| 4 | lead0.2-0.8 | 500 |  77.6% [73.7- 81.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  20.8% [17.5- 24.6] |   1.6% [ 0.8-  3.1] |  55.8% [51.4- 60.1] |  20.8% [17.5- 24.6] |  17.4% [14.3- 21.0] |
| 0 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  99.4% [98.3- 99.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 2 | lead0.6-1.2 | 500 |  98.6% [97.1- 99.3] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.4% [ 0.7-  2.9] |   0.0% [ 0.0-  0.8] |  92.0% [89.3- 94.1] |   1.4% [ 0.7-  2.9] |   4.4% [ 2.9-  6.6] |
| 4 | lead0.6-1.2 | 500 |  55.6% [51.2- 59.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  44.4% [40.1- 48.8] |   0.0% [ 0.0-  0.8] |  82.4% [78.8- 85.5] |  44.4% [40.1- 48.8] |  20.4% [17.1- 24.2] |

**adjacent(gap0.1m) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   3.2% [ 2.0-  5.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   3.2% [ 2.0-  5.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   3.2% [ 2.0-  5.1] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |
| 2 | lead0.0-0.2 | 500 |  99.4% [98.3- 99.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |   3.2% [ 2.0-  5.1] |   0.0% [ 0.0-  0.8] |   5.2% [ 3.6-  7.5] |
| 4 | lead0.0-0.2 | 500 |  91.6% [88.8- 93.7] |   0.2% [ 0.0-  1.1] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   8.0% [ 5.9- 10.7] |   3.8% [ 2.4-  5.9] |   0.2% [ 0.0-  1.1] |  23.2% [19.7- 27.1] |
| 0 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  25.6% [22.0- 29.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  25.6% [22.0- 29.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  25.6% [22.0- 29.6] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |
| 2 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  25.2% [21.6- 29.2] |   0.0% [ 0.0-  0.8] |   2.6% [ 1.5-  4.4] |
| 4 | lead0.2-0.4 | 500 |  98.6% [97.1- 99.3] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   1.2% [ 0.6-  2.6] |  25.4% [21.8- 29.4] |   0.2% [ 0.0-  1.1] |  21.6% [18.2- 25.4] |
| 0 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  50.8% [46.4- 55.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  50.6% [46.2- 55.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  50.4% [46.0- 54.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |
| 2 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  49.6% [45.2- 54.0] |   0.0% [ 0.0-  0.8] |   3.0% [ 1.8-  4.9] |
| 4 | lead0.2-0.8 | 500 |  99.6% [98.6- 99.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   0.2% [ 0.0-  1.1] |  48.0% [43.7- 52.4] |   0.2% [ 0.0-  1.1] |  17.4% [14.3- 21.0] |
| 0 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  85.6% [82.3- 88.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  85.8% [82.5- 88.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  86.6% [83.3- 89.3] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 2 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  86.4% [83.1- 89.1] |   0.0% [ 0.0-  0.8] |   4.4% [ 2.9-  6.6] |
| 4 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  84.2% [80.7- 87.1] |   0.0% [ 0.0-  0.8] |  20.4% [17.1- 24.2] |

**abutting(gap0m) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  14.0% [11.2- 17.3] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  14.2% [11.4- 17.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  14.0% [11.2- 17.3] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |
| 2 | lead0.0-0.2 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |  13.2% [10.5- 16.4] |   0.0% [ 0.0-  0.8] |   6.0% [ 4.2-  8.4] |
| 4 | lead0.0-0.2 | 500 |  90.6% [87.7- 92.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   3.2% [ 2.0-  5.1] |   6.2% [ 4.4-  8.7] |  14.4% [11.6- 17.7] |   3.2% [ 2.0-  5.1] |  26.4% [22.7- 30.4] |
| 0 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  52.4% [48.0- 56.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  52.6% [48.2- 56.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  52.0% [47.6- 56.3] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |
| 2 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  49.0% [44.6- 53.4] |   0.0% [ 0.0-  0.8] |   4.2% [ 2.8-  6.3] |
| 4 | lead0.2-0.4 | 500 |  89.6% [86.6- 92.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   9.0% [ 6.8- 11.8] |   1.4% [ 0.7-  2.9] |  42.4% [38.1- 46.8] |   9.0% [ 6.8- 11.8] |  21.0% [17.7- 24.8] |
| 0 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  77.0% [73.1- 80.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  77.2% [73.3- 80.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  77.4% [73.5- 80.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 2 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  72.6% [68.5- 76.3] |   0.0% [ 0.0-  0.8] |   4.6% [ 3.1-  6.8] |
| 4 | lead0.2-0.8 | 500 |  78.6% [74.8- 82.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  20.8% [17.5- 24.6] |   0.6% [ 0.2-  1.7] |  62.0% [57.7- 66.1] |  20.8% [17.5- 24.6] |  21.4% [18.0- 25.2] |
| 0 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  99.6% [98.6- 99.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 2 | lead0.6-1.2 | 500 |  99.6% [98.6- 99.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |   0.0% [ 0.0-  0.8] |  93.2% [90.6- 95.1] |   0.4% [ 0.1-  1.4] |   2.6% [ 1.5-  4.4] |
| 4 | lead0.6-1.2 | 500 |  65.6% [61.3- 69.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  34.2% [30.2- 38.5] |   0.2% [ 0.0-  1.1] |  77.8% [74.0- 81.2] |  34.2% [30.2- 38.5] |  17.8% [14.7- 21.4] |

**abutting(gap0m) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   4.6% [ 3.1-  6.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   4.4% [ 2.9-  6.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   4.2% [ 2.8-  6.3] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |
| 2 | lead0.0-0.2 | 500 |  99.6% [98.6- 99.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   0.2% [ 0.0-  1.1] |   4.6% [ 3.1-  6.8] |   0.4% [ 0.1-  1.4] |   6.0% [ 4.2-  8.4] |
| 4 | lead0.0-0.2 | 500 |  91.8% [89.1- 93.9] |   0.6% [ 0.2-  1.7] |   0.0% [ 0.0-  0.8] |   1.2% [ 0.6-  2.6] |   6.4% [ 4.6-  8.9] |   5.8% [ 4.1-  8.2] |   1.2% [ 0.6-  2.6] |  26.4% [22.7- 30.4] |
| 0 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  31.2% [27.3- 35.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  31.4% [27.5- 35.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  31.8% [27.9- 36.0] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |
| 2 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  31.4% [27.5- 35.6] |   0.0% [ 0.0-  0.8] |   4.2% [ 2.8-  6.3] |
| 4 | lead0.2-0.4 | 500 |  98.4% [96.9- 99.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.6% [ 0.8-  3.1] |  30.6% [26.7- 34.8] |   0.0% [ 0.0-  0.8] |  21.0% [17.7- 24.8] |
| 0 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  65.4% [61.1- 69.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  65.2% [60.9- 69.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  65.4% [61.1- 69.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 2 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  65.4% [61.1- 69.4] |   0.0% [ 0.0-  0.8] |   4.6% [ 3.1-  6.8] |
| 4 | lead0.2-0.8 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |  64.8% [60.5- 68.9] |   0.0% [ 0.0-  0.8] |  21.4% [18.0- 25.2] |
| 0 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  96.6% [94.6- 97.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  96.6% [94.6- 97.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  96.2% [94.1- 97.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 2 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  95.8% [93.7- 97.2] |   0.0% [ 0.0-  0.8] |   2.6% [ 1.5-  4.4] |
| 4 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  96.0% [93.9- 97.4] |   0.0% [ 0.0-  0.8] |  17.8% [14.7- 21.4] |

**mixed(2adj+2far) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  10.2% [ 7.8- 13.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  10.0% [ 7.7- 12.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   9.8% [ 7.5- 12.7] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |
| 2 | lead0.0-0.2 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   8.0% [ 5.9- 10.7] |   0.0% [ 0.0-  0.8] |   8.4% [ 6.3- 11.2] |
| 4 | lead0.0-0.2 | 500 |  65.8% [61.5- 69.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.0% [ 0.4-  2.3] |  33.2% [29.2- 37.4] |   4.4% [ 2.9-  6.6] |   1.0% [ 0.4-  2.3] |  33.4% [29.4- 37.6] |
| 0 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  47.8% [43.5- 52.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  48.0% [43.7- 52.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  47.6% [43.3- 52.0] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |
| 2 | lead0.2-0.4 | 500 |  97.2% [95.4- 98.3] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   2.2% [ 1.2-  3.9] |   0.6% [ 0.2-  1.7] |  42.6% [38.3- 47.0] |   2.2% [ 1.2-  3.9] |   6.6% [ 4.7-  9.1] |
| 4 | lead0.2-0.4 | 500 |  59.0% [54.6- 63.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  16.4% [13.4- 19.9] |  24.6% [21.0- 28.6] |  32.4% [28.4- 36.6] |  16.4% [13.4- 19.9] |  33.0% [29.0- 37.2] |
| 0 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  74.4% [70.4- 78.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  74.6% [70.6- 78.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  73.2% [69.2- 76.9] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |
| 2 | lead0.2-0.8 | 500 |  92.6% [90.0- 94.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   7.2% [ 5.2-  9.8] |   0.2% [ 0.0-  1.1] |  61.0% [56.7- 65.2] |   7.2% [ 5.2-  9.8] |   9.4% [ 7.1- 12.3] |
| 4 | lead0.2-0.8 | 500 |  39.8% [35.6- 44.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  44.4% [40.1- 48.8] |  15.8% [12.9- 19.3] |  58.0% [53.6- 62.2] |  44.4% [40.1- 48.8] |  34.8% [30.8- 39.1] |
| 0 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  99.6% [98.6- 99.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  99.6% [98.6- 99.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  97.8% [96.1- 98.8] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |
| 2 | lead0.6-1.2 | 500 |  87.4% [84.2- 90.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  12.6% [10.0- 15.8] |   0.0% [ 0.0-  0.8] |  86.2% [82.9- 88.9] |  12.6% [10.0- 15.8] |   7.0% [ 5.1-  9.6] |
| 4 | lead0.6-1.2 | 500 |  34.2% [30.2- 38.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  65.2% [60.9- 69.2] |   0.6% [ 0.2-  1.7] |  84.0% [80.5- 87.0] |  65.2% [60.9- 69.2] |  30.6% [26.7- 34.8] |

**mixed(2adj+2far) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.8% [ 0.9-  3.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.8% [ 0.9-  3.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.0-0.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.8% [ 0.9-  3.4] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |
| 2 | lead0.0-0.2 | 500 |  98.0% [96.4- 98.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   2.0% [ 1.1-  3.6] |   1.8% [ 0.9-  3.4] |   0.0% [ 0.0-  0.8] |   8.4% [ 6.3- 11.2] |
| 4 | lead0.0-0.2 | 500 |  87.0% [83.8- 89.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |  12.4% [ 9.8- 15.6] |   2.4% [ 1.4-  4.1] |   0.6% [ 0.2-  1.7] |  33.4% [29.4- 37.6] |
| 0 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  13.6% [10.9- 16.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  13.6% [10.9- 16.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.4 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  13.6% [10.9- 16.9] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |
| 2 | lead0.2-0.4 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |  13.6% [10.9- 16.9] |   0.0% [ 0.0-  0.8] |   6.6% [ 4.7-  9.1] |
| 4 | lead0.2-0.4 | 500 |  97.0% [95.1- 98.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   2.8% [ 1.7-  4.6] |  13.2% [10.5- 16.4] |   0.2% [ 0.0-  1.1] |  33.0% [29.0- 37.2] |
| 0 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  25.6% [22.0- 29.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  25.6% [22.0- 29.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  25.8% [22.2- 29.8] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |
| 2 | lead0.2-0.8 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  25.0% [21.4- 29.0] |   0.0% [ 0.0-  0.8] |   9.4% [ 7.1- 12.3] |
| 4 | lead0.2-0.8 | 500 |  99.2% [98.0- 99.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |  24.8% [21.2- 28.8] |   0.0% [ 0.0-  0.8] |  34.8% [30.8- 39.1] |
| 0 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  37.2% [33.1- 41.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 0.5 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  38.0% [33.9- 42.3] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |
| 1 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  38.0% [33.9- 42.3] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |
| 2 | lead0.6-1.2 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  37.8% [33.7- 42.1] |   0.0% [ 0.0-  0.8] |   7.0% [ 5.1-  9.6] |
| 4 | lead0.6-1.2 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |  37.4% [33.3- 41.7] |   0.0% [ 0.0-  0.8] |  30.6% [26.7- 34.8] |

### Grid: look_away_prob=0.2, ALIGNED stratum (eyes on the intended panel)

**far(gap1.0m) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 405 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   8.1% [ 5.9- 11.2] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.0-0.2 | 405 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   8.4% [ 6.1- 11.5] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.0-0.2 | 405 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   8.6% [ 6.3- 11.8] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |
| 2 | lead0.0-0.2 | 405 |  99.3% [97.8- 99.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.7% [ 0.3-  2.2] |   8.6% [ 6.3- 11.8] |   0.0% [ 0.0-  0.9] |   6.2% [ 4.2-  9.0] |
| 4 | lead0.0-0.2 | 405 |  72.8% [68.3- 76.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |  26.9% [22.8- 31.4] |   5.2% [ 3.4-  7.8] |   0.2% [ 0.0-  1.4] |  29.1% [24.9- 33.7] |
| 0 | lead0.2-0.4 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  47.0% [42.1- 51.9] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.2-0.4 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  46.7% [41.9- 51.6] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.2-0.4 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  46.2% [41.4- 51.1] |   0.0% [ 0.0-  1.0] |   0.8% [ 0.3-  2.2] |
| 2 | lead0.2-0.4 | 396 |  98.0% [96.1- 99.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   2.0% [ 1.0-  3.9] |   0.0% [ 0.0-  1.0] |  39.4% [34.7- 44.3] |   2.0% [ 1.0-  3.9] |   8.8% [ 6.4- 12.0] |
| 4 | lead0.2-0.4 | 396 |  68.2% [63.4- 72.6] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  15.9% [12.6- 19.8] |  15.9% [12.6- 19.8] |  31.3% [26.9- 36.0] |  15.9% [12.6- 19.8] |  31.3% [26.9- 36.0] |
| 0 | lead0.2-0.8 | 390 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  77.2% [72.8- 81.1] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.2-0.8 | 390 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  77.2% [72.8- 81.1] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.2-0.8 | 390 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  75.9% [71.4- 79.9] |   0.0% [ 0.0-  1.0] |   1.0% [ 0.4-  2.6] |
| 2 | lead0.2-0.8 | 390 |  94.9% [92.2- 96.7] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   5.1% [ 3.3-  7.8] |   0.0% [ 0.0-  1.0] |  67.2% [62.4- 71.7] |   5.1% [ 3.3-  7.8] |   8.2% [ 5.9- 11.4] |
| 4 | lead0.2-0.8 | 390 |  52.1% [47.1- 57.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  38.7% [34.0- 43.6] |   9.2% [ 6.7- 12.5] |  60.0% [55.1- 64.7] |  38.7% [34.0- 43.6] |  30.0% [25.7- 34.7] |
| 0 | lead0.6-1.2 | 382 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.6-1.2 | 382 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.6-1.2 | 382 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  97.9% [95.9- 98.9] |   0.0% [ 0.0-  1.0] |   0.5% [ 0.1-  1.9] |
| 2 | lead0.6-1.2 | 382 |  87.7% [84.0- 90.6] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  12.3% [ 9.4- 16.0] |   0.0% [ 0.0-  1.0] |  88.7% [85.2- 91.5] |  12.3% [ 9.4- 16.0] |   8.1% [ 5.8- 11.3] |
| 4 | lead0.6-1.2 | 382 |  26.2% [22.0- 30.8] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  73.0% [68.4- 77.2] |   0.8% [ 0.3-  2.3] |  88.0% [84.3- 90.8] |  73.0% [68.4- 77.2] |  31.4% [27.0- 36.2] |

**far(gap1.0m) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 405 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.7% [ 0.3-  2.2] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.0-0.2 | 405 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.7% [ 0.3-  2.2] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.0-0.2 | 405 |  99.8% [98.6-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |   0.7% [ 0.3-  2.2] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |
| 2 | lead0.0-0.2 | 405 |  96.0% [93.7- 97.6] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   4.0% [ 2.4-  6.3] |   0.7% [ 0.3-  2.2] |   0.0% [ 0.0-  0.9] |   6.2% [ 4.2-  9.0] |
| 4 | lead0.0-0.2 | 405 |  86.2% [82.5- 89.2] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  13.8% [10.8- 17.5] |   0.5% [ 0.1-  1.8] |   0.0% [ 0.0-  0.9] |  29.1% [24.9- 33.7] |
| 0 | lead0.2-0.4 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  10.1% [ 7.5- 13.5] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.2-0.4 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  10.1% [ 7.5- 13.5] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.2-0.4 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  10.1% [ 7.5- 13.5] |   0.0% [ 0.0-  1.0] |   0.8% [ 0.3-  2.2] |
| 2 | lead0.2-0.4 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  10.1% [ 7.5- 13.5] |   0.0% [ 0.0-  1.0] |   8.8% [ 6.4- 12.0] |
| 4 | lead0.2-0.4 | 396 |  97.5% [95.4- 98.6] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |   2.3% [ 1.2-  4.3] |  10.4% [ 7.7- 13.7] |   0.3% [ 0.0-  1.4] |  31.3% [26.9- 36.0] |
| 0 | lead0.2-0.8 | 390 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  16.2% [12.8- 20.1] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.2-0.8 | 390 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  16.4% [13.1- 20.4] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.2-0.8 | 390 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  16.4% [13.1- 20.4] |   0.0% [ 0.0-  1.0] |   1.0% [ 0.4-  2.6] |
| 2 | lead0.2-0.8 | 390 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  16.4% [13.1- 20.4] |   0.0% [ 0.0-  1.0] |   8.2% [ 5.9- 11.4] |
| 4 | lead0.2-0.8 | 390 |  99.0% [97.4- 99.6] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |   0.8% [ 0.3-  2.2] |  16.9% [13.5- 21.0] |   0.3% [ 0.0-  1.4] |  30.0% [25.7- 34.7] |
| 0 | lead0.6-1.2 | 382 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  23.3% [19.3- 27.8] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.6-1.2 | 382 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  23.3% [19.3- 27.8] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.6-1.2 | 382 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  23.3% [19.3- 27.8] |   0.0% [ 0.0-  1.0] |   0.5% [ 0.1-  1.9] |
| 2 | lead0.6-1.2 | 382 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  22.8% [18.9- 27.2] |   0.0% [ 0.0-  1.0] |   8.1% [ 5.8- 11.3] |
| 4 | lead0.6-1.2 | 382 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  22.8% [18.9- 27.2] |   0.0% [ 0.0-  1.0] |  31.4% [27.0- 36.2] |

**adjacent(gap0.1m) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 403 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  14.4% [11.3- 18.2] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.0-0.2 | 403 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  13.9% [10.9- 17.6] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.0-0.2 | 403 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  13.9% [10.9- 17.6] |   0.0% [ 0.0-  0.9] |   0.5% [ 0.1-  1.8] |
| 2 | lead0.0-0.2 | 403 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  12.2% [ 9.3- 15.7] |   0.0% [ 0.0-  0.9] |   6.2% [ 4.2-  9.0] |
| 4 | lead0.0-0.2 | 403 |  92.6% [89.6- 94.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   3.0% [ 1.7-  5.1] |   4.5% [ 2.8-  6.9] |  11.9% [ 9.1- 15.4] |   3.0% [ 1.7-  5.1] |  23.8% [19.9- 28.2] |
| 0 | lead0.2-0.4 | 393 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  38.9% [34.2- 43.8] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.2-0.4 | 393 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  38.7% [34.0- 43.6] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.2-0.4 | 393 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  38.7% [34.0- 43.6] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |
| 2 | lead0.2-0.4 | 393 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  35.4% [30.8- 40.2] |   0.0% [ 0.0-  1.0] |   2.3% [ 1.2-  4.3] |
| 4 | lead0.2-0.4 | 393 |  90.1% [86.7- 92.7] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   7.4% [ 5.2- 10.4] |   2.5% [ 1.4-  4.6] |  29.0% [24.7- 33.7] |   7.4% [ 5.2- 10.4] |  21.6% [17.8- 26.0] |
| 0 | lead0.2-0.8 | 404 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  75.7% [71.3- 79.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.2-0.8 | 404 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  75.7% [71.3- 79.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.2-0.8 | 404 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |
| 2 | lead0.2-0.8 | 404 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |   0.0% [ 0.0-  0.9] |   2.2% [ 1.2-  4.2] |
| 4 | lead0.2-0.8 | 404 |  78.0% [73.7- 81.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  21.0% [17.3- 25.3] |   1.0% [ 0.4-  2.5] |  56.9% [52.1- 61.7] |  21.0% [17.3- 25.3] |  17.3% [13.9- 21.3] |
| 0 | lead0.6-1.2 | 407 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  99.8% [98.6-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.6-1.2 | 407 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  99.8% [98.6-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.6-1.2 | 407 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  99.3% [97.9- 99.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 2 | lead0.6-1.2 | 407 |  98.3% [96.5- 99.2] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   1.7% [ 0.8-  3.5] |   0.0% [ 0.0-  0.9] |  92.1% [89.1- 94.4] |   1.7% [ 0.8-  3.5] |   4.2% [ 2.6-  6.6] |
| 4 | lead0.6-1.2 | 407 |  53.8% [49.0- 58.6] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  46.2% [41.4- 51.0] |   0.0% [ 0.0-  0.9] |  83.0% [79.1- 86.4] |  46.2% [41.4- 51.0] |  20.9% [17.2- 25.1] |

**adjacent(gap0.1m) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 403 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   3.5% [ 2.1-  5.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.0-0.2 | 403 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   3.5% [ 2.1-  5.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.0-0.2 | 403 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   3.5% [ 2.1-  5.7] |   0.0% [ 0.0-  0.9] |   0.5% [ 0.1-  1.8] |
| 2 | lead0.0-0.2 | 403 |  99.3% [97.8- 99.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.7% [ 0.3-  2.2] |   3.5% [ 2.1-  5.7] |   0.0% [ 0.0-  0.9] |   6.2% [ 4.2-  9.0] |
| 4 | lead0.0-0.2 | 403 |  92.3% [89.3- 94.5] |   0.2% [ 0.0-  1.4] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |   7.2% [ 5.1- 10.1] |   4.2% [ 2.7-  6.7] |   0.2% [ 0.0-  1.4] |  23.8% [19.9- 28.2] |
| 0 | lead0.2-0.4 | 393 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  26.0% [21.9- 30.5] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.2-0.4 | 393 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  26.0% [21.9- 30.5] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.2-0.4 | 393 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  26.0% [21.9- 30.5] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |
| 2 | lead0.2-0.4 | 393 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  25.4% [21.4- 30.0] |   0.0% [ 0.0-  1.0] |   2.3% [ 1.2-  4.3] |
| 4 | lead0.2-0.4 | 393 |  98.2% [96.4- 99.1] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |   1.5% [ 0.7-  3.3] |  26.0% [21.9- 30.5] |   0.3% [ 0.0-  1.4] |  21.6% [17.8- 26.0] |
| 0 | lead0.2-0.8 | 404 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  49.8% [44.9- 54.6] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.2-0.8 | 404 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  49.5% [44.7- 54.4] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.2-0.8 | 404 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  49.3% [44.4- 54.1] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |
| 2 | lead0.2-0.8 | 404 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  48.3% [43.4- 53.1] |   0.0% [ 0.0-  0.9] |   2.2% [ 1.2-  4.2] |
| 4 | lead0.2-0.8 | 404 |  99.8% [98.6-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |   0.0% [ 0.0-  0.9] |  47.0% [42.2- 51.9] |   0.2% [ 0.0-  1.4] |  17.3% [13.9- 21.3] |
| 0 | lead0.6-1.2 | 407 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  86.0% [82.3- 89.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.6-1.2 | 407 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  86.5% [82.8- 89.5] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.6-1.2 | 407 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  87.2% [83.6- 90.1] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 2 | lead0.6-1.2 | 407 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  86.5% [82.8- 89.5] |   0.0% [ 0.0-  0.9] |   4.2% [ 2.6-  6.6] |
| 4 | lead0.6-1.2 | 407 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  84.3% [80.4- 87.5] |   0.0% [ 0.0-  0.9] |  20.9% [17.2- 25.1] |

**abutting(gap0m) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 391 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  14.1% [11.0- 17.9] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.0-0.2 | 391 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  14.3% [11.2- 18.1] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.0-0.2 | 391 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  14.3% [11.2- 18.1] |   0.0% [ 0.0-  1.0] |   0.8% [ 0.3-  2.2] |
| 2 | lead0.0-0.2 | 391 |  99.7% [98.6-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |  13.0% [10.1- 16.7] |   0.0% [ 0.0-  1.0] |   6.1% [ 4.2-  9.0] |
| 4 | lead0.0-0.2 | 391 |  89.8% [86.4- 92.4] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   3.6% [ 2.1-  5.9] |   6.6% [ 4.6-  9.6] |  15.3% [12.1- 19.3] |   3.6% [ 2.1-  5.9] |  28.1% [23.9- 32.8] |
| 0 | lead0.2-0.4 | 412 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  52.7% [47.8- 57.4] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.2-0.4 | 412 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  52.9% [48.1- 57.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.2-0.4 | 412 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  52.4% [47.6- 57.2] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |
| 2 | lead0.2-0.4 | 412 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  49.5% [44.7- 54.3] |   0.0% [ 0.0-  0.9] |   4.1% [ 2.6-  6.5] |
| 4 | lead0.2-0.4 | 412 |  90.5% [87.3- 93.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   8.3% [ 6.0- 11.3] |   1.2% [ 0.5-  2.8] |  42.0% [37.3- 46.8] |   8.3% [ 6.0- 11.3] |  19.9% [16.3- 24.0] |
| 0 | lead0.2-0.8 | 387 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  77.3% [72.8- 81.2] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.2-0.8 | 387 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  77.5% [73.1- 81.4] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.2-0.8 | 387 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  77.8% [73.4- 81.6] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 2 | lead0.2-0.8 | 387 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  72.6% [68.0- 76.8] |   0.0% [ 0.0-  1.0] |   4.7% [ 3.0-  7.2] |
| 4 | lead0.2-0.8 | 387 |  79.1% [74.7- 82.8] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  20.4% [16.7- 24.7] |   0.5% [ 0.1-  1.9] |  63.0% [58.1- 67.7] |  20.4% [16.7- 24.7] |  21.2% [17.4- 25.5] |
| 0 | lead0.6-1.2 | 394 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.6-1.2 | 394 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.6-1.2 | 394 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  99.5% [98.2- 99.9] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 2 | lead0.6-1.2 | 394 |  99.7% [98.6-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |   0.0% [ 0.0-  1.0] |  92.9% [89.9- 95.0] |   0.3% [ 0.0-  1.4] |   2.3% [ 1.2-  4.3] |
| 4 | lead0.6-1.2 | 394 |  64.0% [59.1- 68.5] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  35.8% [31.2- 40.6] |   0.3% [ 0.0-  1.4] |  78.7% [74.4- 82.4] |  35.8% [31.2- 40.6] |  17.8% [14.3- 21.8] |

**abutting(gap0m) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 391 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   4.6% [ 2.9-  7.2] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.0-0.2 | 391 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   4.3% [ 2.7-  6.9] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.0-0.2 | 391 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   4.1% [ 2.5-  6.5] |   0.0% [ 0.0-  1.0] |   0.8% [ 0.3-  2.2] |
| 2 | lead0.0-0.2 | 391 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   4.3% [ 2.7-  6.9] |   0.3% [ 0.0-  1.4] |   6.1% [ 4.2-  9.0] |
| 4 | lead0.0-0.2 | 391 |  93.1% [90.1- 95.2] |   0.3% [ 0.0-  1.4] |   0.0% [ 0.0-  1.0] |   1.3% [ 0.5-  3.0] |   5.4% [ 3.5-  8.1] |   5.4% [ 3.5-  8.1] |   1.3% [ 0.5-  3.0] |  28.1% [23.9- 32.8] |
| 0 | lead0.2-0.4 | 412 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  31.1% [26.8- 35.7] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.2-0.4 | 412 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  31.3% [27.0- 35.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.2-0.4 | 412 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  31.8% [27.5- 36.4] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |
| 2 | lead0.2-0.4 | 412 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  31.1% [26.8- 35.7] |   0.0% [ 0.0-  0.9] |   4.1% [ 2.6-  6.5] |
| 4 | lead0.2-0.4 | 412 |  98.1% [96.2- 99.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   1.9% [ 1.0-  3.8] |  30.1% [25.9- 34.7] |   0.0% [ 0.0-  0.9] |  19.9% [16.3- 24.0] |
| 0 | lead0.2-0.8 | 387 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  67.4% [62.6- 71.9] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.2-0.8 | 387 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  67.2% [62.4- 71.7] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.2-0.8 | 387 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  67.4% [62.6- 71.9] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 2 | lead0.2-0.8 | 387 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  67.4% [62.6- 71.9] |   0.0% [ 0.0-  1.0] |   4.7% [ 3.0-  7.2] |
| 4 | lead0.2-0.8 | 387 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  66.7% [61.8- 71.2] |   0.0% [ 0.0-  1.0] |  21.2% [17.4- 25.5] |
| 0 | lead0.6-1.2 | 394 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  97.0% [94.8- 98.2] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.6-1.2 | 394 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  97.0% [94.8- 98.2] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.6-1.2 | 394 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  96.7% [94.4- 98.1] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 2 | lead0.6-1.2 | 394 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  96.2% [93.8- 97.7] |   0.0% [ 0.0-  1.0] |   2.3% [ 1.2-  4.3] |
| 4 | lead0.6-1.2 | 394 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  96.4% [94.1- 97.9] |   0.0% [ 0.0-  1.0] |  17.8% [14.3- 21.8] |

**mixed(2adj+2far) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  10.4% [ 7.7- 13.7] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.0-0.2 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  10.1% [ 7.5- 13.5] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.0-0.2 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   9.8% [ 7.3- 13.2] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |
| 2 | lead0.0-0.2 | 396 |  99.7% [98.6-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |   8.1% [ 5.8- 11.2] |   0.0% [ 0.0-  1.0] |   8.8% [ 6.4- 12.0] |
| 4 | lead0.0-0.2 | 396 |  66.7% [61.9- 71.1] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   1.3% [ 0.5-  2.9] |  32.1% [27.7- 36.8] |   4.5% [ 2.9-  7.1] |   1.3% [ 0.5-  2.9] |  33.1% [28.6- 37.9] |
| 0 | lead0.2-0.4 | 411 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  48.4% [43.6- 53.2] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.2-0.4 | 411 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  48.7% [43.9- 53.5] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.2-0.4 | 411 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  48.7% [43.9- 53.5] |   0.0% [ 0.0-  0.9] |   1.0% [ 0.4-  2.5] |
| 2 | lead0.2-0.4 | 411 |  97.1% [95.0- 98.3] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   2.2% [ 1.2-  4.1] |   0.7% [ 0.2-  2.1] |  42.6% [37.9- 47.4] |   2.2% [ 1.2-  4.1] |   6.8% [ 4.8-  9.7] |
| 4 | lead0.2-0.4 | 411 |  57.7% [52.8- 62.3] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  17.5% [14.1- 21.5] |  24.8% [20.9- 29.2] |  33.3% [28.9- 38.0] |  17.5% [14.1- 21.5] |  33.6% [29.2- 38.3] |
| 0 | lead0.2-0.8 | 383 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  77.0% [72.6- 81.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.2-0.8 | 383 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  77.3% [72.8- 81.2] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.2-0.8 | 383 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   0.0% [ 0.0-  1.0] |   1.0% [ 0.4-  2.7] |
| 2 | lead0.2-0.8 | 383 |  92.4% [89.3- 94.7] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   7.3% [ 5.1- 10.4] |   0.3% [ 0.0-  1.5] |  64.5% [59.6- 69.1] |   7.3% [ 5.1- 10.4] |   9.4% [ 6.9- 12.7] |
| 4 | lead0.2-0.8 | 383 |  39.2% [34.4- 44.1] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  44.6% [39.7- 49.7] |  16.2% [12.8- 20.2] |  59.0% [54.0- 63.8] |  44.6% [39.7- 49.7] |  35.8% [31.1- 40.7] |
| 0 | lead0.6-1.2 | 397 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  99.5% [98.2- 99.9] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.6-1.2 | 397 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  99.5% [98.2- 99.9] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.6-1.2 | 397 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  97.5% [95.4- 98.6] |   0.0% [ 0.0-  1.0] |   1.0% [ 0.4-  2.6] |
| 2 | lead0.6-1.2 | 397 |  87.4% [83.8- 90.3] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  12.6% [ 9.7- 16.2] |   0.0% [ 0.0-  1.0] |  85.9% [82.1- 89.0] |  12.6% [ 9.7- 16.2] |   7.3% [ 5.1- 10.3] |
| 4 | lead0.6-1.2 | 397 |  32.2% [27.8- 37.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  67.0% [62.2- 71.4] |   0.8% [ 0.3-  2.2] |  85.4% [81.6- 88.5] |  67.0% [62.2- 71.4] |  31.2% [26.9- 36.0] |

**mixed(2adj+2far) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   1.8% [ 0.9-  3.6] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.0-0.2 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   1.8% [ 0.9-  3.6] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.0-0.2 | 396 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   1.8% [ 0.9-  3.6] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |
| 2 | lead0.0-0.2 | 396 |  98.2% [96.4- 99.1] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   1.8% [ 0.9-  3.6] |   1.8% [ 0.9-  3.6] |   0.0% [ 0.0-  1.0] |   8.8% [ 6.4- 12.0] |
| 4 | lead0.0-0.2 | 396 |  86.6% [82.9- 89.6] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.8% [ 0.3-  2.2] |  12.6% [ 9.7- 16.3] |   2.5% [ 1.4-  4.6] |   0.8% [ 0.3-  2.2] |  33.1% [28.6- 37.9] |
| 0 | lead0.2-0.4 | 411 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  14.1% [11.1- 17.8] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 0.5 | lead0.2-0.4 | 411 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  14.1% [11.1- 17.8] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |
| 1 | lead0.2-0.4 | 411 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |  14.1% [11.1- 17.8] |   0.0% [ 0.0-  0.9] |   1.0% [ 0.4-  2.5] |
| 2 | lead0.2-0.4 | 411 |  99.8% [98.6-100.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |  14.1% [11.1- 17.8] |   0.0% [ 0.0-  0.9] |   6.8% [ 4.8-  9.7] |
| 4 | lead0.2-0.4 | 411 |  96.6% [94.4- 98.0] |   0.0% [ 0.0-  0.9] |   0.0% [ 0.0-  0.9] |   0.2% [ 0.0-  1.4] |   3.2% [ 1.9-  5.3] |  13.6% [10.6- 17.3] |   0.2% [ 0.0-  1.4] |  33.6% [29.2- 38.3] |
| 0 | lead0.2-0.8 | 383 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  25.6% [21.5- 30.2] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.2-0.8 | 383 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  25.6% [21.5- 30.2] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.2-0.8 | 383 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  25.8% [21.7- 30.5] |   0.0% [ 0.0-  1.0] |   1.0% [ 0.4-  2.7] |
| 2 | lead0.2-0.8 | 383 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  24.8% [20.7- 29.4] |   0.0% [ 0.0-  1.0] |   9.4% [ 6.9- 12.7] |
| 4 | lead0.2-0.8 | 383 |  99.2% [97.7- 99.7] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.8% [ 0.3-  2.3] |  24.5% [20.5- 29.1] |   0.0% [ 0.0-  1.0] |  35.8% [31.1- 40.7] |
| 0 | lead0.6-1.2 | 397 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  36.5% [31.9- 41.4] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 0.5 | lead0.6-1.2 | 397 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  37.3% [32.7- 42.1] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |
| 1 | lead0.6-1.2 | 397 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  37.0% [32.4- 41.9] |   0.0% [ 0.0-  1.0] |   1.0% [ 0.4-  2.6] |
| 2 | lead0.6-1.2 | 397 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |  36.5% [31.9- 41.4] |   0.0% [ 0.0-  1.0] |   7.3% [ 5.1- 10.3] |
| 4 | lead0.6-1.2 | 397 |  99.7% [98.6-100.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.0% [ 0.0-  1.0] |   0.3% [ 0.0-  1.4] |  36.5% [31.9- 41.4] |   0.0% [ 0.0-  1.0] |  31.2% [26.9- 36.0] |

### Grid: look_away_prob=0.2, LOOK-AWAY stratum (eyes had moved on before the word)

**far(gap1.0m) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 95 |   0.0% [ 0.0-  3.9] |  15.8% [ 9.8- 24.4] |  15.8% [ 9.8- 24.4] |  84.2% [75.6- 90.2] |   0.0% [ 0.0-  3.9] |  84.2% [75.6- 90.2] |  84.2% [75.6- 90.2] | 100.0% [96.1-100.0] |
| 0.5 | lead0.0-0.2 | 95 |   0.0% [ 0.0-  3.9] |  17.9% [11.5- 26.8] |  17.9% [11.5- 26.8] |  82.1% [73.2- 88.5] |   0.0% [ 0.0-  3.9] |  82.1% [73.2- 88.5] |  82.1% [73.2- 88.5] | 100.0% [96.1-100.0] |
| 1 | lead0.0-0.2 | 95 |   0.0% [ 0.0-  3.9] |  15.8% [ 9.8- 24.4] |  15.8% [ 9.8- 24.4] |  84.2% [75.6- 90.2] |   0.0% [ 0.0-  3.9] |  84.2% [75.6- 90.2] |  84.2% [75.6- 90.2] | 100.0% [96.1-100.0] |
| 2 | lead0.0-0.2 | 95 |   0.0% [ 0.0-  3.9] |   7.4% [ 3.6- 14.4] |   7.4% [ 3.6- 14.4] |  92.6% [85.6- 96.4] |   0.0% [ 0.0-  3.9] |  92.6% [85.6- 96.4] |  92.6% [85.6- 96.4] | 100.0% [96.1-100.0] |
| 4 | lead0.0-0.2 | 95 |   0.0% [ 0.0-  3.9] |   0.0% [ 0.0-  3.9] |   0.0% [ 0.0-  3.9] | 100.0% [96.1-100.0] |   0.0% [ 0.0-  3.9] | 100.0% [96.1-100.0] | 100.0% [96.1-100.0] | 100.0% [96.1-100.0] |
| 0 | lead0.2-0.4 | 104 |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] | 100.0% [96.4-100.0] |   0.0% [ 0.0-  3.6] | 100.0% [96.4-100.0] | 100.0% [96.4-100.0] | 100.0% [96.4-100.0] |
| 0.5 | lead0.2-0.4 | 104 |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] | 100.0% [96.4-100.0] |   0.0% [ 0.0-  3.6] | 100.0% [96.4-100.0] | 100.0% [96.4-100.0] | 100.0% [96.4-100.0] |
| 1 | lead0.2-0.4 | 104 |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] | 100.0% [96.4-100.0] |   0.0% [ 0.0-  3.6] | 100.0% [96.4-100.0] | 100.0% [96.4-100.0] | 100.0% [96.4-100.0] |
| 2 | lead0.2-0.4 | 104 |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] | 100.0% [96.4-100.0] |   0.0% [ 0.0-  3.6] | 100.0% [96.4-100.0] | 100.0% [96.4-100.0] | 100.0% [96.4-100.0] |
| 4 | lead0.2-0.4 | 104 |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] | 100.0% [96.4-100.0] |   0.0% [ 0.0-  3.6] | 100.0% [96.4-100.0] | 100.0% [96.4-100.0] | 100.0% [96.4-100.0] |
| 0 | lead0.2-0.8 | 110 |   0.0% [ 0.0-  3.4] |  25.5% [18.2- 34.3] |  25.5% [18.2- 34.3] |  74.5% [65.7- 81.8] |   0.0% [ 0.0-  3.4] |  74.5% [65.7- 81.8] |  74.5% [65.7- 81.8] | 100.0% [96.6-100.0] |
| 0.5 | lead0.2-0.8 | 110 |   0.0% [ 0.0-  3.4] |  25.5% [18.2- 34.3] |  25.5% [18.2- 34.3] |  74.5% [65.7- 81.8] |   0.0% [ 0.0-  3.4] |  74.5% [65.7- 81.8] |  74.5% [65.7- 81.8] | 100.0% [96.6-100.0] |
| 1 | lead0.2-0.8 | 110 |   0.0% [ 0.0-  3.4] |  25.5% [18.2- 34.3] |  25.5% [18.2- 34.3] |  74.5% [65.7- 81.8] |   0.0% [ 0.0-  3.4] |  74.5% [65.7- 81.8] |  74.5% [65.7- 81.8] | 100.0% [96.6-100.0] |
| 2 | lead0.2-0.8 | 110 |   0.0% [ 0.0-  3.4] |  21.8% [15.1- 30.4] |  21.8% [15.1- 30.4] |  78.2% [69.6- 84.9] |   0.0% [ 0.0-  3.4] |  78.2% [69.6- 84.9] |  78.2% [69.6- 84.9] | 100.0% [96.6-100.0] |
| 4 | lead0.2-0.8 | 110 |   0.0% [ 0.0-  3.4] |   9.1% [ 5.0- 15.9] |   9.1% [ 5.0- 15.9] |  90.0% [83.0- 94.3] |   0.9% [ 0.2-  5.0] |  90.0% [83.0- 94.3] |  90.0% [83.0- 94.3] | 100.0% [96.6-100.0] |
| 0 | lead0.6-1.2 | 118 |   0.0% [ 0.0-  3.2] |  69.5% [60.7- 77.1] |  69.5% [60.7- 77.1] |  30.5% [22.9- 39.3] |   0.0% [ 0.0-  3.2] |  30.5% [22.9- 39.3] |  30.5% [22.9- 39.3] | 100.0% [96.8-100.0] |
| 0.5 | lead0.6-1.2 | 118 |   0.0% [ 0.0-  3.2] |  69.5% [60.7- 77.1] |  69.5% [60.7- 77.1] |  30.5% [22.9- 39.3] |   0.0% [ 0.0-  3.2] |  30.5% [22.9- 39.3] |  30.5% [22.9- 39.3] | 100.0% [96.8-100.0] |
| 1 | lead0.6-1.2 | 118 |   0.0% [ 0.0-  3.2] |  69.5% [60.7- 77.1] |  69.5% [60.7- 77.1] |  30.5% [22.9- 39.3] |   0.0% [ 0.0-  3.2] |  30.5% [22.9- 39.3] |  30.5% [22.9- 39.3] | 100.0% [96.8-100.0] |
| 2 | lead0.6-1.2 | 118 |   0.0% [ 0.0-  3.2] |  66.9% [58.0- 74.8] |  66.9% [58.0- 74.8] |  33.1% [25.2- 42.0] |   0.0% [ 0.0-  3.2] |  33.1% [25.2- 42.0] |  33.1% [25.2- 42.0] | 100.0% [96.8-100.0] |
| 4 | lead0.6-1.2 | 118 |   0.0% [ 0.0-  3.2] |  46.6% [37.9- 55.6] |  46.6% [37.9- 55.6] |  50.0% [41.1- 58.9] |   3.4% [ 1.3-  8.4] |  50.0% [41.1- 58.9] |  50.0% [41.1- 58.9] | 100.0% [96.8-100.0] |

**far(gap1.0m) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 95 |   4.2% [ 1.6- 10.3] |   0.0% [ 0.0-  3.9] |   0.0% [ 0.0-  3.9] |  62.1% [52.1- 71.2] |  33.7% [25.0- 43.7] |  63.2% [53.1- 72.2] |  62.1% [52.1- 71.2] | 100.0% [96.1-100.0] |
| 0.5 | lead0.0-0.2 | 95 |   4.2% [ 1.6- 10.3] |   0.0% [ 0.0-  3.9] |   0.0% [ 0.0-  3.9] |  62.1% [52.1- 71.2] |  33.7% [25.0- 43.7] |  63.2% [53.1- 72.2] |  62.1% [52.1- 71.2] | 100.0% [96.1-100.0] |
| 1 | lead0.0-0.2 | 95 |   4.2% [ 1.6- 10.3] |   0.0% [ 0.0-  3.9] |   0.0% [ 0.0-  3.9] |  62.1% [52.1- 71.2] |  33.7% [25.0- 43.7] |  63.2% [53.1- 72.2] |  62.1% [52.1- 71.2] | 100.0% [96.1-100.0] |
| 2 | lead0.0-0.2 | 95 |   5.3% [ 2.3- 11.7] |   0.0% [ 0.0-  3.9] |   0.0% [ 0.0-  3.9] |  62.1% [52.1- 71.2] |  32.6% [24.0- 42.6] |  63.2% [53.1- 72.2] |  62.1% [52.1- 71.2] | 100.0% [96.1-100.0] |
| 4 | lead0.0-0.2 | 95 |   3.2% [ 1.1-  8.9] |   0.0% [ 0.0-  3.9] |   0.0% [ 0.0-  3.9] |  60.0% [49.9- 69.3] |  36.8% [27.8- 46.9] |  60.0% [49.9- 69.3] |  60.0% [49.9- 69.3] | 100.0% [96.1-100.0] |
| 0 | lead0.2-0.4 | 104 |  19.2% [12.8- 27.8] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |  46.2% [36.9- 55.7] |  34.6% [26.2- 44.2] |  48.1% [38.7- 57.6] |  46.2% [36.9- 55.7] | 100.0% [96.4-100.0] |
| 0.5 | lead0.2-0.4 | 104 |  18.3% [12.0- 26.8] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |  45.2% [36.0- 54.8] |  36.5% [27.9- 46.1] |  47.1% [37.8- 56.6] |  45.2% [36.0- 54.8] | 100.0% [96.4-100.0] |
| 1 | lead0.2-0.4 | 104 |  17.3% [11.2- 25.7] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |  45.2% [36.0- 54.8] |  37.5% [28.8- 47.1] |  46.2% [36.9- 55.7] |  45.2% [36.0- 54.8] | 100.0% [96.4-100.0] |
| 2 | lead0.2-0.4 | 104 |  16.3% [10.5- 24.6] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |  46.2% [36.9- 55.7] |  37.5% [28.8- 47.1] |  47.1% [37.8- 56.6] |  46.2% [36.9- 55.7] | 100.0% [96.4-100.0] |
| 4 | lead0.2-0.4 | 104 |  15.4% [ 9.7- 23.5] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |  47.1% [37.8- 56.6] |  37.5% [28.8- 47.1] |  49.0% [39.6- 58.5] |  47.1% [37.8- 56.6] | 100.0% [96.4-100.0] |
| 0 | lead0.2-0.8 | 110 |  11.8% [ 7.0- 19.2] |   3.6% [ 1.4-  9.0] |   3.6% [ 1.4-  9.0] |  60.9% [51.6- 69.5] |  23.6% [16.7- 32.4] |  60.9% [51.6- 69.5] |  60.9% [51.6- 69.5] | 100.0% [96.6-100.0] |
| 0.5 | lead0.2-0.8 | 110 |  11.8% [ 7.0- 19.2] |   3.6% [ 1.4-  9.0] |   3.6% [ 1.4-  9.0] |  60.9% [51.6- 69.5] |  23.6% [16.7- 32.4] |  60.9% [51.6- 69.5] |  60.9% [51.6- 69.5] | 100.0% [96.6-100.0] |
| 1 | lead0.2-0.8 | 110 |  10.9% [ 6.4- 18.1] |   3.6% [ 1.4-  9.0] |   3.6% [ 1.4-  9.0] |  61.8% [52.5- 70.4] |  23.6% [16.7- 32.4] |  61.8% [52.5- 70.4] |  61.8% [52.5- 70.4] | 100.0% [96.6-100.0] |
| 2 | lead0.2-0.8 | 110 |  10.9% [ 6.4- 18.1] |   2.7% [ 0.9-  7.7] |   2.7% [ 0.9-  7.7] |  62.7% [53.4- 71.2] |  23.6% [16.7- 32.4] |  62.7% [53.4- 71.2] |  62.7% [53.4- 71.2] | 100.0% [96.6-100.0] |
| 4 | lead0.2-0.8 | 110 |  10.0% [ 5.7- 17.0] |   2.7% [ 0.9-  7.7] |   2.7% [ 0.9-  7.7] |  61.8% [52.5- 70.4] |  25.5% [18.2- 34.3] |  61.8% [52.5- 70.4] |  61.8% [52.5- 70.4] | 100.0% [96.6-100.0] |
| 0 | lead0.6-1.2 | 118 |   4.2% [ 1.8-  9.5] |  25.4% [18.4- 34.0] |  25.4% [18.4- 34.0] |  61.0% [52.0- 69.3] |   9.3% [ 5.3- 15.9] |  61.9% [52.9- 70.1] |  61.0% [52.0- 69.3] | 100.0% [96.8-100.0] |
| 0.5 | lead0.6-1.2 | 118 |   4.2% [ 1.8-  9.5] |  25.4% [18.4- 34.0] |  25.4% [18.4- 34.0] |  61.0% [52.0- 69.3] |   9.3% [ 5.3- 15.9] |  61.9% [52.9- 70.1] |  61.0% [52.0- 69.3] | 100.0% [96.8-100.0] |
| 1 | lead0.6-1.2 | 118 |   4.2% [ 1.8-  9.5] |  25.4% [18.4- 34.0] |  25.4% [18.4- 34.0] |  60.2% [51.2- 68.5] |  10.2% [ 5.9- 16.9] |  61.0% [52.0- 69.3] |  60.2% [51.2- 68.5] | 100.0% [96.8-100.0] |
| 2 | lead0.6-1.2 | 118 |   4.2% [ 1.8-  9.5] |  22.9% [16.2- 31.2] |  22.9% [16.2- 31.2] |  63.6% [54.6- 71.7] |   9.3% [ 5.3- 15.9] |  64.4% [55.4- 72.5] |  63.6% [54.6- 71.7] | 100.0% [96.8-100.0] |
| 4 | lead0.6-1.2 | 118 |   5.1% [ 2.4- 10.7] |  23.7% [17.0- 32.2] |  23.7% [17.0- 32.2] |  61.9% [52.9- 70.1] |   9.3% [ 5.3- 15.9] |  62.7% [53.7- 70.9] |  61.9% [52.9- 70.1] | 100.0% [96.8-100.0] |

**adjacent(gap0.1m) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 97 |   0.0% [ 0.0-  3.8] |  67.0% [57.2- 75.6] |  57.7% [47.8- 67.1] |  33.0% [24.4- 42.8] |   0.0% [ 0.0-  3.8] |  42.3% [32.9- 52.2] |  42.3% [32.9- 52.2] | 100.0% [96.2-100.0] |
| 0.5 | lead0.0-0.2 | 97 |   0.0% [ 0.0-  3.8] |  67.0% [57.2- 75.6] |  57.7% [47.8- 67.1] |  33.0% [24.4- 42.8] |   0.0% [ 0.0-  3.8] |  42.3% [32.9- 52.2] |  42.3% [32.9- 52.2] | 100.0% [96.2-100.0] |
| 1 | lead0.0-0.2 | 97 |   0.0% [ 0.0-  3.8] |  62.9% [53.0- 71.8] |  53.6% [43.7- 63.2] |  37.1% [28.2- 47.0] |   0.0% [ 0.0-  3.8] |  46.4% [36.8- 56.3] |  46.4% [36.8- 56.3] | 100.0% [96.2-100.0] |
| 2 | lead0.0-0.2 | 97 |   0.0% [ 0.0-  3.8] |  37.1% [28.2- 47.0] |  34.0% [25.4- 43.9] |  62.9% [53.0- 71.8] |   0.0% [ 0.0-  3.8] |  66.0% [56.1- 74.6] |  66.0% [56.1- 74.6] | 100.0% [96.2-100.0] |
| 4 | lead0.0-0.2 | 97 |   0.0% [ 0.0-  3.8] |   4.1% [ 1.6- 10.1] |   4.1% [ 1.6- 10.1] |  95.9% [89.9- 98.4] |   0.0% [ 0.0-  3.8] |  95.9% [89.9- 98.4] |  95.9% [89.9- 98.4] | 100.0% [96.2-100.0] |
| 0 | lead0.2-0.4 | 107 |   0.0% [ 0.0-  3.5] |   3.7% [ 1.5-  9.2] |   0.9% [ 0.2-  5.1] |  96.3% [90.8- 98.5] |   0.0% [ 0.0-  3.5] |  99.1% [94.9- 99.8] |  99.1% [94.9- 99.8] | 100.0% [96.5-100.0] |
| 0.5 | lead0.2-0.4 | 107 |   0.0% [ 0.0-  3.5] |   1.9% [ 0.5-  6.6] |   0.9% [ 0.2-  5.1] |  98.1% [93.4- 99.5] |   0.0% [ 0.0-  3.5] |  99.1% [94.9- 99.8] |  99.1% [94.9- 99.8] | 100.0% [96.5-100.0] |
| 1 | lead0.2-0.4 | 107 |   0.0% [ 0.0-  3.5] |   2.8% [ 1.0-  7.9] |   0.9% [ 0.2-  5.1] |  97.2% [92.1- 99.0] |   0.0% [ 0.0-  3.5] |  99.1% [94.9- 99.8] |  99.1% [94.9- 99.8] | 100.0% [96.5-100.0] |
| 2 | lead0.2-0.4 | 107 |   0.0% [ 0.0-  3.5] |   2.8% [ 1.0-  7.9] |   1.9% [ 0.5-  6.6] |  97.2% [92.1- 99.0] |   0.0% [ 0.0-  3.5] |  98.1% [93.4- 99.5] |  98.1% [93.4- 99.5] | 100.0% [96.5-100.0] |
| 4 | lead0.2-0.4 | 107 |   0.0% [ 0.0-  3.5] |   0.0% [ 0.0-  3.5] |   0.0% [ 0.0-  3.5] | 100.0% [96.5-100.0] |   0.0% [ 0.0-  3.5] | 100.0% [96.5-100.0] | 100.0% [96.5-100.0] |  99.1% [94.9- 99.8] |
| 0 | lead0.2-0.8 | 96 |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |   0.0% [ 0.0-  3.8] |  78.1% [68.9- 85.2] |  78.1% [68.9- 85.2] | 100.0% [96.2-100.0] |
| 0.5 | lead0.2-0.8 | 96 |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |   0.0% [ 0.0-  3.8] |  78.1% [68.9- 85.2] |  78.1% [68.9- 85.2] | 100.0% [96.2-100.0] |
| 1 | lead0.2-0.8 | 96 |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |   0.0% [ 0.0-  3.8] |  78.1% [68.9- 85.2] |  78.1% [68.9- 85.2] | 100.0% [96.2-100.0] |
| 2 | lead0.2-0.8 | 96 |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |   0.0% [ 0.0-  3.8] |  78.1% [68.9- 85.2] |  78.1% [68.9- 85.2] | 100.0% [96.2-100.0] |
| 4 | lead0.2-0.8 | 96 |   0.0% [ 0.0-  3.8] |  17.7% [11.4- 26.5] |  16.7% [10.5- 25.4] |  82.3% [73.5- 88.6] |   0.0% [ 0.0-  3.8] |  83.3% [74.6- 89.5] |  82.3% [73.5- 88.6] | 100.0% [96.2-100.0] |
| 0 | lead0.6-1.2 | 93 |   0.0% [ 0.0-  4.0] |  73.1% [63.3- 81.1] |  72.0% [62.2- 80.1] |  26.9% [18.9- 36.7] |   0.0% [ 0.0-  4.0] |  28.0% [19.9- 37.8] |  28.0% [19.9- 37.8] | 100.0% [96.0-100.0] |
| 0.5 | lead0.6-1.2 | 93 |   0.0% [ 0.0-  4.0] |  73.1% [63.3- 81.1] |  72.0% [62.2- 80.1] |  26.9% [18.9- 36.7] |   0.0% [ 0.0-  4.0] |  28.0% [19.9- 37.8] |  28.0% [19.9- 37.8] | 100.0% [96.0-100.0] |
| 1 | lead0.6-1.2 | 93 |   0.0% [ 0.0-  4.0] |  72.0% [62.2- 80.1] |  72.0% [62.2- 80.1] |  28.0% [19.9- 37.8] |   0.0% [ 0.0-  4.0] |  28.0% [19.9- 37.8] |  28.0% [19.9- 37.8] | 100.0% [96.0-100.0] |
| 2 | lead0.6-1.2 | 93 |   0.0% [ 0.0-  4.0] |  72.0% [62.2- 80.1] |  72.0% [62.2- 80.1] |  28.0% [19.9- 37.8] |   0.0% [ 0.0-  4.0] |  28.0% [19.9- 37.8] |  28.0% [19.9- 37.8] | 100.0% [96.0-100.0] |
| 4 | lead0.6-1.2 | 93 |   0.0% [ 0.0-  4.0] |  54.8% [44.7- 64.6] |  54.8% [44.7- 64.6] |  43.0% [33.4- 53.2] |   2.2% [ 0.6-  7.5] |  43.0% [33.4- 53.2] |  43.0% [33.4- 53.2] | 100.0% [96.0-100.0] |

**adjacent(gap0.1m) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 97 |  59.8% [49.8- 69.0] |   0.0% [ 0.0-  3.8] |   0.0% [ 0.0-  3.8] |  40.2% [31.0- 50.2] |   0.0% [ 0.0-  3.8] |  99.0% [94.4- 99.8] |  40.2% [31.0- 50.2] | 100.0% [96.2-100.0] |
| 0.5 | lead0.0-0.2 | 97 |  59.8% [49.8- 69.0] |   0.0% [ 0.0-  3.8] |   0.0% [ 0.0-  3.8] |  40.2% [31.0- 50.2] |   0.0% [ 0.0-  3.8] |  99.0% [94.4- 99.8] |  40.2% [31.0- 50.2] | 100.0% [96.2-100.0] |
| 1 | lead0.0-0.2 | 97 |  61.9% [51.9- 70.9] |   0.0% [ 0.0-  3.8] |   0.0% [ 0.0-  3.8] |  38.1% [29.1- 48.1] |   0.0% [ 0.0-  3.8] |  99.0% [94.4- 99.8] |  38.1% [29.1- 48.1] | 100.0% [96.2-100.0] |
| 2 | lead0.0-0.2 | 97 |  60.8% [50.9- 69.9] |   0.0% [ 0.0-  3.8] |   0.0% [ 0.0-  3.8] |  39.2% [30.1- 49.1] |   0.0% [ 0.0-  3.8] | 100.0% [96.2-100.0] |  39.2% [30.1- 49.1] | 100.0% [96.2-100.0] |
| 4 | lead0.0-0.2 | 97 |  48.5% [38.8- 58.3] |   0.0% [ 0.0-  3.8] |   0.0% [ 0.0-  3.8] |  51.5% [41.7- 61.2] |   0.0% [ 0.0-  3.8] | 100.0% [96.2-100.0] |  51.5% [41.7- 61.2] | 100.0% [96.2-100.0] |
| 0 | lead0.2-0.4 | 107 |  62.6% [53.2- 71.2] |   0.0% [ 0.0-  3.5] |   0.0% [ 0.0-  3.5] |  37.4% [28.8- 46.8] |   0.0% [ 0.0-  3.5] |  88.8% [81.4- 93.5] |  37.4% [28.8- 46.8] | 100.0% [96.5-100.0] |
| 0.5 | lead0.2-0.4 | 107 |  62.6% [53.2- 71.2] |   0.0% [ 0.0-  3.5] |   0.0% [ 0.0-  3.5] |  37.4% [28.8- 46.8] |   0.0% [ 0.0-  3.5] |  88.8% [81.4- 93.5] |  37.4% [28.8- 46.8] | 100.0% [96.5-100.0] |
| 1 | lead0.2-0.4 | 107 |  62.6% [53.2- 71.2] |   0.0% [ 0.0-  3.5] |   0.0% [ 0.0-  3.5] |  37.4% [28.8- 46.8] |   0.0% [ 0.0-  3.5] |  86.9% [79.2- 92.0] |  37.4% [28.8- 46.8] | 100.0% [96.5-100.0] |
| 2 | lead0.2-0.4 | 107 |  62.6% [53.2- 71.2] |   0.0% [ 0.0-  3.5] |   0.0% [ 0.0-  3.5] |  37.4% [28.8- 46.8] |   0.0% [ 0.0-  3.5] |  86.9% [79.2- 92.0] |  37.4% [28.8- 46.8] | 100.0% [96.5-100.0] |
| 4 | lead0.2-0.4 | 107 |  59.8% [50.3- 68.6] |   0.0% [ 0.0-  3.5] |   0.0% [ 0.0-  3.5] |  39.3% [30.5- 48.7] |   0.9% [ 0.2-  5.1] |  85.0% [77.1- 90.6] |  39.3% [30.5- 48.7] |  99.1% [94.9- 99.8] |
| 0 | lead0.2-0.8 | 96 |  62.5% [52.5- 71.5] |  11.5% [ 6.5- 19.4] |  11.5% [ 6.5- 19.4] |  26.0% [18.3- 35.6] |   0.0% [ 0.0-  3.8] |  74.0% [64.4- 81.7] |  26.0% [18.3- 35.6] | 100.0% [96.2-100.0] |
| 0.5 | lead0.2-0.8 | 96 |  62.5% [52.5- 71.5] |  11.5% [ 6.5- 19.4] |  11.5% [ 6.5- 19.4] |  26.0% [18.3- 35.6] |   0.0% [ 0.0-  3.8] |  75.0% [65.5- 82.6] |  26.0% [18.3- 35.6] | 100.0% [96.2-100.0] |
| 1 | lead0.2-0.8 | 96 |  61.5% [51.5- 70.6] |  11.5% [ 6.5- 19.4] |  11.5% [ 6.5- 19.4] |  27.1% [19.2- 36.7] |   0.0% [ 0.0-  3.8] |  76.0% [66.6- 83.5] |  27.1% [19.2- 36.7] | 100.0% [96.2-100.0] |
| 2 | lead0.2-0.8 | 96 |  59.4% [49.4- 68.7] |  11.5% [ 6.5- 19.4] |  11.5% [ 6.5- 19.4] |  29.2% [21.0- 38.9] |   0.0% [ 0.0-  3.8] |  77.1% [67.7- 84.4] |  29.2% [21.0- 38.9] | 100.0% [96.2-100.0] |
| 4 | lead0.2-0.8 | 96 |  58.3% [48.3- 67.7] |  11.5% [ 6.5- 19.4] |  11.5% [ 6.5- 19.4] |  29.2% [21.0- 38.9] |   1.0% [ 0.2-  5.7] |  76.0% [66.6- 83.5] |  29.2% [21.0- 38.9] | 100.0% [96.2-100.0] |
| 0 | lead0.6-1.2 | 93 |  22.6% [15.3- 32.1] |  50.5% [40.6- 60.5] |  50.5% [40.6- 60.5] |  26.9% [18.9- 36.7] |   0.0% [ 0.0-  4.0] |  45.2% [35.4- 55.3] |  26.9% [18.9- 36.7] | 100.0% [96.0-100.0] |
| 0.5 | lead0.6-1.2 | 93 |  22.6% [15.3- 32.1] |  50.5% [40.6- 60.5] |  50.5% [40.6- 60.5] |  26.9% [18.9- 36.7] |   0.0% [ 0.0-  4.0] |  44.1% [34.4- 54.2] |  26.9% [18.9- 36.7] | 100.0% [96.0-100.0] |
| 1 | lead0.6-1.2 | 93 |  22.6% [15.3- 32.1] |  50.5% [40.6- 60.5] |  50.5% [40.6- 60.5] |  26.9% [18.9- 36.7] |   0.0% [ 0.0-  4.0] |  44.1% [34.4- 54.2] |  26.9% [18.9- 36.7] | 100.0% [96.0-100.0] |
| 2 | lead0.6-1.2 | 93 |  21.5% [14.4- 30.9] |  49.5% [39.5- 59.4] |  49.5% [39.5- 59.4] |  29.0% [20.8- 38.9] |   0.0% [ 0.0-  4.0] |  47.3% [37.5- 57.4] |  29.0% [20.8- 38.9] | 100.0% [96.0-100.0] |
| 4 | lead0.6-1.2 | 93 |  21.5% [14.4- 30.9] |  49.5% [39.5- 59.4] |  49.5% [39.5- 59.4] |  29.0% [20.8- 38.9] |   0.0% [ 0.0-  4.0] |  47.3% [37.5- 57.4] |  29.0% [20.8- 38.9] | 100.0% [96.0-100.0] |

**abutting(gap0m) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 109 |   0.0% [ 0.0-  3.4] |  74.3% [65.4- 81.6] |  49.5% [40.3- 58.8] |  25.7% [18.4- 34.6] |   0.0% [ 0.0-  3.4] |  50.5% [41.2- 59.7] |  50.5% [41.2- 59.7] | 100.0% [96.6-100.0] |
| 0.5 | lead0.0-0.2 | 109 |   0.0% [ 0.0-  3.4] |  78.9% [70.3- 85.5] |  51.4% [42.1- 60.6] |  21.1% [14.5- 29.7] |   0.0% [ 0.0-  3.4] |  48.6% [39.4- 57.9] |  48.6% [39.4- 57.9] | 100.0% [96.6-100.0] |
| 1 | lead0.0-0.2 | 109 |   0.0% [ 0.0-  3.4] |  79.8% [71.3- 86.3] |  55.0% [45.7- 64.1] |  20.2% [13.7- 28.7] |   0.0% [ 0.0-  3.4] |  45.0% [35.9- 54.3] |  45.0% [35.9- 54.3] | 100.0% [96.6-100.0] |
| 2 | lead0.0-0.2 | 109 |   0.0% [ 0.0-  3.4] |  45.0% [35.9- 54.3] |  35.8% [27.4- 45.1] |  55.0% [45.7- 64.1] |   0.0% [ 0.0-  3.4] |  64.2% [54.9- 72.6] |  64.2% [54.9- 72.6] | 100.0% [96.6-100.0] |
| 4 | lead0.0-0.2 | 109 |   0.0% [ 0.0-  3.4] |   3.7% [ 1.4-  9.1] |   3.7% [ 1.4-  9.1] |  96.3% [90.9- 98.6] |   0.0% [ 0.0-  3.4] |  96.3% [90.9- 98.6] |  96.3% [90.9- 98.6] |  98.2% [93.6- 99.5] |
| 0 | lead0.2-0.4 | 88 |   0.0% [ 0.0-  4.2] |   5.7% [ 2.5- 12.6] |   3.4% [ 1.2-  9.5] |  94.3% [87.4- 97.5] |   0.0% [ 0.0-  4.2] |  96.6% [90.5- 98.8] |  96.6% [90.5- 98.8] | 100.0% [95.8-100.0] |
| 0.5 | lead0.2-0.4 | 88 |   0.0% [ 0.0-  4.2] |   5.7% [ 2.5- 12.6] |   3.4% [ 1.2-  9.5] |  94.3% [87.4- 97.5] |   0.0% [ 0.0-  4.2] |  96.6% [90.5- 98.8] |  96.6% [90.5- 98.8] | 100.0% [95.8-100.0] |
| 1 | lead0.2-0.4 | 88 |   0.0% [ 0.0-  4.2] |   6.8% [ 3.2- 14.1] |   3.4% [ 1.2-  9.5] |  93.2% [85.9- 96.8] |   0.0% [ 0.0-  4.2] |  96.6% [90.5- 98.8] |  96.6% [90.5- 98.8] | 100.0% [95.8-100.0] |
| 2 | lead0.2-0.4 | 88 |   0.0% [ 0.0-  4.2] |   5.7% [ 2.5- 12.6] |   3.4% [ 1.2-  9.5] |  94.3% [87.4- 97.5] |   0.0% [ 0.0-  4.2] |  96.6% [90.5- 98.8] |  96.6% [90.5- 98.8] | 100.0% [95.8-100.0] |
| 4 | lead0.2-0.4 | 88 |   0.0% [ 0.0-  4.2] |   0.0% [ 0.0-  4.2] |   0.0% [ 0.0-  4.2] | 100.0% [95.8-100.0] |   0.0% [ 0.0-  4.2] | 100.0% [95.8-100.0] | 100.0% [95.8-100.0] | 100.0% [95.8-100.0] |
| 0 | lead0.2-0.8 | 113 |   0.0% [ 0.0-  3.3] |  19.5% [13.2- 27.7] |  15.0% [ 9.6- 22.8] |  80.5% [72.3- 86.8] |   0.0% [ 0.0-  3.3] |  85.0% [77.2- 90.4] |  85.0% [77.2- 90.4] | 100.0% [96.7-100.0] |
| 0.5 | lead0.2-0.8 | 113 |   0.0% [ 0.0-  3.3] |  19.5% [13.2- 27.7] |  15.0% [ 9.6- 22.8] |  80.5% [72.3- 86.8] |   0.0% [ 0.0-  3.3] |  85.0% [77.2- 90.4] |  85.0% [77.2- 90.4] | 100.0% [96.7-100.0] |
| 1 | lead0.2-0.8 | 113 |   0.0% [ 0.0-  3.3] |  18.6% [12.5- 26.7] |  15.9% [10.3- 23.8] |  81.4% [73.3- 87.5] |   0.0% [ 0.0-  3.3] |  84.1% [76.2- 89.7] |  84.1% [76.2- 89.7] | 100.0% [96.7-100.0] |
| 2 | lead0.2-0.8 | 113 |   0.0% [ 0.0-  3.3] |  17.7% [11.8- 25.8] |  14.2% [ 8.9- 21.8] |  82.3% [74.2- 88.2] |   0.0% [ 0.0-  3.3] |  85.8% [78.2- 91.1] |  85.8% [78.2- 91.1] |  99.1% [95.2- 99.8] |
| 4 | lead0.2-0.8 | 113 |   0.9% [ 0.2-  4.8] |   9.7% [ 5.5- 16.6] |   8.8% [ 4.9- 15.5] |  89.4% [82.4- 93.8] |   0.0% [ 0.0-  3.3] |  91.2% [84.5- 95.1] |  89.4% [82.4- 93.8] |  96.5% [91.3- 98.6] |
| 0 | lead0.6-1.2 | 106 |   0.0% [ 0.0-  3.5] |  72.6% [63.5- 80.2] |  71.7% [62.5- 79.4] |  27.4% [19.8- 36.5] |   0.0% [ 0.0-  3.5] |  28.3% [20.6- 37.5] |  28.3% [20.6- 37.5] | 100.0% [96.5-100.0] |
| 0.5 | lead0.6-1.2 | 106 |   0.0% [ 0.0-  3.5] |  72.6% [63.5- 80.2] |  71.7% [62.5- 79.4] |  27.4% [19.8- 36.5] |   0.0% [ 0.0-  3.5] |  28.3% [20.6- 37.5] |  28.3% [20.6- 37.5] | 100.0% [96.5-100.0] |
| 1 | lead0.6-1.2 | 106 |   0.0% [ 0.0-  3.5] |  72.6% [63.5- 80.2] |  71.7% [62.5- 79.4] |  27.4% [19.8- 36.5] |   0.0% [ 0.0-  3.5] |  28.3% [20.6- 37.5] |  28.3% [20.6- 37.5] | 100.0% [96.5-100.0] |
| 2 | lead0.6-1.2 | 106 |   0.0% [ 0.0-  3.5] |  70.8% [61.5- 78.6] |  69.8% [60.5- 77.7] |  29.2% [21.4- 38.5] |   0.0% [ 0.0-  3.5] |  30.2% [22.3- 39.5] |  29.2% [21.4- 38.5] | 100.0% [96.5-100.0] |
| 4 | lead0.6-1.2 | 106 |   0.9% [ 0.2-  5.2] |  60.4% [50.9- 69.2] |  52.8% [43.4- 62.1] |  35.8% [27.4- 45.3] |   2.8% [ 1.0-  8.0] |  43.4% [34.4- 52.9] |  35.8% [27.4- 45.3] |  97.2% [92.0- 99.0] |

**abutting(gap0m) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 109 |  56.0% [46.6- 64.9] |   0.0% [ 0.0-  3.4] |   0.0% [ 0.0-  3.4] |  44.0% [35.1- 53.4] |   0.0% [ 0.0-  3.4] | 100.0% [96.6-100.0] |  50.5% [41.2- 59.7] | 100.0% [96.6-100.0] |
| 0.5 | lead0.0-0.2 | 109 |  57.8% [48.4- 66.6] |   0.0% [ 0.0-  3.4] |   0.0% [ 0.0-  3.4] |  42.2% [33.4- 51.6] |   0.0% [ 0.0-  3.4] | 100.0% [96.6-100.0] |  51.4% [42.1- 60.6] | 100.0% [96.6-100.0] |
| 1 | lead0.0-0.2 | 109 |  57.8% [48.4- 66.6] |   0.0% [ 0.0-  3.4] |   0.0% [ 0.0-  3.4] |  42.2% [33.4- 51.6] |   0.0% [ 0.0-  3.4] | 100.0% [96.6-100.0] |  51.4% [42.1- 60.6] | 100.0% [96.6-100.0] |
| 2 | lead0.0-0.2 | 109 |  58.7% [49.3- 67.5] |   0.9% [ 0.2-  5.0] |   0.9% [ 0.2-  5.0] |  40.4% [31.6- 49.8] |   0.0% [ 0.0-  3.4] |  99.1% [95.0- 99.8] |  50.5% [41.2- 59.7] | 100.0% [96.6-100.0] |
| 4 | lead0.0-0.2 | 109 |  50.5% [41.2- 59.7] |   1.8% [ 0.5-  6.4] |   1.8% [ 0.5-  6.4] |  46.8% [37.7- 56.1] |   0.9% [ 0.2-  5.0] |  97.2% [92.2- 99.1] |  53.2% [43.9- 62.3] |  98.2% [93.6- 99.5] |
| 0 | lead0.2-0.4 | 88 |  76.1% [66.3- 83.8] |   0.0% [ 0.0-  4.2] |   0.0% [ 0.0-  4.2] |  23.9% [16.2- 33.7] |   0.0% [ 0.0-  4.2] |  97.7% [92.1- 99.4] |  31.8% [23.0- 42.1] | 100.0% [95.8-100.0] |
| 0.5 | lead0.2-0.4 | 88 |  77.3% [67.5- 84.8] |   0.0% [ 0.0-  4.2] |   0.0% [ 0.0-  4.2] |  22.7% [15.2- 32.5] |   0.0% [ 0.0-  4.2] |  97.7% [92.1- 99.4] |  28.4% [20.0- 38.6] | 100.0% [95.8-100.0] |
| 1 | lead0.2-0.4 | 88 |  76.1% [66.3- 83.8] |   0.0% [ 0.0-  4.2] |   0.0% [ 0.0-  4.2] |  23.9% [16.2- 33.7] |   0.0% [ 0.0-  4.2] |  96.6% [90.5- 98.8] |  28.4% [20.0- 38.6] | 100.0% [95.8-100.0] |
| 2 | lead0.2-0.4 | 88 |  76.1% [66.3- 83.8] |   0.0% [ 0.0-  4.2] |   0.0% [ 0.0-  4.2] |  23.9% [16.2- 33.7] |   0.0% [ 0.0-  4.2] |  94.3% [87.4- 97.5] |  27.3% [19.1- 37.4] | 100.0% [95.8-100.0] |
| 4 | lead0.2-0.4 | 88 |  69.3% [59.0- 78.0] |   2.3% [ 0.6-  7.9] |   2.3% [ 0.6-  7.9] |  28.4% [20.0- 38.6] |   0.0% [ 0.0-  4.2] |  94.3% [87.4- 97.5] |  31.8% [23.0- 42.1] | 100.0% [95.8-100.0] |
| 0 | lead0.2-0.8 | 113 |  67.3% [58.2- 75.2] |   7.1% [ 3.6- 13.4] |   6.2% [ 3.0- 12.2] |  25.7% [18.5- 34.4] |   0.0% [ 0.0-  3.3] |  92.9% [86.6- 96.4] |  31.9% [24.0- 40.9] | 100.0% [96.7-100.0] |
| 0.5 | lead0.2-0.8 | 113 |  67.3% [58.2- 75.2] |   7.1% [ 3.6- 13.4] |   6.2% [ 3.0- 12.2] |  25.7% [18.5- 34.4] |   0.0% [ 0.0-  3.3] |  92.9% [86.6- 96.4] |  31.9% [24.0- 40.9] | 100.0% [96.7-100.0] |
| 1 | lead0.2-0.8 | 113 |  67.3% [58.2- 75.2] |   7.1% [ 3.6- 13.4] |   6.2% [ 3.0- 12.2] |  25.7% [18.5- 34.4] |   0.0% [ 0.0-  3.3] |  93.8% [87.8- 97.0] |  33.6% [25.6- 42.7] | 100.0% [96.7-100.0] |
| 2 | lead0.2-0.8 | 113 |  67.3% [58.2- 75.2] |   7.1% [ 3.6- 13.4] |   6.2% [ 3.0- 12.2] |  25.7% [18.5- 34.4] |   0.0% [ 0.0-  3.3] |  92.0% [85.6- 95.8] |  32.7% [24.8- 41.8] |  99.1% [95.2- 99.8] |
| 4 | lead0.2-0.8 | 113 |  63.7% [54.5- 72.0] |   8.0% [ 4.2- 14.4] |   6.2% [ 3.0- 12.2] |  28.3% [20.8- 37.2] |   0.0% [ 0.0-  3.3] |  91.2% [84.5- 95.1] |  32.7% [24.8- 41.8] |  96.5% [91.3- 98.6] |
| 0 | lead0.6-1.2 | 106 |  26.4% [19.0- 35.5] |  58.5% [49.0- 67.4] |  50.9% [41.6- 60.3] |  15.1% [ 9.5- 23.1] |   0.0% [ 0.0-  3.5] |  48.1% [38.8- 57.5] |  17.0% [11.0- 25.3] | 100.0% [96.5-100.0] |
| 0.5 | lead0.6-1.2 | 106 |  26.4% [19.0- 35.5] |  58.5% [49.0- 67.4] |  50.9% [41.6- 60.3] |  15.1% [ 9.5- 23.1] |   0.0% [ 0.0-  3.5] |  49.1% [39.7- 58.4] |  17.0% [11.0- 25.3] | 100.0% [96.5-100.0] |
| 1 | lead0.6-1.2 | 106 |  26.4% [19.0- 35.5] |  57.5% [48.0- 66.5] |  50.9% [41.6- 60.3] |  16.0% [10.3- 24.2] |   0.0% [ 0.0-  3.5] |  49.1% [39.7- 58.4] |  17.9% [11.8- 26.3] | 100.0% [96.5-100.0] |
| 2 | lead0.6-1.2 | 106 |  26.4% [19.0- 35.5] |  58.5% [49.0- 67.4] |  50.9% [41.6- 60.3] |  15.1% [ 9.5- 23.1] |   0.0% [ 0.0-  3.5] |  49.1% [39.7- 58.4] |  17.9% [11.8- 26.3] | 100.0% [96.5-100.0] |
| 4 | lead0.6-1.2 | 106 |  27.4% [19.8- 36.5] |  59.4% [49.9- 68.3] |  51.9% [42.5- 61.2] |  13.2% [ 8.0- 21.0] |   0.0% [ 0.0-  3.5] |  48.1% [38.8- 57.5] |  17.0% [11.0- 25.3] |  97.2% [92.0- 99.0] |

**mixed(2adj+2far) / smoothing OFF**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 104 |   0.0% [ 0.0-  3.6] |  25.0% [17.7- 34.1] |  24.0% [16.8- 33.1] |  75.0% [65.9- 82.3] |   0.0% [ 0.0-  3.6] |  76.0% [66.9- 83.2] |  76.0% [66.9- 83.2] | 100.0% [96.4-100.0] |
| 0.5 | lead0.0-0.2 | 104 |   0.0% [ 0.0-  3.6] |  25.0% [17.7- 34.1] |  23.1% [16.0- 32.0] |  75.0% [65.9- 82.3] |   0.0% [ 0.0-  3.6] |  76.9% [68.0- 84.0] |  76.9% [68.0- 84.0] | 100.0% [96.4-100.0] |
| 1 | lead0.0-0.2 | 104 |   0.0% [ 0.0-  3.6] |  23.1% [16.0- 32.0] |  22.1% [15.2- 31.0] |  76.9% [68.0- 84.0] |   0.0% [ 0.0-  3.6] |  77.9% [69.0- 84.8] |  77.9% [69.0- 84.8] | 100.0% [96.4-100.0] |
| 2 | lead0.0-0.2 | 104 |   0.0% [ 0.0-  3.6] |  13.5% [ 8.2- 21.3] |  12.5% [ 7.5- 20.2] |  86.5% [78.7- 91.8] |   0.0% [ 0.0-  3.6] |  87.5% [79.8- 92.5] |  87.5% [79.8- 92.5] | 100.0% [96.4-100.0] |
| 4 | lead0.0-0.2 | 104 |   0.0% [ 0.0-  3.6] |   1.9% [ 0.5-  6.7] |   1.9% [ 0.5-  6.7] |  98.1% [93.3- 99.5] |   0.0% [ 0.0-  3.6] |  98.1% [93.3- 99.5] |  98.1% [93.3- 99.5] | 100.0% [96.4-100.0] |
| 0 | lead0.2-0.4 | 89 |   0.0% [ 0.0-  4.1] |   1.1% [ 0.2-  6.1] |   0.0% [ 0.0-  4.1] |  98.9% [93.9- 99.8] |   0.0% [ 0.0-  4.1] | 100.0% [95.9-100.0] | 100.0% [95.9-100.0] | 100.0% [95.9-100.0] |
| 0.5 | lead0.2-0.4 | 89 |   0.0% [ 0.0-  4.1] |   1.1% [ 0.2-  6.1] |   1.1% [ 0.2-  6.1] |  98.9% [93.9- 99.8] |   0.0% [ 0.0-  4.1] |  98.9% [93.9- 99.8] |  98.9% [93.9- 99.8] | 100.0% [95.9-100.0] |
| 1 | lead0.2-0.4 | 89 |   0.0% [ 0.0-  4.1] |   1.1% [ 0.2-  6.1] |   1.1% [ 0.2-  6.1] |  98.9% [93.9- 99.8] |   0.0% [ 0.0-  4.1] |  98.9% [93.9- 99.8] |  98.9% [93.9- 99.8] | 100.0% [95.9-100.0] |
| 2 | lead0.2-0.4 | 89 |   0.0% [ 0.0-  4.1] |   1.1% [ 0.2-  6.1] |   1.1% [ 0.2-  6.1] |  98.9% [93.9- 99.8] |   0.0% [ 0.0-  4.1] |  98.9% [93.9- 99.8] |  98.9% [93.9- 99.8] | 100.0% [95.9-100.0] |
| 4 | lead0.2-0.4 | 89 |   0.0% [ 0.0-  4.1] |   0.0% [ 0.0-  4.1] |   0.0% [ 0.0-  4.1] | 100.0% [95.9-100.0] |   0.0% [ 0.0-  4.1] | 100.0% [95.9-100.0] | 100.0% [95.9-100.0] | 100.0% [95.9-100.0] |
| 0 | lead0.2-0.8 | 117 |   0.0% [ 0.0-  3.2] |  20.5% [14.2- 28.7] |  19.7% [13.5- 27.8] |  79.5% [71.3- 85.8] |   0.0% [ 0.0-  3.2] |  80.3% [72.2- 86.5] |  80.3% [72.2- 86.5] | 100.0% [96.8-100.0] |
| 0.5 | lead0.2-0.8 | 117 |   0.0% [ 0.0-  3.2] |  20.5% [14.2- 28.7] |  19.7% [13.5- 27.8] |  79.5% [71.3- 85.8] |   0.0% [ 0.0-  3.2] |  80.3% [72.2- 86.5] |  80.3% [72.2- 86.5] | 100.0% [96.8-100.0] |
| 1 | lead0.2-0.8 | 117 |   0.0% [ 0.0-  3.2] |  18.8% [12.8- 26.8] |  17.9% [12.0- 25.9] |  81.2% [73.2- 87.2] |   0.0% [ 0.0-  3.2] |  82.1% [74.1- 88.0] |  82.1% [74.1- 88.0] | 100.0% [96.8-100.0] |
| 2 | lead0.2-0.8 | 117 |   0.0% [ 0.0-  3.2] |  16.2% [10.6- 24.0] |  16.2% [10.6- 24.0] |  83.8% [76.0- 89.4] |   0.0% [ 0.0-  3.2] |  83.8% [76.0- 89.4] |  83.8% [76.0- 89.4] | 100.0% [96.8-100.0] |
| 4 | lead0.2-0.8 | 117 |   0.0% [ 0.0-  3.2] |   6.8% [ 3.5- 12.9] |   6.8% [ 3.5- 12.9] |  92.3% [86.0- 95.9] |   0.9% [ 0.2-  4.7] |  92.3% [86.0- 95.9] |  92.3% [86.0- 95.9] | 100.0% [96.8-100.0] |
| 0 | lead0.6-1.2 | 103 |   0.0% [ 0.0-  3.6] |  74.8% [65.6- 82.2] |  74.8% [65.6- 82.2] |  25.2% [17.8- 34.4] |   0.0% [ 0.0-  3.6] |  25.2% [17.8- 34.4] |  25.2% [17.8- 34.4] | 100.0% [96.4-100.0] |
| 0.5 | lead0.6-1.2 | 103 |   0.0% [ 0.0-  3.6] |  73.8% [64.5- 81.3] |  73.8% [64.5- 81.3] |  26.2% [18.7- 35.5] |   0.0% [ 0.0-  3.6] |  26.2% [18.7- 35.5] |  26.2% [18.7- 35.5] | 100.0% [96.4-100.0] |
| 1 | lead0.6-1.2 | 103 |   0.0% [ 0.0-  3.6] |  73.8% [64.5- 81.3] |  73.8% [64.5- 81.3] |  26.2% [18.7- 35.5] |   0.0% [ 0.0-  3.6] |  26.2% [18.7- 35.5] |  26.2% [18.7- 35.5] | 100.0% [96.4-100.0] |
| 2 | lead0.6-1.2 | 103 |   0.0% [ 0.0-  3.6] |  69.9% [60.5- 77.9] |  69.9% [60.5- 77.9] |  30.1% [22.1- 39.5] |   0.0% [ 0.0-  3.6] |  30.1% [22.1- 39.5] |  30.1% [22.1- 39.5] | 100.0% [96.4-100.0] |
| 4 | lead0.6-1.2 | 103 |   0.0% [ 0.0-  3.6] |  38.8% [30.0- 48.5] |  38.8% [30.0- 48.5] |  46.6% [37.3- 56.2] |  14.6% [ 9.0- 22.6] |  46.6% [37.3- 56.2] |  46.6% [37.3- 56.2] | 100.0% [96.4-100.0] |

**mixed(2adj+2far) / smoothing ON**

| noise (deg) | lead (s) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | prompt w/o target-changed | naive ray-at-word wrong |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | lead0.0-0.2 | 104 |  11.5% [ 6.7- 19.1] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |  75.0% [65.9- 82.3] |  13.5% [ 8.2- 21.3] |  85.6% [77.6- 91.1] |  75.0% [65.9- 82.3] | 100.0% [96.4-100.0] |
| 0.5 | lead0.0-0.2 | 104 |  12.5% [ 7.5- 20.2] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |  74.0% [64.9- 81.5] |  13.5% [ 8.2- 21.3] |  85.6% [77.6- 91.1] |  74.0% [64.9- 81.5] | 100.0% [96.4-100.0] |
| 1 | lead0.0-0.2 | 104 |  11.5% [ 6.7- 19.1] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |  75.0% [65.9- 82.3] |  13.5% [ 8.2- 21.3] |  85.6% [77.6- 91.1] |  75.0% [65.9- 82.3] | 100.0% [96.4-100.0] |
| 2 | lead0.0-0.2 | 104 |  12.5% [ 7.5- 20.2] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |  75.0% [65.9- 82.3] |  12.5% [ 7.5- 20.2] |  86.5% [78.7- 91.8] |  75.0% [65.9- 82.3] | 100.0% [96.4-100.0] |
| 4 | lead0.0-0.2 | 104 |  10.6% [ 6.0- 18.0] |   0.0% [ 0.0-  3.6] |   0.0% [ 0.0-  3.6] |  70.2% [60.8- 78.1] |  19.2% [12.8- 27.8] |  79.8% [71.1- 86.4] |  70.2% [60.8- 78.1] | 100.0% [96.4-100.0] |
| 0 | lead0.2-0.4 | 89 |  25.8% [17.9- 35.8] |   0.0% [ 0.0-  4.1] |   0.0% [ 0.0-  4.1] |  56.2% [45.8- 66.0] |  18.0% [11.4- 27.2] |  70.8% [60.6- 79.2] |  56.2% [45.8- 66.0] | 100.0% [95.9-100.0] |
| 0.5 | lead0.2-0.4 | 89 |  25.8% [17.9- 35.8] |   0.0% [ 0.0-  4.1] |   0.0% [ 0.0-  4.1] |  56.2% [45.8- 66.0] |  18.0% [11.4- 27.2] |  70.8% [60.6- 79.2] |  56.2% [45.8- 66.0] | 100.0% [95.9-100.0] |
| 1 | lead0.2-0.4 | 89 |  27.0% [18.8- 37.0] |   0.0% [ 0.0-  4.1] |   0.0% [ 0.0-  4.1] |  53.9% [43.6- 63.9] |  19.1% [12.3- 28.5] |  68.5% [58.3- 77.2] |  53.9% [43.6- 63.9] | 100.0% [95.9-100.0] |
| 2 | lead0.2-0.4 | 89 |  28.1% [19.8- 38.2] |   0.0% [ 0.0-  4.1] |   0.0% [ 0.0-  4.1] |  52.8% [42.5- 62.8] |  19.1% [12.3- 28.5] |  67.4% [57.1- 76.3] |  52.8% [42.5- 62.8] | 100.0% [95.9-100.0] |
| 4 | lead0.2-0.4 | 89 |  25.8% [17.9- 35.8] |   0.0% [ 0.0-  4.1] |   0.0% [ 0.0-  4.1] |  52.8% [42.5- 62.8] |  21.3% [14.1- 31.0] |  67.4% [57.1- 76.3] |  52.8% [42.5- 62.8] | 100.0% [95.9-100.0] |
| 0 | lead0.2-0.8 | 117 |  21.4% [14.9- 29.6] |   5.1% [ 2.4- 10.7] |   5.1% [ 2.4- 10.7] |  65.0% [56.0- 73.0] |   8.5% [ 4.7- 15.0] |  78.6% [70.4- 85.1] |  65.0% [56.0- 73.0] | 100.0% [96.8-100.0] |
| 0.5 | lead0.2-0.8 | 117 |  21.4% [14.9- 29.6] |   5.1% [ 2.4- 10.7] |   5.1% [ 2.4- 10.7] |  64.1% [55.1- 72.2] |   9.4% [ 5.3- 16.1] |  76.9% [68.5- 83.6] |  64.1% [55.1- 72.2] | 100.0% [96.8-100.0] |
| 1 | lead0.2-0.8 | 117 |  21.4% [14.9- 29.6] |   5.1% [ 2.4- 10.7] |   5.1% [ 2.4- 10.7] |  64.1% [55.1- 72.2] |   9.4% [ 5.3- 16.1] |  76.9% [68.5- 83.6] |  64.1% [55.1- 72.2] | 100.0% [96.8-100.0] |
| 2 | lead0.2-0.8 | 117 |  21.4% [14.9- 29.6] |   4.3% [ 1.8-  9.6] |   4.3% [ 1.8-  9.6] |  65.0% [56.0- 73.0] |   9.4% [ 5.3- 16.1] |  77.8% [69.4- 84.4] |  65.0% [56.0- 73.0] | 100.0% [96.8-100.0] |
| 4 | lead0.2-0.8 | 117 |  20.5% [14.2- 28.7] |   4.3% [ 1.8-  9.6] |   4.3% [ 1.8-  9.6] |  64.1% [55.1- 72.2] |  11.1% [ 6.6- 18.1] |  76.9% [68.5- 83.6] |  64.1% [55.1- 72.2] | 100.0% [96.8-100.0] |
| 0 | lead0.6-1.2 | 103 |   6.8% [ 3.3- 13.4] |  35.9% [27.3- 45.5] |  35.9% [27.3- 45.5] |  53.4% [43.8- 62.7] |   3.9% [ 1.5-  9.6] |  57.3% [47.6- 66.4] |  53.4% [43.8- 62.7] | 100.0% [96.4-100.0] |
| 0.5 | lead0.6-1.2 | 103 |   6.8% [ 3.3- 13.4] |  35.9% [27.3- 45.5] |  35.9% [27.3- 45.5] |  53.4% [43.8- 62.7] |   3.9% [ 1.5-  9.6] |  57.3% [47.6- 66.4] |  53.4% [43.8- 62.7] | 100.0% [96.4-100.0] |
| 1 | lead0.6-1.2 | 103 |   6.8% [ 3.3- 13.4] |  35.9% [27.3- 45.5] |  35.9% [27.3- 45.5] |  53.4% [43.8- 62.7] |   3.9% [ 1.5-  9.6] |  57.3% [47.6- 66.4] |  53.4% [43.8- 62.7] | 100.0% [96.4-100.0] |
| 2 | lead0.6-1.2 | 103 |   5.8% [ 2.7- 12.1] |  35.9% [27.3- 45.5] |  35.9% [27.3- 45.5] |  54.4% [44.8- 63.7] |   3.9% [ 1.5-  9.6] |  58.3% [48.6- 67.3] |  54.4% [44.8- 63.7] | 100.0% [96.4-100.0] |
| 4 | lead0.6-1.2 | 103 |   5.8% [ 2.7- 12.1] |  35.9% [27.3- 45.5] |  35.9% [27.3- 45.5] |  54.4% [44.8- 63.7] |   3.9% [ 1.5-  9.6] |  58.3% [48.6- 67.3] |  54.4% [44.8- 63.7] | 100.0% [96.4-100.0] |

### Prompt reasons, summed over leads, per condition, layout and noise

| look_away_prob | stratum | layout | smoothing | noise (deg) | trials | no_target | ambiguous_panels | target_changed | low_confidence | silent(none) |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | aligned | far(gap1.0m) | OFF | 0 | 2000 | 0 | 0 | 1145 | 0 | 855 |
| 0 | aligned | far(gap1.0m) | OFF | 0.5 | 2000 | 0 | 0 | 1145 | 0 | 855 |
| 0 | aligned | far(gap1.0m) | OFF | 1 | 2000 | 0 | 0 | 1129 | 0 | 871 |
| 0 | aligned | far(gap1.0m) | OFF | 2 | 2000 | 4 | 92 | 914 | 0 | 990 |
| 0 | aligned | far(gap1.0m) | OFF | 4 | 2000 | 261 | 640 | 269 | 0 | 830 |
| 0 | aligned | far(gap1.0m) | ON | 0 | 2000 | 0 | 0 | 250 | 0 | 1750 |
| 0 | aligned | far(gap1.0m) | ON | 0.5 | 2000 | 0 | 0 | 252 | 0 | 1748 |
| 0 | aligned | far(gap1.0m) | ON | 1 | 2000 | 1 | 0 | 251 | 0 | 1748 |
| 0 | aligned | far(gap1.0m) | ON | 2 | 2000 | 20 | 0 | 250 | 0 | 1730 |
| 0 | aligned | far(gap1.0m) | ON | 4 | 2000 | 79 | 3 | 248 | 0 | 1670 |
| 0 | aligned | adjacent(gap0.1m) | OFF | 0 | 2000 | 0 | 0 | 1151 | 0 | 849 |
| 0 | aligned | adjacent(gap0.1m) | OFF | 0.5 | 2000 | 0 | 0 | 1148 | 0 | 852 |
| 0 | aligned | adjacent(gap0.1m) | OFF | 1 | 2000 | 0 | 0 | 1145 | 0 | 855 |
| 0 | aligned | adjacent(gap0.1m) | OFF | 2 | 2000 | 0 | 8 | 1049 | 0 | 943 |
| 0 | aligned | adjacent(gap0.1m) | OFF | 4 | 2000 | 45 | 381 | 525 | 0 | 1049 |
| 0 | aligned | adjacent(gap0.1m) | ON | 0 | 2000 | 0 | 0 | 826 | 0 | 1174 |
| 0 | aligned | adjacent(gap0.1m) | ON | 0.5 | 2000 | 0 | 0 | 826 | 0 | 1174 |
| 0 | aligned | adjacent(gap0.1m) | ON | 1 | 2000 | 0 | 0 | 829 | 0 | 1171 |
| 0 | aligned | adjacent(gap0.1m) | ON | 2 | 2000 | 3 | 0 | 822 | 0 | 1175 |
| 0 | aligned | adjacent(gap0.1m) | ON | 4 | 2000 | 47 | 3 | 804 | 0 | 1146 |
| 0 | aligned | abutting(gap0m) | OFF | 0 | 2000 | 0 | 0 | 1217 | 0 | 783 |
| 0 | aligned | abutting(gap0m) | OFF | 0.5 | 2000 | 0 | 0 | 1220 | 0 | 780 |
| 0 | aligned | abutting(gap0m) | OFF | 1 | 2000 | 0 | 0 | 1215 | 0 | 785 |
| 0 | aligned | abutting(gap0m) | OFF | 2 | 2000 | 1 | 2 | 1138 | 0 | 859 |
| 0 | aligned | abutting(gap0m) | OFF | 4 | 2000 | 42 | 336 | 647 | 0 | 975 |
| 0 | aligned | abutting(gap0m) | ON | 0 | 2000 | 0 | 0 | 989 | 0 | 1011 |
| 0 | aligned | abutting(gap0m) | ON | 0.5 | 2000 | 0 | 0 | 988 | 0 | 1012 |
| 0 | aligned | abutting(gap0m) | ON | 1 | 2000 | 0 | 0 | 988 | 0 | 1012 |
| 0 | aligned | abutting(gap0m) | ON | 2 | 2000 | 1 | 1 | 985 | 0 | 1013 |
| 0 | aligned | abutting(gap0m) | ON | 4 | 2000 | 41 | 6 | 980 | 0 | 973 |
| 0 | aligned | mixed(2adj+2far) | OFF | 0 | 2000 | 0 | 0 | 1160 | 0 | 840 |
| 0 | aligned | mixed(2adj+2far) | OFF | 0.5 | 2000 | 0 | 0 | 1161 | 0 | 839 |
| 0 | aligned | mixed(2adj+2far) | OFF | 1 | 2000 | 0 | 0 | 1142 | 0 | 858 |
| 0 | aligned | mixed(2adj+2far) | OFF | 2 | 2000 | 5 | 110 | 879 | 0 | 1006 |
| 0 | aligned | mixed(2adj+2far) | OFF | 4 | 2000 | 371 | 635 | 259 | 0 | 735 |
| 0 | aligned | mixed(2adj+2far) | ON | 0 | 2000 | 0 | 0 | 391 | 0 | 1609 |
| 0 | aligned | mixed(2adj+2far) | ON | 0.5 | 2000 | 0 | 0 | 395 | 0 | 1605 |
| 0 | aligned | mixed(2adj+2far) | ON | 1 | 2000 | 0 | 0 | 396 | 0 | 1604 |
| 0 | aligned | mixed(2adj+2far) | ON | 2 | 2000 | 11 | 0 | 391 | 0 | 1598 |
| 0 | aligned | mixed(2adj+2far) | ON | 4 | 2000 | 81 | 4 | 385 | 0 | 1530 |
| 0.2 | aligned | far(gap1.0m) | OFF | 0 | 1573 | 0 | 0 | 902 | 0 | 671 |
| 0.2 | aligned | far(gap1.0m) | OFF | 0.5 | 1573 | 0 | 0 | 902 | 0 | 671 |
| 0.2 | aligned | far(gap1.0m) | OFF | 1 | 1573 | 0 | 0 | 888 | 0 | 685 |
| 0.2 | aligned | far(gap1.0m) | OFF | 2 | 1573 | 3 | 75 | 717 | 0 | 778 |
| 0.2 | aligned | far(gap1.0m) | OFF | 4 | 1573 | 211 | 494 | 221 | 0 | 647 |
| 0.2 | aligned | far(gap1.0m) | ON | 0 | 1573 | 0 | 0 | 195 | 0 | 1378 |
| 0.2 | aligned | far(gap1.0m) | ON | 0.5 | 1573 | 0 | 0 | 196 | 0 | 1377 |
| 0.2 | aligned | far(gap1.0m) | ON | 1 | 1573 | 1 | 0 | 196 | 0 | 1376 |
| 0.2 | aligned | far(gap1.0m) | ON | 2 | 1573 | 16 | 0 | 194 | 0 | 1363 |
| 0.2 | aligned | far(gap1.0m) | ON | 4 | 1573 | 68 | 2 | 194 | 0 | 1309 |
| 0.2 | aligned | adjacent(gap0.1m) | OFF | 0 | 1607 | 0 | 0 | 923 | 0 | 684 |
| 0.2 | aligned | adjacent(gap0.1m) | OFF | 0.5 | 1607 | 0 | 0 | 920 | 0 | 687 |
| 0.2 | aligned | adjacent(gap0.1m) | OFF | 1 | 1607 | 0 | 0 | 917 | 0 | 690 |
| 0.2 | aligned | adjacent(gap0.1m) | OFF | 2 | 1607 | 0 | 7 | 840 | 0 | 760 |
| 0.2 | aligned | adjacent(gap0.1m) | OFF | 4 | 1607 | 32 | 314 | 416 | 0 | 845 |
| 0.2 | aligned | adjacent(gap0.1m) | ON | 0 | 1607 | 0 | 0 | 667 | 0 | 940 |
| 0.2 | aligned | adjacent(gap0.1m) | ON | 0.5 | 1607 | 0 | 0 | 668 | 0 | 939 |
| 0.2 | aligned | adjacent(gap0.1m) | ON | 1 | 1607 | 0 | 0 | 670 | 0 | 937 |
| 0.2 | aligned | adjacent(gap0.1m) | ON | 2 | 1607 | 3 | 0 | 661 | 0 | 943 |
| 0.2 | aligned | adjacent(gap0.1m) | ON | 4 | 1607 | 35 | 3 | 649 | 0 | 920 |
| 0.2 | aligned | abutting(gap0m) | OFF | 0 | 1584 | 0 | 0 | 965 | 0 | 619 |
| 0.2 | aligned | abutting(gap0m) | OFF | 0.5 | 1584 | 0 | 0 | 968 | 0 | 616 |
| 0.2 | aligned | abutting(gap0m) | OFF | 1 | 1584 | 0 | 0 | 965 | 0 | 619 |
| 0.2 | aligned | abutting(gap0m) | OFF | 2 | 1584 | 1 | 1 | 901 | 0 | 681 |
| 0.2 | aligned | abutting(gap0m) | OFF | 4 | 1584 | 34 | 268 | 519 | 0 | 763 |
| 0.2 | aligned | abutting(gap0m) | ON | 0 | 1584 | 0 | 0 | 789 | 0 | 795 |
| 0.2 | aligned | abutting(gap0m) | ON | 0.5 | 1584 | 0 | 0 | 788 | 0 | 796 |
| 0.2 | aligned | abutting(gap0m) | ON | 1 | 1584 | 0 | 0 | 789 | 0 | 795 |
| 0.2 | aligned | abutting(gap0m) | ON | 2 | 1584 | 0 | 0 | 785 | 0 | 799 |
| 0.2 | aligned | abutting(gap0m) | ON | 4 | 1584 | 29 | 5 | 778 | 0 | 772 |
| 0.2 | aligned | mixed(2adj+2far) | OFF | 0 | 1587 | 0 | 0 | 930 | 0 | 657 |
| 0.2 | aligned | mixed(2adj+2far) | OFF | 0.5 | 1587 | 0 | 0 | 931 | 0 | 656 |
| 0.2 | aligned | mixed(2adj+2far) | OFF | 1 | 1587 | 0 | 0 | 916 | 0 | 671 |
| 0.2 | aligned | mixed(2adj+2far) | OFF | 2 | 1587 | 5 | 87 | 708 | 0 | 787 |
| 0.2 | aligned | mixed(2adj+2far) | OFF | 4 | 1587 | 294 | 514 | 206 | 0 | 573 |
| 0.2 | aligned | mixed(2adj+2far) | ON | 0 | 1587 | 0 | 0 | 308 | 0 | 1279 |
| 0.2 | aligned | mixed(2adj+2far) | ON | 0.5 | 1587 | 0 | 0 | 311 | 0 | 1276 |
| 0.2 | aligned | mixed(2adj+2far) | ON | 1 | 1587 | 0 | 0 | 311 | 0 | 1276 |
| 0.2 | aligned | mixed(2adj+2far) | ON | 2 | 1587 | 8 | 0 | 305 | 0 | 1274 |
| 0.2 | aligned | mixed(2adj+2far) | ON | 4 | 1587 | 67 | 4 | 301 | 0 | 1215 |
| 0.2 | look | far(gap1.0m) | OFF | 0 | 427 | 0 | 302 | 0 | 0 | 125 |
| 0.2 | look | far(gap1.0m) | OFF | 0.5 | 427 | 0 | 300 | 0 | 0 | 127 |
| 0.2 | look | far(gap1.0m) | OFF | 1 | 427 | 0 | 302 | 0 | 0 | 125 |
| 0.2 | look | far(gap1.0m) | OFF | 2 | 427 | 0 | 317 | 0 | 0 | 110 |
| 0.2 | look | far(gap1.0m) | OFF | 4 | 427 | 5 | 357 | 0 | 0 | 65 |
| 0.2 | look | far(gap1.0m) | ON | 0 | 427 | 105 | 246 | 4 | 0 | 72 |
| 0.2 | look | far(gap1.0m) | ON | 0.5 | 427 | 107 | 245 | 4 | 0 | 71 |
| 0.2 | look | far(gap1.0m) | ON | 1 | 427 | 109 | 245 | 3 | 0 | 70 |
| 0.2 | look | far(gap1.0m) | ON | 2 | 427 | 107 | 251 | 3 | 0 | 66 |
| 0.2 | look | far(gap1.0m) | ON | 4 | 427 | 113 | 247 | 3 | 0 | 64 |
| 0.2 | look | adjacent(gap0.1m) | OFF | 0 | 393 | 0 | 235 | 0 | 13 | 145 |
| 0.2 | look | adjacent(gap0.1m) | OFF | 0.5 | 393 | 0 | 237 | 0 | 11 | 145 |
| 0.2 | look | adjacent(gap0.1m) | OFF | 1 | 393 | 0 | 241 | 0 | 11 | 141 |
| 0.2 | look | adjacent(gap0.1m) | OFF | 2 | 393 | 0 | 266 | 0 | 4 | 123 |
| 0.2 | look | adjacent(gap0.1m) | OFF | 4 | 393 | 2 | 319 | 1 | 0 | 71 |
| 0.2 | look | adjacent(gap0.1m) | ON | 0 | 393 | 0 | 129 | 175 | 0 | 89 |
| 0.2 | look | adjacent(gap0.1m) | ON | 0.5 | 393 | 0 | 129 | 175 | 0 | 89 |
| 0.2 | look | adjacent(gap0.1m) | ON | 1 | 393 | 0 | 128 | 175 | 0 | 90 |
| 0.2 | look | adjacent(gap0.1m) | ON | 2 | 393 | 0 | 133 | 175 | 0 | 85 |
| 0.2 | look | adjacent(gap0.1m) | ON | 4 | 393 | 2 | 147 | 158 | 0 | 86 |
| 0.2 | look | abutting(gap0m) | OFF | 0 | 416 | 0 | 231 | 0 | 35 | 150 |
| 0.2 | look | abutting(gap0m) | OFF | 0.5 | 416 | 0 | 226 | 0 | 38 | 152 |
| 0.2 | look | abutting(gap0m) | OFF | 1 | 416 | 0 | 225 | 0 | 34 | 157 |
| 0.2 | look | abutting(gap0m) | OFF | 2 | 416 | 0 | 267 | 1 | 16 | 132 |
| 0.2 | look | abutting(gap0m) | OFF | 4 | 416 | 3 | 332 | 10 | 0 | 71 |
| 0.2 | look | abutting(gap0m) | ON | 0 | 416 | 0 | 114 | 227 | 10 | 65 |
| 0.2 | look | abutting(gap0m) | ON | 0.5 | 416 | 0 | 111 | 232 | 9 | 64 |
| 0.2 | look | abutting(gap0m) | ON | 1 | 416 | 0 | 113 | 230 | 9 | 64 |
| 0.2 | look | abutting(gap0m) | ON | 2 | 416 | 0 | 110 | 227 | 10 | 69 |
| 0.2 | look | abutting(gap0m) | ON | 4 | 416 | 1 | 122 | 213 | 8 | 72 |
| 0.2 | look | mixed(2adj+2far) | OFF | 0 | 413 | 0 | 285 | 0 | 3 | 125 |
| 0.2 | look | mixed(2adj+2far) | OFF | 0.5 | 413 | 0 | 286 | 0 | 3 | 124 |
| 0.2 | look | mixed(2adj+2far) | OFF | 1 | 413 | 0 | 290 | 0 | 2 | 121 |
| 0.2 | look | mixed(2adj+2far) | OFF | 2 | 413 | 0 | 307 | 0 | 1 | 105 |
| 0.2 | look | mixed(2adj+2far) | OFF | 4 | 413 | 16 | 347 | 0 | 0 | 50 |
| 0.2 | look | mixed(2adj+2far) | ON | 0 | 413 | 44 | 259 | 44 | 0 | 66 |
| 0.2 | look | mixed(2adj+2far) | ON | 0.5 | 413 | 45 | 257 | 44 | 0 | 67 |
| 0.2 | look | mixed(2adj+2far) | ON | 1 | 413 | 46 | 256 | 43 | 0 | 68 |
| 0.2 | look | mixed(2adj+2far) | ON | 2 | 413 | 45 | 257 | 44 | 0 | 67 |
| 0.2 | look | mixed(2adj+2far) | ON | 4 | 413 | 56 | 251 | 42 | 0 | 64 |

### Threshold sensitivity (smoothing OFF, lead 0.2-0.8 s, look_away_prob=0.2; one parameter varied at a time from the defaults lead_s=0.4, lag_s=0.2, min_share=0.6, min_margin=0.25)

| layout | noise (deg) | varied | value | n aligned / look | ALIGNED: correct-bound | ALIGNED: silent-wrong | ALIGNED: prompt | LOOK-AWAY: correct-bound | LOOK-AWAY: silent-wrong | LOOK-AWAY: prompt |
|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.2/0.1 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  72.9% [63.3- 80.8] |  27.1% [19.2- 36.7] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.2/0.2 | 404 / 96 |  99.8% [98.6-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  99.0% [94.3- 99.8] |   1.0% [ 0.2-  5.7] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.2/0.4 | 404 / 96 |  54.2% [49.3- 59.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] | 100.0% [96.2-100.0] |   0.0% [ 0.0-  3.8] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.4/0.1 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   7.3% [ 3.6- 14.3] |  20.8% [13.9- 30.0] |  78.1% [68.9- 85.2] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.4/0.2 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.4/0.4 | 404 / 96 |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  65.6% [55.7- 74.4] |  34.4% [25.6- 44.3] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.6/0.1 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |  53.1% [43.2- 62.8] |  15.6% [ 9.7- 24.2] |  32.3% [23.8- 42.2] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.6/0.2 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |  19.8% [13.1- 28.9] |  17.7% [11.4- 26.5] |  72.9% [63.3- 80.8] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.6/0.4 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  30.2% [21.9- 40.0] |  69.8% [60.0- 78.1] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.8/0.1 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |  62.5% [52.5- 71.5] |   7.3% [ 3.6- 14.3] |  32.3% [23.8- 42.2] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.8/0.2 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |  40.6% [31.3- 50.6] |  12.5% [ 7.3- 20.6] |  50.0% [40.2- 59.8] |
| adjacent(gap0.1m) | 1 | lead_s/lag_s | 0.8/0.4 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  19.8% [13.1- 28.9] |  80.2% [71.1- 86.9] |
| adjacent(gap0.1m) | 1 | min_share | 0.5 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   7.3% [ 3.6- 14.3] |  24.0% [16.5- 33.4] |  76.0% [66.6- 83.5] |
| adjacent(gap0.1m) | 1 | min_share | 0.6 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |
| adjacent(gap0.1m) | 1 | min_share | 0.75 | 404 / 96 |  95.0% [92.5- 96.8] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  18.8% [12.2- 27.7] |  81.2% [72.3- 87.8] |
| adjacent(gap0.1m) | 1 | min_share | 0.9 | 404 / 96 |  54.2% [49.3- 59.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  12.5% [ 7.3- 20.6] |  87.5% [79.4- 92.7] |
| adjacent(gap0.1m) | 1 | min_margin | 0.1 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |
| adjacent(gap0.1m) | 1 | min_margin | 0.25 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |
| adjacent(gap0.1m) | 1 | min_margin | 0.4 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  20.8% [13.9- 30.0] |  79.2% [70.0- 86.1] |
| adjacent(gap0.1m) | 1 | min_margin | 0.6 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  75.5% [71.1- 79.4] |   0.0% [ 0.0-  3.8] |  17.7% [11.4- 26.5] |  82.3% [73.5- 88.6] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.2/0.1 | 404 / 96 |  99.8% [98.6-100.0] |   0.0% [ 0.0-  0.9] |  70.5% [65.9- 74.8] |   0.0% [ 0.0-  3.8] |  64.6% [54.6- 73.4] |  35.4% [26.6- 45.4] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.2/0.2 | 404 / 96 |  93.3% [90.5- 95.4] |   0.0% [ 0.0-  0.9] |  71.8% [67.2- 75.9] |   0.0% [ 0.0-  3.8] |  94.8% [88.4- 97.8] |   5.2% [ 2.2- 11.6] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.2/0.4 | 404 / 96 |  52.5% [47.6- 57.3] |   0.0% [ 0.0-  0.9] |  74.8% [70.3- 78.7] |   0.0% [ 0.0-  3.8] | 100.0% [96.2-100.0] |   0.0% [ 0.0-  3.8] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.4/0.1 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |   5.2% [ 2.2- 11.6] |  19.8% [13.1- 28.9] |  77.1% [67.7- 84.4] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.4/0.2 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.4/0.4 | 404 / 96 |  68.8% [64.1- 73.1] |   0.0% [ 0.0-  0.9] |  73.5% [69.0- 77.6] |   0.0% [ 0.0-  3.8] |  53.1% [43.2- 62.8] |  46.9% [37.2- 56.8] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.6/0.1 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |  49.0% [39.2- 58.8] |  14.6% [ 8.9- 23.0] |  38.5% [29.4- 48.5] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.6/0.2 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |   9.4% [ 5.0- 16.9] |  17.7% [11.4- 26.5] |  76.0% [66.6- 83.5] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.6/0.4 | 404 / 96 |  94.1% [91.3- 96.0] |   0.0% [ 0.0-  0.9] |  71.3% [66.7- 75.5] |   0.0% [ 0.0-  3.8] |  25.0% [17.4- 34.5] |  75.0% [65.5- 82.6] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.8/0.1 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |  56.2% [46.3- 65.7] |   7.3% [ 3.6- 14.3] |  39.6% [30.4- 49.6] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.8/0.2 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |  36.5% [27.5- 46.4] |  10.4% [ 5.8- 18.1] |  58.3% [48.3- 67.7] |
| adjacent(gap0.1m) | 2 | lead_s/lag_s | 0.8/0.4 | 404 / 96 |  98.5% [96.8- 99.3] |   0.0% [ 0.0-  0.9] |  70.8% [66.2- 75.0] |   0.0% [ 0.0-  3.8] |  17.7% [11.4- 26.5] |  82.3% [73.5- 88.6] |
| adjacent(gap0.1m) | 2 | min_share | 0.5 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |   5.2% [ 2.2- 11.6] |  22.9% [15.6- 32.3] |  77.1% [67.7- 84.4] |
| adjacent(gap0.1m) | 2 | min_share | 0.6 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |
| adjacent(gap0.1m) | 2 | min_share | 0.75 | 404 / 96 |  81.4% [77.4- 84.9] |   0.0% [ 0.0-  0.9] |  73.0% [68.5- 77.1] |   0.0% [ 0.0-  3.8] |  18.8% [12.2- 27.7] |  81.2% [72.3- 87.8] |
| adjacent(gap0.1m) | 2 | min_share | 0.9 | 404 / 96 |  47.5% [42.7- 52.4] |   0.0% [ 0.0-  0.9] |  73.5% [69.0- 77.6] |   0.0% [ 0.0-  3.8] |  11.5% [ 6.5- 19.4] |  88.5% [80.6- 93.5] |
| adjacent(gap0.1m) | 2 | min_margin | 0.1 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |
| adjacent(gap0.1m) | 2 | min_margin | 0.25 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |   0.0% [ 0.0-  3.8] |  21.9% [14.8- 31.1] |  78.1% [68.9- 85.2] |
| adjacent(gap0.1m) | 2 | min_margin | 0.4 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  70.3% [65.7- 74.5] |   0.0% [ 0.0-  3.8] |  19.8% [13.1- 28.9] |  80.2% [71.1- 86.9] |
| adjacent(gap0.1m) | 2 | min_margin | 0.6 | 404 / 96 | 100.0% [99.1-100.0] |   0.0% [ 0.0-  0.9] |  72.5% [68.0- 76.7] |   0.0% [ 0.0-  3.8] |  17.7% [11.4- 26.5] |  82.3% [73.5- 88.6] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.2/0.1 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   0.0% [ 0.0-  3.2] |  44.4% [35.8- 53.5] |  55.6% [46.5- 64.2] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.2/0.2 | 383 / 117 |  86.2% [82.3- 89.3] |   0.0% [ 0.0-  1.0] |  76.5% [72.0- 80.5] |   0.0% [ 0.0-  3.2] |  96.6% [91.5- 98.7] |   3.4% [ 1.3-  8.5] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.2/0.4 | 383 / 117 |  47.5% [42.6- 52.5] |   0.0% [ 0.0-  1.0] |  76.8% [72.3- 80.7] |   0.0% [ 0.0-  3.2] | 100.0% [96.8-100.0] |   0.0% [ 0.0-  3.2] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.4/0.1 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   1.7% [ 0.5-  6.0] |  16.2% [10.6- 24.0] |  82.1% [74.1- 88.0] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.4/0.2 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   0.0% [ 0.0-  3.2] |  17.9% [12.0- 25.9] |  82.1% [74.1- 88.0] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.4/0.4 | 383 / 117 |  59.8% [54.8- 64.6] |   0.0% [ 0.0-  1.0] |  76.5% [72.0- 80.5] |   0.0% [ 0.0-  3.2] |  47.9% [39.0- 56.8] |  52.1% [43.2- 61.0] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.6/0.1 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |  47.9% [39.0- 56.8] |   9.4% [ 5.3- 16.1] |  42.7% [34.1- 51.8] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.6/0.2 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   3.4% [ 1.3-  8.5] |  13.7% [ 8.6- 21.1] |  84.6% [77.0- 90.0] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.6/0.4 | 383 / 117 |  97.9% [95.9- 98.9] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   0.0% [ 0.0-  3.2] |  23.9% [17.1- 32.4] |  76.1% [67.6- 82.9] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.8/0.1 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |  61.5% [52.5- 69.9] |   6.8% [ 3.5- 12.9] |  31.6% [23.9- 40.5] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.8/0.2 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |  31.6% [23.9- 40.5] |   8.5% [ 4.7- 15.0] |  60.7% [51.6- 69.1] |
| mixed(2adj+2far) | 1 | lead_s/lag_s | 0.8/0.4 | 383 / 117 |  99.7% [98.5-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   0.0% [ 0.0-  3.2] |  16.2% [10.6- 24.0] |  83.8% [76.0- 89.4] |
| mixed(2adj+2far) | 1 | min_share | 0.5 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   1.7% [ 0.5-  6.0] |  20.5% [14.2- 28.7] |  79.5% [71.3- 85.8] |
| mixed(2adj+2far) | 1 | min_share | 0.6 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   0.0% [ 0.0-  3.2] |  17.9% [12.0- 25.9] |  82.1% [74.1- 88.0] |
| mixed(2adj+2far) | 1 | min_share | 0.75 | 383 / 117 |  77.5% [73.1- 81.4] |   0.0% [ 0.0-  1.0] |  76.5% [72.0- 80.5] |   0.0% [ 0.0-  3.2] |  13.7% [ 8.6- 21.1] |  86.3% [78.9- 91.4] |
| mixed(2adj+2far) | 1 | min_share | 0.9 | 383 / 117 |  47.0% [42.1- 52.0] |   0.0% [ 0.0-  1.0] |  76.8% [72.3- 80.7] |   0.0% [ 0.0-  3.2] |   7.7% [ 4.1- 14.0] |  92.3% [86.0- 95.9] |
| mixed(2adj+2far) | 1 | min_margin | 0.1 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   0.0% [ 0.0-  3.2] |  18.8% [12.8- 26.8] |  81.2% [73.2- 87.2] |
| mixed(2adj+2far) | 1 | min_margin | 0.25 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   0.0% [ 0.0-  3.2] |  17.9% [12.0- 25.9] |  82.1% [74.1- 88.0] |
| mixed(2adj+2far) | 1 | min_margin | 0.4 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  75.7% [71.2- 79.7] |   0.0% [ 0.0-  3.2] |  16.2% [10.6- 24.0] |  83.8% [76.0- 89.4] |
| mixed(2adj+2far) | 1 | min_margin | 0.6 | 383 / 117 | 100.0% [99.0-100.0] |   0.0% [ 0.0-  1.0] |  76.5% [72.0- 80.5] |   0.0% [ 0.0-  3.2] |  12.8% [ 7.9- 20.1] |  87.2% [79.9- 92.1] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.2/0.1 | 383 / 117 |  95.6% [93.0- 97.2] |   0.0% [ 0.0-  1.0] |  64.0% [59.0- 68.6] |   0.0% [ 0.0-  3.2] |  38.5% [30.1- 47.5] |  61.5% [52.5- 69.9] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.2/0.2 | 383 / 117 |  73.6% [69.0- 77.8] |   0.0% [ 0.0-  1.0] |  67.9% [63.1- 72.4] |   0.0% [ 0.0-  3.2] |  76.1% [67.6- 82.9] |  23.9% [17.1- 32.4] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.2/0.4 | 383 / 117 |  44.1% [39.2- 49.1] |   0.0% [ 0.0-  1.0] |  74.2% [69.5- 78.3] |   0.0% [ 0.0-  3.2] |  88.0% [80.9- 92.7] |  12.0% [ 7.3- 19.1] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.4/0.1 | 383 / 117 |  98.7% [97.0- 99.4] |   0.0% [ 0.0-  1.0] |  62.4% [57.5- 67.1] |   1.7% [ 0.5-  6.0] |  15.4% [10.0- 23.0] |  82.9% [75.1- 88.7] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.4/0.2 | 383 / 117 |  92.4% [89.3- 94.7] |   0.0% [ 0.0-  1.0] |  64.5% [59.6- 69.1] |   0.0% [ 0.0-  3.2] |  16.2% [10.6- 24.0] |  83.8% [76.0- 89.4] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.4/0.4 | 383 / 117 |  52.2% [47.2- 57.2] |   0.0% [ 0.0-  1.0] |  71.8% [67.1- 76.1] |   0.0% [ 0.0-  3.2] |  38.5% [30.1- 47.5] |  61.5% [52.5- 69.9] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.6/0.1 | 383 / 117 |  99.0% [97.3- 99.6] |   0.0% [ 0.0-  1.0] |  62.1% [57.2- 66.9] |  27.4% [20.1- 36.1] |   8.5% [ 4.7- 15.0] |  64.1% [55.1- 72.2] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.6/0.2 | 383 / 117 |  97.4% [95.3- 98.6] |   0.0% [ 0.0-  1.0] |  63.2% [58.2- 67.9] |   2.6% [ 0.9-  7.3] |  10.3% [ 6.0- 17.1] |  89.7% [82.9- 94.0] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.6/0.4 | 383 / 117 |  75.5% [70.9- 79.5] |   0.0% [ 0.0-  1.0] |  68.9% [64.1- 73.4] |   0.0% [ 0.0-  3.2] |  19.7% [13.5- 27.8] |  80.3% [72.2- 86.5] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.8/0.1 | 383 / 117 |  99.5% [98.1- 99.9] |   0.0% [ 0.0-  1.0] |  62.1% [57.2- 66.9] |  40.2% [31.7- 49.2] |   6.0% [ 2.9- 11.8] |  53.8% [44.8- 62.6] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.8/0.2 | 383 / 117 |  98.2% [96.3- 99.1] |   0.0% [ 0.0-  1.0] |  62.9% [58.0- 67.6] |  12.0% [ 7.3- 19.1] |   6.8% [ 3.5- 12.9] |  81.2% [73.2- 87.2] |
| mixed(2adj+2far) | 2 | lead_s/lag_s | 0.8/0.4 | 383 / 117 |  83.6% [79.5- 86.9] |   0.0% [ 0.0-  1.0] |  67.1% [62.2- 71.6] |   0.0% [ 0.0-  3.2] |  12.8% [ 7.9- 20.1] |  87.2% [79.9- 92.1] |
| mixed(2adj+2far) | 2 | min_share | 0.5 | 383 / 117 |  98.7% [97.0- 99.4] |   0.0% [ 0.0-  1.0] |  62.7% [57.7- 67.4] |   1.7% [ 0.5-  6.0] |  21.4% [14.9- 29.6] |  78.6% [70.4- 85.1] |
| mixed(2adj+2far) | 2 | min_share | 0.6 | 383 / 117 |  92.4% [89.3- 94.7] |   0.0% [ 0.0-  1.0] |  64.5% [59.6- 69.1] |   0.0% [ 0.0-  3.2] |  16.2% [10.6- 24.0] |  83.8% [76.0- 89.4] |
| mixed(2adj+2far) | 2 | min_share | 0.75 | 383 / 117 |  59.5% [54.5- 64.3] |   0.0% [ 0.0-  1.0] |  70.2% [65.5- 74.6] |   0.0% [ 0.0-  3.2] |  11.1% [ 6.6- 18.1] |  88.9% [81.9- 93.4] |
| mixed(2adj+2far) | 2 | min_share | 0.9 | 383 / 117 |  29.8% [25.4- 34.5] |   0.0% [ 0.0-  1.0] |  71.3% [66.6- 75.6] |   0.0% [ 0.0-  3.2] |   5.1% [ 2.4- 10.7] |  94.0% [88.2- 97.1] |
| mixed(2adj+2far) | 2 | min_margin | 0.1 | 383 / 117 |  92.4% [89.3- 94.7] |   0.0% [ 0.0-  1.0] |  64.5% [59.6- 69.1] |   0.0% [ 0.0-  3.2] |  16.2% [10.6- 24.0] |  83.8% [76.0- 89.4] |
| mixed(2adj+2far) | 2 | min_margin | 0.25 | 383 / 117 |  92.4% [89.3- 94.7] |   0.0% [ 0.0-  1.0] |  64.5% [59.6- 69.1] |   0.0% [ 0.0-  3.2] |  16.2% [10.6- 24.0] |  83.8% [76.0- 89.4] |
| mixed(2adj+2far) | 2 | min_margin | 0.4 | 383 / 117 |  92.4% [89.3- 94.7] |   0.0% [ 0.0-  1.0] |  64.5% [59.6- 69.1] |   0.0% [ 0.0-  3.2] |  15.4% [10.0- 23.0] |  84.6% [77.0- 90.0] |
| mixed(2adj+2far) | 2 | min_margin | 0.6 | 383 / 117 |  92.4% [89.3- 94.7] |   0.0% [ 0.0-  1.0] |  68.9% [64.1- 73.4] |   0.0% [ 0.0-  3.2] |  12.0% [ 7.3- 19.1] |  88.0% [80.9- 92.7] |

### Systematic bias (constant yaw of every ray toward +x; 1 deg Gaussian noise on top; look_away_prob=0)

| layout | lead (s) | smoothing | bias (deg) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | naive ray-at-word wrong |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| far(gap1.0m) | lead0.0-0.2 | OFF | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   8.2% [ 6.1- 10.9] |   0.2% [ 0.0-  1.1] |
| far(gap1.0m) | lead0.0-0.2 | ON | 0 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   0.6% [ 0.2-  1.7] |   0.2% [ 0.0-  1.1] |
| far(gap1.0m) | lead0.0-0.2 | OFF | 1 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   8.2% [ 6.1- 10.9] |   1.2% [ 0.6-  2.6] |
| far(gap1.0m) | lead0.0-0.2 | ON | 1 | 500 |  99.2% [98.0- 99.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |   1.0% [ 0.4-  2.3] |   1.2% [ 0.6-  2.6] |
| far(gap1.0m) | lead0.0-0.2 | OFF | 2 | 500 |  93.8% [91.3- 95.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   6.2% [ 4.4-  8.7] |   7.0% [ 5.1-  9.6] |   5.8% [ 4.1-  8.2] |
| far(gap1.0m) | lead0.0-0.2 | ON | 2 | 500 |  94.8% [92.5- 96.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   5.2% [ 3.6-  7.5] |   1.0% [ 0.4-  2.3] |   5.8% [ 4.1-  8.2] |
| far(gap1.0m) | lead0.0-0.2 | OFF | 3 | 500 |  82.8% [79.2- 85.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  17.2% [14.1- 20.8] |   5.6% [ 3.9-  8.0] |  13.8% [11.1- 17.1] |
| far(gap1.0m) | lead0.0-0.2 | ON | 3 | 500 |  86.4% [83.1- 89.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  13.6% [10.9- 16.9] |   0.6% [ 0.2-  1.7] |  13.8% [11.1- 17.1] |
| far(gap1.0m) | lead0.0-0.2 | OFF | 5 | 500 |  60.2% [55.8- 64.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |  39.6% [35.4- 44.0] |   3.2% [ 2.0-  5.1] |  38.4% [34.2- 42.7] |
| far(gap1.0m) | lead0.0-0.2 | ON | 5 | 500 |  60.8% [56.5- 65.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  39.2% [35.0- 43.5] |   0.6% [ 0.2-  1.7] |  38.4% [34.2- 42.7] |
| far(gap1.0m) | lead0.2-0.4 | OFF | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  44.8% [40.5- 49.2] |   1.2% [ 0.6-  2.6] |
| far(gap1.0m) | lead0.2-0.4 | ON | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   8.8% [ 6.6- 11.6] |   1.2% [ 0.6-  2.6] |
| far(gap1.0m) | lead0.2-0.4 | OFF | 1 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |   0.0% [ 0.0-  0.8] |  43.6% [39.3- 48.0] |   1.4% [ 0.7-  2.9] |
| far(gap1.0m) | lead0.2-0.4 | ON | 1 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   9.2% [ 7.0- 12.1] |   1.4% [ 0.7-  2.9] |
| far(gap1.0m) | lead0.2-0.4 | OFF | 2 | 500 |  93.2% [90.6- 95.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   2.6% [ 1.5-  4.4] |   4.2% [ 2.8-  6.3] |  41.2% [37.0- 45.6] |   6.4% [ 4.6-  8.9] |
| far(gap1.0m) | lead0.2-0.4 | ON | 2 | 500 |  95.4% [93.2- 96.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |   4.2% [ 2.8-  6.3] |   9.0% [ 6.8- 11.8] |   6.4% [ 4.6-  8.9] |
| far(gap1.0m) | lead0.2-0.4 | OFF | 3 | 500 |  82.0% [78.4- 85.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   5.2% [ 3.6-  7.5] |  12.8% [10.2- 16.0] |  35.0% [30.9- 39.3] |  15.6% [12.7- 19.0] |
| far(gap1.0m) | lead0.2-0.4 | ON | 3 | 500 |  84.0% [80.5- 87.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |  15.2% [12.3- 18.6] |   8.4% [ 6.3- 11.2] |  15.6% [12.7- 19.0] |
| far(gap1.0m) | lead0.2-0.4 | OFF | 5 | 500 |  55.2% [50.8- 59.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  10.4% [ 8.0- 13.4] |  34.4% [30.4- 38.7] |  24.0% [20.5- 27.9] |  41.4% [37.2- 45.8] |
| far(gap1.0m) | lead0.2-0.4 | ON | 5 | 500 |  58.4% [54.0- 62.6] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   2.0% [ 1.1-  3.6] |  39.6% [35.4- 44.0] |   7.6% [ 5.6- 10.3] |  41.4% [37.2- 45.8] |
| adjacent(gap0.1m) | lead0.0-0.2 | OFF | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  14.6% [11.8- 18.0] |   0.4% [ 0.1-  1.4] |
| adjacent(gap0.1m) | lead0.0-0.2 | ON | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   3.2% [ 2.0-  5.1] |   0.4% [ 0.1-  1.4] |
| adjacent(gap0.1m) | lead0.0-0.2 | OFF | 1 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  13.8% [11.1- 17.1] |   1.2% [ 0.6-  2.6] |
| adjacent(gap0.1m) | lead0.0-0.2 | ON | 1 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   3.4% [ 2.1-  5.4] |   1.2% [ 0.6-  2.6] |
| adjacent(gap0.1m) | lead0.0-0.2 | OFF | 2 | 500 |  99.6% [98.6- 99.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |  13.6% [10.9- 16.9] |   3.0% [ 1.8-  4.9] |
| adjacent(gap0.1m) | lead0.0-0.2 | ON | 2 | 500 |  98.8% [97.4- 99.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.2% [ 0.6-  2.6] |   4.0% [ 2.6-  6.1] |   3.0% [ 1.8-  4.9] |
| adjacent(gap0.1m) | lead0.0-0.2 | OFF | 3 | 500 |  91.2% [88.4- 93.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |   8.4% [ 6.3- 11.2] |  11.6% [ 9.1- 14.7] |   8.6% [ 6.4- 11.4] |
| adjacent(gap0.1m) | lead0.0-0.2 | ON | 3 | 500 |  92.4% [89.7- 94.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   7.6% [ 5.6- 10.3] |   3.6% [ 2.3-  5.6] |   8.6% [ 6.4- 11.4] |
| adjacent(gap0.1m) | lead0.0-0.2 | OFF | 5 | 500 |  73.8% [69.8- 77.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   4.0% [ 2.6-  6.1] |  22.2% [18.8- 26.0] |  11.4% [ 8.9- 14.5] |  23.4% [19.9- 27.3] |
| adjacent(gap0.1m) | lead0.0-0.2 | ON | 5 | 500 |  74.2% [70.2- 77.8] |   0.4% [ 0.1-  1.4] |   0.4% [ 0.1-  1.4] |   0.0% [ 0.0-  0.8] |  25.4% [21.8- 29.4] |   3.0% [ 1.8-  4.9] |  23.4% [19.9- 27.3] |
| adjacent(gap0.1m) | lead0.2-0.4 | OFF | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  39.4% [35.2- 43.7] |   0.2% [ 0.0-  1.1] |
| adjacent(gap0.1m) | lead0.2-0.4 | ON | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  25.6% [22.0- 29.6] |   0.2% [ 0.0-  1.1] |
| adjacent(gap0.1m) | lead0.2-0.4 | OFF | 1 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  39.0% [34.8- 43.3] |   0.2% [ 0.0-  1.1] |
| adjacent(gap0.1m) | lead0.2-0.4 | ON | 1 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  26.0% [22.3- 30.0] |   0.2% [ 0.0-  1.1] |
| adjacent(gap0.1m) | lead0.2-0.4 | OFF | 2 | 500 |  99.4% [98.3- 99.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |   0.2% [ 0.0-  1.1] |  39.2% [35.0- 43.5] |   2.2% [ 1.2-  3.9] |
| adjacent(gap0.1m) | lead0.2-0.4 | ON | 2 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |  24.0% [20.5- 27.9] |   2.2% [ 1.2-  3.9] |
| adjacent(gap0.1m) | lead0.2-0.4 | OFF | 3 | 500 |  92.0% [89.3- 94.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   2.8% [ 1.7-  4.6] |   5.2% [ 3.6-  7.5] |  36.6% [32.5- 40.9] |   7.8% [ 5.8- 10.5] |
| adjacent(gap0.1m) | lead0.2-0.4 | ON | 3 | 500 |  93.2% [90.6- 95.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |   6.2% [ 4.4-  8.7] |  23.4% [19.9- 27.3] |   7.8% [ 5.8- 10.5] |
| adjacent(gap0.1m) | lead0.2-0.4 | OFF | 5 | 500 |  76.2% [72.3- 79.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   8.0% [ 5.9- 10.7] |  15.8% [12.9- 19.3] |  30.8% [26.9- 35.0] |  23.0% [19.5- 26.9] |
| adjacent(gap0.1m) | lead0.2-0.4 | ON | 5 | 500 |  76.8% [72.9- 80.3] |   0.2% [ 0.0-  1.1] |   0.2% [ 0.0-  1.1] |   0.6% [ 0.2-  1.7] |  22.4% [19.0- 26.3] |  19.4% [16.2- 23.1] |  23.0% [19.5- 26.9] |
| abutting(gap0m) | lead0.0-0.2 | OFF | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  14.0% [11.2- 17.3] |   0.8% [ 0.3-  2.0] |
| abutting(gap0m) | lead0.0-0.2 | ON | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   4.2% [ 2.8-  6.3] |   0.8% [ 0.3-  2.0] |
| abutting(gap0m) | lead0.0-0.2 | OFF | 1 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  14.2% [11.4- 17.5] |   0.8% [ 0.3-  2.0] |
| abutting(gap0m) | lead0.0-0.2 | ON | 1 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   5.4% [ 3.7-  7.7] |   0.8% [ 0.3-  2.0] |
| abutting(gap0m) | lead0.0-0.2 | OFF | 2 | 500 |  99.6% [98.6- 99.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |  14.0% [11.2- 17.3] |   2.6% [ 1.5-  4.4] |
| abutting(gap0m) | lead0.0-0.2 | ON | 2 | 500 |  99.2% [98.0- 99.7] |   0.4% [ 0.1-  1.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |   6.2% [ 4.4-  8.7] |   2.6% [ 1.5-  4.4] |
| abutting(gap0m) | lead0.0-0.2 | OFF | 3 | 500 |  91.6% [88.8- 93.7] |   2.6% [ 1.5-  4.4] |   1.2% [ 0.6-  2.6] |   2.2% [ 1.2-  3.9] |   3.6% [ 2.3-  5.6] |  17.0% [14.0- 20.5] |   6.8% [ 4.9-  9.4] |
| abutting(gap0m) | lead0.0-0.2 | ON | 3 | 500 |  93.4% [90.9- 95.3] |   3.2% [ 2.0-  5.1] |   2.2% [ 1.2-  3.9] |   0.0% [ 0.0-  0.8] |   3.4% [ 2.1-  5.4] |   7.0% [ 5.1-  9.6] |   6.8% [ 4.9-  9.4] |
| abutting(gap0m) | lead0.0-0.2 | OFF | 5 | 500 |  75.8% [71.9- 79.3] |  12.2% [ 9.6- 15.4] |   8.8% [ 6.6- 11.6] |   1.6% [ 0.8-  3.1] |  10.4% [ 8.0- 13.4] |  15.6% [12.7- 19.0] |  22.8% [19.3- 26.7] |
| abutting(gap0m) | lead0.0-0.2 | ON | 5 | 500 |  77.8% [74.0- 81.2] |  12.2% [ 9.6- 15.4] |  11.0% [ 8.5- 14.0] |   0.2% [ 0.0-  1.1] |   9.8% [ 7.5- 12.7] |   7.6% [ 5.6- 10.3] |  22.8% [19.3- 26.7] |
| abutting(gap0m) | lead0.2-0.4 | OFF | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  52.0% [47.6- 56.3] |   0.6% [ 0.2-  1.7] |
| abutting(gap0m) | lead0.2-0.4 | ON | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  31.8% [27.9- 36.0] |   0.6% [ 0.2-  1.7] |
| abutting(gap0m) | lead0.2-0.4 | OFF | 1 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  51.8% [47.4- 56.1] |   0.8% [ 0.3-  2.0] |
| abutting(gap0m) | lead0.2-0.4 | ON | 1 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  31.6% [27.7- 35.8] |   0.8% [ 0.3-  2.0] |
| abutting(gap0m) | lead0.2-0.4 | OFF | 2 | 500 |  99.6% [98.6- 99.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |   0.0% [ 0.0-  0.8] |  51.6% [47.2- 56.0] |   2.2% [ 1.2-  3.9] |
| abutting(gap0m) | lead0.2-0.4 | ON | 2 | 500 |  99.8% [98.9-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |  31.8% [27.9- 36.0] |   2.2% [ 1.2-  3.9] |
| abutting(gap0m) | lead0.2-0.4 | OFF | 3 | 500 |  92.4% [89.7- 94.4] |   2.2% [ 1.2-  3.9] |   1.0% [ 0.4-  2.3] |   3.4% [ 2.1-  5.4] |   2.0% [ 1.1-  3.6] |  52.0% [47.6- 56.3] |   6.4% [ 4.6-  8.9] |
| abutting(gap0m) | lead0.2-0.4 | ON | 3 | 500 |  94.0% [91.6- 95.8] |   3.2% [ 2.0-  5.1] |   2.0% [ 1.1-  3.6] |   0.8% [ 0.3-  2.0] |   2.0% [ 1.1-  3.6] |  33.4% [29.4- 37.6] |   6.4% [ 4.6-  8.9] |
| abutting(gap0m) | lead0.2-0.4 | OFF | 5 | 500 |  74.6% [70.6- 78.2] |  14.6% [11.8- 18.0] |   8.6% [ 6.4- 11.4] |   4.4% [ 2.9-  6.6] |   6.4% [ 4.6-  8.9] |  43.0% [38.7- 47.4] |  22.0% [18.6- 25.8] |
| abutting(gap0m) | lead0.2-0.4 | ON | 5 | 500 |  77.0% [73.1- 80.5] |  15.2% [12.3- 18.6] |  11.6% [ 9.1- 14.7] |   1.2% [ 0.6-  2.6] |   6.6% [ 4.7-  9.1] |  30.2% [26.3- 34.4] |  22.0% [18.6- 25.8] |
| mixed(2adj+2far) | lead0.0-0.2 | OFF | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   9.8% [ 7.5- 12.7] |   0.2% [ 0.0-  1.1] |
| mixed(2adj+2far) | lead0.0-0.2 | ON | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.8% [ 0.9-  3.4] |   0.2% [ 0.0-  1.1] |
| mixed(2adj+2far) | lead0.0-0.2 | OFF | 1 | 500 |  99.2% [98.0- 99.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |   9.8% [ 7.5- 12.7] |   2.6% [ 1.5-  4.4] |
| mixed(2adj+2far) | lead0.0-0.2 | ON | 1 | 500 |  99.2% [98.0- 99.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.8% [ 0.3-  2.0] |   1.8% [ 0.9-  3.4] |   2.6% [ 1.5-  4.4] |
| mixed(2adj+2far) | lead0.0-0.2 | OFF | 2 | 500 |  91.0% [88.2- 93.2] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   9.0% [ 6.8- 11.8] |   9.2% [ 7.0- 12.1] |  10.0% [ 7.7- 12.9] |
| mixed(2adj+2far) | lead0.0-0.2 | ON | 2 | 500 |  93.2% [90.6- 95.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   6.8% [ 4.9-  9.4] |   2.0% [ 1.1-  3.6] |  10.0% [ 7.7- 12.9] |
| mixed(2adj+2far) | lead0.0-0.2 | OFF | 3 | 500 |  79.4% [75.6- 82.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.2% [ 0.0-  1.1] |  20.4% [17.1- 24.2] |   8.0% [ 5.9- 10.7] |  18.8% [15.6- 22.5] |
| mixed(2adj+2far) | lead0.0-0.2 | ON | 3 | 500 |  81.2% [77.5- 84.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  18.8% [15.6- 22.5] |   2.0% [ 1.1-  3.6] |  18.8% [15.6- 22.5] |
| mixed(2adj+2far) | lead0.0-0.2 | OFF | 5 | 500 |  56.8% [52.4- 61.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.6% [ 0.8-  3.1] |  41.6% [37.4- 46.0] |   6.6% [ 4.7-  9.1] |  41.0% [36.8- 45.4] |
| mixed(2adj+2far) | lead0.0-0.2 | ON | 5 | 500 |  56.2% [51.8- 60.5] |   0.2% [ 0.0-  1.1] |   0.2% [ 0.0-  1.1] |   0.0% [ 0.0-  0.8] |  43.6% [39.3- 48.0] |   2.0% [ 1.1-  3.6] |  41.0% [36.8- 45.4] |
| mixed(2adj+2far) | lead0.2-0.4 | OFF | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  47.6% [43.3- 52.0] |   0.8% [ 0.3-  2.0] |
| mixed(2adj+2far) | lead0.2-0.4 | ON | 0 | 500 | 100.0% [99.2-100.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  13.6% [10.9- 16.9] |   0.8% [ 0.3-  2.0] |
| mixed(2adj+2far) | lead0.2-0.4 | OFF | 1 | 500 |  98.8% [97.4- 99.4] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   1.0% [ 0.4-  2.3] |   0.2% [ 0.0-  1.1] |  46.8% [42.5- 51.2] |   2.0% [ 1.1-  3.6] |
| mixed(2adj+2far) | lead0.2-0.4 | ON | 1 | 500 |  99.6% [98.6- 99.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.4% [ 0.1-  1.4] |  12.6% [10.0- 15.8] |   2.0% [ 1.1-  3.6] |
| mixed(2adj+2far) | lead0.2-0.4 | OFF | 2 | 500 |  90.8% [87.9- 93.0] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   3.4% [ 2.1-  5.4] |   5.8% [ 4.1-  8.2] |  44.0% [39.7- 48.4] |   8.0% [ 5.9- 10.7] |
| mixed(2adj+2far) | lead0.2-0.4 | ON | 2 | 500 |  93.0% [90.4- 94.9] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |   6.4% [ 4.6-  8.9] |  12.4% [ 9.8- 15.6] |   8.0% [ 5.9- 10.7] |
| mixed(2adj+2far) | lead0.2-0.4 | OFF | 3 | 500 |  79.4% [75.6- 82.7] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   6.6% [ 4.7-  9.1] |  14.0% [11.2- 17.3] |  39.2% [35.0- 43.5] |  18.8% [15.6- 22.5] |
| mixed(2adj+2far) | lead0.2-0.4 | ON | 3 | 500 |  82.2% [78.6- 85.3] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   0.6% [ 0.2-  1.7] |  17.2% [14.1- 20.8] |  11.2% [ 8.7- 14.3] |  18.8% [15.6- 22.5] |
| mixed(2adj+2far) | lead0.2-0.4 | OFF | 5 | 500 |  55.2% [50.8- 59.5] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |  13.2% [10.5- 16.4] |  31.6% [27.7- 35.8] |  28.4% [24.6- 32.5] |  43.2% [38.9- 47.6] |
| mixed(2adj+2far) | lead0.2-0.4 | ON | 5 | 500 |  57.8% [53.4- 62.1] |   0.0% [ 0.0-  0.8] |   0.0% [ 0.0-  0.8] |   3.0% [ 1.8-  4.9] |  39.2% [35.0- 43.5] |  11.6% [ 9.1- 14.7] |  43.2% [38.9- 47.6] |

---

## Appendix C. The script (`xr_eval.py`)

```python
#!/usr/bin/env python3
"""Synthetic evaluation of the yazses.xr deixis-binding + confirm pipeline (v2).

Pipeline per trial (mirrors XrSession.resolve_demonstrative):
    make_scenarios -> (optional RayFilter) -> raycast.nearest_hit -> PanelObservation
    -> bind_demonstrative -> confirm.decide(binding.margin, binding.confidence,
       panel nearest the onset vs panel nearest the utterance end)

SYNTHETIC ONLY: the trajectories come from yazses.xr.synth, whose assumptions are the
same ones the binder was designed around. This tests self-consistency and parameter
sensitivity, not real-world accuracy.

Scoring (see the synth.py module docstring): every trial is scored against
``truth_panel_id`` (the intent). Trials are split into two strata by the NOISE-FREE
generated gaze at the word onset (the same seed, noise 0):
    aligned  - the eyes are on the intended panel when the word is spoken
    look     - the eyes have moved on before the word (look_away trials)
and are reported separately; a pooled number would depend on look_away_prob.

Run (from the worktree, so `yazses` resolves to src/):
    cd /home/mohsen/scratch/repos/yazses-xr
    PYTHONPATH=src python3 <this file> --n 500 --seed 20261030 --out <dir>
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from itertools import product

from yazses.xr.binding import PanelObservation, bind_demonstrative
from yazses.xr.confirm import decide
from yazses.xr.raycast import nearest_hit
from yazses.xr.smoothing import RayFilter
from yazses.xr.synth import make_scenarios
from yazses.xr.types import Panel, Ray, Vec3

W, H, Z = 0.6, 0.4, -2.0           # panel size and distance (m); eye at (0, 1.6, 0)
NOISE_DEG = (0.0, 0.5, 1.0, 2.0, 4.0)
BIAS_DEG = (0.0, 1.0, 2.0, 3.0, 5.0)
LOOK_AWAY_PROBS = (0.0, 0.2)
LEADS = {"lead0.0-0.2": (0.0, 0.2), "lead0.2-0.4": (0.2, 0.4),
         "lead0.2-0.8": (0.2, 0.8), "lead0.6-1.2": (0.6, 1.2)}
UTTERANCE_S = 0.3                   # "utterance end" = word onset + this
EDGE_TOL_S = 0.25                   # XrSession.edge_tolerance_s default
KEEP_BEFORE_S, KEEP_AFTER_S = 1.0, 0.6   # samples kept around the onset (no effect on results)
STRATA = ("aligned", "look")


def _panel(pid: str, x: float) -> Panel:
    return Panel(pid, Vec3(x, 1.6, Z), Vec3(0, 0, 1), Vec3(0, 1, 0), W, H)


def layouts() -> dict[str, list[tuple[str, float]]]:
    def row(gap: float, k: int = 3) -> list[tuple[str, float]]:
        pitch = W + gap
        return [(chr(65 + i), (i - (k - 1) / 2) * pitch) for i in range(k)]
    return {
        "far(gap1.0m)": row(1.0),                      # ~27 deg edge gap
        "adjacent(gap0.1m)": row(0.1),                 # ~2.9 deg edge gap
        "abutting(gap0m)": row(0.0),                   # touching edges
        "mixed(2adj+2far)": [("A", -0.35), ("B", 0.35), ("C", -2.0), ("D", 2.0)],
    }


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def yaw(sample, rad):
    """Rotate a sample's ray direction about the vertical axis: a constant tracker bias."""
    d = sample.ray.direction
    c, s_ = math.cos(rad), math.sin(rad)
    nd = Vec3(c * d.x + s_ * d.z, d.y, -s_ * d.x + c * d.z)
    return replace(sample, ray=Ray(sample.ray.origin, nd))


def _nearest_panel(obs, t):
    """Panel under the observation closest to t, within EDGE_TOL_S (XrSession._panel_near)."""
    best = min(obs, key=lambda o: abs(o.timestamp_s - t), default=None)
    if best is None or abs(best.timestamp_s - t) > EDGE_TOL_S:
        return None
    return best.hit.panel_id if best.hit is not None else None


def run_trial(sc, panels, smooth, params):
    samples = list(sc.samples)
    on = sc.word_onset_s
    # What a naive "ray at the word" resolver would answer, on the raw (unsmoothed) rays.
    before = [s for s in samples if s.timestamp_s <= on]
    naive = None
    if before:
        h = nearest_hit(before[-1].ray, panels)
        naive = h.panel_id if h else None
    if smooth:
        f = RayFilter()
        samples = [f.update(s) for s in samples]
    samples = [s for s in samples if on - KEEP_BEFORE_S <= s.timestamp_s <= on + KEEP_AFTER_S]
    obs = [PanelObservation(s.timestamp_s, nearest_hit(s.ray, panels), s.confidence)
           for s in samples]
    res = bind_demonstrative(obs, on, **params["bind"])
    d = decide(outcome=res.outcome.value, margin=res.margin, confidence=res.confidence,
               destructive=False, panel_at_onset=_nearest_panel(obs, on),
               panel_at_end=_nearest_panel(obs, on + UTTERANCE_S), **params["confirm"])
    # Diagnostic: the prompt that would remain if the eyes did not change panel during the
    # utterance (panel_at_end unknown), i.e. without the TARGET_CHANGED reason.
    d_no_tc = decide(outcome=res.outcome.value, margin=res.margin, confidence=res.confidence,
                     destructive=False, panel_at_onset=_nearest_panel(obs, on),
                     panel_at_end=None, **params["confirm"])
    return res.outcome.value, res.panel_id, d.confirm, d.reason.value, naive, d_no_tc.confirm


def cell(args):
    (lname, panels_spec, noise_deg, lead_name, lead, smooth, n, seed, params, bias_deg,
     look_away) = args
    panels = [_panel(p, x) for p, x in panels_spec]
    noise = math.radians(noise_deg)
    scs = make_scenarios(panels, n, seed, noise, lead, look_away_prob=look_away)
    ideal = make_scenarios(panels, n, seed, 0.0, lead, look_away_prob=look_away)
    if bias_deg:
        b = math.radians(bias_deg)
        scs = [replace(sc, samples=tuple(yaw(x, b) for x in sc.samples)) for sc in scs]
    out = {s: Counter() for s in ("all",) + STRATA}
    reasons = {s: Counter() for s in ("all",) + STRATA}
    for sc, isc in zip(scs, ideal):
        assert sc.truth_panel_id == isc.truth_panel_id and sc.word_onset_s == isc.word_onset_s
        stratum = "aligned" if isc.gaze_panel_at_onset == sc.truth_panel_id else "look"
        outcome, pid, confirm, reason, naive, confirm_no_tc = run_trial(sc, panels, smooth, params)
        ok = outcome == "bound" and pid == sc.truth_panel_id
        bad = outcome == "bound" and pid != sc.truth_panel_id
        for s in ("all", stratum):
            c = out[s]
            c["n"] += 1
            c[outcome] += 1
            c["correct"] += ok
            c["wrong"] += bad
            c["prompt"] += confirm
            c["prompt_no_tc"] += confirm_no_tc
            c["silent_wrong"] += bad and not confirm
            c["silent_correct"] += ok and not confirm
            c["naive_wrong"] += naive != sc.truth_panel_id
            reasons[s][reason] += 1
    return {"layout": lname, "noise_deg": noise_deg, "lead": lead_name, "smooth": smooth,
            "bias_deg": bias_deg, "look_away": look_away,
            "counts": {s: dict(c) for s, c in out.items()},
            "reasons": {s: dict(c) for s, c in reasons.items()}, "params": params}


DEFAULT_PARAMS = {"bind": {}, "confirm": {}}


def fmt(k, n):
    if n == 0:
        return "n/a"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:5.1f}% [{100 * lo:4.1f}-{100 * hi:5.1f}]"


COLS = [("correct", "correct-bound"), ("wrong", "WRONG-bound"), ("silent_wrong", "silent-wrong"),
        ("ambiguous", "ambiguous"), ("none", "none"), ("prompt", "prompt"),
        ("prompt_no_tc", "prompt w/o target-changed"), ("naive_wrong", "naive ray-at-word wrong")]


def table(rows, stratum, title):
    out = [f"**{title}**", "",
           "| noise (deg) | lead (s) | n | " + " | ".join(h for _, h in COLS) + " |",
           "|---:|---|---:|" + "|".join(["---:"] * len(COLS)) + "|"]
    for r in rows:
        c = r["counts"][stratum]
        n = c.get("n", 0)
        out.append(f"| {r['noise_deg']:g} | {r['lead']} | {n} | "
                   + " | ".join(fmt(c.get(k, 0), n) for k, _ in COLS) + " |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    spec = layouts()
    jobs = []
    for pi, la in enumerate(LOOK_AWAY_PROBS):
        for li, lname in enumerate(spec):
            for lj, (lead_name, lead) in enumerate(LEADS.items()):
                seed = a.seed + 1000 * li + lj       # same trials for every noise level/smoothing
                for noise, smooth in product(NOISE_DEG, (False, True)):
                    jobs.append((lname, spec[lname], noise, lead_name, lead, smooth, a.n, seed,
                                 DEFAULT_PARAMS, 0.0, la))
    # Sensitivity of the binder/confirm thresholds (unsmoothed, lead 0.2-0.8, look_away 0.2).
    sens_jobs = []
    for lname in ("adjacent(gap0.1m)", "mixed(2adj+2far)"):
        li = list(spec).index(lname)
        seed = a.seed + 1000 * li + 2
        for noise in (1.0, 2.0):
            variants = []
            for lead_s, lag_s in product((0.2, 0.4, 0.6, 0.8), (0.1, 0.2, 0.4)):
                variants.append({"bind": {"lead_s": lead_s, "lag_s": lag_s}, "confirm": {}})
            for ms in (0.5, 0.6, 0.75, 0.9):
                variants.append({"bind": {"min_share": ms}, "confirm": {}})
            for mm in (0.1, 0.25, 0.4, 0.6):
                variants.append({"bind": {}, "confirm": {"min_margin": mm}})
            for params in variants:
                sens_jobs.append((lname, spec[lname], noise, "lead0.2-0.8", LEADS["lead0.2-0.8"],
                                  False, a.n, seed, params, 0.0, 0.2))
    # Systematic bias (constant yaw of every ray toward +x, 1 deg Gaussian noise on top): the
    # error a zero-mean noise model cannot produce. look_away 0 (the eyes are on the target).
    bias_jobs = []
    for li, lname in enumerate(spec):
        for lead_name in ("lead0.0-0.2", "lead0.2-0.4"):
            lj = list(LEADS).index(lead_name)
            seed = a.seed + 1000 * li + lj
            for bias, smooth in product(BIAS_DEG, (False, True)):
                bias_jobs.append((lname, spec[lname], 1.0, lead_name, LEADS[lead_name], smooth,
                                  a.n, seed, DEFAULT_PARAMS, bias, 0.0))

    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(cell, jobs, chunksize=2))
        sres = list(ex.map(cell, sens_jobs, chunksize=2))
        bres = list(ex.map(cell, bias_jobs, chunksize=2))

    with open(f"{a.out}/xr_eval_results.json", "w") as fh:
        json.dump({"n": a.n, "seed": a.seed, "cells": res, "sensitivity": sres, "bias": bres}, fh)

    md = []
    conds = [(0.0, "aligned", "look_away_prob=0 (eyes still on the intended panel at the word)"),
             (0.2, "aligned", "look_away_prob=0.2, ALIGNED stratum (eyes on the intended panel)"),
             (0.2, "look", "look_away_prob=0.2, LOOK-AWAY stratum (eyes had moved on before the word)")]
    for la, stratum, label in conds:
        md.append(f"### Grid: {label}\n")
        for lname in spec:
            for smooth in (False, True):
                rows = [r for r in res if r["layout"] == lname and r["smooth"] == smooth
                        and r["look_away"] == la]
                md.append(table(rows, stratum, f"{lname} / smoothing {'ON' if smooth else 'OFF'}"))
                md.append("")
    md.append("### Prompt reasons, summed over leads, per condition, layout and noise\n")
    md.append("| look_away_prob | stratum | layout | smoothing | noise (deg) | trials | no_target | ambiguous_panels | target_changed | low_confidence | silent(none) |")
    md.append("|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for la, stratum, _ in conds:
        for lname in spec:
            for smooth in (False, True):
                for noise in NOISE_DEG:
                    tot = Counter()
                    n_tot = 0
                    for r in res:
                        if (r["layout"] == lname and r["smooth"] == smooth and r["look_away"] == la
                                and r["noise_deg"] == noise):
                            tot.update(r["reasons"][stratum])
                            n_tot += r["counts"][stratum].get("n", 0)
                    md.append(f"| {la:g} | {stratum} | {lname} | {'ON' if smooth else 'OFF'} | {noise:g} | {n_tot} | "
                              f"{tot['no_target']} | {tot['ambiguous_panels']} | "
                              f"{tot['target_changed_during_utterance']} | {tot['low_confidence']} | "
                              f"{tot['none']} |")
    md.append("")
    md.append("### Threshold sensitivity (smoothing OFF, lead 0.2-0.8 s, look_away_prob=0.2; one parameter varied at a time from the defaults lead_s=0.4, lag_s=0.2, min_share=0.6, min_margin=0.25)\n")
    md.append("| layout | noise (deg) | varied | value | n aligned / look | ALIGNED: correct-bound | ALIGNED: silent-wrong | ALIGNED: prompt | LOOK-AWAY: correct-bound | LOOK-AWAY: silent-wrong | LOOK-AWAY: prompt |")
    md.append("|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|")
    for r in sres:
        p = r["params"]
        if "lead_s" in p["bind"]:
            var, val = "lead_s/lag_s", f"{p['bind']['lead_s']}/{p['bind']['lag_s']}"
        elif "min_share" in p["bind"]:
            var, val = "min_share", str(p["bind"]["min_share"])
        else:
            var, val = "min_margin", str(p["confirm"]["min_margin"])
        ca, cl = r["counts"]["aligned"], r["counts"]["look"]
        md.append(f"| {r['layout']} | {r['noise_deg']:g} | {var} | {val} | {ca['n']} / {cl.get('n', 0)} | "
                  + " | ".join(fmt(ca.get(k, 0), ca["n"]) for k in ("correct", "silent_wrong", "prompt")) + " | "
                  + " | ".join(fmt(cl.get(k, 0), cl.get("n", 0)) for k in ("correct", "silent_wrong", "prompt"))
                  + " |")
    md.append("")
    md.append("### Systematic bias (constant yaw of every ray toward +x; 1 deg Gaussian noise on top; look_away_prob=0)\n")
    md.append("| layout | lead (s) | smoothing | bias (deg) | n | correct-bound | WRONG-bound | silent-wrong | ambiguous | none | prompt | naive ray-at-word wrong |")
    md.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in bres:
        c = r["counts"]["all"]
        n = c["n"]
        md.append(f"| {r['layout']} | {r['lead']} | {'ON' if r['smooth'] else 'OFF'} | {r['bias_deg']:g} | {n} | "
                  + " | ".join(fmt(c.get(k, 0), n) for k in
                               ("correct", "wrong", "silent_wrong", "ambiguous", "none", "prompt",
                                "naive_wrong")) + " |")
    with open(f"{a.out}/xr_eval_tables.md", "w") as fh:
        fh.write("\n".join(md) + "\n")
    print(f"wrote {a.out}/xr_eval_tables.md and xr_eval_results.json; "
          f"{len(res)} cells + {len(sres)} sensitivity + {len(bres)} bias cells, n={a.n}, seed={a.seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## Appendix D. Post-processing script for the Headline tables (`headline.py`)

Edit the `S` path (and the `full2/` input path) to wherever `xr_eval_results.json` was written.

```python
import json, math, collections
S = "<dir>/"
d = json.load(open(S + "xr_eval_results.json"))
cells = d["cells"]
LAY = ["far(gap1.0m)", "adjacent(gap0.1m)", "abutting(gap0m)", "mixed(2adj+2far)"]
LEADS = ["lead0.0-0.2", "lead0.2-0.4", "lead0.2-0.8", "lead0.6-1.2"]


def wil(k, n, z=1.959964):
    if n == 0:
        return 0, 1
    p = k / n; dd = 1 + z * z / n; c = (p + z * z / (2 * n)) / dd
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / dd
    return max(0, c - h), min(1, c + h)


def pct(c, k, ci=False):
    n = c.get("n", 0)
    if n == 0:
        return "n/a"
    v = c.get(k, 0)
    if ci:
        lo, hi = wil(v, n)
        return f"{100*v/n:.1f} [{100*lo:.1f}-{100*hi:.1f}]"
    return f"{100*v/n:.1f}"


def pool(la, stratum, lead, noise, smooth, layouts=LAY):
    t = collections.Counter()
    for r in cells:
        if (r["look_away"] == la and r["lead"] == lead and r["noise_deg"] == noise
                and r["smooth"] == smooth and r["layout"] in layouts):
            t.update(r["counts"][stratum])
    return t


out = []
# A: p=0, lead sweep at 1 deg, per layout
out.append("**Headline A. look_away_prob = 0 (eyes still on the intended panel): lead-time sweep at 1 degree mean noise.** Percent of trials, silent-wrong with 95% Wilson interval; n=500 per row.\n")
out.append("| layout | lead (s) | OFF: WRONG-bound | OFF: silent-wrong [CI] | OFF: correct-bound | OFF: prompt | OFF: prompt w/o target-changed | ON: WRONG-bound | ON: silent-wrong [CI] | ON: correct-bound | ON: prompt | ON: prompt w/o target-changed |")
out.append("|---|---|---:|---|---:|---:|---:|---:|---|---:|---:|---:|")
for l in LAY:
    for lead in LEADS:
        row = []
        for sm in (False, True):
            c = pool(0.0, "aligned", lead, 1.0, sm, [l])
            row += [pct(c, "wrong"), pct(c, "silent_wrong", True), pct(c, "correct"), pct(c, "prompt"), pct(c, "prompt_no_tc")]
        out.append(f"| {l} | {lead[4:]} | " + " | ".join(row) + " |")
out.append("")
# B: p=0 noise sweep, lead 0.2-0.4
out.append("**Headline B. look_away_prob = 0: noise sweep at lead 0.2-0.4 s.** Refused = ambiguous + none.\n")
out.append("| layout | noise (deg) | OFF: silent-wrong [CI] | OFF: correct-bound | OFF: refused | OFF: prompt | ON: silent-wrong [CI] | ON: correct-bound | ON: refused | ON: prompt |")
out.append("|---|---:|---|---:|---:|---:|---|---:|---:|---:|")
for l in LAY:
    for nz in (0.0, 0.5, 1.0, 2.0, 4.0):
        row = []
        for sm in (False, True):
            c = pool(0.0, "aligned", "lead0.2-0.4", nz, sm, [l])
            ref = 100 * (c.get("ambiguous", 0) + c.get("none", 0)) / c["n"]
            row += [pct(c, "silent_wrong", True), pct(c, "correct"), f"{ref:.1f}", pct(c, "prompt")]
        out.append(f"| {l} | {nz:g} | " + " | ".join(row) + " |")
out.append("")
# C: p=0.2 look-away stratum pooled across the 4 layouts
out.append("**Headline C. look_away_prob = 0.2, LOOK-AWAY stratum only (the eyes had moved on before the word), pooled over the four layouts** (layouts use different seeds, so these trials are independent across layouts; n is the pooled count; noise 1 degree). Scored against the intended panel. 'naive' = answering with the panel under the last ray at the word.\n")
out.append("| lead (s) | smoothing | n | correct-bound [CI] | WRONG-bound [CI] | silent-wrong [CI] | refused (ambig.+none) | prompt | naive ray-at-word wrong |")
out.append("|---|---|---:|---|---|---|---:|---:|---:|")
for lead in LEADS:
    for sm in (False, True):
        c = pool(0.2, "look", lead, 1.0, sm)
        ref = 100 * (c.get("ambiguous", 0) + c.get("none", 0)) / c["n"]
        out.append(f"| {lead[4:]} | {'ON' if sm else 'OFF'} | {c['n']} | {pct(c,'correct',True)} | {pct(c,'wrong',True)} | {pct(c,'silent_wrong',True)} | {ref:.1f} | {pct(c,'prompt')} | {pct(c,'naive_wrong')} |")
out.append("")
out.append("**Headline D. same look-away stratum, by noise (lead 0.2-0.8 s, pooled over layouts).**\n")
out.append("| noise (deg) | smoothing | n | correct-bound | WRONG-bound [CI] | silent-wrong [CI] | refused | prompt |")
out.append("|---:|---|---:|---:|---|---|---:|---:|")
for nz in (0.0, 0.5, 1.0, 2.0, 4.0):
    for sm in (False, True):
        c = pool(0.2, "look", "lead0.2-0.8", nz, sm)
        ref = 100 * (c.get("ambiguous", 0) + c.get("none", 0)) / c["n"]
        out.append(f"| {nz:g} | {'ON' if sm else 'OFF'} | {c['n']} | {pct(c,'correct')} | {pct(c,'wrong',True)} | {pct(c,'silent_wrong',True)} | {ref:.1f} | {pct(c,'prompt')} |")
out.append("")
out.append("**Headline E. look_away_prob = 0.2, ALIGNED stratum (the eyes are on the intended panel), pooled over layouts, noise 1 degree.** Should agree with Headline A.\n")
out.append("| lead (s) | smoothing | n | WRONG-bound [CI] | silent-wrong | correct-bound | prompt |")
out.append("|---|---|---:|---|---:|---:|---:|")
for lead in LEADS:
    for sm in (False, True):
        c = pool(0.2, "aligned", lead, 1.0, sm)
        out.append(f"| {lead[4:]} | {'ON' if sm else 'OFF'} | {c['n']} | {pct(c,'wrong',True)} | {pct(c,'silent_wrong')} | {pct(c,'correct')} | {pct(c,'prompt')} |")
open(S + "headline.md", "w").write("\n".join(out) + "\n")

# totals for the prose
def total(la, stratum, cond):
    t = collections.Counter()
    for r in cells:
        if r["look_away"] == la and cond(r):
            t.update(r["counts"][stratum])
    return t
for la, st in ((0.0, "aligned"), (0.2, "aligned"), (0.2, "look")):
    t = total(la, st, lambda r: True)
    print(la, st, "cells-trials", t["n"], "wrong", t["wrong"], "silent", t["silent_wrong"], "correct", t["correct"])
    t = total(la, st, lambda r: r["noise_deg"] <= 2 and r["lead"] in ("lead0.0-0.2", "lead0.2-0.4"))
    print("  short lead noise<=2:", t["n"], "wrong", t["wrong"])
    t = total(la, st, lambda r: r["noise_deg"] <= 2)
    print("  noise<=2 all leads:", t["n"], "wrong", t["wrong"], "silent", t["silent_wrong"])
```

## Appendix E. Rev-3 tables (generated by report.py from rob_eval.py, unedited)

Scenarios, cost model and column meanings are in section 0.2. OLD = the rev-2 `confirm.decide` (frozen copy in Appendix F); NEW = the shipped policy. Seeds 20270101-3 were not used to choose any default.

n per cell = 300, seeds = [20270101, 20270102, 20270103], noise 1 deg, defaults = {'error_budget_deg': 3.0, 'settle_s': 0.3, 'min_departure_s': 0.5, 'min_top_share': 0.6, 'history_s': 1.5, 'min_prior_dwell_s': 0.15}

#### Smoothing OFF: correct-silent / SILENT-WRONG [95% CI] / prompt / abstain (percent of trials), OLD policy then NEW policy

| scenario | lead (s) | n | OLD correct | OLD silent-wrong | OLD prompt | OLD abstain | NEW correct | NEW silent-wrong | NEW prompt | NEW abstain | cost@W=10 old -> new |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| eyes on target (utterance end +0.3 s) | 0.0-0.2 | 3600 | 87.6 | 0.0 [0.0-0.1] | 12.4 | 0.0 | 98.9 | 0.0 [0.0-0.1] | 1.1 | 0.0 | 0.12 -> 0.01 |
| eyes on target (utterance end +0.3 s) | 0.2-0.4 | 3600 | 55.7 | 0.0 [0.0-0.1] | 44.3 | 0.0 | 98.8 | 0.0 [0.0-0.1] | 1.2 | 0.0 | 0.44 -> 0.01 |
| eyes on target (utterance end +0.3 s) | 0.2-0.8 | 3600 | 25.3 | 0.0 [0.0-0.1] | 74.7 | 0.0 | 98.8 | 0.0 [0.0-0.1] | 1.2 | 0.0 | 0.75 -> 0.01 |
| eyes on target (utterance end +0.3 s) | 0.6-1.2 | 3600 | 0.9 | 0.0 [0.0-0.1] | 99.1 | 0.0 | 98.7 | 0.0 [0.0-0.1] | 1.3 | 0.0 | 0.99 -> 0.01 |
| look-away (eyes left before the word) | 0.0-0.2 | 3600 | 0.0 | 28.5 [27.1-30.0] | 71.5 | 0.0 | 0.0 | 28.4 [27.0-29.9] | 71.6 | 0.0 | 3.68 -> 3.56 |
| look-away (eyes left before the word) | 0.2-0.4 | 3600 | 0.0 | 0.4 [0.2-0.6] | 99.6 | 0.0 | 0.0 | 0.3 [0.2-0.5] | 99.7 | 0.0 | 1.04 -> 1.03 |
| look-away (eyes left before the word) | 0.2-0.8 | 3600 | 0.0 | 19.9 [18.6-21.2] | 80.1 | 0.0 | 0.0 | 5.3 [4.6-6.1] | 94.7 | 0.0 | 2.79 -> 1.48 |
| look-away (eyes left before the word) | 0.6-1.2 | 3600 | 0.0 | 75.2 [73.8-76.6] | 24.8 | 0.0 | 0.0 | 48.4 [46.8-50.0] | 51.6 | 0.0 | 7.78 -> 5.36 |
| transit: came from another panel, intent = new panel | 0.0-0.2 | 3600 | 61.9 | 0.0 [0.0-0.1] | 38.1 | 0.0 | 0.0 | 0.0 [0.0-0.1] | 100.0 | 0.0 | 0.38 -> 1.00 |
| transit: came from another panel, intent = new panel | 0.2-0.4 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 71.7 | 0.0 [0.0-0.1] | 28.3 | 0.0 | 0.00 -> 0.28 |
| transit: came from another panel, intent = new panel | 0.2-0.8 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 90.1 | 0.0 [0.0-0.1] | 9.9 | 0.0 | 0.00 -> 0.10 |
| transit: came from another panel, intent = new panel | 0.6-1.2 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 98.5 | 0.0 [0.0-0.1] | 1.5 | 0.0 | 0.00 -> 0.01 |
| eyes stay on target to +1.0 s | 0.0-0.2 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 98.6 | 0.0 [0.0-0.1] | 1.4 | 0.0 | 0.00 -> 0.01 |
| eyes stay on target to +1.0 s | 0.2-0.4 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 98.6 | 0.0 [0.0-0.1] | 1.4 | 0.0 | 0.00 -> 0.01 |
| eyes stay on target to +1.0 s | 0.2-0.8 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 98.6 | 0.0 [0.0-0.1] | 1.4 | 0.0 | 0.00 -> 0.01 |
| eyes stay on target to +1.0 s | 0.6-1.2 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 98.6 | 0.0 [0.0-0.1] | 1.4 | 0.0 | 0.00 -> 0.01 |
| eyes rest on another panel from +0.1 s to +1.0 s | 0.0-0.2 | 3600 | 0.7 | 0.0 [0.0-0.1] | 99.3 | 0.0 | 11.1 | 0.0 [0.0-0.1] | 88.9 | 0.0 | 0.99 -> 0.89 |
| eyes rest on another panel from +0.1 s to +1.0 s | 0.2-0.4 | 3600 | 0.7 | 0.0 [0.0-0.1] | 99.3 | 0.0 | 11.1 | 0.0 [0.0-0.1] | 88.9 | 0.0 | 0.99 -> 0.89 |
| eyes rest on another panel from +0.1 s to +1.0 s | 0.2-0.8 | 3600 | 0.8 | 0.0 [0.0-0.1] | 99.2 | 0.0 | 11.0 | 0.0 [0.0-0.1] | 89.0 | 0.0 | 0.99 -> 0.89 |
| eyes rest on another panel from +0.1 s to +1.0 s | 0.6-1.2 | 3600 | 0.8 | 0.0 [0.0-0.1] | 99.2 | 0.0 | 11.0 | 0.0 [0.0-0.1] | 89.0 | 0.0 | 0.99 -> 0.89 |

#### Smoothing ON: correct-silent / SILENT-WRONG [95% CI] / prompt / abstain (percent of trials), OLD policy then NEW policy

| scenario | lead (s) | n | OLD correct | OLD silent-wrong | OLD prompt | OLD abstain | NEW correct | NEW silent-wrong | NEW prompt | NEW abstain | cost@W=10 old -> new |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| eyes on target (utterance end +0.3 s) | 0.0-0.2 | 3600 | 96.8 | 0.0 [0.0-0.1] | 3.2 | 0.0 | 98.8 | 0.0 [0.0-0.1] | 1.2 | 0.0 | 0.03 -> 0.01 |
| eyes on target (utterance end +0.3 s) | 0.2-0.4 | 3600 | 80.2 | 0.0 [0.0-0.1] | 19.8 | 0.0 | 98.8 | 0.0 [0.0-0.1] | 1.2 | 0.0 | 0.20 -> 0.01 |
| eyes on target (utterance end +0.3 s) | 0.2-0.8 | 3600 | 60.7 | 0.0 [0.0-0.1] | 39.3 | 0.0 | 98.9 | 0.0 [0.0-0.1] | 1.1 | 0.0 | 0.39 -> 0.01 |
| eyes on target (utterance end +0.3 s) | 0.6-1.2 | 3600 | 39.6 | 0.0 [0.0-0.1] | 60.4 | 0.0 | 98.8 | 0.0 [0.0-0.1] | 1.2 | 0.0 | 0.60 -> 0.01 |
| look-away (eyes left before the word) | 0.0-0.2 | 3600 | 1.2 | 0.0 [0.0-0.1] | 84.2 | 14.6 | 31.8 | 0.0 [0.0-0.1] | 53.6 | 14.6 | 1.13 -> 0.83 |
| look-away (eyes left before the word) | 0.2-0.4 | 3600 | 11.1 | 0.0 [0.0-0.1] | 77.7 | 11.1 | 46.2 | 0.0 [0.0-0.1] | 42.6 | 11.1 | 1.00 -> 0.65 |
| look-away (eyes left before the word) | 0.2-0.8 | 3600 | 10.7 | 5.3 [4.6-6.1] | 74.6 | 9.4 | 39.1 | 1.4 [1.0-1.8] | 50.2 | 9.4 | 1.49 -> 0.85 |
| look-away (eyes left before the word) | 0.6-1.2 | 3600 | 3.4 | 41.8 [40.2-43.4] | 50.9 | 3.9 | 12.6 | 29.6 [28.1-31.1] | 53.9 | 3.9 | 4.87 -> 3.69 |
| transit: came from another panel, intent = new panel | 0.0-0.2 | 3600 | 4.9 | 6.6 [5.8-7.4] | 82.6 | 5.9 | 0.0 | 21.9 [20.5-23.2] | 72.2 | 5.9 | 2.07 -> 3.33 |
| transit: came from another panel, intent = new panel | 0.2-0.4 | 3600 | 51.4 | 0.1 [0.0-0.2] | 48.2 | 0.4 | 20.0 | 0.2 [0.1-0.4] | 79.4 | 0.4 | 0.57 -> 0.89 |
| transit: came from another panel, intent = new panel | 0.2-0.8 | 3600 | 81.8 | 0.0 [0.0-0.1] | 17.2 | 1.0 | 68.0 | 0.1 [0.0-0.2] | 30.9 | 1.0 | 0.22 -> 0.36 |
| transit: came from another panel, intent = new panel | 0.6-1.2 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 98.2 | 0.0 [0.0-0.1] | 1.8 | 0.0 | 0.00 -> 0.02 |
| eyes stay on target to +1.0 s | 0.0-0.2 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 98.8 | 0.0 [0.0-0.1] | 1.2 | 0.0 | 0.00 -> 0.01 |
| eyes stay on target to +1.0 s | 0.2-0.4 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 98.8 | 0.0 [0.0-0.1] | 1.2 | 0.0 | 0.00 -> 0.01 |
| eyes stay on target to +1.0 s | 0.2-0.8 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 98.8 | 0.0 [0.0-0.1] | 1.2 | 0.0 | 0.00 -> 0.01 |
| eyes stay on target to +1.0 s | 0.6-1.2 | 3600 | 100.0 | 0.0 [0.0-0.1] | 0.0 | 0.0 | 98.6 | 0.0 [0.0-0.1] | 1.4 | 0.0 | 0.00 -> 0.01 |
| eyes rest on another panel from +0.1 s to +1.0 s | 0.0-0.2 | 3600 | 0.0 | 0.0 [0.0-0.1] | 100.0 | 0.0 | 13.8 | 0.0 [0.0-0.1] | 86.2 | 0.0 | 1.00 -> 0.86 |
| eyes rest on another panel from +0.1 s to +1.0 s | 0.2-0.4 | 3600 | 0.0 | 0.0 [0.0-0.1] | 100.0 | 0.0 | 13.8 | 0.0 [0.0-0.1] | 86.2 | 0.0 | 1.00 -> 0.86 |
| eyes rest on another panel from +0.1 s to +1.0 s | 0.2-0.8 | 3600 | 0.0 | 0.0 [0.0-0.1] | 100.0 | 0.0 | 14.0 | 0.0 [0.0-0.1] | 86.0 | 0.0 | 1.00 -> 0.86 |
| eyes rest on another panel from +0.1 s to +1.0 s | 0.6-1.2 | 3600 | 0.0 | 0.0 [0.0-0.1] | 100.0 | 0.0 | 14.6 | 0.0 [0.0-0.1] | 85.4 | 0.0 | 1.00 -> 0.85 |

#### Eyes-on-target prompt rate by layout (NEW policy, percent; OLD in brackets)

| layout | smoothing | lead 0.2-0.4 | lead 0.2-0.8 | lead 0.6-1.2 |
|---|---|---:|---:|---:|
| far | OFF | 0.0 (41.1) | 0.0 (73.9) | 0.0 (99.2) |
| far | ON | 0.0 (5.4) | 0.0 (13.4) | 0.0 (24.3) |
| adjacent | OFF | 0.0 (45.2) | 0.0 (76.6) | 0.0 (99.3) |
| adjacent | ON | 0.0 (25.9) | 0.0 (54.4) | 0.0 (83.7) |
| abutting | OFF | 5.0 (47.3) | 5.0 (76.1) | 5.2 (99.4) |
| abutting | ON | 4.8 (32.4) | 4.3 (63.0) | 4.9 (97.0) |
| mixed | OFF | 0.0 (43.4) | 0.0 (72.1) | 0.0 (98.6) |
| mixed | ON | 0.0 (15.6) | 0.0 (26.4) | 0.0 (36.6) |

#### Prompt reasons, NEW policy (counts, pooled over layouts and seeds)

| scenario | smoothing | lead | trials | ambiguous | near_panel_edge | recent_panel_switch | target_changed | low_confidence | silent(none/no_target) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| aligned | OFF | 0.2-0.4 | 3600 | 0 | 45 | 0 | 0 | 0 | 3555 |
| aligned | OFF | 0.2-0.8 | 3600 | 0 | 45 | 0 | 0 | 0 | 3555 |
| aligned | OFF | 0.6-1.2 | 3600 | 0 | 47 | 0 | 0 | 0 | 3553 |
| aligned | ON | 0.2-0.4 | 3600 | 0 | 43 | 0 | 0 | 0 | 3557 |
| aligned | ON | 0.2-0.8 | 3600 | 0 | 39 | 0 | 0 | 0 | 3561 |
| aligned | ON | 0.6-1.2 | 3600 | 0 | 44 | 0 | 0 | 0 | 3556 |
| look | OFF | 0.2-0.4 | 3600 | 3557 | 0 | 26 | 0 | 6 | 11 |
| look | OFF | 0.2-0.8 | 3600 | 2861 | 6 | 539 | 0 | 3 | 191 |
| look | OFF | 0.6-1.2 | 3600 | 877 | 21 | 959 | 0 | 0 | 1743 |
| look | ON | 0.2-0.4 | 3600 | 1452 | 33 | 0 | 0 | 49 | 2066 |
| look | ON | 0.2-0.8 | 3600 | 1595 | 24 | 156 | 0 | 31 | 1794 |
| look | ON | 0.6-1.2 | 3600 | 1462 | 21 | 443 | 0 | 14 | 1660 |
| transit | OFF | 0.2-0.4 | 3600 | 0 | 26 | 992 | 0 | 0 | 2582 |
| transit | OFF | 0.2-0.8 | 3600 | 0 | 46 | 309 | 0 | 0 | 3245 |
| transit | OFF | 0.6-1.2 | 3600 | 0 | 54 | 0 | 0 | 0 | 3546 |
| transit | ON | 0.2-0.4 | 3600 | 1685 | 1 | 1170 | 0 | 4 | 740 |
| transit | ON | 0.2-0.8 | 3600 | 605 | 39 | 469 | 0 | 0 | 2487 |
| transit | ON | 0.6-1.2 | 3600 | 0 | 64 | 0 | 0 | 0 | 3536 |
| stay | OFF | 0.2-0.4 | 3600 | 0 | 52 | 0 | 0 | 0 | 3548 |
| stay | OFF | 0.2-0.8 | 3600 | 0 | 50 | 0 | 0 | 0 | 3550 |
| stay | OFF | 0.6-1.2 | 3600 | 0 | 50 | 0 | 0 | 0 | 3550 |
| stay | ON | 0.2-0.4 | 3600 | 0 | 45 | 0 | 0 | 0 | 3555 |
| stay | ON | 0.2-0.8 | 3600 | 0 | 45 | 0 | 0 | 0 | 3555 |
| stay | ON | 0.6-1.2 | 3600 | 0 | 49 | 0 | 0 | 0 | 3551 |
| leave | OFF | 0.2-0.4 | 3600 | 0 | 40 | 0 | 3161 | 0 | 399 |
| leave | OFF | 0.2-0.8 | 3600 | 0 | 42 | 0 | 3163 | 0 | 395 |
| leave | OFF | 0.6-1.2 | 3600 | 0 | 38 | 0 | 3167 | 0 | 395 |
| leave | ON | 0.2-0.4 | 3600 | 0 | 39 | 0 | 3063 | 0 | 498 |
| leave | ON | 0.2-0.8 | 3600 | 0 | 40 | 0 | 3057 | 0 | 503 |
| leave | ON | 0.6-1.2 | 3600 | 0 | 41 | 0 | 3033 | 0 | 526 |

#### Constant tracker bias, 1 deg noise on top, eyes on target (percent of trials; abutting layout unless stated)

| layout | smoothing | lead | bias (deg) | n | OLD silent-wrong | OLD prompt | NEW silent-wrong | NEW prompt | abstain (both) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| abutting | OFF | 0.0-0.2 | 0 | 900 | 0.0 [0.0-0.4] | 16.9 | 0.0 [0.0-0.4] | 4.2 | 0.0 |
| abutting | OFF | 0.0-0.2 | 3 | 900 | 0.3 [0.1-1.0] | 21.4 | 0.0 [0.0-0.4] | 21.4 | 2.7 |
| abutting | OFF | 0.0-0.2 | 5 | 900 | 10.7 [8.8-12.9] | 18.4 | 0.0 [0.0-0.4] | 33.7 | 10.1 |
| abutting | OFF | 0.2-0.4 | 0 | 900 | 0.0 [0.0-0.4] | 47.3 | 0.0 [0.0-0.4] | 5.0 | 0.0 |
| abutting | OFF | 0.2-0.4 | 3 | 900 | 0.3 [0.1-1.0] | 47.9 | 0.0 [0.0-0.4] | 22.7 | 2.3 |
| abutting | OFF | 0.2-0.4 | 5 | 900 | 7.8 [6.2-9.7] | 41.7 | 0.2 [0.1-0.8] | 36.0 | 8.1 |
| abutting | ON | 0.0-0.2 | 0 | 900 | 0.0 [0.0-0.4] | 6.1 | 0.0 [0.0-0.4] | 4.9 | 0.0 |
| abutting | ON | 0.0-0.2 | 3 | 900 | 2.0 [1.3-3.1] | 9.1 | 0.0 [0.0-0.4] | 20.9 | 2.6 |
| abutting | ON | 0.0-0.2 | 5 | 900 | 12.4 [10.4-14.8] | 8.7 | 0.0 [0.0-0.4] | 32.8 | 10.0 |
| abutting | ON | 0.2-0.4 | 0 | 900 | 0.0 [0.0-0.4] | 32.4 | 0.0 [0.0-0.4] | 4.8 | 0.0 |
| abutting | ON | 0.2-0.4 | 3 | 900 | 1.4 [0.8-2.5] | 30.9 | 0.0 [0.0-0.4] | 21.4 | 2.1 |
| abutting | ON | 0.2-0.4 | 5 | 900 | 10.7 [8.8-12.9] | 28.7 | 0.0 [0.0-0.4] | 34.1 | 9.0 |
| adjacent | OFF | 0.0-0.2 | 0 | 900 | 0.0 [0.0-0.4] | 13.4 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| adjacent | OFF | 0.0-0.2 | 3 | 900 | 0.0 [0.0-0.4] | 11.3 | 0.0 [0.0-0.4] | 0.4 | 8.3 |
| adjacent | OFF | 0.0-0.2 | 5 | 900 | 0.0 [0.0-0.4] | 10.0 | 0.0 [0.0-0.4] | 2.7 | 25.8 |
| adjacent | OFF | 0.2-0.4 | 0 | 900 | 0.0 [0.0-0.4] | 45.2 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| adjacent | OFF | 0.2-0.4 | 3 | 900 | 0.0 [0.0-0.4] | 41.1 | 0.0 [0.0-0.4] | 3.7 | 5.8 |
| adjacent | OFF | 0.2-0.4 | 5 | 900 | 0.0 [0.0-0.4] | 35.6 | 0.0 [0.0-0.4] | 10.9 | 18.0 |
| adjacent | ON | 0.0-0.2 | 0 | 900 | 0.0 [0.0-0.4] | 3.4 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| adjacent | ON | 0.0-0.2 | 3 | 900 | 0.0 [0.0-0.4] | 3.1 | 0.0 [0.0-0.4] | 0.9 | 8.7 |
| adjacent | ON | 0.0-0.2 | 5 | 900 | 0.7 [0.3-1.4] | 2.9 | 0.6 [0.2-1.3] | 0.9 | 26.3 |
| adjacent | ON | 0.2-0.4 | 0 | 900 | 0.0 [0.0-0.4] | 25.9 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| adjacent | ON | 0.2-0.4 | 3 | 900 | 0.0 [0.0-0.4] | 24.1 | 0.0 [0.0-0.4] | 1.6 | 6.8 |
| adjacent | ON | 0.2-0.4 | 5 | 900 | 0.0 [0.0-0.4] | 18.7 | 0.0 [0.0-0.4] | 2.2 | 25.7 |
| mixed | OFF | 0.0-0.2 | 0 | 900 | 0.0 [0.0-0.4] | 9.8 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| mixed | OFF | 0.0-0.2 | 3 | 900 | 0.0 [0.0-0.4] | 7.4 | 0.0 [0.0-0.4] | 0.9 | 17.7 |
| mixed | OFF | 0.0-0.2 | 5 | 900 | 0.0 [0.0-0.4] | 5.2 | 0.0 [0.0-0.4] | 1.4 | 42.3 |
| mixed | OFF | 0.2-0.4 | 0 | 900 | 0.0 [0.0-0.4] | 43.4 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| mixed | OFF | 0.2-0.4 | 3 | 900 | 0.0 [0.0-0.4] | 35.7 | 0.0 [0.0-0.4] | 6.4 | 13.3 |
| mixed | OFF | 0.2-0.4 | 5 | 900 | 0.0 [0.0-0.4] | 26.7 | 0.0 [0.0-0.4] | 13.0 | 31.6 |
| mixed | ON | 0.0-0.2 | 0 | 900 | 0.0 [0.0-0.4] | 2.2 | 0.0 [0.0-0.4] | 0.0 | 0.1 |
| mixed | ON | 0.0-0.2 | 3 | 900 | 0.0 [0.0-0.4] | 1.9 | 0.0 [0.0-0.4] | 0.0 | 15.9 |
| mixed | ON | 0.0-0.2 | 5 | 900 | 0.1 [0.0-0.6] | 1.6 | 0.1 [0.0-0.6] | 0.1 | 41.6 |
| mixed | ON | 0.2-0.4 | 0 | 900 | 0.0 [0.0-0.4] | 15.6 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| mixed | ON | 0.2-0.4 | 3 | 900 | 0.0 [0.0-0.4] | 14.3 | 0.0 [0.0-0.4] | 1.6 | 14.8 |
| mixed | ON | 0.2-0.4 | 5 | 900 | 0.0 [0.0-0.4] | 11.2 | 0.0 [0.0-0.4] | 2.9 | 38.1 |
| far | OFF | 0.0-0.2 | 0 | 900 | 0.0 [0.0-0.4] | 9.6 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| far | OFF | 0.0-0.2 | 3 | 900 | 0.0 [0.0-0.4] | 6.7 | 0.0 [0.0-0.4] | 0.3 | 16.6 |
| far | OFF | 0.0-0.2 | 5 | 900 | 0.0 [0.0-0.4] | 4.1 | 0.0 [0.0-0.4] | 0.4 | 37.6 |
| far | OFF | 0.2-0.4 | 0 | 900 | 0.0 [0.0-0.4] | 41.1 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| far | OFF | 0.2-0.4 | 3 | 900 | 0.0 [0.0-0.4] | 33.6 | 0.0 [0.0-0.4] | 5.1 | 12.1 |
| far | OFF | 0.2-0.4 | 5 | 900 | 0.0 [0.0-0.4] | 23.7 | 0.0 [0.0-0.4] | 7.7 | 31.3 |
| far | ON | 0.0-0.2 | 0 | 900 | 0.0 [0.0-0.4] | 1.1 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| far | ON | 0.0-0.2 | 3 | 900 | 0.0 [0.0-0.4] | 0.9 | 0.0 [0.0-0.4] | 0.0 | 14.8 |
| far | ON | 0.0-0.2 | 5 | 900 | 0.0 [0.0-0.4] | 0.3 | 0.0 [0.0-0.4] | 0.0 | 36.7 |
| far | ON | 0.2-0.4 | 0 | 900 | 0.0 [0.0-0.4] | 5.4 | 0.0 [0.0-0.4] | 0.0 | 0.0 |
| far | ON | 0.2-0.4 | 3 | 900 | 0.0 [0.0-0.4] | 6.8 | 0.0 [0.0-0.4] | 1.0 | 14.1 |
| far | ON | 0.2-0.4 | 5 | 900 | 0.0 [0.0-0.4] | 6.9 | 0.0 [0.0-0.4] | 1.2 | 35.7 |

#### Threshold sweep (smoothing ON; one rule changed at a time from the defaults; pooled over layouts, seeds; lead ranges 0.2-0.4 / 0.2-0.8 / 0.6-1.2 pooled with equal weight)

The 'mixed cost' is c_prompt*P(prompt) + extra + c_abstain*P(abstain) + W*P(silent-wrong), averaged over the three lead ranges, for a population that is a fraction q look-away trials and 1-q transit trials (both are the harsh cases for one of the two rules). [O] c_prompt = 1, c_abstain = 2, an unhelpful prompt +1.

| variant | look-away silent-wrong % | transit prompt % | eyes-on-target prompt % | leave prompt % | bias5 abutting silent-wrong % | bias5 abutting prompt % | mixed cost q=0.2 W=5 / 10 / 20 | q=0.05 W=10 | q=0.5 W=10 |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| OLD policy | 15.7 | 21.8 | 39.9 | 100.0 | 11.6 | 18.7 | 0.54 / 0.70 / 1.02 | 0.37 | 1.36 |
| NEW defaults | 10.3 | 37.4 | 1.2 | 85.9 | 0.0 | 33.4 | 0.58 / 0.68 / 0.90 | 0.49 | 1.08 |
| {"settle_s": 0.0} | 15.2 | 24.2 | 1.2 | 85.9 | 0.0 | 33.4 | 0.52 / 0.69 / 1.03 | 0.41 | 1.24 |
| {"settle_s": 0.2} | 13.1 | 28.1 | 1.2 | 85.9 | 0.0 | 33.4 | 0.53 / 0.68 / 0.97 | 0.44 | 1.17 |
| {"settle_s": 0.5} | 4.4 | 53.6 | 1.2 | 85.9 | 0.0 | 33.4 | 0.66 / 0.71 / 0.80 | 0.61 | 0.89 |
| {"error_budget_deg": 0.0} | 10.5 | 36.4 | 0.0 | 85.9 | 13.6 | 1.6 | 0.57 / 0.68 / 0.89 | 0.48 | 1.07 |
| {"error_budget_deg": 2.0} | 10.5 | 36.4 | 0.0 | 85.9 | 3.1 | 25.2 | 0.57 / 0.68 / 0.89 | 0.48 | 1.08 |
| {"error_budget_deg": 4.0} | 10.0 | 39.1 | 4.1 | 85.9 | 0.0 | 39.7 | 0.59 / 0.69 / 0.89 | 0.50 | 1.07 |
| {"min_departure_s": 0.3} | 10.3 | 37.4 | 1.2 | 99.8 | 0.0 | 33.4 | 0.58 / 0.68 / 0.90 | 0.49 | 1.08 |
| {"min_departure_s": 0.8} | 10.3 | 37.4 | 1.2 | 5.7 | 0.0 | 33.4 | 0.58 / 0.68 / 0.90 | 0.49 | 1.08 |
| {"min_departure_s": 99.0} | 10.3 | 37.4 | 1.2 | 1.1 | 0.0 | 33.4 | 0.58 / 0.68 / 0.90 | 0.49 | 1.08 |
| {"settle_s": 0.0, "error_budget_deg": 0.0, "min_departure_s": 99.0} | 15.9 | 21.4 | 0.0 | 0.0 | 13.7 | 1.3 | 0.50 / 0.68 / 1.03 | 0.39 | 1.26 |


## Appendix F. Rev-3 scripts

Run from the worktree: `PYTHONPATH=src python3 rob_eval.py --n 300 --seeds 20270101 20270102 20270103 --variants "$(cat variants.json)" --out OUT`, then `python3 report.py OUT/rob_results.json`. `old_confirm.py` must sit beside `rob_eval.py`. The `variants.json` used is:

```json
[{"settle_s":0.0},{"settle_s":0.2},{"settle_s":0.5},{"error_budget_deg":0.0},{"error_budget_deg":2.0},{"error_budget_deg":4.0},{"min_departure_s":0.3},{"min_departure_s":0.8},{"min_departure_s":99.0},{"settle_s":0.0,"error_budget_deg":0.0,"min_departure_s":99.0}]
```

### F.rob_eval.py

```python
#!/usr/bin/env python3
"""Decision-layer evaluation (rev. 3): OLD confirm policy vs NEW, on identical binder evidence.

SYNTHETIC ONLY. Trajectories come from yazses.xr.synth (plus the extra generators below, which are
built from the same primitives); they test self-consistency and parameter sensitivity, never accuracy
on real users.

For every trial the binder runs once (the verdict and margin are unchanged by the redesign). Then two
policies are applied to the same evidence:
    OLD = a frozen copy of the pre-redesign confirm.decide (old_confirm.py, in the same directory)
    NEW = yazses.xr.confirm.decide with Evidence + ConfirmPolicy

Per-trial classes (exactly one each):
    silent_correct  bound to the intended panel, no prompt
    silent_wrong    bound to another panel, no prompt         <- the error ADR-021 prices highest
    prompt          a prompt is shown (ambiguous or bound-with-hold)
        prompt_offers_truth   ... and the prompt's candidates (bound panel + alternative) include the intent
    abstain         binder returned NONE: no ray target, fall back to keyboard focus (no prompt)

Cost model [O]: c_prompt = 1 (a one-word release), c_abstain = 2 (the keyboard-focus fallback may be the wrong
window and the user then has to say where), c_silent_wrong = W (find it, undo it, retype; W in 5, 10, 20).
A prompt whose candidates do not include the intent costs one extra unit (the user must name the panel).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from itertools import product
from pathlib import Path

from yazses.xr import confirm as new_confirm
from yazses.xr.binding import (
    PanelObservation,
    bind_demonstrative,
    nearest_rival,
    sustained_departure,
)
from yazses.xr.raycast import nearest_hit
from yazses.xr.smoothing import RayFilter
from yazses.xr.synth import make_scenarios, sweep_between
from yazses.xr.types import Panel, Ray, Vec3

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("old_confirm", HERE / "old_confirm.py")
assert _spec and _spec.loader
old_confirm = importlib.util.module_from_spec(_spec)
sys.modules["old_confirm"] = old_confirm
_spec.loader.exec_module(old_confirm)

W, H, Z = 0.6, 0.4, -2.0
EDGE_TOL_S = 0.25
KEEP_BEFORE_S, KEEP_AFTER_S = 3.0, 1.6
LEADS = {"lead0.0-0.2": (0.0, 0.2), "lead0.2-0.4": (0.2, 0.4),
         "lead0.2-0.8": (0.2, 0.8), "lead0.6-1.2": (0.6, 1.2)}
EYE = Vec3(0.0, 1.6, 0.0)

DEFAULT_NEW = {"error_budget_deg": 3.0, "settle_s": 0.3, "min_departure_s": 0.5, "min_top_share": 0.6,
               "history_s": 1.5, "min_prior_dwell_s": 0.15}


def _panel(pid: str, x: float) -> Panel:
    return Panel(pid, Vec3(x, 1.6, Z), Vec3(0, 0, 1), Vec3(0, 1, 0), W, H)


def layouts() -> dict[str, list[tuple[str, float]]]:
    def row(gap: float, k: int = 3):
        pitch = W + gap
        return [(chr(65 + i), (i - (k - 1) / 2) * pitch) for i in range(k)]
    return {
        "far(gap1.0m)": row(1.0),
        "adjacent(gap0.1m)": row(0.1),
        "abutting(gap0m)": row(0.0),
        "mixed(2adj+2far)": [("A", -0.35), ("B", 0.35), ("C", -2.0), ("D", 2.0)],
    }


def yaw(sample, rad):
    d = sample.ray.direction
    c, s_ = math.cos(rad), math.sin(rad)
    nd = Vec3(c * d.x + s_ * d.z, d.y, -s_ * d.x + c * d.z)
    return replace(sample, ray=Ray(sample.ray.origin, nd))


def wilson(k, n, z=1.959964):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


# --------------------------------------------------------------------------- trial generators

def trials_generator(kind, panels, n, seed, noise_rad, lead):
    """Yield (samples, onset, end, truth_id)."""
    if kind in ("aligned", "bias"):
        for sc in make_scenarios(panels, n, seed, noise_rad, lead, look_away_prob=0.0):
            yield list(sc.samples), sc.word_onset_s, sc.word_onset_s + 0.3, sc.truth_panel_id
    elif kind == "look":
        ideal = make_scenarios(panels, n, seed, 0.0, lead, look_away_prob=1.0)
        real = make_scenarios(panels, n, seed, noise_rad, lead, look_away_prob=1.0)
        for sc, isc in zip(real, ideal):
            if isc.gaze_panel_at_onset == isc.truth_panel_id:   # not a look-away after all
                continue
            yield list(sc.samples), sc.word_onset_s, sc.word_onset_s + 0.3, sc.truth_panel_id
    elif kind in ("transit", "stay", "leave"):
        rng = random.Random(seed)
        ids = [p.panel_id for p in panels]
        for _ in range(n):
            tgt = rng.choice(panels)
            others = [p for p in panels if p.panel_id != tgt.panel_id]
            src = rng.choice(others)
            t0 = rng.uniform(0.2, 1.0)
            d_src = rng.uniform(0.4, 1.2)
            lead_s = rng.uniform(*lead)
            tuv = (rng.uniform(0.15, 0.85), rng.uniform(0.15, 0.85))
            suv = (rng.uniform(0.15, 0.85), rng.uniform(0.15, 0.85))
            sd = rng.getrandbits(32)
            arrival = t0 + d_src + 0.05
            onset = arrival + lead_s
            if kind == "transit":      # came from src, then the word; eyes stay a moment
                smp = sweep_between(src, tgt, start_s=t0, dwell_a_s=d_src, dwell_b_s=lead_s + 0.4,
                                    a_uv=suv, b_uv=tuv, noise_rad=noise_rad, seed=sd)
                yield smp, onset, onset + 0.3, tgt.panel_id
            else:
                # no prior panel: start directly on the target (a long, settled look), then the tail
                t_on = t0
                onset2 = t_on + max(lead_s, 0.6)
                if kind == "stay":
                    from yazses.xr.synth import fixation
                    smp = fixation(tgt, *tuv, start_s=t_on, duration_s=(onset2 - t_on) + 1.3,
                                   noise_rad=noise_rad, seed=sd)
                else:                  # leave: rests on another panel from just after the word
                    dist = rng.choice(others)
                    smp = sweep_between(tgt, dist, start_s=t_on, dwell_a_s=(onset2 - t_on) + 0.1,
                                        dwell_b_s=1.2, a_uv=tuv, b_uv=suv, noise_rad=noise_rad, seed=sd)
                yield smp, onset2, onset2 + 1.0, tgt.panel_id
    else:
        raise ValueError(kind)


# ----------------------------------------------------------------------------- one trial

def _nearest_panel(obs, t):
    best = min(obs, key=lambda o: abs(o.timestamp_s - t), default=None)
    if best is None or abs(best.timestamp_s - t) > EDGE_TOL_S:
        return None
    return best.hit.panel_id if best.hit is not None else None


def run_trial(samples, onset, end, truth, panels, smooth, np_, variants=()):
    if smooth:
        f = RayFilter()
        samples = [f.update(s) for s in samples]
    samples = [s for s in samples if onset - KEEP_BEFORE_S <= s.timestamp_s <= end + 0.6]
    obs = []
    for s in samples:
        h = nearest_hit(s.ray, panels)
        r = None if h is None else nearest_rival(s.ray, h.panel_id, panels)
        obs.append(PanelObservation(s.timestamp_s, h, s.confidence, *( (r[0], r[1]) if r else (None, None))))
    res = bind_demonstrative(obs, onset, history_s=np_["history_s"], min_prior_dwell_s=np_["min_prior_dwell_s"])
    at_on, at_end = _nearest_panel(obs, onset), _nearest_panel(obs, end)
    kw = dict(outcome=res.outcome.value, margin=res.margin, confidence=res.confidence, destructive=False,
              panel_at_onset=at_on, panel_at_end=at_end)
    d_old = old_confirm.decide(**kw)
    ev = new_confirm.Evidence()
    if res.panel_id is not None:
        dpanel, dsec = sustained_departure(obs, res.panel_id, onset, end)
        ev = new_confirm.Evidence(
            panel_id=res.panel_id, top_share=res.top_share,
            runner_up=res.candidates[1] if len(res.candidates) > 1 else None,
            rival_id=res.rival_id, rival_deg=res.rival_deg, prior_panel=res.prior_panel,
            settled_s=res.settled_s, departure_s=dsec, departure_panel=dpanel)
    pol = new_confirm.ConfirmPolicy(min_top_share=np_["min_top_share"], error_budget_deg=np_["error_budget_deg"],
                                    settle_s=np_["settle_s"], min_departure_s=np_["min_departure_s"])
    d_new = new_confirm.decide(**kw, evidence=ev, policy=pol)
    extra = []
    for v in variants:
        pv = new_confirm.ConfirmPolicy(**{**{"min_top_share": np_["min_top_share"], "error_budget_deg": np_["error_budget_deg"],
                                              "settle_s": np_["settle_s"], "min_departure_s": np_["min_departure_s"]}, **v})
        extra.append(new_confirm.decide(**kw, evidence=ev, policy=pv))
    return res, d_old, d_new, extra


def classify(res, d, truth):
    if res.outcome.value == "none":
        return "abstain", False
    if d.confirm:
        offered = set(getattr(d, "candidates", ())) | ({res.panel_id} if res.panel_id else set())
        if res.outcome.value == "ambiguous":
            offered = set(getattr(d, "candidates", ())) or set(res.candidates)
        return "prompt", truth in offered
    ok = res.outcome.value == "bound" and res.panel_id == truth
    return ("silent_correct" if ok else "silent_wrong"), False


def cell(args):
    kind, lname, spec, noise_deg, lead_name, lead, smooth, n, seed, bias_deg, np_ = args[:11]
    variants = args[11] if len(args) > 11 else ()
    panels = [_panel(p, x) for p, x in spec]
    noise = math.radians(noise_deg)
    names = ["old", "new"] + [f"v{i}" for i in range(len(variants))]
    out = {k: Counter() for k in names}
    reasons = {k: Counter() for k in names}
    b = math.radians(bias_deg)
    for samples, onset, end, truth in trials_generator(kind, panels, n, seed, noise, lead):
        if bias_deg:
            samples = [yaw(s, b) for s in samples]
        res, d_old, d_new, extra = run_trial(samples, onset, end, truth, panels, smooth, np_, variants)
        for name, d in [("old", d_old), ("new", d_new)] + [(f"v{i}", e) for i, e in enumerate(extra)]:
            cls, offers = classify(res, d, truth)
            c = out[name]
            c["n"] += 1
            c[cls] += 1
            c["prompt_offers_truth"] += offers
            reasons[name][d.reason.value] += 1
    return {"kind": kind, "layout": lname, "noise_deg": noise_deg, "lead": lead_name, "smooth": smooth,
            "bias_deg": bias_deg, "seed": seed, "params": np_,
            "counts": {k: dict(v) for k, v in out.items()},
            "reasons": {k: dict(v) for k, v in reasons.items()}}


def cost(c, w):
    n = c.get("n", 0)
    if not n:
        return float("nan")
    extra = c.get("prompt", 0) - c.get("prompt_offers_truth", 0)
    return (1.0 * c.get("prompt", 0) + extra + 2.0 * c.get("abstain", 0) + w * c.get("silent_wrong", 0)) / n


def merge(cells):
    tot = {"old": Counter(), "new": Counter()}
    rs = {"old": Counter(), "new": Counter()}
    for r in cells:
        for k in tot:
            tot[k].update(r["counts"][k])
            rs[k].update(r["reasons"][k])
    return tot, rs


def pct(c, k):
    n = c.get("n", 0)
    return "n/a" if not n else f"{100 * c.get(k, 0) / n:5.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seeds", type=int, nargs="+", default=[20261030, 20261031, 20261032])
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out", required=True)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--kinds", nargs="+", default=["aligned", "look", "transit", "stay", "leave", "bias"])
    ap.add_argument("--leads", nargs="+", default=["lead0.2-0.4", "lead0.2-0.8", "lead0.6-1.2", "lead0.0-0.2"])
    ap.add_argument("--smooth", nargs="+", type=int, default=[0, 1])
    ap.add_argument("--biases", nargs="+", type=float, default=[0.0, 2.0, 3.0, 5.0])
    ap.add_argument("--layouts", nargs="+", default=None)
    ap.add_argument("--variants", default="[]")
    a = ap.parse_args()
    np_ = {**DEFAULT_NEW, **json.loads(a.params)}
    variants = json.loads(a.variants)
    spec = layouts()
    jobs = []
    sel = [l for l in spec if a.layouts is None or l.split("(")[0] in a.layouts]
    for kind in [k for k in a.kinds if k != "bias"]:
        for li, lname in enumerate(spec):
            if lname not in sel:
                continue
            for lead_name in a.leads:
                for seed in a.seeds:
                    for smooth in [bool(x) for x in a.smooth]:
                        jobs.append((kind, lname, spec[lname], 1.0, lead_name, LEADS[lead_name], smooth,
                                     a.n, seed + 1000 * li, 0.0, np_, variants))
    for li, lname in enumerate(spec):
        if "bias" not in a.kinds or lname not in sel:
            continue
        for lead_name in [l for l in ("lead0.0-0.2", "lead0.2-0.4") if l in a.leads]:
            for bias in a.biases:
                for seed in a.seeds:
                    for smooth in [bool(x) for x in a.smooth]:
                        jobs.append(("bias", lname, spec[lname], 1.0, lead_name, LEADS[lead_name], smooth,
                                     a.n, seed + 1000 * li, bias, np_, variants))
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(cell, jobs, chunksize=4))
    Path(a.out).mkdir(parents=True, exist_ok=True)
    with open(f"{a.out}/rob_results.json", "w") as fh:
        json.dump({"params": np_, "variants": variants, "n": a.n, "seeds": a.seeds, "cells": res}, fh)
    print(f"{len(res)} cells -> {a.out}/rob_results.json")


if __name__ == "__main__":
    main()
```

### F.report.py

```python
"""Markdown tables from rob_results.json. usage: report.py results.json > tables.md"""
import json
import math
import sys
from collections import Counter, defaultdict

d = json.load(open(sys.argv[1]))
V = d["variants"]
CELLS = d["cells"]


def wilson(k, n, z=1.959964):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    dd = 1 + z * z / n
    c = (p + z * z / (2 * n)) / dd
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / dd
    return (max(0.0, c - h), min(1.0, c + h))


def agg(kind, smooth, lead=None, bias=None, layout=None):
    tot = defaultdict(Counter)
    rs = defaultdict(Counter)
    for r in CELLS:
        if r["kind"] != kind or r["smooth"] != smooth:
            continue
        if lead and r["lead"] != lead:
            continue
        if bias is not None and r["bias_deg"] != bias:
            continue
        if layout and not r["layout"].startswith(layout):
            continue
        for k, c in r["counts"].items():
            tot[k].update(c)
        for k, c in r["reasons"].items():
            rs[k].update(c)
    return tot, rs


def pc(c, k, ci=False):
    n = c.get("n", 0)
    if not n:
        return "n/a"
    v = c.get(k, 0)
    if ci:
        lo, hi = wilson(v, n)
        return f"{100 * v / n:.1f} [{100 * lo:.1f}-{100 * hi:.1f}]"
    return f"{100 * v / n:.1f}"


def cost(c, w):
    n = c["n"]
    extra = c.get("prompt", 0) - c.get("prompt_offers_truth", 0)
    return (c.get("prompt", 0) + extra + 2 * c.get("abstain", 0) + w * c.get("silent_wrong", 0)) / n


LEADS = ["lead0.0-0.2", "lead0.2-0.4", "lead0.2-0.8", "lead0.6-1.2"]
out = []
out.append(f"n per cell = {d['n']}, seeds = {d['seeds']}, noise 1 deg, defaults = {d['params']}\n")

for smooth in (False, True):
    sm = "ON" if smooth else "OFF"
    out.append(f"#### Smoothing {sm}: correct-silent / SILENT-WRONG [95% CI] / prompt / abstain (percent of trials), OLD policy then NEW policy\n")
    out.append("| scenario | lead (s) | n | OLD correct | OLD silent-wrong | OLD prompt | OLD abstain | NEW correct | NEW silent-wrong | NEW prompt | NEW abstain | cost@W=10 old -> new |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for kind, label in (("aligned", "eyes on target (utterance end +0.3 s)"), ("look", "look-away (eyes left before the word)"),
                        ("transit", "transit: came from another panel, intent = new panel"),
                        ("stay", "eyes stay on target to +1.0 s"), ("leave", "eyes rest on another panel from +0.1 s to +1.0 s")):
        for lead in LEADS:
            t, _ = agg(kind, smooth, lead)
            o, n = t["old"], t["new"]
            if not o.get("n"):
                continue
            out.append(f"| {label} | {lead[4:]} | {o['n']} | {pc(o, 'silent_correct')} | {pc(o, 'silent_wrong', True)} | {pc(o, 'prompt')} | {pc(o, 'abstain')} | "
                       f"{pc(n, 'silent_correct')} | {pc(n, 'silent_wrong', True)} | {pc(n, 'prompt')} | {pc(n, 'abstain')} | {cost(o, 10):.2f} -> {cost(n, 10):.2f} |")
    out.append("")

# per-layout prompt rate for eyes-on-target
out.append("#### Eyes-on-target prompt rate by layout (NEW policy, percent; OLD in brackets)\n")
out.append("| layout | smoothing | lead 0.2-0.4 | lead 0.2-0.8 | lead 0.6-1.2 |")
out.append("|---|---|---:|---:|---:|")
for lay in ("far", "adjacent", "abutting", "mixed"):
    for smooth in (False, True):
        cells = []
        for lead in LEADS[1:]:
            t, _ = agg("aligned", smooth, lead, layout=lay)
            cells.append(f"{pc(t['new'], 'prompt')} ({pc(t['old'], 'prompt')})")
        out.append(f"| {lay} | {'ON' if smooth else 'OFF'} | " + " | ".join(cells) + " |")
out.append("")

out.append("#### Prompt reasons, NEW policy (counts, pooled over layouts and seeds)\n")
out.append("| scenario | smoothing | lead | trials | ambiguous | near_panel_edge | recent_panel_switch | target_changed | low_confidence | silent(none/no_target) |")
out.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
for kind in ("aligned", "look", "transit", "stay", "leave"):
    for smooth in (False, True):
        for lead in LEADS[1:]:
            t, r = agg(kind, smooth, lead)
            n = r["new"]
            out.append(f"| {kind} | {'ON' if smooth else 'OFF'} | {lead[4:]} | {t['new']['n']} | {n['ambiguous_panels']} | {n['near_panel_edge']} | {n['recent_panel_switch']} | {n['target_changed_during_utterance']} | {n['low_confidence']} | {n['none'] + n['no_target']} |")
out.append("")

out.append("#### Constant tracker bias, 1 deg noise on top, eyes on target (percent of trials; abutting layout unless stated)\n")
out.append("| layout | smoothing | lead | bias (deg) | n | OLD silent-wrong | OLD prompt | NEW silent-wrong | NEW prompt | abstain (both) |")
out.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
for lay in ("abutting", "adjacent", "mixed", "far"):
    for smooth in (False, True):
        for lead in ("lead0.0-0.2", "lead0.2-0.4"):
            for bias in (0.0, 3.0, 5.0):
                t, _ = agg("bias", smooth, lead, bias, layout=lay)
                o, n = t["old"], t["new"]
                if not o.get("n"):
                    continue
                out.append(f"| {lay} | {'ON' if smooth else 'OFF'} | {lead[4:]} | {bias:g} | {o['n']} | {pc(o, 'silent_wrong', True)} | {pc(o, 'prompt')} | {pc(n, 'silent_wrong', True)} | {pc(n, 'prompt')} | {pc(n, 'abstain')} |")
out.append("")

# variants
labels = {f"v{i}": json.dumps(v) for i, v in enumerate(V)}
out.append("#### Threshold sweep (smoothing ON; one rule changed at a time from the defaults; pooled over layouts, seeds; lead ranges 0.2-0.4 / 0.2-0.8 / 0.6-1.2 pooled with equal weight)\n")
out.append("The 'mixed cost' is c_prompt*P(prompt) + extra + c_abstain*P(abstain) + W*P(silent-wrong), averaged over the three lead ranges, for a population that is a fraction q look-away trials and 1-q transit trials (both are the harsh cases for one of the two rules). [O] c_prompt = 1, c_abstain = 2, an unhelpful prompt +1.\n")
out.append("| variant | look-away silent-wrong % | transit prompt % | eyes-on-target prompt % | leave prompt % | bias5 abutting silent-wrong % | bias5 abutting prompt % | mixed cost q=0.2 W=5 / 10 / 20 | q=0.05 W=10 | q=0.5 W=10 |")
out.append("|---|---:|---:|---:|---:|---:|---:|---|---:|---:|")
for name in ["old", "new"] + [f"v{i}" for i in range(len(V))]:
    def pool(kind, leads, bias=None):
        tot = Counter()
        for ld in leads:
            t, _ = agg(kind, True, ld, bias)
            tot.update(t[name])
        return tot
    L = [pool("look", [ld]) for ld in LEADS[1:]]
    T = [pool("transit", [ld]) for ld in LEADS[1:]]
    Lp, Tp = pool("look", LEADS[1:]), pool("transit", LEADS[1:])
    Al, Le = pool("aligned", LEADS[1:]), pool("leave", LEADS[1:])
    b5 = Counter()
    for ld in ("lead0.0-0.2", "lead0.2-0.4"):
        t, _ = agg("bias", True, ld, 5.0, layout="abutting")
        b5.update(t[name])

    def mixed(q, w):
        return sum(q * cost(l, w) + (1 - q) * cost(t_, w) for l, t_ in zip(L, T)) / len(L)
    lab = {"old": "OLD policy", "new": "NEW defaults"}.get(name, labels.get(name, name))
    out.append(f"| {lab} | {pc(Lp, 'silent_wrong')} | {pc(Tp, 'prompt')} | {pc(Al, 'prompt')} | {pc(Le, 'prompt')} | {pc(b5, 'silent_wrong')} | {pc(b5, 'prompt')} | "
               f"{mixed(0.2, 5):.2f} / {mixed(0.2, 10):.2f} / {mixed(0.2, 20):.2f} | {mixed(0.05, 10):.2f} | {mixed(0.5, 10):.2f} |")
print("\n".join(out))
```

### F.old_confirm.py

```python
"""Confirm policy for XR-targeted actions (pure) — when a ray-chosen target must be confirmed.

A guard is judged on how *rarely* it fires (AGENTS.md rule 9, ADR-021): one that
interrupts a clean bind teaches the user to dismiss it, and a dismissed guard costs
attention and catches nothing. So this policy holds only on a *specific, checkable*
signal, never a heuristic, and the release is one word:

* the binder said the ray touched two panels about equally (``ambiguous``);
* the user's gaze landed on a different panel between word onset and utterance end;
* the action is destructive and its target came from a ray — the same rule as
  ``gaze.route.needs_confirm``, because webcam gaze is coarse (~1-2 degrees) and a
  headset ray is not exact either (ADR-v2-010);
* the binder's own confidence or margin sits under a published threshold.

The common path — a bound, confident, non-destructive target on an unchanged panel —
is silent. An ``outcome`` of ``"none"`` means no ray target exists at all: that is not a
prompt, it is the documented ``NO_TARGET`` result, and the caller falls back to the
keyboard focus exactly as ``gaze.route.route_target`` does.

``outcome`` is a plain string ("bound" | "ambiguous" | "none") so this module never
imports the binder; the integrator maps the binder's result onto it.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

OUTCOMES = frozenset({"bound", "ambiguous", "none"})


class ConfirmReason(Enum):
    """Why a confirmation is (or is not) required. Closed; a new reason is a reviewed diff."""

    NONE = "none"                    # bound, confident, safe, steady: type it, say nothing
    NO_TARGET = "no_target"          # no ray target; fall back to keyboard focus, no prompt
    AMBIGUOUS_PANELS = "ambiguous_panels"
    LOW_CONFIDENCE = "low_confidence"
    DESTRUCTIVE_ACTION = "destructive_action"
    TARGET_CHANGED_DURING_UTTERANCE = "target_changed_during_utterance"


# Reasons that do NOT stop the action for a prompt.
_SILENT = frozenset({ConfirmReason.NONE, ConfirmReason.NO_TARGET})


@dataclass(frozen=True)
class ConfirmDecision:
    """Whether to hold the action, why, and the single word that releases it."""

    confirm: bool
    reason: ConfirmReason
    release_word: str = "yes"

    def __post_init__(self) -> None:
        # confirm and reason must agree, so a caller can trust either one alone.
        if self.confirm == (self.reason in _SILENT):
            raise ValueError(f"confirm={self.confirm} contradicts reason {self.reason.name}")
        if not self.release_word or not self.release_word.isprintable() or len(self.release_word.split()) != 1:
            raise ValueError("release_word must be exactly one printable word")


def _finite(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


def decide(
    *,
    outcome: str,
    margin: float,
    confidence: float,
    destructive: bool,
    panel_at_onset: str | None,
    panel_at_end: str | None,
    min_confidence: float = 0.35,
    min_margin: float = 0.25,
) -> ConfirmDecision:
    """Decide whether an XR-targeted action needs the user to confirm. Pure.

    Checked in this order, first match wins (the order only picks the *reported*
    reason; any match holds the action):

    1. ``outcome == "none"`` -> ``NO_TARGET``, no prompt (use keyboard focus). A target
       that never came from a ray cannot be misrouted by one, so even a destructive
       action does not prompt here — the same stance as ``needs_confirm`` for focus
       fallbacks.
    2. ``outcome == "ambiguous"`` -> ``AMBIGUOUS_PANELS``.
    3. both panels known and different -> ``TARGET_CHANGED_DURING_UTTERANCE``. A missing
       observation (``None``) is *not* a change: absence of data is not a signal.
    4. ``destructive`` -> ``DESTRUCTIVE_ACTION``. ``bound`` means the target came from a ray.
    5. ``confidence < min_confidence`` or ``margin < min_margin`` -> ``LOW_CONFIDENCE``.
       The thresholds are inclusive on the passing side: a value *equal* to its
       threshold is confident, matching ``route_target``'s ``>=``.

    ``confidence`` is within [0, 1]; ``margin`` is the binder's lead of the best panel over
    the runner-up (>= 0). Bad numbers raise ``ValueError`` — they are a bug at the seam.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")
    for name, value in (("margin", margin), ("confidence", confidence),
                        ("min_confidence", min_confidence), ("min_margin", min_margin)):
        _finite(name, value)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be within [0, 1], got {confidence!r}")
    if margin < 0.0:
        raise ValueError(f"margin must be >= 0, got {margin!r}")
    if min_confidence < 0.0 or min_margin < 0.0:
        raise ValueError("min_confidence and min_margin must be >= 0")

    if outcome == "none":
        return ConfirmDecision(False, ConfirmReason.NO_TARGET)
    if outcome == "ambiguous":
        return ConfirmDecision(True, ConfirmReason.AMBIGUOUS_PANELS)
    if panel_at_onset is not None and panel_at_end is not None and panel_at_onset != panel_at_end:
        return ConfirmDecision(True, ConfirmReason.TARGET_CHANGED_DURING_UTTERANCE)
    if destructive:
        return ConfirmDecision(True, ConfirmReason.DESTRUCTIVE_ACTION)
    if confidence < min_confidence or margin < min_margin:
        return ConfirmDecision(True, ConfirmReason.LOW_CONFIDENCE)
    return ConfirmDecision(False, ConfirmReason.NONE)


def expected_prompt_rate(decisions: Iterable[ConfirmDecision]) -> float:
    """Fraction of ``decisions`` that hold for a confirmation; 0.0 for an empty input.

    ``NO_TARGET`` is not a prompt (the caller falls back to keyboard focus), so it counts
    as silent. This measures the firing rate of the *thresholds on whatever mix is passed
    in*. The tests feed it a SYNTHETIC mix, so the "< 5%" they assert is a property of
    these defaults on that invented data, not a measured rate of real users — re-measure
    on real sessions before trusting it (a guard that fired on every realistic burst has
    shipped in this project once already).
    """
    total = 0
    held = 0
    for d in decisions:
        total += 1
        held += d.confirm
    return held / total if total else 0.0
```

