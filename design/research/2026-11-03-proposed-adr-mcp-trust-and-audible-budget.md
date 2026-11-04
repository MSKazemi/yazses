# ADR candidate — MCP output is a client disclosure; audible interruptions need a daemon-scoped budget

**Status:** **Proposed**, **not accepted** (2026-11-03). Research-only; this is **not** an implementation order or an approved API change.  
**Tracking:** [#803](https://github.com/MSKazemi/yazses/issues/803), parent [#788](https://github.com/MSKazemi/yazses/issues/788)  
**Context:** [ADR-011](../adr/adr-011.md), [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md), [ADR-020](../adr/adr-020-agent-protocols.md), [ADR-021](../adr/adr-021-invest-in-error-cost.md), [ADR-030](../adr/adr-030-agent-era-direction.md), [ADR-031](../adr/adr-031-send-to-prefill-handoff.md), [ADR-032](../adr/adr-032-mcp-discoverability.md)  
**Evidence / test plan:** [code and threat audit](2026-11-03-agent-mcp-trust-boundary-audit.md); [replay spec](../specs/agent-mcp-trust-replay-protocol.md).

This is housed in `design/research/` to respect ADR-030's breadth freeze. No numbered ADR is allocated. Acceptance, amendment to ADR-020, or supersession requires a maintainer decision on a reviewed change.

## Decision problem

The existing design says YazSes remains the offline microphone; its MCP bridge offers exactly `transcribe(path)` and, opt-in, `ask_human(question, timeout)` on stdio only. However, **"YazSes did not make a network request"** and **"the words stay within the user's machine"** are not the same claim. MCP responses are delivered to a different application, which may send them to a model or a service.

A more urgent correctness discrepancy: the daemon builds a new `AskHumanService` for *every* `ask_human` IPC call; that service constructs a new sliding-hour `InterruptBudget`. Existing budget unit tests exercise one budget instance and do not test multiple IPC calls. Additionally, an audible question with an empty answer is not charged. Both challenge ADR-020's condition that agents cannot bypass the interruption cap.

This proposal clarifies the trust boundary and the charging semantics without expanding YazSes into an agent.

## Proposed decisions (all pending)

### D1 — Trust ends at the chosen destination

YazSes controls on-device transcription and local injection. A `transcribe` tool result or an `ask_human` answer is **disclosed to the MCP host** when written to stdout/IPC; text typed into an agent window is **disclosed to that application**; a `sendto` URL is **disclosed to the local scheme handler**, and may additionally appear in local process arguments. Whether the recipient subsequently stores/transmits text is governed by the recipient and its own permissions, outside YazSes's guarantee.

Retain "no cloud transcription" and "YazSes itself does not send" where proven; prohibit blanket claims that *all connected agent interactions remain private/offline*. Documentation must state that an online MCP host or AI application may transmit the transcript, despite YazSes decoding locally.

### D2 — Single daemon-owned interruption budget

For `ask_human`, the budget is a daemon-lifetime, **shared**, concurrency-safe object. Creating a new service/IPC request/MCP child/client/label does **not** reset it. An agent must not multiply the quota by spawning another stdio server, using another client name, retrying after no answer, or racing concurrent requests.

If the daemon truly restarts, the in-memory budget will reset under the existing no-persistent-history design; do not promise a cross-restart quota until a separate persistence/privacy decision is made. A process-independent, hourly persistent quota is explicitly **not** part of this proposal.

`ask_human_per_hour = 0` remains a complete refusal; `[mcp] ask_human=false` remains not offered; active hold deferral stays free (because no question is spoken).

### D3 — Count attempts that may be audible, not successful answers

The scarce resource is the person's attention, **not the tool's success rate**. The quota should be reserved atomically **before** a question can be spoken. A question for which TTS may have emitted audio consumes the slot **regardless of whether the person answers**. If the caller is refused by opt-in, active hold or budget before any audio is played, it consumes nothing. A proven pre-output failure can release a reservation; when the adapter cannot prove that no audio was played, do **not** refund on an exception or timeout.

This is a proposed choice requiring maintainer confirmation: charging calls that made no sound without reliable playback signals may be annoying; the safer first implementation is a clear "attempted audible interrupt" cap. Later integration may expose a verified playback-start/completed signal, but no new device API is required merely to articulate the policy.

The check/reserve operation must be atomic across concurrently arriving IPC calls; `allow` followed later by `record` without a lock is not an invariant.

### D4 — Source attribution must not be invented

The existing MCP adapter supplies `caller="mcp"`, not a verified desktop application identity. The spoken label may honestly say "an MCP client asks" but must not fabricate "Claude Code asks" or attribute authorization to a particular app. A future authenticated identity contract is a separate design and must not simply accept a client-provided string as proof. The rate cap applies across all callers anyway.

### D5 — Tool output and errors are untrusted data

`transcribe` outputs, `ask_human` answers, and arbitrary agent-supplied questions may contain natural-language instructions. YazSes must not execute their words as commands inside this MCP path; the host must mark them as untrusted tool data and require host-side approval for privileged actions. No speculative "prompt injection scrubber" may silently rewrite the user's words.

Tool errors should not include uncontrolled exception messages, raw paths or transcript snippets once a separately reviewed code change establishes a safe public error vocabulary. A negative test using a fake error containing a synthetic marker must fail if that marker reaches the result. Before changing an existing error format, review compatibility because clients may expect details.

### D6 — Keep ADR-019's local transport and ADR-031's closed handoff

No HTTP listener, remote MCP, web URL fallback, configurable destination, implicit Enter, automatic cloud send, telemetry, or new runtime dependency. Keep the two-tool limit. Real-client verification of the custom scheme and MCP version compatibility remain separate issues [#800](https://github.com/MSKazemi/yazses/issues/800) and [#801](https://github.com/MSKazemi/yazses/issues/801). An MCP protocol version upgrade is not a prerequisite to fixing a budget's object lifetime.

## Alternatives and why not

| Alternative | Disposition | Reason |
|---|---|---|
| Keep each `AskHumanService`'s own budget | **Reject** | Every IPC request can create a fresh budget; defeats the shared hourly cap. |
| Charge only when a person answers | **Reject for attention protection** | A repeatedly unanswered voice question still interrupts. |
| Persist a permanent counter to disk | **Defer** | Adds user-behavior storage, privacy and restart semantics without evidence it is needed. |
| Use caller-provided name to segment budget | **Reject** | Spoofable names and multiple hosts amplify interruptions; opposite of protecting the person. |
| Automatically inspect/delete "malicious" instructions from transcripts | **Reject** | Changes dictation fidelity and cannot provide a robust security boundary; host owns authorization. |
| Prevent any stdio result until every caller gains a new per-file token | **Defer** | Potentially safer for untrusted hosts but breaks established `transcribe` behavior; needs UX and legitimate-client evidence. |
| Move MCP to HTTP/OAuth for stronger security | **Reject in this scope** | Violates accepted ADR-020's local-only architecture; more reachable surface with no demonstrated benefit. |
| Say "stdio is local; therefore nothing can leave" | **Reject** | The client receives text and can take independent action. |

## Consequences / compatibility

**Benefits if adopted:** transparent privacy promise; a budget enforceable across actual daemon requests; protection even from no-answer floods; no new network transport; a deterministic specification for a bounded bug fix.

**Costs:** possible extra rejected `ask_human` requests under stricter accounting; shared reservation and concurrency correctness must be reviewed; increased documentation specificity. An agent calling over an existing MCP host may already have its own permissions; YazSes cannot infer the host's policy from the transport.

**Failure behavior:** budget exhaustion yields the existing refusal shape (`retry_after_s`/`deferred` as applicable); no speaking while held; no user answer typed into the editor; no new logs that include text. A closed/stale daemon restarts the in-memory budget, which remains an explicit limitation.

## Acceptance criteria for a separately authorized bug fix

- A **daemon-level** test with `max_per_hour=1` sends two sequential successful IPC calls through *different* service constructions and gets **one** audible question, second refused. This must expose the current defect before remediation.
- One unanswered but spoken question exhausts a one-question budget; hold deferral and proven TTS-unavailable path consume no audible slot.
- Two simultaneous permitted calls with remaining capacity one cannot both speak; failure/refund is conservative on uncertain side effects.
- A second MCP child/client does not bypass a still-running daemon's shared counter; no text is injected into focused applications.
- The test harness runs offline with fakes and synthetic strings; existing tests for budget, MCP tool listing, daemon, no-egress and no-log-content remain green; `ruff` and `mypy` follow repository policy. **No test execution is claimed here.**

## Scope / decision gates

This candidate can be promoted only after human review under [AGENTS.md](../../AGENTS.md) and ADR-030. A safety bug fix may be delivered under an existing approved pillar after a bounded delivery issue is assigned an appropriate milestone. Creating this document does not turn the evergreen parent into a release milestone or lift the breadth freeze.

**No tests, experiments, live MCP clients or recordings were executed to validate this proposal.** The two budget findings are source-level observations with explicit regression gates, not claims about a measured attack.
