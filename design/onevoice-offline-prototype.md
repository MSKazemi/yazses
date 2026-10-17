# OneVoice Phase 1 — isolated routing prototype

**Status:** Experimental, offline, draft-only; **not** wired into the daemon or any real application  
**Date:** 2026-10-17  
**Design proposal:** [OneVoice RFC and universal interface, draft PR #596](https://github.com/MSKazemi/yazses/pull/596)  
**Architecture dependencies:** [ADR-025](adr/adr-025-grounded-interaction-kernel.md) (Proposed), [ADR-022](adr/adr-022-a-confirmation-a-voice-user-cannot-give.md) (Proposed), [ADR-020](adr/adr-020-agent-protocols.md) (Accepted), [ADR-021](adr/adr-021-invest-in-error-cost.md) (Accepted).

## Why this experiment exists

The proposed universal interface should first demonstrate **selective named-destination routing without accidental external actions**. This branch introduces a *small, self-contained* implementation that accepts **only text inputs explicitly designated as command-mode**, routes them to one of two in-memory fake editors, validates an expiring destination-bound synthetic grant, and reports whether the fake editor verified the inserted draft.

This is a proof of the *contract*, **not** evidence that arbitrary real applications can be found, focused or written to. There are no OS APIs, browser extensions, accessibility permissions, microphones, LLMs, cloud calls, external accounts, remote control, persistence or background work.

## Try the proof of concept

From the repository root:

```sh
uv run python -m yazses.onevoice.demo
uv run python -m pytest tests/test_onevoice_router.py -q
```

With a source-only Python environment that has pytest installed, the equivalent is:

```sh
PYTHONPATH=src python -m yazses.onevoice.demo
PYTHONPATH=src python -m pytest tests/test_onevoice_router.py -q
```

Illustrative expected demo output:

```text
editor-a: draft_inserted_verified: First application receives this.
editor-b: draft_inserted_verified: Second application receives this.
```

The input is a constant, synthetic phrase; **the microphone does not run**. The words appear in two Python objects, not in desktop windows. The test suite currently contains **72 passing synthetic test cases** in an isolated local environment; full project CI and real OS compatibility require separate verification.

## What the code contains

| File | Responsibility |
|---|---|
| `src/yazses/onevoice/prototype.py` | Minimal command parser, allowlisted destination registry, immutable target snapshot, scope/expiry checks, replay check, staged draft delivery and outcome states |
| `src/yazses/onevoice/demo.py` | Safe two-app illustration using two fake editor instances |
| `tests/test_onevoice_router.py` | Synthetic positive and negative cases: command boundary, language-preserving payload, app collisions, missing grants, focus/field changes, secure fields, verification, duplicate requests, and failures |

The parser recognizes a *deliberate* narrow English grammar:

- `Write to Editor A: <payload>` → **draft only**.
- `Draft for Editor B: <payload>` → **draft only**.
- `Ask Agent: <payload>` → classify as proposed external submission, **never execute**.
- `Send to Agent: <payload>` → likewise **never execute**.

Without `command_mode=True`, none of the phrases route anywhere. In real YazSes the command-mode signal must come from an existing trusted activation source, **not** from a webpage or model output.

The parser intentionally does not interpret a command that appears inside the payload. For example: `Write to Editor A: send the email` produces the draft text `send the email` and **does not send any email**.

## Verified in the isolated experiment

- Two registered editors receive only the drafts explicitly addressed to them.
- Unknown destinations and multiple entries with the same alias do not silently fall back to the focused window.
- A plan binds an app instance, field and revision; changed context causes refusal.
- Draft grants must be scoped to destination + instance + permitted operation + future expiry and represent explicit user approval.
- Password/secure or non-editable fields are refused.
- A repeated request ID is not executed twice *within the live router object*.
- A returned successful insert is only `draft_inserted_verified` when the fake adapter confirms matching content. Missing or mismatched readback is `insertion_unverified`.
- Remote submission operations remain intentionally unimplemented even when a fake adapter claims it supports sending.
- Adapter exceptions do not leak private exception text or crash the pure router.

## What **has not** been proven

- No real desktop, smartphone, browser, VS Code, ChatGPT, Claude, Codex or other provider integration exists in this experiment.
- No live target-identification accuracy, speech command false-positive rate, wrong-window side-effect rate, concurrency safety or usable hands-free confirmation behavior has been measured.
- The `Grant` is a **synthetic input value**, not a signed capability or secure OS authorization mechanism. A caller constructing `Grant(user_approved=True)` is not a trustworthy permission source. A production implementation needs a trusted confirmation gate/authority service designed with ADR-022 and ADR-025.
- The in-memory consumed-request set does not survive a process restart and must **not** be used as durable external-action idempotency.
- Fake editor readback is stronger than many real GUI insertion backends; a key event succeeding cannot be treated as verified delivery.
- No full repository CI was run in the isolated local environment. No platform or feature-availability promises follow from these unit tests.

## Next steps and blocking gates

1. **Review governance:** reconcile ADR-025 (shared kernel) and ADR-022 (hands-free confirmations). This prototype is a disposable adapter experiment, not a competing permanent kernel.
2. **Live Python threat model:** refresh archived Rust-era security analysis for the current daemon before introducing wider app control or external data egress.
3. **Real two-window study on one supported platform:** choose a single OS/desktop combination and two synthetic editor windows or two text editors; define exact target identity, focus handling, editable field confirmation, failure reporting, and return-on-ambiguous behavior.
4. **Real app integration test:** keep readback/verification honest; preserve regular dictation and its fallback. No blind focus-switch-then-paste implementation without race and permission evidence.
5. **Separate provider study:** no networked ChatGPT/Claude/Codex integration or arbitrary plugins until the provider-specific permission, identity, data egress and cost design passes ADR-019 review.
6. **Human accessibility and evaluation study:** voice-only cancel/confirm, false routing, target correctness, time/interaction effort, wrong-target side effects and cost-weighted errors measured against baseline.

**Release gate:** production wiring requires maintainer-reviewed architecture and platform-specific tests. Do not merge this experiment expecting a working universal voice interface, and do not mark it `agent-ready` for automatic execution.
