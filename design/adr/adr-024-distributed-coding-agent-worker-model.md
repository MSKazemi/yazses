# ADR-024 — Distributed coding-agent worker model

**Status:** Proposed (2026-09-22)
**Decider:** Mohsen Seyedkazemi Ardebili
**Extends:** [ADR-023 — Agent-first contribution pipeline](adr-023-agent-first-contribution-pipeline.md)
**Operational companion:** [campaign/agent-workers.md](../../campaign/agent-workers.md)
**Related policy:** [Using AI coding agents safely](../../docs/contribute/ai-agents.md) ·
[Third-party AI tools](../../THIRD_PARTY_AI_TOOLS.md)

---

## Context

ADR-023 established the important boundary: a coding agent removes typing time, not task-design
time. YazSes therefore advertises bounded task contracts through campaign/tasks.json and marks
a task cloud_agent_ready only when a container can produce the complete evidence.

That decision answers **which work is safe to hand to an agent**. It does not yet answer the
next scaling question:

> How can several contributors use their own cloud coding-agent accounts in parallel without
> giving those accounts write authority over the upstream YazSes repository, sharing API keys,
> bypassing review, or creating an unreviewable PR flood?

Google Jules makes this question concrete. Jules can connect to GitHub repositories, read an
AGENTS.md file, execute work in a cloud VM, and open pull requests. Its GitHub integration also
treats a case-insensitive issue label named jules as an execution trigger. Contributor-owned
provider accounts are controlled independently, so YazSes can scale execution without pooling
credentials or turning provider access into repository write authority.

The tempting design is therefore to add contributors as collaborators to MSKazemi/yazses and
let each connect a personal Jules account. That is the wrong trust boundary for this repository.

YazSes is currently owned by a personal GitHub account. A collaborator on a personal repository
has broad write capability. The current main ruleset deliberately blocks deletion and
force-push, but does not yet require a pull request, required status checks, or an approval.
Expanding upstream write access merely to let an agent run would therefore expand the blast
radius far beyond the task being delegated.

At the same time, the repository already has the pieces needed for a safer design:

- campaign/tasks.json is the task source of truth.
- cloud_agent_ready says whether a cloud agent can produce the complete evidence.
- allowed_paths bounds each advertised task.
- validation gives the command that decides whether the task is done.
- risk separates L0/L1/L2 work from maintainer-only L3 work.
- campaign-preflight checks a task PR against its declared scope and scans for personal data.
- campaign_queue.py records human claims and expires abandoned claims.
- AGENTS.md gives every coding agent the same project rules.
- REVIEWING.md preserves the human decisions that automation cannot make.

As of 2026-09-22, the generated campaign inventory reports 75 cloud-agent-ready tasks. That is
enough work to pilot a distributed model without inventing a second task system.

## Decision

YazSes adopts a **bring-your-own-agent, fork-first worker model** for distributed agent-assisted
development.

The project controls **task eligibility and merge authority**. A contributor controls **their
agent account, quota, credentials, fork, and execution session**.

The default path is:

~~~
campaign task
    |
eligibility gate
    |
human claim
    |
contributor account
    |
contributor agent
    |
contributor fork branch
    |
upstream pull request
    |
campaign preflight + CI
    |
human review
    |
merge
~~~

A project-controlled central agent executor is a separate, stricter mode and is not the default.

### 1. Task eligibility is project-owned and provider-neutral

The authoritative signal is campaign/tasks.json, not an issue label and not a provider-specific
feature.

A task is eligible for a cloud coding agent only when all of the following are true:

- state is open;
- cloud_agent_ready is true;
- risk is L0, L1, or L2;
- allowed_paths is non-empty;
- validation is non-empty;
- the task does not require hardware observation, native-language judgement, participant data,
  private evidence, credentials, or a maintainer-only decision.

A task that fails any of those checks is not made executable by adding a label.

Provider names such as Jules, Codex, Claude, or Gemini are execution choices, not task-readiness
states.

