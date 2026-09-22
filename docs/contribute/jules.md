---
title: "Using Google Jules with YazSes"
description: "Least-privilege setup for Google Jules: repository access, issue-label triggering, authorship, environment setup, forks, and YazSes agent-ready task rules."
---

# Using Google Jules with YazSes

**Upstream setup tracking:** [#447 — connect Google Labs Jules and run a smoke task](https://github.com/MSKazemi/yazses/issues/447)

Jules is welcome here, but it is **an execution tool, not the source of project policy**.
The repository's canonical coding-agent instructions remain [`AGENTS.md`](../../AGENTS.md),
and Jules automatically reads a root `AGENTS.md` when it prepares a task.

This page explains how to connect Jules without granting unnecessary GitHub access, how
maintainers can trigger it from an issue, and how an outside contributor can use Jules
without becoming a collaborator on the upstream repository.

Jules is a third-party service. Its pricing, quotas, included usage and account terms can change
independently of this repository. Before using a paid or metered account, read
[Third-party coding tools: accounts, costs, and responsibility](third-party-coding-tools.md).
YazSes does not require Jules and does not assume or reimburse a contributor's Jules charges unless
there is a separate written agreement made before the expense.

## The access model in one minute

YazSes is currently owned by the personal GitHub account `MSKazemi`.

That means there are two deliberately different workflows:

| Person | Upstream GitHub App installation needed? | Upstream write/collaborator access needed? | Recommended workflow |
|---|---:|---:|---|
| Repository owner / maintainer | **Yes, once** | already has it | Install Google Labs Jules for `MSKazemi/yazses`; trigger bounded issues |
| Existing upstream collaborator | owner must still allow the app on the repo | only whatever their normal role already provides | Use the shared upstream workflow only for maintainer-approved tasks |
| Outside contributor | **No** | **No** | Fork YazSes, connect Jules to the fork, then open a normal PR upstream |
| Research/hardware tester | No for the evidence itself | No | Do the human/device measurement; Jules may help with code around it but may not fabricate evidence |

**Do not add a developer's "Jules account" as a GitHub collaborator.** Jules reaches a
repository through the **Google Labs Jules GitHub App**. For the upstream personal
repository, the owner grants that app access once. Individual contributors who do not
already have upstream permissions should use the ordinary fork-and-PR model.

This is the least-privilege setup: nobody receives write access merely because they want
to use a coding agent.

## Owner setup for `MSKazemi/yazses`

Do this once from the repository owner's accounts.

### 1. Connect Jules to GitHub

1. Open [jules.google.com](https://jules.google.com/) and sign in.
2. Choose **Connect to GitHub**.
3. During GitHub installation/authorization, select **Only select repositories**.
4. Select **`MSKazemi/yazses`**.
5. Review the permissions GitHub shows before installing.

Jules can only operate on repositories explicitly granted to its GitHub App. To change
that later, GitHub documents the route as **Settings → Applications → Google Labs Jules
→ Configure → Repository access**.

### 2. Set commit authoring to `User only`

This is mandatory for YazSes.

In Jules:

1. Open **Settings**.
2. Open **Commit Authoring**.
3. Select **User only**.

Jules defaults to authoring its own commits unless this is changed. YazSes's canonical
`AGENTS.md` rule forbids attributing an automated assistant as author/co-author and
forbids generated-with footers or `Co-Authored-By` trailers.

The human who reviews and submits the work remains responsible for the contribution.

### 3. Configure the Jules environment

Jules currently runs an Ubuntu VM with Python, `uv`, pytest, ruff, mypy, GCC and Git
preinstalled. The repository therefore needs only its normal dependency setup:

```sh
uv sync
```

Use that as the Jules **Initial Setup** command and use **Run and Snapshot** so later
tasks can reuse the prepared environment.

The ordinary YazSes validation gates remain:

```sh
uv run python -m pytest tests/ -v
uv run ruff check src tests scripts
uv run mypy src
```

A task should normally run its **narrow definition-of-done command first**, then the
broader gates when feasible.

### 4. Verify that Jules sees the canonical instructions

A Jules plan should reflect at least these repository rules:

- no new runtime network/telemetry path without the existing egress decision process;
- new features are off by default;
- heavy dependencies are optional and lazy;
- pure logic stays dependency-free and directly tested;
- one issue / one focused PR;
- tests ship with behavior changes;
- no AI attribution.

If a plan contradicts `AGENTS.md`, reject the plan before code generation.

## Issue-driven Jules workflow

Jules can be started from GitHub by adding the label **`jules`** to an issue, once the
Jules GitHub App has access to the repository.

YazSes uses **two different labels with different meanings**:

| Label | Meaning | Does it start work? |
|---|---|---:|
| `agent-ready` | the task has an ADR/spec or otherwise has no unresolved design choice | **No** |
| `jules` | execution trigger for the Google Labs Jules GitHub App | **Yes** |

**Never use `jules` as a general classification label.** It is an action.

The safe maintainer flow is:

1. Issue has one bounded goal, explicit non-goals, integration seam, acceptance criteria,
   required tests, blockers and a definition-of-done command.
2. Required ADR/spec is already merged or intentionally available on the base branch.
3. Blockers are merged.
4. Apply `agent-ready`.
5. A maintainer chooses the issue for remote execution.
6. Apply `jules`.
7. Jules comments/starts the task and proposes code/PR work.
8. Human review checks scope, diff, tests, privacy and architecture before merge.
9. Do **not** auto-merge merely because Jules or CI is green.

For eye/camera work, also follow
[`design/eye-control/GOVERNANCE.md`](https://github.com/MSKazemi/yazses/blob/plan/eye-control-roadmap-2026-09-22/design/eye-control/GOVERNANCE.md)
until that planning PR is merged.

## Preferred first upstream smoke task

After this guide/ADR has merged and the owner setup is complete, use
[#448 — JULES-PREFLIGHT-001](https://github.com/MSKazemi/yazses/issues/448) for the first
upstream Jules run. It is intentionally read-only, deterministic and independent of hardware.
Do not add `agent-ready` or `jules` to #448 until #446 is merged.

## Maintainer preflight before applying `jules`

Run this review **before** applying the trigger label, because the label itself starts external work.

- [ ] The issue is labelled `agent-ready`.
- [ ] The governing ADR/spec is on the branch Jules will actually read, normally `main`.
- [ ] Every issue named under "Blocked by" is closed/merged, or the issue has no blocker.
- [ ] The issue has one reviewable goal and an exact definition-of-done command.
- [ ] Required evidence is cloud-completable; otherwise split code from human/device evidence.
- [ ] The task does not ask the agent to choose a new product/architecture policy.
- [ ] No secret, credential, private file or unpublished participant data is required.
- [ ] The expected diff does not require bypassing the normal review lane.
- [ ] Commit Authoring is still set to **User only**.
- [ ] A human is available to review the resulting plan/diff before merge.

If any item is false, leave `jules` off the issue.

## What is safe to give Jules

Good Jules tasks are the repository's **A3 / cloud-ready** tasks: the full result can be
produced and verified in a container/VM without pretending to observe hardware or a human.

Good examples:

- dependency-free data contracts;
- pure parsers/resolvers/state machines;
- regression tests;
- docs synchronized with code;
- fake-adapter/platform contract tests;
- deterministic evaluation harnesses.

Do **not** ask Jules to certify:

- that a webcam, microphone, eye tracker or Wayland compositor behaved a certain way;
- that a translation sounds natural to a native speaker;
- that an accessibility interaction is comfortable or fatigue-free;
- that a destructive action is safe as a product decision;
- a new architecture when the issue still contains design questions.

Those tasks can use Jules for implementation support, but the missing evidence remains human.

## Outside contributors: use a fork

An outside developer does **not** need access to `MSKazemi/yazses` to use Jules.

Recommended path:

1. Fork `MSKazemi/yazses` to the contributor's own GitHub account.
2. In their own Jules account, connect GitHub and grant the Google Labs Jules App access
   to **their fork only**.
3. Set Jules commit authoring to **User only**.
4. Start from the upstream issue and copy its exact issue/ADR/spec/validation context into
   the Jules task.
5. Base the work on the appropriate branch.
6. Review every changed line.
7. Run the issue's definition-of-done command.
8. Open a normal pull request from the fork to `MSKazemi/yazses`.

This keeps upstream permissions unchanged and works with the normal open-source
contribution model.

## A task prompt that fits YazSes

For a manually started Jules task, use the GitHub issue as the contract rather than
rewriting the design in a free-form prompt:

```text
Implement GitHub issue #<NUMBER> for MSKazemi/yazses.

Read AGENTS.md first. Then read the issue completely, including every linked ADR,
spec and named test.

Treat the issue's allowed scope, explicit non-goals, acceptance criteria, blockers and
definition-of-done command as binding.

Before changing code:
1. restate the acceptance criteria;
2. name the files/seams you expect to touch;
3. identify any unresolved design question and stop if one exists.

Make the smallest implementation that satisfies the issue. Do not tidy unrelated code,
add an unrequested dependency, add a runtime network path, enable a feature by default,
or bypass an existing platform/protocol seam.

Add/update the required tests. Run the issue's narrow validation command, then the
repository pytest/ruff gates when feasible.

Do not add AI/Jules attribution, Co-Authored-By trailers, generated-with footers, or
tool credits. Do not auto-merge.
```

## API/CLI automation is optional, not required

Jules also exposes API/CLI workflows, but YazSes does **not** need them to get started.
The GitHub App plus the `jules` issue label is enough for maintainer-triggered work.

If the API is used later:

- create/obtain the Jules API key from the Jules account settings;
- keep it in a secret store or environment variable;
- **never commit `JULES_API_KEY`**;
- note that Jules API sources are created by connecting repositories through the web
  interface first; the API lists/uses those sources rather than creating GitHub access
  by itself.

Repository automation that mass-applies `jules` should not be added. The whole point of the
label is that a human deliberately chooses a task after its blockers and design gates are clear.

## Troubleshooting access

### `MSKazemi/yazses` is missing from the Jules repository selector

On GitHub:

**Profile photo → Settings → Applications → Google Labs Jules → Configure**

Then add `MSKazemi/yazses` under repository access and save.

### A contributor cannot add the `jules` label upstream

That is expected for most outside contributors. They do not need upstream label/write
permission. A maintainer can trigger an approved upstream issue, or the contributor can
run Jules against their own fork and open a PR.

### Jules opens a commit/PR credited to Jules

Change **Jules Settings → Commit Authoring → User only** before running more tasks.
Do not merge an attribution mode that violates `AGENTS.md`.

### Jules cannot prove a hardware acceptance criterion

That is not a Jules configuration failure. Keep the code/test portion separate from the
human/device evidence issue. A cloud VM cannot replace an observed hardware result.

## Repository policy summary

Jules readiness is a property of a **task**, not of the whole backlog.

A professional YazSes task pipeline is:

```text
research / user need
    -> ADR when a reusable decision is required
    -> implementation spec
    -> bounded GitHub issue
    -> agent-ready
    -> optional human-triggered jules label
    -> Jules plan + implementation
    -> CI
    -> human review
    -> hardware/user evidence when required
    -> merge
```

That keeps autonomous coding useful without turning design, accessibility evidence or
repository permissions into automated guesses.

## Official references

- [Jules — Getting started](https://jules.google/docs/)
- [Jules — Managing tasks and repositories](https://jules.google/docs/tasks-repos/)
- [Jules — Environment setup](https://jules.google/docs/environment/)
- [Jules — GitHub issue label integration](https://jules.google/docs/changelog/2025-06-26/)
- [Jules — Commit authoring](https://jules.google/docs/changelog/2026-02-19/)
- [Jules API — Sources](https://jules.google/docs/api/reference/sources/)
- [GitHub — Installing a GitHub App from a third party](https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party)
