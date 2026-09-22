# ADR-024 — Remote coding agents use the existing task contract; tool identity is not authorship

**Status:** Accepted (2026-09-22)  
**Deciders:** Mohsen Seyedkazemi Ardebili  
**Context links:** [ADR-023](adr-023-agent-first-contribution-pipeline.md),
[`AGENTS.md`](../../AGENTS.md), [`.github/CONTRIBUTING.md`](../../.github/CONTRIBUTING.md),
[`docs/contribute/jules.md`](../../docs/contribute/jules.md)

## Context

ADR-023 established the agent-first contribution pipeline: design the work as a bounded,
verifiable contract first, then let a human or coding agent implement it.

The repository now needs to support **remote coding agents** that connect to GitHub and can
create branches or pull requests themselves. Google Jules is the first concrete integration,
but the policy must not become Jules-specific.

Two ambiguities need a durable decision:

1. a remote agent can have repository access through a GitHub App without being a human
   collaborator, so **tool execution access and contributor permissions are different things**;
2. older contributor prose asked people to mention AI assistance in a pull request, while the
   canonical `AGENTS.md` now says automated tools must not be credited as authors, co-authors,
   contributors or generators. Remote tools can also default to their own commit identity,
   which would violate the current repository rule.

The repository also needs to distinguish a label meaning "this issue is suitable for an agent"
from a label that **actually triggers external execution**.

## Decision

### 1. `AGENTS.md` remains the one canonical tool contract

Do not create `JULES.md`, `CODEX.md`, or another tool-specific instruction file.

Any remote coding agent must consume the same:

- repository invariants;
- setup and validation commands;
- generated-file rules;
- platform seams;
- privacy/egress constraints;
- contribution scope rules.

Tool-specific docs may explain **connection mechanics only**. They do not redefine coding policy.

### 2. Agent readiness and agent execution are separate states

`agent-ready` means:

> the issue is implementation-ready: scope, integration seam, acceptance criteria, tests,
> blockers and definition of done are sufficiently explicit that implementation should not
> require a new design decision.

An external execution label such as `jules` means:

> start work in a particular external service.

Therefore:

- `agent-ready` is classification;
- `jules` is an execution trigger;
- `jules` must never be mass-applied by task-generation automation;
- blockers must be cleared before a trigger label is applied;
- applying an execution label remains a deliberate human action.

### 3. Remote agents do not require contributor write access

For the upstream repository, the repository owner/administrator installs the external GitHub App
and grants it access to the selected repository.

Do **not** add a human as an upstream collaborator merely so their coding agent can work.

An outside contributor should normally:

1. fork the public repository;
2. authorize the coding agent for their own fork;
3. implement the bounded upstream issue;
4. submit a normal pull request.

This preserves the open-source least-privilege model.

### 4. The human contributor owns authorship and review responsibility

The project credits **people**, not coding tools.

Where a remote agent supports commit-authoring configuration, select the mode that attributes commits
to the human user only. For Jules that is the `User only` commit-authoring mode.

Do not add:

- tool accounts as co-authors;
- `Co-Authored-By` trailers for an automated assistant;
- "generated with ..." footers;
- AI-tool credit in the PR body, issue or release notes.

This supersedes the **AI-attribution wording only** in ADR-023's sample prompt and any older
contributor prose. ADR-023's task-design, scope, validation and human-responsibility decisions remain
fully in force.

### 5. Cloud-ready means evidence can be produced in the cloud

A task may be remotely executed end-to-end only when all evidence required for completion is
available in the agent environment.

The existing `cloud_agent_ready` concept remains authoritative:

- pure code, docs, deterministic tests and fake-adapter work can be cloud-ready;
- real microphone/camera/device behavior is not;
- native-language naturalness is not;
- accessibility comfort/fatigue evidence is not;
- architectural approval is not.

A remote agent may implement supporting code for those tasks, but it must not manufacture the
missing human/device evidence.

### 6. No automatic merge based only on agent + CI success

An agent-produced pull request receives the same review as any other contribution.

Green CI proves the machine-checkable contract only. It does not prove:

- architecture is appropriate;
- a hardware claim is true;
- a user interaction is usable;
- a privacy-sensitive change is acceptable.

The existing risk/review lanes continue to govern merge authority.

### 7. Credentials remain outside the repository

GitHub App installation, OAuth authorization, API keys and service account credentials are
configuration, not source code.

Never commit remote-agent API keys. In particular, `JULES_API_KEY` belongs in the caller's secret
store/environment, not in YazSes files or GitHub issue text.

## Consequences

### Positive

- one agent contract works for local and remote tools;
- external contributors can use remote coding agents without receiving upstream write access;
- issue-trigger labels cannot be confused with readiness labels;
- automated coding scales while design/evidence gates stay human-owned;
- commit history credits contributors consistently with the repository's current authorship rule.

### Cost

- maintainers must deliberately install/configure GitHub Apps;
- maintainers must deliberately trigger upstream issue automation;
- contributors using forks perform the normal fork/PR step;
- tasks needing real-world evidence cannot be fully delegated even when the code is agent-friendly.

## Jules mapping

Jules is the first implementation of this decision:

| ADR concept | Jules mechanism |
|---|---|
| canonical instructions | root `AGENTS.md`, automatically read by Jules |
| repository access | Google Labs Jules GitHub App |
| least privilege | select only `MSKazemi/yazses` |
| cloud environment | short-lived Ubuntu VM + repo setup |
| human authorship | Jules Settings → Commit Authoring → `User only` |
| readiness | `agent-ready` |
| execution trigger | `jules` issue label |
| outside contributor | Jules on contributor fork → normal upstream PR |
| secret API access | `JULES_API_KEY` outside repository |

Connection/runbook details live in [`docs/contribute/jules.md`](../../docs/contribute/jules.md)
so fast-changing vendor UI instructions do not need to be frozen into this ADR.

## What would supersede this decision

A later ADR is needed if YazSes changes any of these policies:

- automated tools become recognized project authors/contributors;
- remote agents receive standing merge authority;
- upstream write access becomes a prerequisite for external agent-assisted contribution;
- external execution can be triggered automatically from all `agent-ready` tasks;
- hardware/human evidence is allowed to be inferred rather than observed.

Until then, remote agents are **implementers inside the existing human-owned contribution
pipeline**, not a second governance system.