### 2. Distributed contributors use their own fork

A contributor who wants to use a cloud coding agent:

1. forks MSKazemi/yazses;
2. connects the agent to that fork rather than requesting upstream write access;
3. claims one eligible task using the existing campaign claim convention;
4. lets the agent work on a branch in the contributor's fork;
5. reviews the complete diff;
6. runs the task validation and required project gates;
7. opens a normal pull request to MSKazemi/yazses:main.

No contributor is granted upstream collaborator access merely to enable an agent.

The contributor remains responsible for every changed line and for the pull request.

### 3. Credentials never become project configuration

A contributor's Jules API key, Google account, Codex token, Claude credential, or equivalent
belongs to that contributor.

It must not be:

- added to YazSes repository secrets;
- pasted into issues or pull requests;
- stored in campaign/tasks.json;
- collected by a YazSes workflow;
- proxied through a maintainer-owned service.

This keeps worker identity and billing/quota responsibility with the person who chose the
provider. The canonical billing/responsibility rules remain THIRD_PARTY_AI_TOOLS.md; this ADR
does not create reimbursement, spending authority, or a requirement to use a paid agent.

### 4. Public issue text is not automatically executable authority

Public issue text and comments are untrusted input. Applying an execution trigger to an
arbitrary user-authored issue would turn prose from an untrusted boundary into instructions for
a privileged external worker.

A central executor may act only from one of two reviewed contract sources:

1. a campaign task whose authoritative scope comes from `campaign/tasks.json`; or
2. a **trusted structured issue** that was authored or explicitly approved by a maintainer,
   has the required scope/acceptance/validation fields, and passed the read-only pre-trigger
   eligibility check.

For a campaign-backed task, the manifest wins over issue prose for allowed paths, validation,
risk, and cloud readiness. For a trusted structured issue, the issue body is the reviewed
contract, but later public comments remain context only and cannot silently widen that contract.

In both cases the agent must receive the same minimum contract:

- task/issue identifier;
- goal/value;
- allowed or expected paths/seams;
- acceptance criteria or evidence requirements;
- validation commands;
- AGENTS.md;
- explicit escalation boundaries.

Issue discussion may be linked as background, but it cannot weaken validation, authorize
credentials, override a non-negotiable rule, or expand scope without a human revising and
re-approving the execution contract.

This preserves the useful built-in Jules issue-label workflow without treating every public
issue as safe executable input.

### 5. Readiness and execution use different signals

The exact GitHub label `jules` has provider-defined executable semantics when the Jules GitHub
App is connected to a repository. It is therefore **not** a generic readiness label.

Reuse the repository's existing provider-neutral readiness signals:

- `cloud_agent_ready` in `campaign/tasks.json` means the complete campaign task can be
  produced and evidenced in a cloud/container environment;
- `agent-ready` on a structured GitHub issue means the issue has cleared its design/scope
  gate and may be evaluated by the pre-trigger checker.

Neither starts work.

The literal `jules` label is an **execution action** and is reserved for a future
maintainer-controlled upstream Jules executor. It may only be applied after the issue/task
passes the safeguards below.

If operational status labels are added later, they must not duplicate these two readiness
sources or acquire provider-defined execution semantics.

### 6. Human review remains mandatory

The acceptance pipeline is:

~~~
agent output
  -> contributor review
  -> task validation
  -> upstream PR
  -> campaign preflight
  -> full CI
  -> human review
  -> merge
~~~

Green CI is evidence that machine-checkable invariants passed. It is not approval.

There is no agent-to-auto-merge path.

Machines may not decide:

- whether a translation reads naturally;
- whether hardware behaved as claimed;
- whether a research conclusion is warranted;
- whether an architectural change is desirable;
- whether privacy posture should change;
- whether an L3 escalation is acceptable.

Those boundaries remain the ones in ADR-023 and REVIEWING.md.

### 7. Agent authorship and agent disclosure are different things

The human contributor is the author/accountable submitter.

