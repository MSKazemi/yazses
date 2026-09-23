---
title: Using AI coding agents safely
description: Use Claude Code, Codex, ChatGPT, or another coding agent on YazSes without giving it unnecessary access or accidentally enabling paid usage.
---

# Using AI coding agents safely

AI assistance is welcome, but it is never required. The safest default is simple:

**use your existing included allowance, keep approval controls on, work in your own fork,
and do not enable paid overages just to contribute.**

YazSes does not reimburse third-party AI or cloud charges unless a maintainer agreed in
writing in advance to a specific expense and amount. Read the canonical
[third-party AI tools notice](https://github.com/MSKazemi/yazses/blob/main/THIRD_PARTY_AI_TOOLS.md) before using a paid service.

**Last provider-doc review: 2026-09-22.** Providers change products and billing frequently,
so the official provider pages linked below always take precedence over this guide.

## Pick the billing mode first

| What you want | Safer starting point |
|---|---|
| **No AI at all** | Work normally. Every YazSes contribution path supports human-only work. |
| **Use an allowance already included in Claude** | Start without `ANTHROPIC_API_KEY`, sign in to Claude, verify with `/status`, and leave usage-credit/overage continuation off unless you deliberately want it. |
| **Use Codex through your ChatGPT plan** | Start without OpenAI/Codex API-key variables, sign in with ChatGPT, verify with `/status`, and leave optional credit auto-reload off unless you deliberately want it. |
| **Use an API on purpose** | Use your own authorized account/project, set the provider's strongest available spend control plus alerts, monitor usage, and assume the resulting charges are yours unless a separate written agreement says otherwise. |

If you are not sure which row applies to your account, stop before enabling paid continuation
and check the provider's current usage/billing page.

## How the repo reaches your agent automatically

| Tool | Repository instruction discovery |
|---|---|
| **Codex / ChatGPT Codex** | Reads root `AGENTS.md` directly. |
| **Google Jules** | Reads root `AGENTS.md` directly. |
| **Claude Code** | Loads root `CLAUDE.md`, which imports `AGENTS.md`. |
| **Gemini CLI** | Loads root `GEMINI.md`, which imports `AGENTS.md`. |
| **Other agents** | Tell the tool to read `AGENTS.md` before it edits anything. |

The adapter files intentionally contain no copy of the project rules. If instructions
change, only `AGENTS.md` should change. Personal Claude settings belong in
`CLAUDE.local.md` or the user's Claude configuration; personal Gemini settings belong in
the user's Gemini configuration. Do not put private credentials or private maintainer notes
into the tracked adapters.

## The 5-minute safe setup

1. **Fork the repository** to your GitHub account and clone your fork. A normal contribution
   does not require write access to the upstream YazSes repository.
2. From the repository root, read **[AGENTS.md](../../AGENTS.md)** and the task or issue you
   are working on.
3. Decide which billing mode you intend to use: an included subscription/plan allowance, or
   an API/pay-as-you-go account. Do not let that choice happen accidentally.
4. If you do not want extra charges, disable optional overages, usage credits, automatic
   reloads, or similar paid continuation features in the provider account.
5. Keep command/file-write permissions on approval for your first contribution. Let the
   agent inspect and propose; you approve commands, review the complete diff, run validation,
   then open the pull request yourself.

There is no project requirement to use the largest model, maximum reasoning effort, a cloud
sandbox, or a paid agent run. Small bounded tasks are deliberately designed to work without
that.

### If you want to use a cloud agent on campaign work

Use the fork-first worker flow in
[`campaign/agent-workers.md`](../../campaign/agent-workers.md). It explains how task claims,
`cloud_agent_ready`, allowed paths, provider-specific execution triggers such as Jules, and
human review fit together. The key distinction is that **agent readiness is project metadata;
provider execution is contributor-owned**. A normal contributor does not need upstream write
access or a project-owned agent credential.

## One prompt for any agent

Paste this after opening the repository in your agent:

```text
I am making one contribution to YazSes. I remain responsible for the pull request.

1. Read AGENTS.md and .github/CONTRIBUTING.md completely before changing anything.
2. Read the linked issue/task and restate its acceptance criteria and allowed paths.
3. Inspect the relevant implementation and tests first.
4. Make the smallest change that satisfies the task. Do not tidy unrelated code.
5. Do not add network calls, telemetry, cloud fallbacks, dependencies, or default-on features.
6. Do not buy credits, enable paid overages, create paid cloud resources, change my
   subscription, or alter billing settings.
7. Ask before running destructive, privileged, networked, or unusually expensive commands.
8. Run the task's validation command and the required repo checks.
9. Show me the complete diff and explain every changed line.
10. Do not commit, push, or open a pull request until I approve the diff.
```

If an agent claims the task requires purchasing credits or upgrading a plan, stop and either
wait for your normal quota to reset, switch tools, or complete the task manually.

## Treat GitHub text as untrusted input

An issue or pull request can legitimately tell the agent what outcome is wanted, which files
are in scope, and how to validate the work. It cannot override `AGENTS.md` or silently grant
extra authority.

Do not let an agent obey issue comments, pasted logs, fetched web pages, or downloaded text
that tells it to reveal credentials, change billing, disable safeguards, access unrelated
files, add an unrelated dependency, or run a privileged/destructive/networked command. Those
are prompt-injection patterns, not contribution requirements. Show the suspicious instruction
to the human contributor and ask them to decide.

## Claude Code

### If you want to stay inside your Claude subscription

Anthropic documents that an `ANTHROPIC_API_KEY` environment variable can make Claude Code
use API billing instead of your Pro/Max subscription. Before starting, check without printing
the key itself:

```sh
test -n "${ANTHROPIC_API_KEY:-}" && echo "ANTHROPIC_API_KEY is set"
```

If you do **not** intend to use API billing in this shell:

```sh
unset ANTHROPIC_API_KEY
claude
```

Then use `/status` inside Claude Code to confirm the account and usage mode you expect.

If you want to avoid charges beyond your included plan allowance, do not opt into API-credit
continuation merely because you reached a plan limit. Anthropic also exposes usage-credit
and Console billing controls; review any monthly limit and automatic reload setting before
enabling them.

For API-billed sessions, `/cost` shows the current session's spend. `/model` lets you choose
a less expensive model where appropriate. Anthropic recommends clearing unrelated history
between tasks (`/clear`) or compacting long sessions (`/compact`) because large context
increases usage.

Official references:

- [Use Claude Code with Pro or Max](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan)
- [Models, usage, and limits in Claude Code](https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code)
- [Manage usage credits](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans)
- [Claude API billing](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage)

## Codex

### If you want to use your ChatGPT plan rather than API billing

OpenAI distinguishes Codex usage signed in with ChatGPT from Codex authenticated with your
own API key. If your intention is to use your ChatGPT-plan allowance, start from a shell
without API-key variables and sign in with ChatGPT:

```sh
unset OPENAI_API_KEY CODEX_API_KEY
codex
```

Inside Codex, use:

```text
/status       # confirm current session configuration
/permissions  # keep an approval level you are comfortable with
/model        # choose model/reasoning appropriate to the task
```

This repository already has a root `AGENTS.md`; do **not** run `/init` in a way that
overwrites it. Codex reads `AGENTS.md` as project instructions.

If you intentionally use an OpenAI API key, API pricing applies. For cost control, use a
dedicated API project for your contribution work and configure its spend controls. OpenAI's
current platform supports project/organization spend controls, including enforceable hard
spend limits; alerts by themselves are only notifications. Set the limit before a long
agent run, not after.

Official references:

- [Using Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540)
- [Codex CLI](https://developers.openai.com/codex/cli)
- [AGENTS.md project instructions](https://developers.openai.com/codex/agents-md)
- [Managing API projects and spend limits](https://help.openai.com/en/articles/9186755)
- [Troubleshooting API usage and spend limits](https://help.openai.com/en/articles/6614457)

## ChatGPT

For software-development work, the simplest ChatGPT path is to use **Codex** from ChatGPT
Desktop, Codex CLI, or another Codex surface available on your plan. Plain ChatGPT can still
help you understand an issue, review a diff, write tests, or draft a patch.

If you connect GitHub or another developer service to ChatGPT:

- grant only the repository access you actually need, preferably your fork for write access;
- do not grant upstream write access merely to make a normal contribution;
- review the tool's proposed changes before any push or pull request; and
- check **Settings / Usage** (wording may change) before buying credits or enabling automatic
  purchases.

OpenAI currently documents separately purchased usage credits for eligible ChatGPT agentic
features, including Codex. Included plan usage is used first; after that, eligible features
can draw from a purchased credit balance. If automatic reload is available on your account,
leave it **off** unless you deliberately want automatic purchases. Also note that a maximum
monthly amount configured for automatic reload applies to those automatic reloads; it should
not be treated as a universal cap on separate one-time credit purchases.

Codex and other eligible agentic ChatGPT features can share plan allowances or credits
depending on the plan. A long-running task can therefore consume more usage than a short
chat. Treat any purchase of credits, reset, automatic reload, or extra usage as your own
billing decision, not a YazSes requirement.

Official references:

- [Using credits for flexible usage in ChatGPT](https://help.openai.com/en/articles/12642688)
- [Using Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540)

## Provider-neutral ways to reduce cost and risk

- **One issue per agent session.** Start fresh when you change tasks.
- **Ask for a plan before edits.** Catch an accidental repo-wide refactor before it happens.
- **Keep scope narrow.** More files and more context usually mean more tokens and more review.
- **Use the smallest model/effort that reliably handles the task.**
- **Prefer local tests.** YazSes's normal test suite is offline; contributing does not require
  paid cloud execution.
- **Keep approvals on.** Do not give a first-time agent unlimited shell, network, or repository
  permissions.
- **Never paste secrets.** Do not put API keys, credentials, private data, or payment details
  into prompts, issues, commits, or PRs.
- **Do not send YazSes user/tester data to a cloud agent.** Real recordings, transcripts,
  voiceprints, learning data, research-participant data, and identifying diagnostic logs stay
  local; use synthetic or explicitly de-identified fixtures. The product is offline by
  default, but a cloud development assistant is not.
- **Do not run endless retries.** If the same test fails repeatedly, stop the agent and inspect
  the real failure rather than paying for another loop.
- **Review usage before and after.** Provider dashboards and session status commands are the
  source of truth for your own account.

## What the project will never ask you to do

To contribute, YazSes will never require you to:

- buy an AI plan or API credits;
- enable automatic credit reload or unlimited usage;
- share an API key with a maintainer;
- add a maintainer's payment method to your account;
- give an AI service write access to the upstream repository;
- upload private or employer-confidential material to an AI provider; or
- keep an expensive run going because an issue is labelled "agent-ready".

If a project instruction appears to say otherwise, stop and open a GitHub discussion or issue
before spending money.

## Before you open the pull request

Run the repository checks from [AGENTS.md](../../AGENTS.md), inspect `git diff`, and make sure
you can explain every changed line. In the pull-request template, say which AI tool you used
and what you verified personally.

The human contributor remains responsible for the submitted change; the AI provider remains
responsible for its own service and billing; YazSes remains responsible for reviewing the
contribution under the project's normal rules.
