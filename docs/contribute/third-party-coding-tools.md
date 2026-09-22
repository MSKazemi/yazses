---
title: "Third-party coding tools: accounts, costs, and responsibility"
description: "What contributors need to know before using Jules, Codex, Claude Code, Copilot, Cursor, or another third-party coding service with YazSes."
---

# Third-party coding tools: accounts, costs, and responsibility

Using a coding agent is **optional**. You can contribute to YazSes with Git, GitHub and the normal
development tools without creating or paying for any AI/coding-agent account.

This page is the project's usage notice for third-party developer tools. It is not a replacement for
a provider's current pricing, terms, privacy documentation, or professional legal advice.

## Your provider account is your responsibility

If you choose to use Jules, Codex, Claude Code, Copilot, Cursor, Gemini, or another external service,
you choose and control that provider relationship.

Unless a maintainer has agreed otherwise **in writing before the expense is incurred**:

- YazSes does not buy the subscription for you;
- YazSes does not provide shared paid credentials;
- YazSes does not reimburse subscriptions, API usage, credits, tokens, compute, overages or other
  provider charges;
- the maintainer does not control your provider's billing meter, quota, renewal, upgrade or
  overage behavior;
- a GitHub issue, prompt example, setup guide, label or maintainer suggestion is **not** a promise
  that the third-party service is free;
- a task being marked `agent-ready`, `cloud_agent_ready` or triggered with `jules` does not
  transfer your provider bill to the project.

You are responsible for checking the provider's **current official** pricing and terms before
starting work. Provider pricing, plan limits, included credits and overage behavior can change
without a YazSes repository change.

## Before running a paid or metered tool

Use this checklist:

- [ ] Confirm which provider account/workspace will be charged.
- [ ] Confirm the current plan, included usage and overage behavior on the provider's own site.
- [ ] Set a spending cap, budget alert, usage limit or equivalent control when the provider offers
      one.
- [ ] Disable automatic plan upgrades or overage spending if you do not want them.
- [ ] If the account belongs to an employer, school, client or team, confirm you are authorized to
      use it for this contribution.
- [ ] Know how to stop/cancel the task if it begins consuming more resources than expected.
- [ ] Do not assume an estimate in a YazSes issue is an estimate of provider cost; YazSes task
      estimates are about human scope/review size unless they explicitly say otherwise.

If a provider does not give you adequate cost controls for your situation, use a different tool or
contribute without that service.

## API keys and credentials

Never commit or paste into a public issue, PR, discussion, test fixture or log:

- API keys;
- OAuth tokens;
- GitHub personal access tokens;
- provider session cookies;
- billing/account identifiers that should remain private;
- employer or organization secrets.

Use the provider's credential store, your operating system's secret store, a CI secret, or an
environment variable as appropriate.

For Jules specifically, `JULES_API_KEY` must never be committed. The normal GitHub App workflow
does not require contributors to put an API key in the repository.

If a secret is accidentally exposed, revoke/rotate it at the provider first; deleting the GitHub
text afterwards is not sufficient because repository/history/log copies may already exist.

## Data sent to the coding-tool provider

YazSes's product promise that dictation/audio stays on-device applies to **YazSes runtime behavior**.
It does not mean a third-party coding service is offline.

A cloud coding agent may receive repository files, prompts, diffs, issue text, test output or other
development context according to that provider's service design and your settings.

The repository is public, but your working directory may contain things the repository does not:

- unpublished research data;
- participant data;
- local configuration;
- credentials;
- private forks/submodules;
- personal paths or files.

Do not expose those to an external coding tool unless you are authorized to do so and the relevant
data-handling rules permit it.

Human-subject or participant-level research data must follow the research/consent rules for that
study; an `agent-ready` implementation task is not permission to send participant data to an AI
provider.

## Provider terms and contribution rights

You remain responsible for ensuring that you are allowed to submit the contribution you open.

The YazSes contribution itself is handled under the repository's Apache-2.0 licensing/contribution
rules. Your external coding-tool provider has separate terms governing its service. If those terms,
your employer's policy, or another agreement prevents you from contributing the resulting work,
do not submit it until that conflict is resolved.

The project does not make representations about a third-party provider's service, uptime, security,
output quality, pricing or legal terms.

## No tool is required for acceptance

Review is based on the contribution:

- scope;
- correctness;
- tests/evidence;
- privacy/security;
- architecture;
- licensing;
- maintainability.

A contributor does not receive preference for using a paid agent, and nobody is required to purchase
one to complete a YazSes contribution.

Where a task requires human/device/native-language evidence, paying for a more capable coding agent
does not replace that evidence.

## Where to get provider help

For billing, account access, service outages, quotas, refunds, plan changes or provider-side
permissions, use that provider's official support and documentation.

YazSes documentation can explain how the repository is structured for a tool, but it cannot
authoritatively answer what a provider will charge your account today.

For Google Jules repository setup specifically, see [Using Google Jules with YazSes](jules.md).

## Project boundary

Opening an issue, publishing an agent-ready task, linking to a third-party tool, or documenting a
sample command does not create an agency, employment, reimbursement, procurement or paid-service
relationship between the contributor and the YazSes maintainer.

If the project ever intentionally sponsors a contributor's third-party-tool cost, that arrangement
must be agreed separately and explicitly before the cost is incurred.
