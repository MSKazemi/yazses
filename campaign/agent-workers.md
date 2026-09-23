# Cloud coding-agent workers

This page is the operational companion to
[ADR-024](../design/adr/adr-024-distributed-coding-agent-worker-model.md).

YazSes welcomes coding agents, including cloud agents, as execution tools. The project does
not turn those tools into repository maintainers. Task eligibility, review, and merge authority
stay with the project and its human reviewers.

This page is about **worker ownership, task routing, and review flow**. For account permissions,
data handling, billing, cost controls, and provider setup, the canonical guides are
[Using AI coding agents safely](../docs/contribute/ai-agents.md) and
[Third-party AI tools](../THIRD_PARTY_AI_TOOLS.md).

## The safe default

Use your own agent account against your own fork:

~~~text
YazSes task
   |
claim it
   |
your GitHub fork
   |
your coding agent
   |
you inspect the complete diff
   |
task validation + project gates
   |
pull request to MSKazemi/yazses
   |
CI + human review
   |
merge
~~~

You do **not** need upstream write access to use an agent on YazSes.

Do not ask to become a repository collaborator merely so Jules, Codex, Claude, or another
provider can work on a branch. A fork is the normal trust boundary.

## What work is suitable?

The source of truth is campaign/tasks.json.

A cloud agent may take a task only when the task is open and has cloud_agent_ready set to true.

That flag means a cloud/container environment can produce the complete evidence needed for the
task. It does **not** mean the task can bypass review.

Run:

~~~sh
uv run python scripts/check-task.py
~~~

to see the open inventory, then inspect the task before claiming it.

Do not reinterpret a task with cloud_agent_ready set to false as cloud-ready because an agent
says it can probably do it. Hardware observation, compatibility testing, measurement, and
native-language judgement are deliberately excluded where a container cannot provide the
evidence.

## Claim before starting

Use the existing campaign claim convention on the task's umbrella issue:

~~~text
claiming APP-014
~~~

or:

~~~text
I'll take APP-014
~~~

The claim ledger is read-only project tooling; it reads those comments and lets abandoned work
return to the pool.

| Risk | Claim lifetime |
|---|---:|
| L0 | 48 hours |
| L1 | 48 hours |
| L2 | 7 days |

A lapsed claim is not a judgement on the contributor. It only means someone else may take the
task. New participants should keep one active agent task at a time.

## Fork-first setup

### 1. Fork YazSes

Create a GitHub fork under your account and clone that fork. Keep the upstream remote as
read-only unless you already have project permissions for another reason.

Typical layout:

~~~text
origin   -> your-user/yazses
upstream -> MSKazemi/yazses
~~~

### 2. Connect your coding agent to your fork

Grant the provider access to the minimum repository set it needs. Prefer selecting only your
YazSes fork rather than granting broad GitHub account access.

Your provider account and quota are yours. YazSes does not collect or pool contributor
credentials. Follow the canonical safe-agent and third-party-tool policies linked above for
permissions, secrets, billing, data boundaries, and current provider documentation.

### 3. Give the agent the project contract

Every tool must read the root [AGENTS.md](../AGENTS.md).

For a campaign task, also give it the exact task ID. The task manifest, not a free-form issue
comment, defines the allowed paths and validation.

For a future upstream issue-triggered Jules run, the issue itself may be the execution contract
only after it is a maintainer-approved structured issue and passes the read-only pre-trigger
eligibility check. Public comments remain context, not authority to widen scope.

A safe provider-neutral prompt is:

~~~text
You are helping me complete one YazSes campaign task. I remain responsible for the PR.

1. Read AGENTS.md completely.
2. Read the campaign task for TASK-ID and restate:
   - the goal;
   - allowed paths;
   - forbidden/out-of-scope paths;
   - acceptance/evidence requirements;
   - validation command.
3. Inspect the existing implementation and tests before editing.
4. Make the smallest change that satisfies the task.
5. Do not add network calls, telemetry, cloud fallbacks, new credentials, or a default-on feature.
6. Do not change dependencies, lockfiles, release/signing configuration, accepted ADR semantics,
   public IPC/contracts, or repository permission workflows unless the task explicitly says so
   and a maintainer has approved that scope.
7. Run the task validation and the relevant project gates.
8. Show me the complete diff and explain the changed lines.
9. Stop if completion requires real hardware evidence, native-language judgement, participant
   data, private files, credentials, or a maintainer-only decision.
10. Do not open the upstream PR until I have reviewed the diff.
~~~

The human contributor reviews the output before submission.

## Jules

Jules is one supported provider for this model, not a special source of project authority.

Official Jules documentation:

