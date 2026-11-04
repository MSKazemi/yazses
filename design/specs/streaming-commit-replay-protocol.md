# Specification: deterministic streaming commit and endpoint replay

**ID:** research-spec-streaming-replay-v1  
**Status:** Proposed / design-only, 2026-11-03  
**Tracker:** [#796](https://github.com/MSKazemi/yazses/issues/796)  
**Research:** [assessment](../research/2026-11-03-streaming-endpointing-and-commit-safety.md)  
**Proposed decision:** [ADR candidate](../research/2026-11-03-proposed-adr-streaming-delivery-boundary.md)  
**Fixtures:** [JSONL v1](../research/fixtures/streaming-replay-v1.jsonl)

No implementation, default/config/CLI change, model acquisition, or platform validation is authorized by this document.

## 1. Goal and scope

Prove safety at the **boundary between provisional ASR and external application text**, especially for long thinking pauses and staged review. Isolate a **pure event state machine** from the real model/audio/injection code, run synthetic traces, and compare it to an instrumented current-path adapter without modifying a real user's target. An existing functional failure may be a valid, visible red test; never rewrite the oracle to make a buggy implementation pass.

Not in scope: novel ASR model, punctuation quality model, full editor integration, new runtime streaming pipeline, automation of real user interaction, actual agent submission, model download, cloud benchmark or change of the accepted ADR-030 freeze.

## 2. Event schema (all durations are integer milliseconds)

Each JSONL record is independent; fields `id`, `description`, `mode`, `events`, `expect` are mandatory:

- `mode`: `{"activation":"hold"|"handsfree","staged":boolean,"streaming":boolean}`.
- Events are monotonic in `t_ms`, sorted by (`t_ms`, array order); each has `kind`.
- `hold_start`: begins burst; `audio` may carry synthetic `duration_ms` and `energy_band` only.
- `hypothesis`: full model hypothesis `text`, not a delta; optional `decode_id`; every hypothesis is **provisional**.
- `pause`: silence/thinking gap; length in `duration_ms`, not a completion order.
- `hold_release`: finalization permission for `activation=hold`; `handsfree_stop` for the **separately opted-in** control.
- `final_decode`: full `text` from authoritative decode; cannot finalize earlier than release/stop.
- `target`: synthetic `focus_id`, `caret_version`, `editable` flags; their changes invalidate assumptions about a live partial's safe removal.
- `stage_commit` and `stage_discard`: explicit staged user actions, separate from speech ending.
- `late_partial`: delayed partial that arrives after a release or seal.
- `failure`: category `decode`, `inject_before_effect`, `inject_after_partial_effect`, or `target_lost`; never infer rollback from a thrown exception.
- `expect`: `target_writes` list of final external strings, `staged_chunks` list after all events, `finalizations` integer, `no_pre_release_writes` boolean, `no_forbidden_deletions` boolean, optionally `known_defect`. A test comparing against the *proposed policy oracle* must not consider current implementation green by default.

**No real speech, identifying window title, code from a private workspace, or user transcript belongs in fixtures.** Use synthetic English tokens, abstract target IDs and integer timestamps.

## 3. Oracle rules

A pure `ReplayState` holds `phase` (`idle`, `recording`, `released`, `final_ready`, `staged_pending`, `sealed`), `burst_id`, `last_hypothesis`, `stable_prefix`, `target_snapshot`, `review_chunks`, and an `external_writes` log. State transitions are deterministic: no sleeping, subprocesses, clocks, NumPy, model download or I/O in the pure reducer.

1. `hold_start` opens a unique burst only from idle/sealed; duplicate start is rejected without changing state.
2. Each `hypothesis` may update the private preview and computed LocalAgreement-2 prefix but **never** `external_writes` when staged is on.
3. A `pause` may record interval duration; cannot finalize a physical hold.
4. `hold_release` (or opted-in `handsfree_stop`) changes permission to finalize **once**. Repeated releases and stale final decodes cannot cause duplicate external writes.
5. `final_decode` after release produces an *authoritative candidate*, not a command. Classification, gates, empty results, target health and staging must be evaluated before deciding on writing. In staged mode append one final chunk (nonempty) and do not write; in ordinary mode write exactly once only if approved and target remains valid.
6. `stage_commit` writes reviewed buffered text at the explicit action, provided the target is eligible; if injection fails, the text remains buffered or the result is flagged **indeterminate** when some side effects may have happened. Do not silently replay an indeterminate commit.
7. After `sealed`, `hypothesis`/`late_partial` cannot write to target. A focus/caret change invalidates any deletion authorization; the replay oracle never blindly erases target content.
8. A `final_decode` before an authorized stop is invalid and never counted. Missing, duplicate, late, corrupt, or failed decoder events preserve the safe boundary.

The independent oracle concerns *safe delivery*. Quality metrics for partial stabilization use a separate pure function driven by successive hypothesis strings; do not let a stable prefix create an extra delivery permission.

## 4. Mandatory deterministic negative cases

| ID | Situation | Expected safe outcome |
|---|---|---|
| SR-001 | 18-second held-key thinking pause and full prompt after it | no early finalization; one final on release |
| SR-002 | staged+streaming with multiple partials | no external write; final chunk staged; explicit commit types once |
| SR-003 | stable prefix regresses from one equal-length token to another | private preview can correct; no external deletion |
| SR-004 | two partial updates before poll consumption / overwritten pending slot | no lost/duplicated final; count missing updates as churn/coverage warning |
| SR-005 | a late partial arrives after release | sealed path drops it |
| SR-006 | focus or caret changes during speech | no destructive cleanup; final target delivery gated |
| SR-007 | final decode empty or rejected by gate | no new external write; provisional output never leaked |
| SR-008 | injection fails after unknown partial effects | indeterminate, not a blind retry or false success |
| SR-009 | repeat release / repeat final event | zero duplicate final deliveries |
| SR-010 | 120-second prompt with several pauses | no time/length-induced auto-finalization; bounded policy/resource instrumentation required |
| SR-011 | partial text contains astral Unicode, combining mark, RTL sequence | never use Python `len(text)` alone as caret/delete proof |
| SR-012 | hands-free pause with explicitly opted-in stop | only that control's authorized stop may finalize; not silently substitute for physical hold |
| SR-013 | staged commit fails before side effects | buffer retained; future explicit user retry possible |
| SR-014 | a command-intent final decode after provisional text | zero unapproved target writes |
| SR-015 | a no-editable-target gate after provisional text | no leakage; no blind cleanup |
| SR-016 | a prior user-written target prefix exists | never delete/replace that prefix under replay |

## 5. Metrics and measurement definitions

**Safety (must be exact):** forbidden writes per 1,000 traces; deletion/overwrite outside an owned known-safe span; duplicate final writes; late writes after seal; premature physical-hold endpoints; staged leaks; unresolved indeterminate delivery. All must be **zero** for the safety-gate fixture suite. A zero result on synthetic fixtures is **not** a statistical upper bound on real app failure probability.

**Live-preview quality:** first stable-prefix availability, prefix churn as sum of characters retracted/changed between successive hypothetical committed prefixes, stale preview character-time (time × incorrect visible characters), suffix missing rate from a one-slot consumer, and # repeated full decodes. Report both word-based and character-based comparison; distinguish CJK/RTL/grapheme cases.

**Performance:** onset-to-first-useful-private-preview; release-to-final-authorized-delivery p50/p95; total decode CPU seconds / captured-audio seconds; peak RSS; decoder count per minute; long-prompt drop/failure rate. Compare batch-off and streaming-on with the **same device, model hash, data and host**, including a no-preview baseline.

**Accuracy:** original reference and raw/normalized WER/CER at utterance level; timeouts or failed runs count as failures, not excluded. Stratify by model, language, pause duration, prompt length, CPU, operating system, injector and editor class. No accuracy numbers are reported in this spec.

## 6. Evaluation plan and reproducibility contract

**Phase R0: pure oracle** — parse JSONL fixtures, schema-validate, reduce each trace, and assert all expected outputs and invariants. Report per-fixture result, evaluated revision SHA, fixtures SHA-256 and Python version; never use `or True` test assertions.

**Phase R1: adapter to existing classes** — drive the current `StreamingEngine` using a deterministic fake decoder; drive `StreamingInjector` with a fake screen that models success, partial effects, focus change, and failure. Use explicit scheduling barriers rather than sleeps for poll/commit races. Prove the staged-path defect by asserting *current observed behavior* separately from the *desired oracle*. Do not conceal an intentionally red test in CI.

**Phase R2: candidate safe design** — after approval only, implement the minimal staged-path suppression with no API additions; add an end-to-end daemon + fake-target regression for `streaming=true, staged=true`, then test error/abort/empty-final/command/target-guard paths. No user-facing switch added.

**Phase R3: validation + benchmark** — only after passing pure gates, run a safe dedicated editor harness (never a live terminal or private text); obtain named OS/hardware reports for X11, Wayland GNOME/KDE, macOS and Windows individually, distinguish preview from verified. Publish machine metadata, models/licenses/hashes, data provenance, raw aggregate JSON, failures and honest confidence intervals.

**No acceptance of a runtime change** until ADR owner approval, a separately tracked delivery item and green offline regression suite. Preserve legacy `[streaming]` disabled default. The tests in this spec are *proposals*: no result should be reported as executed until they are actually committed and run.

## 7. Security, privacy and license gates

- No network, telemetry, cloud API, recording upload, new on-device model or extra package required for R0/R1.
- Generated fixtures must contain no participant speech, developer secrets, real transcripts or sensitive editor text.
- Logs store timings, state transitions, synthetic IDs, lengths and failure classes only; plaintext transcript logs must be controlled by the existing local log/debug policy, never forwarded to an outside telemetry endpoint.
- Pin existing dependencies and upstream model provenance before R3; see research note license ledger. Separate licensing review required before any new weights or third-party runtime are included.
- Distinguish `[C]` audited implementation, `[H]` historical measurement, `[P]` upstream evidence and `[U]` unverified inference in all reports.

## 8. Stop / go criteria

**GO on research only:** pure fixture schema and deterministic oracle tests reproducible, staged+streaming conflicting path documented, historical #153 regression retained, no unintended egress. **NO-GO runtime:** any unaccounted character deletion, staged leak, duplicate final, partial after seal, or uncertain focus/selection recovery. **NO-GO default change:** absent maintainer's separate explicit decision and platform/quality evidence.

See [ADR-030](../adr/adr-030-agent-era-direction.md) and [milestone policy](../milestone-policy.md): #796 remains an evergreen research issue with no milestone.
