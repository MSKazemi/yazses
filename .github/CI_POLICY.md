# CI/CD operating policy

**Status:** project CI contract  
**Applies to:** GitHub Actions, validation scripts, release/publishing automation, and contributors or coding agents that modify them  
**Programme:** #539

This document defines how YazSes CI/CD should behave as the repository grows beyond a
single-maintainer project. It is intentionally stricter than “the YAML runs”: a workflow
must have a clear role, a bounded cost, a security model, and a failure meaning.

The goal is not to run every possible check on every commit. The goal is to produce the
right evidence early, preserve stronger evidence for main and releases, and make obsolete
work leave the queue quickly.

---

## 1. The five CI lanes

Every workflow belongs to one primary lane. If a new workflow does not fit one of these
lanes, document why before adding it.

| Lane | Purpose | Typical trigger | Blocking on PR? | Cancellation rule |
|---|---|---|---|---|
| Fast PR gate | Cheap, decisive contributor feedback | pull request | yes | newest PR head wins |
| Full validation | Cross-platform/runtime confidence | scoped PR, main, manual | yes when selected | newest PR head wins; main evidence is durable |
| Specialized platform | Android, macOS, Windows, packaging surfaces | scoped PR/main/manual | only when relevant | newest PR head wins |
| Scheduled assurance | fuzzing, links, heavy extras, drift, scorecard | schedule/manual | no ordinary PR blocking | one intentional run at a time where useful |
| Release/publish | produce or publish user-facing artifacts | tag/manual/release events | release gate | never cancelled merely because a newer PR exists |

A workflow name is not a lane. For example, CodeQL is security assurance but participates
in PR validation; a release workflow may contain validation steps but still belongs to the
release/publish lane because its permissions and failure consequences are different.

---

## 2. Pull-request concurrency is a repository invariant

Any workflow triggered by pull_request that can consume a runner must declare an explicit
concurrency policy.

The default rule is:

- runs for different pull requests do not cancel each other;
- a newer head of the same pull request cancels the older run;
- tag, main, release, and manual runs are not accidentally grouped with PR runs;
- cancellation is not used to hide a deterministic failure.

For workflows that also run on tags, main, or workflow_dispatch, use the pull-request
number only for PR grouping and a unique/non-PR identity for durable runs.

tests/test_workflow_concurrency.py is the executable guard for this contract.

pull_request_target is different. It carries a more privileged security posture and must
not be treated as interchangeable with pull_request. A pull_request_target workflow must
never check out or execute contributor-controlled code unless the security design
explicitly proves that path safe.

---

## 3. Validate before deploy

A publish/deploy workflow must not discover preventable source errors only after merge.

Documentation is the canonical example:

1. a docs/design PR runs the same strict MkDocs build used by main;
2. privacy/site-output checks run on the PR;
3. PR runs do not receive Pages write or OIDC deployment permission;
4. only main/manual deployment runs graft deployment-only content, upload the Pages
   artifact, and deploy.

The same pattern should be used for package manifests and release metadata: validate the
publishable shape before the event that has permission to publish it.

---

## 4. Change classification and fail-safe routing

The repository is moving toward a tested change classifier in #534.

The intended classes are:

- docs/design;
- Python runtime/core;
- tests;
- Android;
- macOS;
- Windows/MSIX;
- packaging/channels;
- workflow/security;
- release/publishing;
- unknown.

A file may belong to multiple classes.

The safety rule is simple: **unknown means more validation, never less**.

Do not optimize CI by adding a broad paths-ignore to the only stable required check.
Path-scoped jobs are acceptable only when an always-present aggregate/fast gate can explain
the result and GitHub branch protection still has one stable status to require. The stable
aggregate gate is tracked in #462.

---

## 5. Fast feedback before expensive confidence

The target PR experience in #535 is two-stage.

### Fast lane

Target: useful result within 10 minutes after a runner starts.

It should contain checks such as:

- repository hygiene;
- generated index/file drift;
- lint and inexpensive static analysis;
- workflow contract tests;
- documentation/design consistency;
- a small Linux runtime smoke set;
- change-classification validation.

A fast lane failure should normally stop a human reviewer from waiting for the expensive
matrix to tell them the same PR is broken.

### Full lane

The current Python OS/interpreter matrix remains valuable for runtime changes. It should
not be the first or only answer for a typo-only documentation change.

