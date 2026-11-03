# Research specification: deterministic MCP and agent trust-boundary replay

**ID:** research-spec-agent-mcp-trust-v1  
**Status:** Proposed (2026-11-03), research and design only — not an implementation authorization.  
**Issue:** [#803](https://github.com/MSKazemi/yazses/issues/803), parent #788.  
**Evidence:** [source audit](../research/2026-11-03-agent-mcp-trust-boundary-audit.md) · [ADR candidate](../research/2026-11-03-proposed-adr-mcp-trust-and-audible-budget.md) · [synthetic fixtures](../research/fixtures/agent-mcp-trust-v1.jsonl).

## Goal

Define an **offline, deterministic and falsifiable oracle** for the two current MCP tools (`transcribe` and opt-in `ask_human`) and local `sendto`. It must catch the existing **per-request budget lifetime error** even when the pure `InterruptBudget` class passes isolated tests. It must separately catch **unanswered audible questions** that currently go uncharged. It must distinguish a YazSes direct transmission from a tool result delivered to a host that may later go online.

No real microphone, client, private data, external network connection, model, or prompt is needed.

## Fixture schema

One JSON object per line:

- `id`, `description`, `boundary` (interrupt / transcribe / tool_result / handoff / logging / identity / compatibility).
- `setup`: `enabled`, `limit`, `daemon_id`, `time_start_ms`, optional `source_policy`.
- `events`: list of objects with integer `t_ms` and `kind`; equal times retain list order.
- `expect`: asserted metrics and a note on baseline current behavior where the proposed invariant is not yet enforced.

Events: `ipc_ask` (request_id, client_ref, question), `tts_started`, `tts_failed_before_audio`, `tts_failed_indeterminate`, `listener_answer`, `listener_empty`, `hold_start`, `hold_end`, `daemon_restart`, `window_advance` (delta_ms), `transcribe_call` (synthetic path class), `tool_result` (synthetic text), `fake_backend_exception` (fake message), `custom_handoff` (target and synthetic text), `client_network_action`, `debug_log`, `export_report`, `mcp_client_name` (display_name, verified).

Expected metrics: `spoken_count`, `refused_count`, `deferred_count`, `returned_answers`, `client_disclosures`, `direct_yazses_network_sends`, `auto_submit_count`, `raw_sentinel_in_tool_error`, `raw_sentinel_in_export`, `verified_identity_claims`, `known_current_defect`. Each fixture asserts only applicable fields. No real file path, secret, log or uploaded transcript.

## Security invariants

**I1: One budget per running daemon.** Across different IPC requests, MCP child processes, and arbitrary caller labels, attempts that may have spoken within the configured sliding hour ≤ `max_per_hour`. A service object must not own the only quota state. A real daemon restart is a separate generation: current policy may reset an in-memory budget at restart; cross-restart persistence is out of scope.

**I2: Atomic budget admission.** Two requests racing with exactly one remaining slot cannot both reserve an audible question; admission and reservation happen under one synchronization policy. Never use a budget per caller as the sole safety gate.

**I3: Count attention, not answer rate.** A TTS question that may have been spoken consumes a slot even when the listener answers nothing, times out, or returns corrupted transcription. A refused request during a held key, a disabled feature or a provable failure before playback consumes no audible slot. An uncertain partial playback remains charged until proven silent.

**I4: No speaking during physical hold.** An active hold defers without audio, injection or quota consumption. The answer returned from `ask_human` reaches the MCP caller but never types into the focused window.

**I5: Truthful identity.** `caller="mcp"` is a generic transport label, not authentication. An unverified client-supplied string cannot be represented as a verified desktop app identity; the user is not told a specific agent asked unless identity can be established.

**I6: Correct disclosure accounting.** `transcribe(path)` does local recognition and returns text to the requesting MCP host; the host obtains the text (a disclosure even with no YazSes socket). If the host subsequently transmits it, classify that as **host-controlled egress**, not a direct YazSes network request. The tool itself does not call a cloud transcription endpoint.

**I7: Prompt injection remains data.** A synthetic media transcript saying "ignore the previous instructions" is passed as literal text; it cannot trigger a YazSes control-plane side effect. The receiving host is responsible for untrusted tool-output handling and approval before privileged actions. No heuristic filter in YazSes is required or assumed effective.

**I8: Error privacy.** A fake backend exception containing `SENTINEL_NOLOG` or a synthetic path must not be embedded verbatim in a *future redacted public error*; current `mcp/protocol.py` returns `str(exc)` and should be reported separately as a code-inspected unsafe edge until tested, not silently counted green.

**I9: Logs distinguish local DEBUG storage from export.** With DEBUG enabled, the local daemon log may contain transcripts (as documented); a shareable filtered report must not contain them. A synthetic marker in DEBUG output must never cross a simulated export boundary.

**I10: Handoff never automatically sends.** The allow-listed `claude://`/`codex://` local handlers, encoded query parameters, character/URL limits and absence of HTTPS fallback remain enforced. Actual client version/OS submission behavior is unknown and belongs to #800.

**I11: Compatibility is separate from transport security.** MCP protocol `2025-06-18` support in YazSes and newer `2026-07-28` lifecycle are distinct facts. No automatic upgrade, third tool, network listener or HTTP auth is introduced by this replay.

## Required fixture families

| ID | Scenario | Policy oracle |
|---|---|---|
| AG-001 | Three **separate IPC requests**, all answered, limit one | One spoken, two budget refusals |
| AG-002 | One TTS question played but user stays silent, then retry | Retry refused, even with empty first answer |
| AG-003 | TTS fails with proof it emitted no audio | Slot can be released |
| AG-004 | TTS fails after potential partial playback | Slot is charged |
| AG-005 | Agent asks during hold | Deferred, not spoken, not charged |
| AG-006 | Two clients race for one slot | At most one spoken |
| AG-007 | Three requests on one persistent service | Ordinary positive budget baseline |
| AG-008 | Daemon restart after exhausted budget | In-memory window lifetime explicit |
| AG-009 | Spoofed MCP caller label | No verified client identity claim |
| AG-010 | MCP transcribes synthetic local media | Tool content to host, no YazSes network request |
| AG-011 | Audio content contains malicious instructions as data | No control execution, faithful text only |
| AG-012 | Fake exception contains sentinel | Negative current protocol error-leak oracle |
| AG-013 | Handoff asked to open HTTPS | Refused; no opener |
| AG-014 | Custom URL with delimiters and non-Latin text | Exact single-parameter encoding |
| AG-015 | Local DEBUG transcript and shareable report | Marker removed from export |
| AG-016 | Host transmits a result later | Host egress distinct from YazSes |
| AG-017 | Spoken answer returned with editor focused | Only caller receives it; no injected text |
| AG-018 | Default disabled ask_human | Not offered, no TTS |
| AG-019 | Unusually long question | Resource-risk evidence, not an invented limit |
| AG-020 | Modern MCP host speaks new lifecycle | Compatibility warning, not automatic remote server |

Explicitly classify AG-001, AG-002 and AG-012 as **expected failing checks for the as-built policy**. An intentionally red diagnostic may be documented, but must not be silently committed as a failing normal-CI gate. Record separately the current behavior and the desired future oracle.

## Pure reducer model

```python
# Research pseudocode only, not a shipped implementation
def admit_ask(state, request):
    if not state.ask_enabled:
        return "refuse-off"
    if state.hold_active:
        return "defer-hold"
    with state.budget_lock:
        state.evict_expired_attempts()
        if state.attempts_in_window >= state.limit:
            return "refuse-budget"
        state.reserve(request.id)  # before any TTS can begin
    return "admit"

def settle_attempt(state, request_id, outcome):
    if outcome == "proved-no-audio":
        state.release_reservation(request_id)
    else:
        state.consume_reservation(request_id)
        # Includes no answer, timeout and unknown partial playback
```

The harness should be a dependency-free state reducer with injected clock, events and fake transport. A **daemon integration regression**, if later authorized, must actually invoke `Daemon._handle_ask_human` on the **same daemon object** multiple times. Testing two successive calls to `InterruptBudget.allow` on one manually constructed budget will **not** catch the current lifetime error.

For MCP result tests, use an injected `ToolSpec` and `mcp.protocol.handle` with synthetic output and a fake exception. For opener tests, reuse `tests/test_sendto_targets.py` and `tests/test_sendto_handoff.py` rather than duplicating existing controls. For concurrency, schedule with explicit barriers instead of sleeps.

## Acceptance metrics

- **0** quota overruns within the same live daemon; **0** cross-client quota resets; **0** unanswered audible questions outside quota.
- **0** concurrent admission overshoot; **0** playback while the hold is active.
- **0** verified-caller assertions from untrusted names; **0** answer injection into an editor.
- **0** new direct YazSes outbound network calls in replay; client/tool-result disclosure recorded as a distinct boundary.
- **0** automatic send/Enter; **0** sentinel text in a filtered diagnostic report or future public error.
- Every assertion reports denominators and whether it was checked in pure replay, daemon fake, or real client. Passing synthetic fixtures is **not** proof that a cloud AI client is safe.

**Proposed sequence:** R0 research documents and fixtures (this branch); R1 reviewed safety bug task with delivery milestone; R2 deterministic reproducer that fails on current daemon code; R3 minimal daemon-scoped quota fix and unit tests; R4 full offline tests/ruff/mypy; R5 client documentation and versioned validation under #800/#801. No production default changes are approved by this spec.

**No tests or live client experiments have been executed as part of this research-only spec.** Follow [AGENTS.md](../../AGENTS.md), [ADR-020](../adr/adr-020-agent-protocols.md) and [ADR-030](../adr/adr-030-agent-era-direction.md) for any later implementation decision.
