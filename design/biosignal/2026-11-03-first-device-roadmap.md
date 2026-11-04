# ThinkGear first-device engineering roadmap — 2026-11-03

**Status:** G0 design review pending; implementation NOT started; hardware qualification NOT performed  
**Owner/decision authority:** project maintainer (architecture, release claims); cloud coder may implement reviewed synthetic-only tasks; a human must run physical device tests  
**Canonical epic:** [#826](https://github.com/MSKazemi/yazses/issues/826)  
**Existing delivery milestone:** GitHub **milestone #10** for bounded accessibility/validation delivery. This roadmap defines *phases and gates*, **not** additional GitHub milestones.  
**Decision/spec:** [ADR-v2-155](../adr/adr-v2-155-thinkgear-transport-safety.md), [implementation contract](../specs/thinkgear-hardware-qualification.md), [evidence review](../research/2026-11-03-thinkgear-first-device-evidence.md).

## Why this workstream, why now

YazSes has an experimental ThinkGear raw-signal path already shipped off by default, but no device validation. Existing parser/stream tests are fake-transport/synthetic. The first real-device effort should remove uncertainty at the adapter/quality/measurement boundary **before** treating a first-person field result as meaningful.

This is the narrowest, most falsifiable follow-on to the existing biosignal ADRs; it does not create another EEG feature, user-facing capability, commercialization programme or separate BCI roadmap. The main project still prioritizes verified everyday offline dictation under ADR-030.

## Tracked work packages and dependencies

| Phase / gate | GitHub work item | Owner | Approx. relative effort (planning only) | Prerequisite | Exit artifact | Current |
|---|---|---|---|---|---|---|
| **G0** architecture | [#827 — review proposed ADR](https://github.com/MSKazemi/yazses/issues/827) | Maintainer | S | Existing ADR-030/152 review | Dated accepted/revised/rejected narrow ADR | **Needs review** |
| **G1a** source health | [#828 — pure ThinkGear health state/tests](https://github.com/MSKazemi/yazses/issues/828) | Cloud coder + human PR review | M | G0 approved | Fake-wire health model, TG-01..11 tests, tests/CI result | **Blocked by G0** |
| **G1b** runtime gate | [#829 — compose source/integrity/waveform gates](https://github.com/MSKazemi/yazses/issues/829) | Cloud coder + human PR review | M/L | #828 + G0 | Unified fail-closed runtime, source provenance and watchdog tests | **Blocked** |
| **G2a** field evidence | [#830 — daemon/monitor/field-test parity](https://github.com/MSKazemi/yazses/issues/830) | Cloud coder + human PR review | M | #829 | Identical fake trace admissions, honest usable exposure and voided cues | **Blocked** |
| **G2b** docs + observability | [#831 — diagnostics and Linux preflight](https://github.com/MSKazemi/yazses/issues/831) | Cloud coder + docs reviewer | S/M | #829, #830 | Privacy-safe docs, diagnostics, release caveats | **Blocked** |
| **G3** physical qualification | [#832 — Linux first-headset pilot](https://github.com/MSKazemi/yazses/issues/832) | Human with device | Hardware-dependent | G2 passed + physical unit | Real-device field/safety aggregate or explicit blocked record | **Not started** |
| **G4** claims decision | [#833 — evidence review/release decision](https://github.com/MSKazemi/yazses/issues/833) | Maintainer | S/M | #832 result or blocked record | Dated support/no-support decision, honest technical docs | **Not started** |

**Task size (S/M/L)** is a rough prioritization heuristic, not a time estimate or delivery commitment. No device delivery date is assumed, and none of the tasks can justifiably be marked tested/complete because documentation exists.

### Dependency flow

~~~text
#827 ADR decision
     |
     v
#828 pure health + packet test fixtures
     |
     v
#829 runtime / provenance guard
     |
     v
#830 field-test + monitor parity
     |
     v
#831 local diagnostics + docs
     |
     v
#832 human hardware feasibility
     |
     v
#833 evidence review / public support claim
~~~

G0 can reject or revise the approach; if so, update blocked implementation issues **before** assigning cloud coding. No autonomous deployment, release, hardware order or public study is part of this roadmap.

## Done vs. not done (as of 2026-11-03)

**Done (design artifacts):**
- `AGENTS.md` (repo root) and code path inspected; related epic #102, EEG/EOG #696, biosignal ADRs and field protocol cross-checked.
- A source-specific evidence/alternatives and limitations report drafted.
- An explicit, **proposed** ADR-v2-155 and implementation contract including TG-01..18 synthetic test cases drafted.
- Seven bounded issues plus scoped epic created in existing milestone #10.

**Not done:** maintainer architectural approval; any runtime code modifications; any test or CI execution; any real-unit pairing, contact test or blink measurement; native GitHub sub-issue linkage (connector does not expose the write API); any supported-device claim or release.

## Roadmap completion criteria / KPIs

| Dimension | Target/measurement | Current evidence |
|---|---|---|
| Offline and default-off safety | No new egress; no headset discovery by default | Existing project invariant; **new implementation not tested** |
| Parser and health state correctness | TG-01..11 pass on arbitrary synthetic byte chunking | Proposed tests only |
| Guard fail-closed invariant | No event from any source-health/integrity/waveform veto; zero stuck holds across stop/pause/stall | Proposed tests only |
| Evidence parity | One fake stream yields equivalent admission and closed reasons in daemon, monitor and field-test | Gap confirmed by code inspection; fix proposed |
| No-data-leak reporting | Shared output aggregate counts/exposure; no raw/identity metadata | Existing schema, regression proposed |
| Live raw connection feasibility | Device reports local `0x80` raw and actionable `0x02` contact metadata | **Unknown until device** |
| Field accuracy/FP | Use existing per-phase phantom upper bounds, deliberate hit Wilson lower bounds, zero stuck mic | **No real device figures** |
| ADR-v2-152 promotion | Requires >=5 participants and >=2 qualifying configurations, plus other explicit gates | **Out of scope of first pilot** |

Numbers such as `CONTACT_TTL_S=3.0`, two fresh good reports and 1s clean rearm are **conservative proposed design choices**, not universal hardware constants or validated clinical criteria.

## Work packages ready for cloud coding (conditional)

When #827 records a maintainer-approved decision:

**Task packet A (#828):**
- Implement pure, injected-clock source health and per-read fault/quality provenance in `thinkgear.py` or `thinkgear_health.py`. Use only generated fake-serial test data. Preserve raw-only events, nominal scaling and strict parser bounds.
- Deliver tests for contact unknown/stale/no-contact, corrupted interleavings, batch ordering, restart and clean rearm.
- Do not touch other source kinds or the CLI.

**Task packet B (#829):**
- Carry health snapshots through `IntegrityGuard` even after sanitized-block copy; combine with waveform and stream gate.
- Preserve runner watchdog and one-release semantics, per-source no-op failure and governor.
- Test independent source types for zero behavioral regression.

**Task packet C (#830):**
- Replace monitor/field-test duplicate gate assembly with a shared function, using exactly the runner policy.
- Run same trace through three call paths, compare accepted/dropped outcomes, test excluded/voided exposure and non-overwriting report schema.

**Task packet D (#831):**
- Print actionable, non-identifying local reason codes, no raw signal or device address; add Linux **investigation** docs.
- Regenerate docs and ADR index with repository scripts whenever changed. Avoid unrelated refactors and false device claims.

**Safety:** all task PRs are reviewed by the human author before opening; no background billing, no paid compute, no cloud recording uploads, no new default-enabled feature.

## Real hardware handoff and release-governance boundaries

The coding agent stops after tests and a local setup guide. Only a person with the device can pair it and run `yazses biosignal check-source`, monitor, field-test and live shutdown stress cases. Record actual version, hardware and OS, measured sample coverage, counted false activations, hit rate with intervals, and failures. Existing [validation protocol](../specs/biosignal-validation-protocol.md) is canonical and must not be rewritten to make a result pass.

The earliest defensible claim after a successful pilot is **"tested with one specific unit/configuration under the described conditions; experimental"**. If the serial transport is absent, contact metadata never turns healthy, or safety stress fails, the right output is **"not qualified / inconclusive"**. Never change ADR-v2-152 to Accepted solely on a single-device run.

## Risk and decision register

| Risk | Likelihood (prior; unmeasured) | Impact | Mitigation / stop trigger | Owning issue |
|---|---|---|---|---|
| No Linux host-accessible raw RFCOMM serial profile | Unknown | High | Verify on actual device; treat as blocked rather than buying services or guessing protocol | #832 |
| Contact quality not emitted or always nonzero | Unknown | High | First inspect raw packets; conservative no-activation; revisit policy only with honest evidence | #828, #832 |
| Corrupted packet hides an arbitrary number of samples | Known protocol limitation | High | Separate uncertainty epoch, zero guessed samples, whole-batch gate | #828, #829 |
| Field-test counts exposure runtime would reject | **Confirmed code gap** | High | Shared constructor; same fake trace parity test | #830 |
| Stale Bluetooth buffer accepted as fresh blink | Unknown | High | Arrival drift/stall plus source contact TTL and rejection; measure on device | #829, #832 |
| Excessive strictness prevents usability | Unknown | Medium | Separate tuning vs evaluation rounds, record no-data outcome, limited rearm policy review | #827, #832 |
| Vendor/private research details accidentally published | Avoidable | High | Public engineering only; no private contacts, terms or cross-repo paths; aggregate data only | All |
| False support/accuracy claim from one person | Likely without governance | High | #833 decision must honor ADR-v2-152 A0–A6 and experimental label | #833 |
| Duplicative issues/docs and stale branch | Manageable | Medium | Link canonical existing docs, only one new safety ADR and scoped epic; re-inspect latest main on each PR | #827 |

No numeric business ROI or commercial rationale belongs in this public roadmap.

## Management notes / actions not supported by the current connector

- **Native issue parent/child linkage:** GitHub milestone policy requires real sub-issue relationships. The issues currently reference the parent in prose; the project maintainer must add native sub-issue links via GitHub's Issues UI or another authorized API client.
- **Milestones:** All bounded issues use existing milestone **#10**; none were created or renamed. The epic carries #10 because every planned delivery child uses that milestone.
- **Review branch:** All research/ADR/spec/roadmap files are on `research/thinkgear-first-device-2026-11-03`. They are **not on main** until a human-reviewed PR merges them. Do not treat branch docs as accepted policies.
- **Next phase:** #827 maintainer review; after approval, code agent starts #828 only, then #829, and so on. Avoid parallel fixes that bypass the guard design.

**No tests, device interactions or runtime changes were performed in writing this plan.**
