# BIO-TG-00 (#827) review evidence pack: ThinkGear first-device safety contract

**Status:** RESEARCH DRAFT, REVIEW PENDING. This is a review aid for the G0 decision on
[#827](https://github.com/MSKazemi/yazses/issues/827). **It decides nothing.** It does not
accept, revise or reject ADR-v2-155, it does not change the status of ADR-v2-152, and it
authorizes no runtime code.
**Date:** 2026-11-06
**Code baseline:** `main` @ `8a72bbc6`. Every `file:line` below refers to that tree.
**Read for this pack:** issues #826–#833 (GitHub REST API, read 2026-11-06);
[ADR-v2-155](../adr/adr-v2-155-thinkgear-transport-safety.md);
[the qualification spec](../specs/thinkgear-hardware-qualification.md);
[ADR-030](../adr/adr-030-agent-era-direction.md) (2026-11-01 amendment);
`src/yazses/biosignal/{thinkgear,integrity,pipeline,runner,cli_impl,fieldtest}.py`;
`tests/test_biosignal_thinkgear.py`.
**Nothing was executed** apart from `git`/`grep`/`gh api` reads. No test, hardware or device
was run.

---

## 0. Housekeeping findings the reviewer should know first

These are facts about the review package itself, not about the design.

| # | Finding | Evidence | Consequence for G0 |
|---|---|---|---|
| H1 | **The ADR under review is ADR-v2-155, not ADR-v2-154.** #826 and #827 still say "Proposed ADR-v2-154". On `main`, ADR-v2-154 is a *different* decision (EEG/EOG research evidence gates, #696). | `design/adr/adr-v2-154-eeg-eog-evidence-gates.md:1`; `design/adr/adr-v2-155-thinkgear-transport-safety.md:1`; renumbering commit `a86176ee`; ADR index rows `design/adr/README.md:246-247` | The decision annotation must go on **v2-155**. The issue texts need their ADR number corrected (owner action; this pack edits no issue). |
| H2 | **Every "review branch" link in #826–#833 is dead.** `research/thinkgear-first-device-2026-11-03` returns HTTP 404 on GitHub; it was merged as PR #856. | `gh api repos/MSKazemi/yazses/branches/research/thinkgear-first-device-2026-11-03` → 404 (2026-11-06); merge commit `400908f1` | Review the files on `main` instead: the three documents are at the paths above. |
| H3 | **No overlapping runtime fix exists.** No ThinkGear runtime commit in the last 300 commits on `main` besides the docs merge; the CHANGELOG `[Unreleased]` section does not mention ThinkGear, `poor_signal`, `IntegrityGuard` or field-test parity; no local branch matches `thinkgear`/`tg`. | `git log --oneline -300`, `CHANGELOG.md` `[Unreleased]` grep (2026-11-06) | #827 acceptance item "inspect latest main for overlapping fixes" is satisfied as of `8a72bbc6`. |
| H4 | ADR-v2-155 is already in the generated ADR index as **Proposed**. | `design/adr/README.md:247` | After a decision, re-run `uv run python scripts/gen-adr-index.py`; do not hand-edit the index. |

---

## 1. Clause → current code evidence

"GAP" means the clause describes behaviour that `main` does not have. A GAP is expected — the
ADR is a proposal for new behaviour — so the column tells the reviewer **how big** each
implementation step is, not that anything is broken today in the shipped default (the whole
feature is off by default: `src/yazses/config.py:1074`, `enabled: bool = False`).

### 1.1 ADR-v2-155 decision clauses

| Clause (ADR-v2-155) | Current code at `8a72bbc6` | Verdict |
|---|---|---|
| **D1** Raw `0x80` is the only detector input; eSense/attention/meditation/vendor blink never exposed | The parser returns only `raw` and `poor_signal` per packet (`thinkgear.py:128-137`, built at `:258`); vendor scores are skipped and a test pins it (`tests/test_biosignal_thinkgear.py:93`, `test_esense_attention_meditation_are_never_exposed`). | **MET** (already true; keep) |
| **D2a** Read *all* `POOR_SIGNAL` reports in wire order; any nonzero taints the whole read | `read()` overwrites a single attribute with each report, so only the **last** survives: `thinkgear.py:439-442`. A `0 → 200 → 0` read ends with `poor_signal == 0` and nothing else records the 200. | **GAP** (the core finding of #826 gap 1, confirmed) |
| **D2b** Any checksum / length / malformed frame taints the whole read | Rejections are counted (`thinkgear.py:146-148`, incremented at `:195`, `:203`, `:208`) and logged once per read (`:443-447`), but the emitted `SampleBlock` carries no taint and nothing downstream reads the counter. | **GAP** (counting exists; veto does not) |
| **D2c** Unknown contact (no report yet) is untrusted | `poor_signal` starts as `None` (`thinkgear.py:390`, reset at `:422`) but nothing consults it; raw blocks are emitted before any `0x02` report (`:448-454`). | **GAP** |
| **D2d** Stale contact report (>3 s) is untrusted | No contact timestamp is kept anywhere in `thinkgear.py`. The only time-based guard is generic stream stall (`integrity.py:710-721`), which is about *blocks*, not contact reports. | **GAP** |
| **D2e** Health kept separate from samples; batch with no raw may update health but emit no event | A read with no raw rows returns `None` (`thinkgear.py:448-449`) after updating `poor_signal` (`:441-442`). So the *shape* is right, but a `200` in a raw-less read is visible only as a mutable attribute that no gate reads. | **PARTIAL** |
| **D3a** Event gate requires source-health AND stream integrity AND waveform quality | Integrity + waveform are composed today: `IntegrityGate.update` ORs the guard's per-block verdict with the inner monitor (`integrity.py:826-844`), and the pipeline closes on `BAD`/`suppress_events`/`bad_during_update` (`pipeline.py:769-788`). There is no third (source-health) input. | **PARTIAL** (2 of 3 legs) |
| **D3b** Missing/unrecognised provenance is untrusted | Already the integrity guard's rule: `gate_closed_for` returns `True` for a block not in its bounded journal (`integrity.py:680-686`; depth `_PROVENANCE_DEPTH = 8` at `:162`; journal at `:625`, filled at `:652-656`). | **MET for integrity; reusable seam for health** |
| **D3c** A health veto releases a held activation, suppresses a pending double blink, and nothing fires on recovery | A closed quality gate already drops events and releases a held squeeze (`integrity.py:800-807` docstring; `pipeline.py:785-788`). Detector reset on a **stream gap** exists in the runner (`runner.py:391-399`, `pipeline.reset(keep_governor_state=True)`). There is no reset tied to a *health* transition, because there is no health transition. | **PARTIAL** |
| **D4** Fixed constants: first explicit `0` required; `!= 0` unhealthy; TTL 3.0 s; 2 fresh zero reports + ≥1.0 s clean raw; completing batch still vetoed | None of these constants exist in code (`grep` for TTL/rearm in `src/yazses/biosignal/` finds none tied to ThinkGear). | **GAP** (needs decision Q3 first) |
| **D5** Rejections create an uncertainty epoch; never synthesize samples or invent gaps; label lost count `unknown` | The "never fabricate" half is **already true**: `t0 = emitted / fs` (`thinkgear.py:451-453`), no padding, and the warning text says "no samples were substituted" (`:445-446`); a test pins it (`tests/test_biosignal_thinkgear.py:261`). The epoch half (invalidating gestures across the boundary, excluding exposure) does not exist. Note: `skipped_bytes` (`thinkgear.py:149`, `:182`, `:185`, `:217`) is **not** part of `rejected_packets` (`:152-153`), so a resync is not even logged as a loss. | **PARTIAL** (no-fabrication MET; epoch GAP; resync uncounted — see Q8) |
| **D6** One shared live-policy construction for daemon, monitor, field-test | Daemon: guard + gate built inline (`runner.py:853`, `:918-919`, `:923-924`, `live` from scheme at `:862`). Monitor: a second hand-written copy (`cli_impl.py:753-757`). **Field-test: no guard, no gate** — it opens the raw source (`cli_impl.py:1678`), builds the plain pipeline (`:1690-1691`), and feeds raw blocks (`:1725`, `:1735`). | **GAP** (#826 gap 3 / #830 problem confirmed) |
| **D6b** `check-source` adds a ThinkGear protocol-health line without claiming support | `conformance.py` has no ThinkGear-specific code (`grep thinkgear\|poor` → none; entry point `conformance.py:203`). | **GAP** (small; diagnostics only) |
| **D7a** Missing pyserial / port / disappearance cannot crash dictation or cause an activation | Lazy import with a clear ImportError (`thinkgear.py:266-287`); open failure and read failure degrade to unavailable no-op (`:410-417`, `:433-435`, `_fail` at `:464-470`); tests at `tests/test_biosignal_thinkgear.py:283`, `:295`, `:305`. | **MET** |
| **D7b** A generic quality-gate exception must not silently disable the health veto | Two existing fail-**open** paths a health leg would inherit unless designed around: (1) `IntegrityGate` drops a raising inner monitor and continues on integrity alone (`integrity.py:829-834`) — fine for integrity, but waveform quality is then silently gone for the session; (2) if the **whole** `parts.quality` object raises, the pipeline disables the quality gate and returns *open* (`pipeline.py:773-777`). A health veto placed inside `parts.quality` would be switched off by path (2). | **GAP with a design trap** (see Q4/Q9) |
| **D8** Off by default; no network; local hardware only; aggregate-only reports | Default off (`config.py:1074`); ADR-030 amendment requires a default daemon to load none of the code (`adr-030-agent-era-direction.md:175-176`, enforced by `tests/test_biosignal_default_stays_out.py`). Field-test docstring promises counts only (`cli_impl.py:1658-1663`). No ThinkGear module opens a socket (it opens only `serial.Serial`, `thinkgear.py:290-293`). | **MET** (re-verify with TG-17/TG-18 tests in #831) |
| **Boundary** No change to `SampleBlock`, its `t0` contract, event vocabulary, action mapping or blink thresholds | Nothing in the proposal requires one *if* the health snapshot rides the guard's existing identity journal (`integrity.py:625`, `:652-656`, `:680-686`). | **Feasible as written** |

### 1.2 Spec state-table rows that depend on wiring, not on the source

| Spec row / test | Current evidence | Verdict |
|---|---|---|
| TG-11: stop/start must not carry trust | `start()` rebuilds the parser and resets `poor_signal`/counters (`thinkgear.py:418-423`), but returns early when a port is already open (`:403-404`), so a `start()` without `stop()` keeps everything. `IntegrityGuard.start()` clears its journal (`integrity.py:629-637`). | **PARTIAL** — fine on stop→start; a double-start keeps state |
| TG-15: held action released once across fault/pause/watchdog | Watchdog thread + release path exist (`runner.py:320-356`, `:434-451`, `:665-671`; `DEFAULT_WATCHDOG_SECONDS = 1.5` at `:96`). | **MET for stream silence**; health-driven release is new |
| TG-16: untrusted exposure excluded, overlapping cues voided | The **accounting already exists**: untrusted blocks are not added to `usable` (`fieldtest.py:947-948`) and overlapping cues are voided (`:953-954`), driven by `_trust(status)` (`:893`, `:1054-1060`). What is missing is any untrusted *signal* reaching that status, because field-test has no guard (row D6). | **Accounting MET; input GAP** |
| "Failure without block" (health packet with no raw, then silence) | Raw-less read returns `None` (`thinkgear.py:448-449`); the guard then runs only its stall check (`integrity.py:644-646`); the runner resets detectors after a gap > watchdog (`runner.py:391-399`). A pending blink candidate is therefore cleared only by **time**, not by the contact fault. | **GAP** (bounded by watchdog 1.5 s, per current code) |

---

## 2. Decisions for the maintainer (yes/no)

Each item restates one #827 question (Q1–Q6) or a question this pack surfaced (Q7–Q10) as a
yes/no decision, gives the evidence that bears on it, and names what the answer unblocks.
**The pack expresses no preference.** Where the ADR proposes an answer, it is labelled
"ADR proposes".

| ID | Decision (answer yes or no) | Evidence that bears on it | A "yes" unblocks | A "no" means |
|---|---|---|---|---|
| **Q1** | Does any nonzero `POOR_SIGNAL` anywhere in one serial read veto **the whole read**, even if a later report in the same read is `0`? *(ADR proposes: yes.)* | D2a GAP at `thinkgear.py:439-442`; there is no per-sample timestamp to localise the bad report (`thinkgear.py:59-63` docstring; ADR-v2-155 §Context). | #828 (TG-03, TG-04) | #828 needs a written alternative that is "demonstrably causal and equally safe" (#827 Q1) before coding. |
| **Q2** | Does a parser reject mean an **uncertainty epoch** with lost-sample count recorded as `unknown`, never an estimate? *(ADR proposes: yes.)* | D5: no-fabrication already holds and is tested (`thinkgear.py:445-453`; test `:261`); ThinkGear has no sequence number (`thinkgear.py:59-61`). | #828 (TG-05, TG-06), #833 audit item "record explicit unknown sample loss" | #828 must specify a loss estimator, which ADR-v2-155 §Alternatives already rejects. |
| **Q3a** | Accept `CONTACT_TTL_S = 3.0`, `REARM_GOOD_REPORTS = 2`, `REARM_CLEAN_SAMPLE_S = 1.0`, "zero only is healthy", and "completing batch still vetoed" as **experimental engineering constants**, hard-coded, not user-configurable? | D4 GAP (none exist). No hardware measurement exists (spec §0 table "Hardware: not yet available"; ADR-v2-155 last line). | #828 (TG-07, TG-08) | #828 waits for revised constants. |
| **Q3b** | Is "the device is unusably restrictive under these constants" an **acceptable, reportable G3 outcome** (INCONCLUSIVE/FAIL) rather than a reason to loosen the gate during the pilot? *(ADR proposes: yes, ADR-v2-155 §Consequences bullet 1.)* | Spec §10 open question 2; #832 Outcomes "INCONCLUSIVE ... quality permanently untrusted". | #832 (its outcome definitions), #833 option 2/3 | The pilot needs a pre-registered loosening rule before it runs (spec §10 forbids tuning on scored data). |
| **Q4** | Carry the per-read health snapshot through `IntegrityGuard` via its **existing identity journal** (a read-only `health_for(block)` next to `gate_closed_for`), with no `SampleBlock` change? | D3b: journal and fail-closed lookup already exist (`integrity.py:625`, `:652-656`, `:680-686`); sanitized copies are produced by `checker.check` and the *emitted* block is what is journaled (`:651-656`), so the seam sees both inner and outer block. | #829 (TG-12, TG-13) | #829 needs a different provenance design, likely touching `SampleBlock` (forbidden by ADR boundary) → would need a revised ADR. |
| **Q5** | Factor **one** guarded-source + gated-pipeline constructor used by daemon, monitor and field-test, with **no** change to config keys, CLI flags or IPC? | D6: three call sites, two hand-written copies (`runner.py:918-924`, `cli_impl.py:753-757`) and one missing (`cli_impl.py:1678-1735`). No new public surface is needed to share them; `live` is already derived from the spec scheme in both copies (`runner.py:862`, `cli_impl.py:755`). | #829 (constructor), #830 (TG-14, TG-16) | #830 must define per-caller differences and document why (its DoD already allows "documented and justified" differences). |
| **Q6** | Is this work a **narrow hardening inside the existing ADR-030 biosignal exception**, not a new capability or device family? | ADR-030 amendment: exception covers the finished ADR-v2-152 pipeline; "further biosignal capabilities and new device families" stay frozen (`adr-030-agent-era-direction.md:162-178`). ThinkGear is already a shipped source (`sources.py:1414-1416`, `boards.py:269-276`). ADR-v2-155 §Scope calls itself "correctness hardening ... not a new capability". | The whole epic: #828–#833 | Under ADR-030 §3 the epic is frozen; #828–#831 stay blocked and #832 cannot start. |
| **Q7** | Is fixing the **field-test parity gap** (field-test measures on an ungated stream) in scope for this epic even for **non-ThinkGear** sources? | D6: `run_field_test` uses no guard for *any* source (`cli_impl.py:1678-1735`), so this is a generic evidence-parity defect, not ThinkGear-specific. ADR-v2-155 D6 and #830 frame it inside this epic. | #830 can fix it generically in one PR | Split: a generic parity fix as its own issue (it is a correctness fix, arguably outside the freeze) and a ThinkGear-only health leg in #830. |
| **Q8** | Does a parser **resync** (`skipped_bytes` increase with no checksum/length/malformed reject) also veto the read? *(Spec §3 says "a lone extraneous framing byte need not equal a dropped sample but **may** conservatively veto" — undecided.)* | `skipped_bytes` is counted (`thinkgear.py:149`, `:182`, `:185`, `:217`) but excluded from `rejected_packets` (`:152-153`) and from the loss warning (`:443-447`). A test already treats leading extra SYNC bytes as tolerated (`tests/test_biosignal_thinkgear.py:195`). | #828 (TG-06 expected values) | #828 must define a "significant resync" threshold — a number the spec does not give. |
| **Q9** | Must the health veto sit **outside** the `parts.quality` exception path, so that a raising waveform monitor (or a raising gate object) can never reopen the gate for a ThinkGear source? | D7b: `pipeline.py:773-777` disables the whole quality gate and returns *open* on an exception; `integrity.py:829-834` drops only the inner monitor. ADR-v2-155 D7 last sentence requires fail-closed for this path. | #829 (its step 3 "even if a generic quality monitor degrades on failure") | #829 needs an explicit statement of which exception reopens what, and a test pinning it. |
| **Q10** | Is a contact fault in a **raw-less** read allowed to reset a pending blink only at the **next** block (or after the 1.5 s watchdog gap), rather than immediately? | §1.2 "failure without block": no synthetic empty block is allowed (spec §4 caveat); reset today is time-driven (`runner.py:391-399`, `DEFAULT_WATCHDOG_SECONDS = 1.5` at `:96`). | #829 (TG-09, TG-15 edge case "health update with no raw samples followed by silence") | #829 needs a new non-block signal path from source to pipeline — a larger change than the ADR describes. |

**Status-hygiene decisions (procedural, from #827 acceptance list):**

| ID | Decision | Unblocks |
|---|---|---|
| P1 | Record the outcome (Accepted / revised / rejected, with date) **on ADR-v2-155**, and re-run `scripts/gen-adr-index.py`. ADR-v2-152 status unchanged. | #828–#831 READY labels |
| P2 | Correct the ADR number (154 → 155) and the dead branch links in #826–#833 (H1, H2). | Reviewers and cloud agents following the issue links |

---

## 3. Unblock matrix

Which decisions each downstream issue needs before it can be marked READY. "—" means the
issue does not depend on that decision.

| Issue | Phase | Hard prerequisites (decision IDs) | Soft (affects tests / wording only) | Also blocked by |
|---|---|---|---|---|
| [#828](https://github.com/MSKazemi/yazses/issues/828) pure health state + fake wire | G1 | Q1, Q2, Q3a, Q6, Q8, P1 | Q4 (shape of snapshot type) | — |
| [#829](https://github.com/MSKazemi/yazses/issues/829) gate composition + shared constructor | G1 | Q4, Q5, Q6, Q9, Q10, P1 | Q7 | #828 |
| [#830](https://github.com/MSKazemi/yazses/issues/830) daemon/monitor/field-test parity | G2 | Q5, Q6, Q7 | Q3b (report wording) | #829 |
| [#831](https://github.com/MSKazemi/yazses/issues/831) diagnostics + privacy-safe docs | G2 | Q6 | Q2 (how "unknown loss" is worded), Q3b, Q8 | #829, #830 |
| [#832](https://github.com/MSKazemi/yazses/issues/832) first physical device | G3 | Q3a, Q3b, Q6 | — | #828–#831 merged; **hardware available** |
| [#833](https://github.com/MSKazemi/yazses/issues/833) evidence review / release decision | G4 | Q2, Q3b | all (its evidence matrix maps every ADR-v2-155 clause) | #832 result or explicit BLOCKED |

Reading the matrix: **Q6 is the gate on everything** — a "no" freezes the epic under ADR-030
§3. After Q6, **Q1/Q2/Q3a/Q8** are the minimum for G1 to start (#828); **Q4/Q5/Q9/Q10** are
the minimum for #829.

---

## 4. What this pack does not establish

- It does not show that any proposed constant is right. No device was observed; the 3 s / 2
  report / 1 s values are from ADR-v2-155 and the spec, unmeasured (ADR-v2-155 last line).
- It does not verify the NeuroSky protocol claims; those are cited by ADR-v2-155 to the vendor
  page `https://developer.neurosky.com/docs/doku.php?id=thinkgear_communications_protocol`
  (vendor documentation; not re-read for this pack).
- Line numbers are valid only at `8a72bbc6`; re-check before coding (spec §0 item 1).
- It does not modify #826–#833, ADR-v2-155, ADR-v2-152 or any runtime file.
