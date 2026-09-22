# ADR-023 — Agent-first contribution pipeline: the design behind `campaign/`

**Status:** Accepted (2026-08 design, in force)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [`campaign/README.md`](../../campaign/README.md) (the mechanics this
ADR explains the reasoning for), [`AGENTS.md`](../../AGENTS.md), [`.github/CONTRIBUTING.md`](../../.github/CONTRIBUTING.md)
("Using an AI coding assistant"), [[adr-021-invest-in-error-cost]] (the same "L3 is never
advertised" boundary, applied to code review rather than contribution risk)

---

## Context

Most first-time open-source contributions fail for the same reason regardless of the
contributor's skill: the task was never actually bounded. "Fix a bug", "add a feature",
even a labelled `good first issue` usually still requires the maintainer's tacit knowledge
of which files matter, what "done" looks like, and how long it should take — knowledge a
newcomer doesn't have and a coding agent can't infer reliably either.

A coding agent (Claude Code, Codex, Copilot, Gemini CLI, …) removes *typing time*, not
*task-design time*. Handed an unbounded prompt, it produces an unbounded diff — more code
to review, not less. So the question this ADR answers is not "should contributors use AI
assistants" (`.github/CONTRIBUTING.md` already says yes, and that a human remains the
author) but: **what has to be true of a task before handing it to a human-plus-agent pair
is a net win for the maintainer, not a new source of review burden?**

## Decision

Keep one canonical repository instruction source, `AGENTS.md`. Where a major tool uses a
different auto-discovery filename, ship only a thin adapter that imports the canonical file
(for example `CLAUDE.md` → `AGENTS.md` and `GEMINI.md` → `AGENTS.md`). A tool adapter may
not copy setup commands, policy, or architecture rules: duplicated agent instructions are
treated as configuration drift.

Structure every advertised contribution — human-only or agent-assisted — as a **bounded
contract**, not a prompt: the objective is that a contributor can pick a task, hand it to
an agent, inspect the diff, run one validation command, and open a correct PR in 10–30
minutes, with the agent held to the same non-negotiables as a human (no unsolicited
dependencies, no network calls, no default-on features — the same list `AGENTS.md`
already states).

### A task is only ready to advertise once it has five properties

1. **Independent** — two contributors never need to edit the same lines.
2. **Useful** — the output changes a product, decision, test, compatibility claim, or user
   path. Not a typo fix or a name-list edit; those don't scale as a strategy.
3. **Bounded** — finishable in one sitting.
4. **Verifiable** — a schema, test, reproducible command, or a qualified human reviewer can
   decide pass/fail without re-deriving the task from scratch.
5. **Low-review-cost** — evidence sits beside the claim, and the task declares which paths
   are off-limits so an unrelated edit is a rejection, not a judgment call.

`campaign/tasks.json`'s validator enforces this directly: a task with no stated value, no
bounded paths, no validation command, or an estimate longer than one sitting is refused at
generation time, not at review time.

### The agent contract block

Every advertised task carries a fixed-shape block, generated from its manifest entry
rather than freehand:

```md
## Agent contract

Task ID: COMPAT-GNOME47-WAYLAND-001
Risk: L0 — schema-only
Expected time: 15–25 minutes
Cloud agent: No; real desktop evidence required
Cost: No paid service required; no authority to enable overages or incur project expenses

Read first:
- AGENTS.md
- CONTRIBUTING.md
- docs/compatibility/SCHEMA.md

Allowed paths:
- compatibility/reports/**

Do not change:
- src/**
- pyproject.toml
- uv.lock
- generated contributor files

Acceptance criteria:
- Record passes the compatibility schema.
- Commands and observed results are included.
- No username, home path, hostname, audio, or other personal data is committed.

Validation:
uv run python scripts/check-compatibility.py --file <new-file>
```

The paths and commands are read from the task manifest, never guessed by an LLM — a
generated instruction is only trustworthy if nothing between the source of truth and the
contributor's screen was free to improvise.

### A prompt a contributor can hand to any agent unmodified