- https://jules.google/docs
- https://jules.google/docs/cli/examples
- https://jules.google/docs/api/reference/
- https://jules.google/docs/usage-limits
- https://jules.google/docs/changelog/2025-06-26/

Connect Jules to **your fork** for the contributor workflow.

The GitHub integration uses the exact case-insensitive issue label named jules as an execution
trigger when configured. For that reason, YazSes does not use that label as a generic
agent-friendly marker.

If Jules offers an authorship mode, prefer a mode where you remain the commit author. Do not add
an agent as a human co-author or add generated Co-Authored-By trailers.

The pull request may disclose that Jules assisted and state what you verified personally. That is
tooling disclosure, not authorship.

## Readiness versus execution

Reuse the project's existing signals rather than creating a second label vocabulary:

| Signal | Meaning | Starts work? |
|---|---|---:|
| `cloud_agent_ready: true` | Campaign task can be completed and evidenced in a cloud/container environment. | No |
| `agent-ready` | A structured issue has cleared its design/scope gate and can be evaluated for remote execution. | No |
| `jules` | Google Jules execution trigger after the pre-trigger safeguards pass. | **Yes** |

For campaign work, `cloud_agent_ready` in the manifest is authoritative. An issue label cannot
turn a manifest-ineligible task into a cloud-ready one.

The exact `jules` label is reserved for a future maintainer-controlled central executor.

## Before opening the pull request

For a campaign task, run:

~~~sh
uv run python scripts/check-task.py TASK-ID
~~~

Then run any project gates required by the task or affected area. For ordinary Python/code
changes this normally includes:

~~~sh
uv run python -m pytest tests/ -v
uv run ruff check src tests scripts
uv run mypy src
~~~

Do not claim a gate passed unless you actually ran it.

Review the complete diff yourself. Remove unrelated cleanup. Confirm the diff stays inside the
task's allowed_paths.

In the PR, include the Task ID, explain what changed and why, list the commands you actually ran,
state the agent/tool used when applicable, and state what you verified personally.

The human opening the PR is accountable for its contents.

## What an agent must stop on

Stop and ask for human/maintainer review before proceeding if the task unexpectedly touches:

- network egress, telemetry, analytics, crash reporting, or cloud fallback;
- microphone permission policy or ambient capture;
- shell execution or command interpolation;
- dependencies or lockfiles outside explicitly approved scope;
- IPC, public contracts, accepted ADR semantics, or default feature state;
- GitHub Actions permissions, branch/ruleset policy, release workflows, signing, publishing, or credentials;
- private repository tiers;
- participant data, voice samples, unpublished study data, or other sensitive evidence;
- native-language quality decisions;
- claims that require physical hardware or OS behaviour the cloud worker did not actually observe.

Do not solve a stop condition by weakening validation.

## Review backpressure

Cloud workers can create changes faster than humans can review them. That does not make review
optional.

For the pilot:

- one active agent task per new participant;
- pause new agent claims when 8 agent-assisted PRs are waiting on a human;
- the project-wide REVIEWING.md stop conditions still apply.

If the queue is full, finish review before starting more work.

## Project-controlled agents are different

A future maintainer-controlled Jules, Codex, or other executor may create branches directly in
the upstream repository. That is a separate trust mode.

It stays disabled until all ADR-024 prerequisites are met, including:

- pull requests required for main;
- a stable required CI gate;
- an execution trigger limited to authorized actors and trusted contract sources;
- an execution contract from `campaign/tasks.json` or a maintainer-approved structured issue
  that passed the read-only pre-trigger check, never arbitrary public issue/comment prose;
- no release, signing, or private-data credentials exposed to the worker;
- no auto-merge;
- documented emergency disable procedure.

Do not assume the contributor-fork rules are sufficient for a central bot.

## Pilot metrics

We care about whether agents reduce the cost of useful contributions, not how many sessions run.

Track only public/repository operational data: task claims, claim-to-PR conversion, first-pass
preflight success, first-pass CI success, scope corrections requested, human review minutes by
risk lane, abandoned claims, duplicate work, merged PRs, and post-merge revert/rollback rate.

Do not collect contributor provider keys, private prompts, private account data, billing details,
speech, or participant data for this programme.

## If something goes wrong

Out-of-scope diff: do not merge it. Reduce the PR to the declared task and check whether the task
contract itself was ambiguous.

Secret or personal-data exposure: follow
[incident-response.md](incident-response.md) and
[SECURITY.md](../.github/SECURITY.md) immediately; rotate/revoke credentials when relevant.

Repeated provider failure: record the task/provider path as blocked in the tracker and
investigate. Do not loosen a safety gate just to increase completion rate.

Review overload: stop starting new agent work. The purpose of the worker model is to make useful
contributions cheaper to review, not to maximize open PR count.