An automated assistant must not be credited as a human author, co-author, project contributor,
or commit co-author. In particular, agent-generated Co-Authored-By trailers are not used.

The pull request may state which tool assisted the work and what the human verified. That is
tooling disclosure, not authorship.

Provider-generated platform metadata that cannot reasonably be suppressed is not treated as a
project attribution statement.

### 8. Backpressure is part of safety

The limiting resource is human review, not agent compute.

The worker system must stop advertising or launching more agent work before review capacity is
exhausted.

Pilot thresholds:

- at most one active agent task per new participant;
- pause new agent claims when 8 agent-assisted PRs are waiting on a human;
- keep the existing project-wide REVIEWING.md stop condition of more than 25 PRs waiting on a
  human;
- L0/L1 claims expire after 48 hours and L2 claims after seven days, using the existing claim
  ledger.

The first number is intentionally below the project-wide threshold. An agent programme should
not consume the entire review budget.

### 9. Central upstream execution has additional prerequisites

A maintainer-controlled Jules or other cloud executor may be added later, but not by reusing the
fork model's trust assumptions.

Before an agent is allowed to create branches directly in MSKazemi/yazses, all of these must be
true:

1. main requires pull requests rather than accepting ordinary direct contributor pushes;
2. a stable aggregate required check exists and is required by the ruleset;
3. the central trigger is limited to trusted contract sources and the actor applying the
   execution label is authorized to do so;
4. the execution contract comes from `campaign/tasks.json` or a maintainer-approved structured
   issue that has passed the read-only pre-trigger check — never an arbitrary public issue body
   or comment stream;
5. the executor receives no release/signing/private-data credentials;
6. it cannot auto-merge;
7. literal jules is documented as an executable label;
8. emergency disable instructions are written and tested.

A central executor is an automation account, not an additional maintainer.

### 10. L3 and sensitive surfaces always escalate

Even a well-bounded task must stop rather than proceed automatically when the requested change
touches or requires:

- network egress, telemetry, analytics, crash reporting, or cloud fallback;
- microphone permission policy or ambient capture;
- shell execution or command interpolation;
- base dependency additions or lockfile-policy exceptions;
- IPC, public contracts, or accepted ADR semantics;
- default enabled/disabled state;
- release workflows, signing, publishing, package-manager credentials, or repository secrets;
- private trees, participant data, voice samples, or unpublished study data.

This list is a minimum. AGENTS.md and later ADRs may make the boundary stricter.

## Trust boundaries

| Boundary | Trusted for | Not trusted for |
|---|---|---|
| campaign/tasks.json on the target base branch | scope, eligibility, validation contract | proof that the implementation is good |
| AGENTS.md on the target base branch | project invariants and agent rules | merge approval |
| contributor fork | producing a candidate diff | upstream write authority |
| contributor agent account | executing the contributor's chosen task | project secrets or maintainer identity |
| arbitrary public issues/comments | discussion and links | executable instructions |
| maintainer-approved structured issue | reviewed issue-level execution contract | permission to bypass AGENTS/CI/review |
| GitHub CI on a PR | machine-checkable evidence | product/design judgement |
| human reviewer | acceptance decision inside governance | bypassing non-negotiable ADR boundaries |

## Jules provider mapping

Jules is a supported provider for the fork-first model when a contributor chooses it.

Current official references:

- Documentation: https://jules.google/docs
- CLI examples: https://jules.google/docs/cli/examples
- API reference: https://jules.google/docs/api/reference/
- Usage limits: https://jules.google/docs/usage-limits
- GitHub label trigger announcement:
  https://jules.google/docs/changelog/2025-06-26/

Provider behaviour can change, so campaign eligibility must never depend on a Jules-specific
quota, plan name, or UI feature.

For the contributor path, Jules should be connected to the contributor's fork only. If Jules
offers an authorship mode, use a mode that keeps the human contributor as commit author where
possible.

## Operational metrics

The pilot is successful only if it reduces maintainer work per useful merged contribution.

Measure, using public repository metadata only:

