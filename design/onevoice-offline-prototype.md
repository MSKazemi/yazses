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


## Experimental X11 read-only feasibility probe (stacked follow-up)

**Status:** separate experiment on top of the fake-editor prototype. It is not the live two-editor insertion milestone, and **does not resolve** ADR-025 / ADR-022 or #600.

The follow-up module `src/yazses/onevoice/x11_probe.py` reads basic **X11 window identity only** for two window IDs the participant explicitly selects. It never enumerates an app's documents, reads field contents, changes focus, types, presses Enter, records audio, connects to a network, or launches a coding agent. The capability is deliberately limited:

| Signal | What the probe can conclude |
|---|---|
| Explicit X11 window ID | A known numeric window identifier was requested |
| X11-reported PID and WM_CLASS | The window reports consistent metadata at probe time |
| Repeat PID check | Some changes during observation can be detected |
| Optional repeat inspection | A prior window-ID/PID/class tuple still matches or is stale |
| Editable field, document, browser tab, account | **Unknown — not inspected; insertion forbidden** |

Window ID + PID + WM_CLASS does **not** reliably identify or authorize a text field. X11 metadata can be absent, stale or spoofed; even an unchanged window can have a different active editor. This experiment therefore always returns `field_verified=False` and has no action/execution method. It does not bridge the earlier `FakeEditor` router to real windows.

### Local human feasibility check (only on a Linux X11 session)

1. Open two unrelated editors with synthetic, non-sensitive documents.
2. Obtain each editor's numeric X11 window ID using the system's own window-inspection tool (for example `xwininfo` with an explicit manual selection; do not paste actual document text or window titles into an issue).
3. If `xdotool` is installed, run the **read-only** probe:

```sh
uv run python -m yazses.onevoice.x11_probe --window-a 0x00123456 --window-b 0x00234567
uv run python -m pytest tests/test_onevoice_x11_probe.py -q
```

The hexadecimal IDs above are **placeholders**; substitute two different IDs you selected. The commands have no network requirement. If either window cannot be identified, or when invoked on Wayland, they report an unavailable/unsupported status rather than guessing. A successful probe prints `window_observed_field_unverified` for A and B, followed by `routing_and_insertion_not_authorized`. Success only means two **window records** were observed, not that text could be delivered.

For privacy, the CLI intentionally prints neither window titles, process IDs, WM_CLASS strings, document contents, nor transcripts. Collect just each result state and locally observed platform/app class for the planned #600 human study. Do not upload screenshots, usernames, real IDs from private windows, or raw process listings. The prototype remains inert when not invoked.

### Verification and next unanswered question

- The follow-up probe has **35 local unit-test cases passing** using a synthetic command runner. Local bytecode compilation passed. Full upstream GitHub CI and real X11/AT-SPI field targeting are separate gates.
- Tests refuse unknown sessions, duplicate/invalid window IDs, absent `xdotool`, failures, PID changes, stale metadata and incomplete windows. They also assert that only property-read `xdotool` commands are issued.
- The next task is **semantic-field binding**, not pressing keys: inspect permissioned accessibility metadata and prove the exact editable role/field identity survives app focus changes. Reuse the existing `grounding/contracts.py` and related ADR-v2-151 work; do not invent another target vocabulary. Human platform measurements are required under #444 and #600.

**Shipping prohibition:** Never promote this window-only probe into a `draft_insert` adapter: it cannot verify an exact editor field, so it is insufficient to prevent wrong-target insertion.
