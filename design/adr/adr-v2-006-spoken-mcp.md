# ADR-v2-006 — Voice-to-Tool (offline Spoken MCP)

**Status:** Accepted (2026-07-02) · Wave B
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v04-001-slm-inference]] (SLM tier), [[adr-011]] (offline)

## Context

MCP became the industry-standard agent tool interface in ~12 months (Anthropic Nov
2024 → OpenAI, Google DeepMind → Linux Foundation), but every MCP host today is
chat/keyboard-driven and usually cloud-adjacent (internal).
A hold-to-talk, fully-offline MCP client does not exist. llama.cpp GBNF grammars make a
3–4B local model emit schema-valid tool JSON deterministically; OSWorld-Human shows
long-horizon agents collapse past ~50 steps, so the safe niche is short, verifiable,
human-confirmed actions.

## Decision

Add an opt-in **Voice-to-Tool** path: speak an intent → local SLM emits a GBNF-constrained
tool call → executed against **local** MCP servers (files, git, editor, calendar) over
stdio. Governed by the human-in-the-loop invariant:
- Any side-effecting tool call is spoken/overlaid back and executed only on confirmation
  ("I'll create a branch and commit — say 'go'"); read-only tools may auto-run.
- Strict per-tool **allowlist**; no network tools by default; nothing leaves the machine.

Config: `[agent] enabled=false`, `model_path`, `servers` (list of local MCP stdio commands),
`allowlist`, `confirm=all|writes|none` (default `writes`). New package `agent/` (planner +
MCP client + confirm loop); reuses SLMRouter, TTS read-back, overlay.

## Consequences

- **+** A genuinely novel offline voice agent; rides the MCP standard; reuses SLM + TTS + overlay.
- **+** Confirmation loop turns existing components into an agent safety mechanism.
- **−** Tool-call hallucination/misfire → mandatory confirm for writes + allowlist + read-only
  default; keep actions to 1–5 steps.
- **−** Optional heavy dep (local LLM) → dependency-isolated behind an extra; default off; refuse
  `features enable` without `--force` (experimental until proven).