- eligible tasks claimed;
- claim-to-PR conversion;
- median claim-to-PR time;
- first-pass campaign-preflight success;
- first-pass CI success;
- percentage of PRs requiring scope correction;
- median human review minutes by risk lane;
- abandoned claims;
- duplicate work;
- merged PRs per participant;
- rollback/revert rate after merge.

Do not collect provider credentials, private prompts, private repository data, user speech, or
billing information.

A provider's cost and quota remain the contributor's responsibility; project documentation may
link to the provider's current pricing/limit pages but must not promise a price or quota.

## Rollout

### Phase 0 — documentation and policy

- adopt this ADR;
- publish campaign/agent-workers.md;
- link the worker model from the existing safe-agent documentation;
- keep AGENTS.md and THIRD_PARTY_AI_TOOLS.md canonical for authorship, data, permission, and
  billing rules;
- keep the central executor disabled.

### Phase 1 — fork-first pilot

- 3–5 contributors;
- L0/L1 cloud-agent-ready tasks only;
- one active task per contributor;
- no automatic PR before the contributor has reviewed the diff;
- collect the operational metrics above.

Exit criteria:

- at least 10 merged agent-assisted PRs;
- no secret/privacy incident;
- no merged scope violation;
- median review cost no worse than comparable non-agent work;
- no sustained review queue above the agent backpressure threshold.

### Phase 2 — bounded expansion

- allow proven participants to take L2 cloud-agent-ready tasks;
- allow at most two concurrent tasks for participants with a clean history;
- add provider-specific helper documentation only where it does not duplicate AGENTS.md.

### Phase 3 — optional central executor

Only after the central-execution prerequisites in this ADR are enforced.

## Failure and incident response

If an agent PR goes out of scope:

- do not merge it;
- ask for the smallest in-scope correction or close it;
- inspect whether the task contract was ambiguous;
- fix the contract if the task caused the failure.

If an agent exposes a secret or personal data:

- follow campaign/incident-response.md and SECURITY.md;
- rotate/revoke the secret where applicable;
- remove public exposure through the appropriate GitHub process;
- suspend the relevant execution path until the cause is understood.

If the agent repeatedly ignores allowed_paths or validation:

- record the task/provider path as blocked in the tracker or issue;
- do not weaken the validation to make the agent pass.

If review capacity is exceeded:

- stop new agent claims first;
- finish or return existing claims to the pool;
- do not auto-merge to clear the queue.

## Consequences

**Good.** Parallel agent capacity scales with contributors without distributing upstream write
authority or pooling secrets.

**Good.** The existing campaign schema remains the single source of truth. Jules, Codex, Claude,
or another provider can be swapped without redefining what counts as safe work.

**Good.** A compromised or misconfigured contributor agent is normally contained to that
contributor's fork until a human-reviewed PR crosses the boundary.

**Accepted cost.** Contributors must create a fork and connect their own provider. This is one
extra setup step compared with direct upstream write access, but it buys a much smaller trust
surface.

**Accepted cost.** Human review remains the throughput limit. The project explicitly chooses
reviewable useful work over maximum agent task count.

## Rejected alternatives

### Add every agent user as an upstream collaborator

Rejected. It grants repository write capability for the sake of a tool integration and couples
agent access to GitHub trust.

### Treat the jules label as the generic agent-ready marker

Rejected. The literal label can be executable provider input. Readiness and execution must be
separate states.

### Store contributors' agent API keys in YazSes

Rejected. It mixes identity, billing, quota, and secret custody across trust domains.

### Auto-run every issue labelled good first issue

Rejected. A friendly issue is not necessarily bounded, cloud-reproducible, or safe for an
autonomous agent.

### Auto-merge when CI is green

Rejected. CI cannot decide usefulness, architecture, truth of observed evidence, or governance.

### Build a central scheduler before trying forks

Rejected. The repository already has a claim ledger and a provider-neutral task manifest. A
central secret-bearing service would add operational risk before there is evidence it is needed.