Full validation is required when:

- runtime/core code changes;
- dependency or interpreter behavior changes;
- tests change in a way that can alter coverage meaning;
- CI/workflow policy changes;
- the change classifier cannot classify a path safely;
- a maintainer explicitly requests a full run;
- main/release policy says it is required.

Optimization must preserve evidence, not redefine green.

---

## 6. Stable branch-protection surface

Do not require dozens of matrix-generated job names individually in repository rules.

The target is one stable aggregate status, tracked in #462, whose result reflects all
blocking jobs selected for that change.

That aggregate gate must:

- have a stable name;
- fail/non-success when a blocking dependency fails or is cancelled unexpectedly;
- distinguish advisory jobs from blocking jobs deliberately;
- be covered by a repository test so dependencies cannot disappear silently;
- remain present even when specialized lanes are conditionally skipped.

Live repository rules are an administrative control. Source changes may prepare and test
the gate, but changing the live GitHub ruleset must be recorded in the governing issue.

---

## 7. Permissions and untrusted input

Top-level workflow permissions default to read-only unless a job proves it needs more.

Rules:

1. Grant write permissions at the narrowest job boundary.
2. A validation job does not need release, Pages, package, or signing permissions.
3. Fork PRs must not receive repository secrets.
4. Contributor-controlled text must enter scripts through data channels such as
   environment variables or files, not direct expression interpolation into shell code.
5. pull_request_target workflows must not execute contributor code.
6. Publishing credentials belong only in release/deploy jobs that need them.
7. OIDC is preferred where the external service supports it.
8. Third-party actions remain commit-SHA pinned.

A faster workflow is not an improvement if it broadens the token or secret boundary.

---

## 8. Timeouts, caches, and repeated setup

#537 owns the implementation programme.

### Timeouts

Every expensive job should have an intentional timeout-minutes value.

The timeout should be:

- longer than healthy p95 runtime plus reasonable runner variance;
- short enough to terminate a hung installer/build;
- reviewed when telemetry shows healthy work frequently approaches the limit.

Do not raise a timeout to hide a hang without identifying why runtime changed.

### Caches

A cache key must include every property that changes compatibility, including as relevant:

- operating system;
- architecture;
- interpreter/runtime version;
- lockfile or manifest hash;
- toolchain version.

Restore keys must not allow incompatible artifacts to cross architecture/interpreter
boundaries.

A cache miss is a performance event, not a correctness failure. A poisoned or incompatible
cache is a correctness risk.

### Reuse

Extract stable, non-secret setup first. Keep signing, publishing, and permission-sensitive
steps explicit until a reusable boundary can preserve their security model clearly.

The purpose of reuse is preventing policy drift, not minimizing line count.

---

## 9. Flakes, reruns, advisory jobs, and experimental legs

#538 owns the detailed implementation.

Current policy:

- a blocking failure is a failure until explained;
- one diagnostic rerun can distinguish an infrastructure/transient event from a
  deterministic failure;
- repeated blind reruns are not a fix;
- a test is not called flaky because it passed once on retry;
- a quarantine needs a linked issue, owner, reason, and review/expiry point;
- quarantined coverage stays visible;
- continue-on-error requires an explicit reason and a promotion/removal condition.

Advisory platform coverage must remain honest. A green advisory job is useful evidence, but
it must not be described as a blocking guarantee if the workflow permits failure.

FreeBSD-specific limitations remain tracked in #306 rather than being hidden by retries.

---

## 10. Scheduled assurance is not PR noise

Scheduled jobs exist to catch classes of failure that do not need to delay every
contributor:

- newly-published security/query findings;
- fuzz failures;
- heavy optional dependency breakage;
- outbound link rot;
- channel/version drift;
- supply-chain posture changes.

Scheduled workflows should:

- have bounded runtime;
- avoid overlapping identical work when overlap has no value;
- create actionable summaries/artifacts;
- link a persistent failure to an issue rather than remaining silently red forever.

A scheduled check that has never run does not provide assurance merely because its YAML
exists.

---

## 11. Release and publishing lane

Release workflows are intentionally conservative.

Requirements:

- release/tag inputs are immutable or explicitly versioned;
- build provenance/attestations remain attached where supported;
- signing and publishing permissions are job-scoped;
- PR optimization cannot skip release validation;
- release workflows are never grouped into a PR cancellation key;
- artifact names include architecture/platform where ambiguity would be unsafe;
- a workflow that claims to publish a supported channel must have a trigger that can
  actually fire for the current version line;
