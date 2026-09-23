---
title: "Connect Google Jules to YazSes"
description: "Step-by-step Jules setup for contributors using forks today, plus the gated maintainer-only upstream connection procedure."
---

# Connect Google Jules to YazSes

**Last checked against official Google Jules and GitHub documentation: 2026-09-23.**

There are **two different ways** to use Jules with YazSes. Choose the one that matches who you are:

| You are... | Use this path | Upstream YazSes access needed? | Available now? |
|---|---|---:|---:|
| Outside contributor / community developer | **Fork-first Jules** | No | **Yes — recommended** |
| Existing contributor who does not need upstream write | **Fork-first Jules** | No | **Yes — recommended** |
| Repository owner / maintainer testing central Jules | **Upstream Jules** | Owner-controlled GitHub App install | **Not yet — gated by #447** |

!!! important "Do not connect Jules directly to upstream yet"

    ADR-024 deliberately requires the fork-first pilot and repository safety gates before a
    project-controlled Jules worker is given access to `MSKazemi/yazses`.

    Until [#447](https://github.com/MSKazemi/yazses/issues/447) says its blockers are complete,
    **do not install/authorize the Google Labs Jules GitHub App for the upstream
    `MSKazemi/yazses` repository and do not use the literal `jules` label upstream.**

The recommended contribution architecture today is:

```text
YazSes task
   ↓
your fork
   ↓
your Jules account
   ↓
you review the complete diff
   ↓
tests / task validation
   ↓
normal pull request to MSKazemi/yazses
   ↓
CI + human project review
```

This requires **no upstream collaborator access**.

---

## Path A — contributor: connect Jules to your own fork

This is the normal and currently approved Jules workflow.

### Step 1 — fork YazSes

1. Open the YazSes repository on GitHub.
2. Click **Fork**.
3. Create the fork under your own GitHub account.
4. Keep the repository name `yazses` unless you have a reason to change it.

**Expected result:** you have a repository such as:

```text
YOUR_GITHUB_USERNAME/yazses
```

You do not need write permission to `MSKazemi/yazses`.

### Step 2 — sign in to Jules

1. Open [jules.google.com](https://jules.google.com/).
2. Sign in with the Google account you want to use for Jules.
3. Accept the Jules privacy notice if shown.
4. Click **Connect to GitHub account**.

Google's current setup flow redirects you to GitHub so you can authorize the connection and choose
which repositories the Google Labs Jules GitHub App may access.

### Step 3 — give Jules access to your fork only

On the GitHub installation/authorization screen:

1. Choose **your own GitHub account**.
2. Choose **Only select repositories**.
3. Select **your fork**, for example `YOUR_GITHUB_USERNAME/yazses`.
4. Review the permissions GitHub displays.
5. Click **Install**, **Save**, or the equivalent approval button shown by GitHub.
6. Return to Jules.

**Expected result:** your fork appears in the Jules repository/codebase selector.

!!! tip "If your fork does not appear"

    On GitHub go to:

    **Profile photo → Settings → Applications → Google Labs Jules → Configure → Repository access**

    Add your `yazses` fork and save. Then refresh Jules.

    Jules also currently provides **+ Add repository** at the bottom of its repository selector,
    which sends you back to GitHub to change repository access.

### Step 4 — set commit authoring correctly

For YazSes, use human-only Git authorship.

In Jules:

1. Open **Settings**.
2. Open **Commit Authoring**.
3. Select **User only**.

**Expected result:** future Jules commits use your identity as the commit author rather than making
Jules the author/co-author.

YazSes allows tool disclosure in the pull request's **AI assistance** section, but automated tools
are not project authors or co-authors. See root `AGENTS.md`.

### Step 5 — configure the YazSes environment

In Jules:

1. Open your `yazses` codebase from the left sidebar/repository list.
2. Open **Configuration**.
3. In **Initial Setup**, enter:

```sh
uv sync
```

4. Click **Run and Snapshot**.

Jules currently documents an Ubuntu VM with Python, `uv`, pytest, ruff, mypy, Git, C/C++
compilers and other common developer tooling preinstalled. The `uv sync` step installs YazSes's
repository dependencies.

**Expected result:** setup succeeds and Jules stores an environment snapshot for later tasks.

For the first setup only, you may use this slightly more verbose check:

```sh
uv --version
python --version
uv sync
uv run python -m pytest tests/test_agent_instructions.py -q
```

After it works, `uv sync` is sufficient as the normal initial setup.

### Step 6 — verify Jules reads the YazSes rules

Before asking Jules to edit code, run one planning-only prompt:

```text
Read AGENTS.md in this repository. Do not change any files.

Summarize:
1. the required setup/test commands;
2. the offline/network rule;
3. the rule for new feature defaults;
4. dependency/lazy-load rules;
5. authorship rules;
6. what evidence a cloud agent may not claim.
```

**Do not create a branch or PR from this verification task.**

A healthy result should identify at least:

- `uv sync`;
- pytest and ruff validation;
- no new runtime telemetry/network/cloud fallback without the repository's egress process;
- new features off by default;
- optional/lazy heavy dependencies;
- the human remains the responsible contributor;
- hardware, native-language and participant evidence cannot be invented by a cloud VM.

If it does not, stop and fix the repository selection/setup before asking Jules to implement work.

### Step 7 — choose an eligible task

For campaign work, use:

```sh
uv run python scripts/check-task.py
```

Choose only a task that is:

- open;
- `cloud_agent_ready: true`;
- within the risk/worker rules in `campaign/agent-workers.md`;
- fully verifiable in a cloud/container environment.

Do not turn a hardware, native-language, accessibility-comfort, participant-research or other
human-evidence task into a cloud task just because Jules says it can write the code.

Claim the task using the normal campaign claim workflow before starting.

### Step 8 — give Jules the exact task contract

Use the campaign task/structured issue as the contract and tell Jules to read `AGENTS.md`.

A safe starting prompt is:

```text
I am completing one YazSes contribution and remain responsible for the pull request.

Read AGENTS.md completely, then read TASK-ID and restate:
- the goal;
- allowed paths;
- explicit non-goals;
- acceptance/evidence requirements;
- validation command.

Inspect the implementation and tests before editing.
Make the smallest change that satisfies the task.
Stop if completion requires hardware evidence, native-language judgement,
participant/private data, credentials, billing changes, or a maintainer-only decision.

Run the task validation and relevant repository checks.
Show me the complete diff before I submit anything upstream.
```

### Step 9 — review and validate before opening the PR

Do not treat "Jules finished" as "the contribution is finished."

Review every changed file, then run the task's exact validation. For ordinary Python changes, the
project-wide gates are:

```sh
uv run python -m pytest tests/ -v
uv run ruff check src tests scripts
uv run mypy src
```

The task's narrower command should normally run first.

### Step 10 — open a normal fork → upstream pull request

Push/create the branch in **your fork**, then open a pull request to:

```text
base: MSKazemi/yazses : main
head: YOUR_GITHUB_USERNAME/yazses : your-branch
```

Complete the normal YazSes PR template, including:

- what changed;
- the related task/issue;
- commands you ran;
- AI assistance/tool disclosure if applicable;
- what **you personally verified**.

The PR goes through exactly the same CI and human review as any other contribution.

---

## Contributor connection checklist

Before starting real work, all of these should be true:

- [ ] I have my own fork of YazSes.
- [ ] Jules is connected to my GitHub account.
- [ ] Google Labs Jules has access to **my fork**, not upstream.
- [ ] My fork appears in the Jules repository selector.
- [ ] Commit Authoring is **User only**.
- [ ] `uv sync` succeeds in **Run and Snapshot**.
- [ ] Jules correctly summarizes root `AGENTS.md`.
- [ ] My selected task is actually cloud-agent-ready.
- [ ] I understand that my provider account/quota/charges are my responsibility.
- [ ] I will review the complete diff before opening the PR.

If all ten are true, you are ready to use Jules for a fork-first YazSes contribution.

---

## Path B — repository owner: direct upstream Jules connection

This is the future maintainer-controlled route where Jules can act directly from an upstream
GitHub issue.

**It is intentionally not enabled yet.**

The live gate is [#447 — JULES-SETUP-001](https://github.com/MSKazemi/yazses/issues/447).

Before upstream access is granted, #447 currently requires the relevant ADR/pilot/contract,
read-only preflight, CI/ruleset and repository-protection gates to be complete. Read the issue
itself for the authoritative current blocker list.

### When #447 says the upstream gate is open

Only then should the repository owner perform these steps:

1. Open [jules.google.com](https://jules.google.com/) and sign in.
2. Click **Connect to GitHub account**.
3. On GitHub choose personal account **`MSKazemi`**.
4. Choose **Only select repositories**.
5. Select **`MSKazemi/yazses`**.
6. Review the GitHub App permissions carefully.
7. Install/save the GitHub App access.
8. Return to Jules and confirm `MSKazemi/yazses` appears in the repository selector.
9. Jules **Settings → Commit Authoring → User only**.
10. Open the YazSes codebase → **Configuration**.
11. Set **Initial Setup** to `uv sync`.
12. Click **Run and Snapshot**.
13. Run the planning-only `AGENTS.md` verification described above.
14. Verify the project's read-only Jules preflight passes for the chosen smoke issue.
15. Only then apply the literal **`jules`** GitHub issue label.

### What the `jules` label means

Google currently documents the issue integration as:

```text
open GitHub issue
    ↓
add label: jules
    ↓
Jules starts a task
    ↓
Jules comments on the issue
    ↓
finished task links to a PR for review
```

The label is case-insensitive in Jules, but YazSes treats the canonical spelling `jules` as an
**execution trigger**.

It is not:

- a generic "AI friendly" tag;
- equivalent to `agent-ready`;
- permission to skip blockers;
- permission to merge automatically.

### Selecting the first upstream smoke issue

**Do not use #448 as the smoke task.** #448 is the eligibility checker that must exist before the
central smoke run.

The smoke issue must pass the current #447 requirements and the read-only pre-trigger checker.
In the initial central deployment it should be small, cloud-completable, trusted/maintainer-approved,
non-sensitive, and independent of hardware/native-language/research evidence.

### Expected upstream result

After the owner deliberately adds `jules` to an eligible issue:

1. Jules should comment/start the task.
2. Jules should operate from the intended issue contract.
3. The resulting commit should use **User only** authorship.
4. Jules should produce/update a PR branch rather than bypass `main`.
5. Normal repository CI should run.
6. Human review remains mandatory before merge.

If any of those properties fail, stop the central rollout and use the emergency-disable procedure in
#447.

---

## Do contributors need access to the upstream repository?

**No.**

For normal community development:

```text
contributor
    owns their fork
        ↓
Jules gets access to that fork
        ↓
contributor opens normal PR upstream
```

Do not make someone an upstream collaborator merely because they want to use Jules.

For `MSKazemi/yazses`, which is currently a personal-account repository, the owner controls the
GitHub App installation used for direct upstream Jules access.

If the repository moves to a GitHub organization in the future, organization policy may add an
owner/admin approval step for GitHub App installation.

---

## If the repository is missing in Jules

For a repository you own/control:

**GitHub profile photo → Settings → Applications → Google Labs Jules → Configure → Repository access**

Then:

1. choose **Only select repositories** if appropriate;
2. add the intended repository;
3. save;
4. return to Jules;
5. refresh the repository selector.

Jules also currently exposes **+ Add repository** at the bottom of its repository selector, which
opens the GitHub repository-access flow.

---

## If the `jules` issue label does nothing

For the upstream flow, check in this order:

1. The central-upstream gate in #447 is actually complete.
2. Google Labs Jules is installed for the account that owns `MSKazemi/yazses`.
3. The GitHub App has explicit access to `MSKazemi/yazses`.
4. The repository is visible in Jules.
5. The issue is in that repository and is open.
6. The label is exactly `jules` (case-insensitive according to Jules).
7. The project's own pre-trigger checker passed **before** the label was applied.

If the provider still does not react, use the provider's current support/feedback path rather than
widening GitHub permissions.

---

## If commits are attributed to Jules

Open:

**Jules → Settings → Commit Authoring → User only**

That setting applies to future Jules sessions. Correct the configuration before creating more YazSes
work.

Do not add generated `Co-Authored-By` trailers. The PR may disclose Jules assistance and state
what the human contributor verified; that is review disclosure, not authorship.

---

## Removing or reducing Jules access

You can revoke access without changing YazSes code.

### Remove one repository

On GitHub:

**Profile photo → Settings → Applications → Google Labs Jules → Configure → Repository access**

Remove the repository and save.

### Remove the GitHub App entirely

From the same installed-app configuration area, use GitHub's suspend/uninstall/remove option if you
no longer want the app to access resources owned by that account.

GitHub recommends periodically reviewing installed GitHub Apps and removing access that is no
longer required.

### Jules API key

The normal GitHub App + fork/issue workflow does **not** require a `JULES_API_KEY`.

If you separately create a Jules REST API key later, keep it outside the repository. Revoke it in
Jules Settings when no longer needed.

---

## Billing, credentials and private data

Before using Jules, read:

- [Using AI coding agents safely](ai-agents.md)
- [Third-party AI tools](https://github.com/MSKazemi/yazses/blob/main/THIRD_PARTY_AI_TOOLS.md)

In particular:

- Jules is optional for contribution.
- Use your own provider account/quota for the fork-first workflow.
- YazSes does not authorize or reimburse third-party charges unless explicitly agreed in writing
  beforehand.
- Do not put provider/API/GitHub secrets in prompts, issues, source files or logs.
- Do not send user audio/transcripts, private repository material, research-participant data or
  non-deidentified tester data to a cloud coding agent.
- A task being `agent-ready` or `cloud_agent_ready` is not authority to spend money.

---

## Official documentation

The provider UI can change; the current provider documentation takes precedence over button names
in this page.

- [Jules — Getting started](https://jules.google/docs/)
- [Jules — Managing tasks and repositories](https://jules.google/docs/tasks-repos/)
- [Jules — Environment setup](https://jules.google/docs/environment/)
- [Jules — Running tasks](https://jules.google/docs/running-tasks/)
- [Jules — issue-label integration](https://jules.google/docs/changelog/2025-06-26/)
- [Jules — commit authoring](https://jules.google/docs/changelog/2026-02-19/)
- [GitHub — installing a GitHub App from a third party](https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party)
- [GitHub — reviewing/modifying installed GitHub Apps](https://docs.github.com/en/apps/using-github-apps/reviewing-and-modifying-installed-github-apps)

---

## Related YazSes policy

- [ADR-024 — distributed coding-agent worker model](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-024-distributed-coding-agent-worker-model.md)
- [Cloud coding-agent workers](https://github.com/MSKazemi/yazses/blob/main/campaign/agent-workers.md)
- [Using AI coding agents safely](ai-agents.md)
- [Third-party AI tools](https://github.com/MSKazemi/yazses/blob/main/THIRD_PARTY_AI_TOOLS.md)
- [#451 — coding-agent worker epic](https://github.com/MSKazemi/yazses/issues/451)
- [#447 — gated direct-upstream Jules setup](https://github.com/MSKazemi/yazses/issues/447)