```text
You are helping me complete one YazSes contribution. I remain responsible for the PR.

1. Read AGENTS.md, CONTRIBUTING.md, and the linked task completely.
2. Restate the acceptance criteria and identify the allowed file paths.
3. Inspect the relevant implementation and tests before changing anything.
4. Make the smallest change that satisfies the task; do not tidy unrelated code.
5. Do not add network calls, telemetry, cloud fallbacks, or an enabled-by-default feature.
6. Run the exact task validation command, then any required lint command.
7. Show me the complete diff and explain every changed line in plain language.
8. Stop if evidence requires hardware or native-language judgment I cannot personally provide.
9. Do not commit, push, or open a PR until I approve the diff.
10. Draft a PR description that states what changed, how it was validated, and any AI assistance.
```

It is deliberately tool-agnostic — the same ten steps work whether the contributor is
running Claude Code, Codex, Copilot, or Gemini CLI, because the constraints come from the
project (`AGENTS.md`), not from any one assistant.

### Readiness is a separate axis from review risk

`campaign/README.md`'s `L0`–`L3` lanes say **who reviews** a merged change. A second,
orthogonal axis says **whether a task is ready to publish at all**:

| Level | Definition | Advertised? |
|---|---|---|
| A0 — idea | Desired outcome, no pointers or validation | No |
| A1 — scoped | Files and acceptance criteria known | Only to experienced contributors |
| A2 — agent-ready | Allowed paths, relevant symbols, narrow validation, risks stated | Yes |
| A3 — cloud-ready | A2, plus a reproducible container environment and no hardware dependency | Yes, preferred |

Only A2/A3 tasks enter `tasks.json`'s `open` state. A hardware measurement or a
native-language translation review can never be marked A3 — no container substitutes for
a real microphone or a native speaker's judgment, and `cloud_agent_ready` is `false` for
every compatibility, measurement, and localization task for exactly this reason.

### What a machine may generate, and what it may never decide

An LLM may draft candidate task rows and acceptance criteria from real sources — open
issues, support questions, coverage gaps, the compatibility matrix, docs gaps. It may not
decide that a task is *useful*, that a translation *reads naturally*, or that hardware
behavior was *actually observed*. Each drafted family goes through the same sequence
before release:

1. Mine real sources (not synthetic ones).
2. Draft rows and acceptance criteria.
3. Deduplicate by affected surface and expected outcome.
4. A maintainer confirms value and scope.
5. Run a *negative test*: what fabricated or low-effort submission could technically pass?
6. Add validation that rejects that failure mode.
7. Complete one instance of the task internally with two different agents, to catch an
   ambiguity before a contributor does.
8. Mark it `verified`, then release in a small batch rather than all at once.

This is the source of `campaign/`'s "What a machine may and may not decide" boundary and
of `incident-response.md`'s governing bias — act on the contribution, not the person,
because an unclear task produces more bad-faith-looking submissions than bad faith does.

### Safety boundaries that don't relax for a bounded task

A task this well-specified can still touch something that must stay a human decision
regardless of how clean the diff looks. Escalate rather than auto-proceed when a change
touches: audio or text leaving the machine; telemetry, analytics, crash reporting, or a
cloud fallback; microphone permissions or ambient capture; command execution or shell
interpolation; a dependency addition or lockfile change; an IPC/public interface or an
accepted ADR; a default feature state; or release signing and packaging credentials. These
map directly onto the canonical top-level `AGENTS.md` — the same public instruction file
used for Claude Code, Codex, ChatGPT, Gemini, Cursor, and other assistants — so contributors'
agents and maintainers' agents are held to the same repository-visible boundaries.

## Consequences

**Good.** `campaign/tasks.json`, its schema, its risk lanes, and `incident-response.md`'s
bias already implement this design — this ADR is the rationale that was missing for why
they're shaped the way they are, not a plan to build something new. A future task family
can be checked against the same five properties and the same generation workflow instead
of re-deriving them.

**Accepted cost.** A well-bounded task takes longer to design than an unbounded GitHub
issue, and a family that stops producing useful information should be retired rather than
kept running out of habit — `campaign/README.md`'s weekly inventory review exists for that
reason.

**What this is not.** Not a claim that every task in `campaign/tasks.json` was designed
this rigorously in practice, and not a promise about contributor volume — those are
operational, measured in `campaign/generated/stats.json`, and belong there, not frozen
into an ADR that would go stale the day the numbers move.
