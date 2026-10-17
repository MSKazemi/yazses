# OneVoice — evaluation and contributor-sized tasks

**Status:** Proposed work breakdown. Not `agent-ready`; prerequisite maintainer decisions and platform evidence are unresolved. Do not label with `jules` or trigger execution.

## Study questions

1. Can a user speak to an explicitly selected app without first manually focusing its editor?
2. Can the router distinguish dictate/draft/submit/agent call reliably?
3. How often does it abstain versus deliver to the wrong target?
4. Does confirmation impose less effort than manual switching, and is that benefit worth the security surface?
5. Can desktop Linux, Windows, macOS and Android share the same behavior vectors without pretending that platform permissions are identical?

## Minimum test harness

Synthetic `CommandEvent`, `ContextSnapshot`, `DestinationRef`, `CapabilitySet`, `RouteProposal` and `DeliveryOutcome` fixtures. No real user audio/transcripts, credentials, real third-party accounts, screenshots or window titles in committed fixtures.

Track independent steps:
- speech-to-text correctness (WER/CER for a synthetic test corpus);
- command detection precision/recall and false trigger rate on ordinary dictation;
- destination top-1 correct rate;
- wrong-target **side-effect** rate, including stale focus/tab cases;
- ambiguous/abstain/clarification rates, including avoidable clarification;
- draft insertion success rate vs *verified* insertion rate;
- outbound submission duplicate rate and verified-ack rate;
- user task completion; median/p95 activation-to-draft and activation-to-ack latency;
- user interaction effort (button presses, app switches, time) versus baseline;
- consent comprehension and revocation success;
- error-cost weighted measure for actual wrong external actions.

**No unverifiable target percentages are published as results.** Set pilot acceptance thresholds with a maintainer and measured baseline before running the study. A wrong external recipient is a safety failure requiring investigation, not a tolerable optimization loss.

## Tasks and dependencies

| ID | Size | Deliverable | Dependencies and acceptance |
|---|---|---|---|
| OV-001 | XS | Audit current `inject/target.py`, `agent/plan.py`, app profiles and ADRs | Link current behavior and gaps; no runtime changes |
| OV-002 | S | 40 synthetic utterances: normal dictation, quoted trigger, write, ask, ambiguous, multilingual | Deterministic fixture + review; no cloud |
| OV-003 | S | Pure command-boundary parser preserving payload exactly | All OV-002 test cases pass; unknown -> ordinary dictation |
| OV-004 | S | Pure registry for explicit named destinations | Reject collisions and disallowed targets; fake instances only |
| OV-005 | S | Pure policy: compose vs submit, confirmation, expiry | Fail-closed tests for stale snapshots, unknown scopes, multiple targets |
| OV-006 | S | Adapter contract and fake editor adapter | No platform imports, sends, screenshots or writes outside test memory |
| OV-007 | S | Outcome verification state machine and retry policy | Explicit unknown/verified distinction; no auto retry after unknown sends |
| OV-008 | M | Desktop pilot with one OS + one native editor | OS and app selected by maintainer; permissions, snapshot and live verification documented |
| OV-009 | S | Accessible overlay with destination, edit/draft/submit and abort | Screen-reader tested; no default send; app changes visible |
| OV-010 | M | Browser composer feasibility study (user-selected ChatGPT tab) | Identify stable app-specific integration and limitations; no login bypass |
| OV-011 | S | Privacy/egress threat-model delta and consent copy | ADR-019 review before *any* outbound adapter |
| OV-012 | S | Provider/agent integration feasibility matrix (ChatGPT, Claude, Codex, local MCP) | Explicit distinction web draft vs API request vs local agent tool |
| OV-013 | M | Human usability pilot with reproducible task script | Informed consent; aggregate reports; independent device/OS metadata |
| OV-014 | S | Android IME-bound destination contract vectors | Respects MOB-003: no background arbitrary-field promise |
| OV-015 | S | iOS handoff feasibility design only | Respects MOB-010: no mic in keyboard extension |
| OV-016 | S | Documentation and compatibility matrix | Names unsupported and unverified cases, no universal-app claims |

**Implementation gate:** OV-001 / OV-002 research may be done before a core decision. The remaining tasks must receive a maintainer-approved narrow ADR or a revised/accepted ADR-025 integration plan before being marked implementation ready. Cross-device relays and autonomous agent orchestration are **not** included.

## Repeatable acceptance scenarios

- A. Plain text with the words "ask ChatGPT" inside a quote: no route.
- B. Explicit "write to" known editor: only a draft, never send.
- C. Explicit "ask" external destination: exact payload, provider and cost disclosed, explicit approval before submission.
- D. Changed foreground window at delivery: do not write to unintended field.
- E. No accessible field: preserve local draft, show meaningful fallback.
- F. Two matching app instances: ask for disambiguation.
- G. Frozen/crashed target: no ghost success message.
- H. App rewrites text after insertion: final verified result reflects mismatch.
- I. Network failure after remote request: status unknown, no automatic duplicate send.
- J. User revokes destination before queued action: abort and show cancelled.
- K. Multi-destination request with one failure: per-target report.
- L. Screen-reader / keyboard-only operator: preview/confirmation/abort can be completed without a pointer.

## Platform matrix for human evidence

For each OS and session (Linux X11; Wayland GNOME/KDE; Windows; macOS; Android IME; iOS design-only), record platform version, method, permission state, app type/version, editable-field exposure, outcome verification, observed restrictions, failure screenshots **only if participants separately consent and redact them locally**. Prefer synthetic apps and mock documents.

Include several people and several machines per OS where possible. Do not combine one user's repeated runs with independent-user coverage. Report per-OS sample counts and hardware class. Human participants see a short consent notice explaining local audio processing, any connected-service transfer, saved aggregate metadata, retention, deletion rights, and optional data sharing before testing. Default evaluation collects no raw audio, transcripts, account identities, private window titles, screenshots or voiceprints.

## Research novelty: potential claims, not conclusions

- Named-destination voice routing with independently tested destination accuracy.
- Safety through explicit uncertainty/abstention and separation of draft versus send.
- Outcome-verified app/agent delivery, measured across OS and UI types.
- Interaction-cost comparison: one voice capture versus repeated app selection.

Publish only after a preregistered protocol, baselines, repeatable fixtures, consent review and actual measured results. Tests alone do not establish usability or publication-grade novelty.