- manual recovery steps are documented for external service failures.

Release failures should be treated as user-facing incidents because the output may already
be partially visible across package channels.

---

## 12. CI service-level objectives

#536 will automate measurement. Until there is enough history, these are targets rather
than guarantees.

| Metric | Initial target |
|---|---|
| Fast PR gate queue delay p95 | under 5 minutes |
| Fast PR gate execution p95 | under 10 minutes |
| Superseded PR head cancellation | within 2 minutes |
| Deterministic main failure without linked owner/issue | under 24 hours |
| Unexplained scheduled workflow red state | under 7 days |
| Release/publish failure acknowledgement | same working day |

Do not optimize for a single average. p95 and worst recurring outliers matter because they
describe the contributor experience during busy periods.

Telemetry must not collect contributor email addresses, arbitrary PR bodies, secrets, or
full logs merely to compute timing metrics.

---

## 13. CI incident response

When Actions becomes heavily queued or broadly red:

1. **Establish scope.** Is the problem queue capacity, one workflow, one branch, or main?
2. **Separate obsolete from current.** Check whether failures belong to old PR heads.
3. **Find the first deterministic error.** Do not diagnose from the final red matrix count.
4. **Check shared invariants.** Generated indexes, nav/manifest drift, lockfiles, and
   repository-wide guards can fail many OS legs identically.
5. **Preserve current heads.** Do not cancel the newest run for an open PR merely to make
   the UI quieter.
6. **Prefer structural correction.** Add cancellation/validation policy rather than
   repeatedly clearing symptoms.
7. **Record cross-PR conflicts.** Shared identifiers such as ADR numbers are repository
   coordination problems, not CI flakes.
8. **Link persistent incidents to issues.** A red main branch needs an owner and next
   action.

The September 2026 queue storm is the reference case: superseded PR runs were the dominant
capacity problem, while several red matrices shared one deterministic generated-doc
failure.

---

## 14. Coding-agent rules

Coding agents are welcome execution tools, but CI policy is part of the repository
architecture.

An agent changing CI must:

- read this file and AGENTS.md first;
- inspect existing workflow-contract tests before editing YAML;
- preserve SHA pinning and least privilege;
- avoid introducing a new write-token pull_request_target execution path;
- add or update a regression test for a policy change;
- keep rapid intermediate commits on a PR safe to cancel;
- not interpret cancellation of an obsolete head as a product failure;
- not rerun failing checks repeatedly to manufacture green;
- explain any new secret, permission, runner class, or paid external service in the PR.

Agents should prefer small CI PRs with one policy purpose. Large generated batches are
exactly why cancellation and stable gates are necessary.

---

## 15. New-workflow review checklist

Before merging a new or substantially changed workflow, answer all of these in the PR:

- [ ] Which lane does it belong to?
- [ ] What event(s) trigger it?
- [ ] If it runs on PRs, what is its superseded-head cancellation policy?
- [ ] What makes it blocking versus advisory?
- [ ] What permissions does it request, and why?
- [ ] Does it execute untrusted contributor input?
- [ ] Does it expose secrets or OIDC?
- [ ] What is its timeout?
- [ ] What caches/artifacts does it read or write?
- [ ] Which test prevents its trigger/permission/concurrency contract from drifting?
- [ ] What happens on a docs-only or unrelated PR?
- [ ] What happens on main?
- [ ] What happens on a release/tag?
- [ ] Who owns a persistent failure?

If those questions do not have short answers, the workflow is not ready to become project
infrastructure.

---

## 16. Scale-hardening roadmap

The coordination issue is #539.

- #523 — repair current strict docs link failure.
- #534 — tested change classifier and fast-gate contract.
- #535 — split fast and full PR lanes without coverage loss.
- #536 — CI telemetry and SLO reporting.
- #537 — reusable setup, cache rules, and timeouts.
- #538 — flake/rerun/quarantine policy.
- #462 — stable aggregate gate and main ruleset hardening.
- #306 — FreeBSD advisory-job dependency/toolchain limitation.

The order matters: first stop obsolete work and move validation before deployment; then
classify changes; then optimize lanes; then enforce the stable gate at the repository
ruleset layer; measure the result throughout.
