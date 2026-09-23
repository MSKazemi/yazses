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

## Connect Jules to YazSes — 5-minute owner quick start

Use this section if you are the owner of **`MSKazemi/yazses`** and want Jules to work
directly on the upstream repository.

> **Repository-side status:** YazSes is prepared for Jules in PR
> [#446](https://github.com/MSKazemi/yazses/pull/446). The remaining connection itself is
> an account-level GitHub/Jules action tracked in
> [#447](https://github.com/MSKazemi/yazses/issues/447).
>
> **Do not trigger a real task until #446 is merged.** The first intended smoke task is
> [#448](https://github.com/MSKazemi/yazses/issues/448).

### A. Connect your GitHub account to Jules

1. Open **[jules.google.com](https://jules.google.com/)**.
2. Sign in with the Google account you want to use for Jules.
3. Accept Jules's privacy notice if it is shown.
4. Click **Connect to GitHub account**.
5. Complete the GitHub login/authorization flow.

**Expected result:** Jules returns you to its app and shows a repository/codebase selector.

If you are already connected to GitHub, skip to **B**.

### B. Give the Google Labs Jules GitHub App access to YazSes

When GitHub asks where Jules may be installed:

1. Choose your personal GitHub account **`MSKazemi`**.
2. Choose **Only select repositories**.
3. Select **`MSKazemi/yazses`**.
4. Read the permissions GitHub displays.
5. Click **Install** / **Save** / the equivalent approval button shown by GitHub.
6. Return to Jules and refresh if the repository does not appear immediately.

**Expected result:** `MSKazemi/yazses` appears in the Jules repository/codebase selector.

If Jules is already installed but YazSes is missing, use either route:

- **GitHub:** Profile photo → **Settings** → **Applications** → **Google Labs Jules** →
  **Configure** → **Repository access** → add `MSKazemi/yazses` → **Save**.
- **Jules:** open the repository selector → scroll to **+ Add repository** → GitHub opens →
  select `MSKazemi/yazses` → save → return to Jules.

For the current personal-account repository, **you do not need to add another developer as a
GitHub collaborator just to make Jules work**. The repository owner installs the GitHub App.
GitHub documents that GitHub Apps are installed on the personal/organization account that owns the
resources and are then granted access to selected repositories.

### C. Make Jules commits comply with YazSes authorship policy

Before the first task:

1. In Jules, open **Settings**.
2. Open **Commit Authoring**.
3. Select **User only**.
4. Leave that setting in place for future YazSes sessions.

**Expected result:** future Jules commits are attributed to your GitHub identity rather than Jules
or a Jules+user co-author pair.

This is required by YazSes `AGENTS.md`.

### D. Configure the YazSes environment

1. In Jules, click **`MSKazemi/yazses`** under the codebases/repositories area.
2. Open **Configuration**.
3. In **Initial Setup**, enter:

```sh
uv sync
```

4. Click **Run and Snapshot**.
5. Confirm the setup finishes successfully.

Jules currently documents an Ubuntu VM with Python, `uv`, pytest, ruff, mypy, Git and common
build tools already available. `uv sync` installs the repository's own locked dependencies.

**Expected result:** Jules creates an environment snapshot and can reuse it for future YazSes tasks.

If you want an explicit sanity check before snapshotting, temporarily use:

```sh
uv --version
python --version
uv sync
uv run python -m pytest tests/test_agent_instructions.py -q
```

Once validated, keeping the setup script to `uv sync` is enough.

### E. Verify Jules is reading the repository rules

Start a **non-destructive planning task** against `main`, for example:

```text
Read AGENTS.md for MSKazemi/yazses. Do not change any files.
Summarize the repository's setup commands, offline/network rule,
feature-default rule, testing requirements, and authorship rule.
```

Do not create a branch from this verification task.

**Pass condition:** the response identifies at least:

- `uv sync`;
- pytest + ruff as required validation;
- no new runtime network/telemetry path without the repository's egress process;
- new features off by default;
- heavy dependencies optional/lazy;
- human-only project authorship / no AI attribution.

If Jules contradicts those rules, fix the repository selection/configuration before giving it an
implementation task.

### F. Run the first real Jules task

After **#446 is merged** and owner setup **#447** is complete:

1. Open [#448](https://github.com/MSKazemi/yazses/issues/448).
2. Confirm its blocker (#446) is closed.
3. Add the **`agent-ready`** label.
4. Run the maintainer preflight from this guide.
5. Open the issue's **Labels** control (gear icon in GitHub).
6. Add the label **`jules`**.
7. Watch for Jules to comment on the issue.
8. Follow the Jules task/PR link when it finishes.
9. Review the plan, diff and CI normally before merge.

Google documents the `jules` label as the GitHub-issue trigger: **adding the label starts the
task**. Removing/adding labels should therefore be treated as an execution action, not as
categorization.

**Expected result:** Jules comments on the GitHub issue and, when finished, provides a link to the
pull request for human review.

### G. Connection-success checklist

The upstream Jules connection is considered healthy only when all of these are true:

- [ ] `MSKazemi/yazses` is visible in Jules.
- [ ] GitHub shows **Google Labs Jules** with repository access to `MSKazemi/yazses`.
- [ ] Commit Authoring is **User only**.
- [ ] `uv sync` succeeds in **Run and Snapshot**.
- [ ] Jules can read root `AGENTS.md`.
- [ ] A planning-only test correctly states the core YazSes rules.
- [ ] The `jules` GitHub label exists before the first triggered task.
- [ ] Adding `jules` to the approved smoke issue causes Jules to comment/start work.
- [ ] The resulting PR still goes through normal CI and human review.

If the first five pass but the issue label does nothing, see **Troubleshooting access** below.

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

### Who can connect what?

- **For this upstream personal repository:** the GitHub personal account that owns
  `MSKazemi/yazses` controls the installation that gives Jules access to it.
- **For a contributor's fork:** the contributor can install/authorize Jules for their own GitHub
  account and select their fork.
- **For a future organization-owned repository:** organization policy may require an owner/admin
  approval step before the GitHub App can be installed or granted to a repository.
- **Applying `jules` upstream:** requires enough GitHub issue permission to edit labels; ordinary
  outside contributors should not need that permission.

So the normal answer to "do contributors need extra access?" is **no**: use a fork. Direct
upstream Jules execution is a maintainer-controlled workflow.


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

## Outside contributor quick start — no upstream access required

Use this path if you are **not** the owner/maintainer of `MSKazemi/yazses`.

You do **not** need:
- upstream collaborator access;
- permission to install Jules on the owner's GitHub account;
- permission to apply the upstream `jules` label.

Do this instead:

1. On GitHub, fork **`MSKazemi/yazses`** into your own account.
2. Open Jules and connect your GitHub account.
3. Grant **Google Labs Jules** access to **your fork only**.
4. In Jules Settings, set **Commit Authoring → User only**.
5. Configure your fork's environment with **Initial Setup = `uv sync`** and **Run and Snapshot**.
6. Select a YazSes issue that is ready for contribution.
7. Give Jules the upstream issue number/URL and tell it to read `AGENTS.md`.
8. Run and review the work in your fork.
9. Push/create the branch in your fork.
10. Open a normal GitHub pull request from your fork to **`MSKazemi/yazses:main`**.

Your fork does not give Jules any new permission on the upstream repository. The upstream PR is
reviewed exactly like any other external contribution.

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

## How to remove or reduce Jules access later

You can change your mind without changing any YazSes source code.

### Remove only YazSes repository access

On GitHub:

**Profile photo → Settings → Applications → Google Labs Jules → Configure → Repository access**

Remove `MSKazemi/yazses` from the selected repositories and save.

### Stop using Jules entirely for the GitHub account

From the same GitHub App configuration area, use GitHub's option to suspend/uninstall the app if
you no longer want it to access resources owned by that account.

GitHub recommends periodically reviewing installed GitHub Apps and removing access that is no
longer needed.

### Remove an API key if you experimented with the Jules API

The normal GitHub App/issue-label workflow does **not** require `JULES_API_KEY`.
If you created an API key separately, revoke it in Jules Settings and delete it from your local
secret store/environment.

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

## Documentation freshness

The connection UI is owned by Google/GitHub and can change. This runbook was checked against the
official Jules and GitHub documentation on **2026-09-23**. If a button name differs, follow the
same permission model and confirm against the official references below rather than guessing.

## Official references

- [Jules — Getting started](https://jules.google/docs/)
- [Jules — Managing tasks and repositories](https://jules.google/docs/tasks-repos/)
- [Jules — Environment setup](https://jules.google/docs/environment/)
- [Jules — GitHub issue label integration](https://jules.google/docs/changelog/2025-06-26/)
- [Jules — Commit authoring](https://jules.google/docs/changelog/2026-02-19/)
- [Jules API — Sources](https://jules.google/docs/api/reference/sources/)
- [GitHub — Installing a GitHub App from a third party](https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party)
