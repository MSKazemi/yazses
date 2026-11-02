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

The classifier is `scripts/classify_changes.py` (#534): a standard-library script that maps the
changed paths of a pull request to the classes below, pinned by `tests/test_classify_changes.py`.
`test.yml` reads its one routing decision, `full`, to choose the lane (section 5, #535).
Callers must list changed files with `git diff --name-only --no-renames`, or a file moved out of
`src/` would show only its new name and lose its runtime scope.

The classes are:

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
aggregate gate is `ci-gate` in `test.yml` (§6.1, #462). That is why `test.yml` itself must
never gain a path filter.

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

### How `test.yml` implements it (#535)

| Job | Lane | Runs when |
|---|---|---|
| `changes` | fast | every run; decides `full` |
| `repo-hygiene` (size, translations, ruff, dependency budget, CI contract and generated-file drift tests) | fast | every run |
| `test-linux`: the whole suite on ubuntu-latest / 3.12 | Linux baseline | every run |
| `test` (the rest of the OS/interpreter matrix), `gui`, `extras` | full | `full` is not `false` |
| `freebsd`, `windows-update-handoff` (both advisory) | full | `full` is not `false` |
| `ci-gate` | aggregate | always; see section 6 |

`full` is `false` only when every changed path classifies as `docs_design` or `android`
(`BASELINE_ONLY` in `scripts/classify_changes.py`). Everything else takes the full lane:
`unknown`, runtime, tests, workflows, packaging, release. So does a push to main, a
manual `workflow_dispatch` run (the escape hatch), and a PR labelled `ci:full`. The label
is read from the event, so after adding it, push a commit or close and reopen the PR.
The classifier is itself `workflow_security`, and so is `test.yml`, which holds the
gate's verdict, so a change to the code that picks the lane or judges it always takes the
full lane.
A change that skips the full lane loses no test: the Linux baseline still runs the whole
suite, including every test that reads `docs/`, `design/` or `android/`.

The fixtures below are pinned by `tests/test_ci_lanes.py`. Every row also runs the fast
lane, the Linux baseline and `ci-gate`, plus the workflows that have no path filter
(CodeQL, dependency review, the labeler, campaign preflight).

| Fixture | Scopes | Full lane | Path-filtered workflows | Why |
|---|---|---|---|---|
| Typo-only docs PR | `docs_design` | no | `docs.yml` | the strict site build and the Linux suite cover it |
| New ADR / design page | `docs_design` | no | `docs.yml` | same |
| Python runtime change | `python_core` | yes | — | runtime behaviour differs by OS and interpreter |
| Test-only change | `tests` | yes | — | a changed test can change what the matrix proves |
| Windows packaging change | `windows`, `packaging` | yes | `build-windows.yml`, `msix-validate.yml` | packaging is not baseline-only |
| Android change | `android` | no | `android-test.yml` | no Python behaviour changes; Gradle tests run |
| Workflow/security change | `workflow_security` | yes | — | CI policy changes get full validation |
| Previously unseen top-level path | `unknown` | yes | — | unknown means more validation |

A root file such as `README.md` is `unknown` (#534), so a docs PR that also touches one
takes the full lane.

---

## 6. Stable branch-protection surface

Do not require dozens of matrix-generated job names individually in repository rules.

The target is one stable aggregate status, tracked in #462, whose result reflects all
blocking jobs selected for that change. For `test.yml` that status is `ci-gate`
(#462; lane-aware since #535). Making it required in the live ruleset is #462's Part B.

That aggregate gate must:

- have a stable name;
- fail/non-success when a blocking dependency fails or is cancelled unexpectedly;
- distinguish advisory jobs from blocking jobs deliberately;
- be covered by a repository test so dependencies cannot disappear silently;
- remain present even when specialized lanes are conditionally skipped.

Live repository rules are an administrative control. Source changes may prepare and test
the gate, but changing the live GitHub ruleset must be recorded in the governing issue.

### 6.1 The gate: `ci-gate` in `test.yml`

The aggregate gate is the `ci-gate` job at the end of `.github/workflows/test.yml`. Its
check name is `ci-gate`, reported by the GitHub Actions app (integration id `15368`).

| Property | How it holds |
|---|---|
| Stable name | `name: ci-gate`, no matrix. No other workflow may report a check of that name. |
| Depends on, does not re-run | `needs:` lists the blocking jobs; the one step reads `toJSON(needs)` from an env var and checks nothing out. |
| Blocking vs advisory | A job is **advisory exactly when it declares a literal `continue-on-error: true`** (today: `freebsd` and `windows-update-handoff`). Every other job in `test.yml` is blocking and must be a need. |
| Fails on failure, cancellation, skip | It passes only when every need's `result` is `success`, except that a full-lane job may be `skipped` when the lane decision (`needs.changes.outputs.full`) is literally `false` (section 5). A decision that is neither `true` nor `false`, and empty or unparsable input, fail it too. |
| Cannot itself skip | `if: always()`. A skipped required check counts as passed ([GitHub docs][skip]), so `!cancelled()` or a path condition would let it pass without evidence. |
| Never pending forever | `test.yml` has no `paths`/`paths-ignore` filter, so every PR to `main` gets the check. Path-scoped workflows (docs, Android, macOS, Windows packaging) stay outside the gate and are not required. |

`tests/test_ci_gate.py` enforces every row. It **derives** the blocking set from the
workflow file instead of listing it, so a new job in `test.yml` fails the suite until it
is either a need or deliberately advisory. It also runs the embedded verdict script
against success, failure, cancelled, skipped, empty and malformed `needs` payloads.

[skip]: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-jobs-with-conditions

Rules for changing it:

- **Adding a job to `test.yml`:** add it to `ci-gate.needs`, or make it advisory with
  `continue-on-error: true` plus the reason and promotion condition that §9 requires.
- **Making a blocking job conditional** (a job-level `if:`, such as path scoping): the gate
  fails a skipped need, so first teach the gate which skip is legitimate and add a test.
  The suite rejects a conditional blocking job until then. The one such allowance today
  is the full lane (#535): a job whose `if:` is exactly
  `needs.changes.outputs.full != 'false'` is in the verdict script's `FULL_LANE` set, and
  `tests/test_ci_lanes.py` fails if the set and the gated jobs disagree in either
  direction.
- **Advisory legs inside a blocking matrix:** the `test` matrix's arm64 leg uses an
  expression-valued `continue-on-error`, so the `test` job is still a need. GitHub does
  not document how such a leg's failure appears in `needs.test.result`. If it appears as
  `failure`, the gate fails closed. Arm64 last passed in run
  [39471109286](https://github.com/MSKazemi/yazses/actions/runs/39471109286). If it
  starts failing, promote the leg to blocking or move it into its own advisory job. Do not
  weaken the gate.
- **Workflows other than `test.yml`** (CodeQL, docs, dependency review, campaign preflight)
  are not needs, because `needs` cannot cross workflows. They stay visible and remain
  unrequired, as they are today. To require one, make it always-present and give it a
  stable name first. Do not add a path-filtered workflow to the ruleset.
- **Integrity boundary:** a pull request runs its own copy of `test.yml`, so a PR could
  edit the gate. The ruleset cannot stop that. Human review of any PR touching
  `.github/workflows/` can (CODEOWNERS, REVIEWING.md, ADR-024 §10). Pinning
  `integration_id` only stops a different app from posting a fake `ci-gate` status.

### 6.2 Owner step: require `ci-gate` on `main` (issue #462 Part B)

This is an administrative action. Agents prepare it and do not apply it. Apply it only
after `ci-gate` has reported on at least one ordinary PR **and** on `main` (Part B: "after
the aggregate check is proven"). PRs opened before the gate merged have no `ci-gate`
check, so their head must be updated before they can merge.

**That precondition is met (read on 2026-10-30).** `ci-gate` has reported from the GitHub
Actions app (`app.id` 15368) on `main` and on ordinary PRs. Every path the gate decides
has occurred live:

| Case | Run | Result |
|---|---|---|
| `main` push (4fda3403) | [40964872494](https://github.com/MSKazemi/yazses/actions/runs/40964872494) | `ci-gate` success |
| Blocking jobs red (PR #730) | [40965213978](https://github.com/MSKazemi/yazses/actions/runs/40965213978) | ten `test` legs failed, so `ci-gate` failed |
| Only an advisory job red (PR #732) | [40995314982](https://github.com/MSKazemi/yazses/actions/runs/40995314982) | `freebsd` failed and `ci-gate` succeeded |
| Fast lane (PR #731) | [40966653407](https://github.com/MSKazemi/yazses/actions/runs/40966653407) | `changes`, `repo-hygiene` and `test-linux` succeeded; the full-lane jobs were skipped; `ci-gate` succeeded |

The arm64 question in §6.1 is still open. In run 40965213978 every `test` leg failed, so
that run does not show how an arm64-only failure appears in `needs.test.result`.

The live ruleset as read on 2026-10-20 and again, unchanged, on 2026-10-30
(`gh api repos/MSKazemi/yazses/rulesets/20550886`): `main: no force-push, no delete`,
target `~DEFAULT_BRANCH`, rules `deletion` and `non_fast_forward`, **`bypass_actors: []`**.

The change keeps both existing rules and adds `pull_request` and `required_status_checks`.
`PUT` replaces the whole rule list, so the payload repeats the two existing rules:

```json
{
  "name": "main: PR + ci-gate, no force-push, no delete",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }
  ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false } },
    { "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "do_not_enforce_on_create": false,
        "required_status_checks": [ { "context": "ci-gate", "integration_id": 15368 } ] } }
  ]
}
```

Apply it (owner, personal account):

```sh
GH_TOKEN=$(gh auth token --user MSKazemi) \
  gh api -X PUT repos/MSKazemi/yazses/rulesets/20550886 --input ruleset-main.json
```

Or use Settings → Rules → Rulesets → `main: no force-push, no delete`. Turn on "Require a
pull request before merging" with 0 approvals, and "Require status checks to pass" with
`ci-gate`, source GitHub Actions. Leave force-push and deletion blocked.

Each choice in the payload is deliberate and needs the owner's decision:

- **`required_approving_review_count: 0`.** The issue says not to invent self-approval
  with one maintainer. Review responsibility stays in REVIEWING.md and GOVERNANCE.md.
  Revisit this when the maintainer set changes.
- **Bypass actor = repository admin role (`actor_id` 5; check the id in the UI).** Today
  the ruleset has **no** bypass actors. Requiring PRs with an empty bypass list would
  also stop the owner's direct pushes to `main`. `bypass_mode: "always"` keeps those
  pushes working as a documented admin bypass. `"pull_request"` limits the bypass to
  merging a PR whose checks are red. An empty list makes the owner go through PRs too.
  A central agent's GitHub App is not a repository admin, so none of these options lets
  the agent push to `main`. Do **not** add the agent's App as a bypass actor.
- **`strict_required_status_checks_policy: false`.** A PR does not have to be rebased on
  the latest `main` before it merges. Setting it to `true` is stricter, but it re-runs the
  full matrix whenever `main` moves.
- **No merge queue and no auto-merge.** If a merge queue is turned on later, `test.yml`
  needs a `merge_group:` trigger first. Without one, `ci-gate` never reports for the
  queue.

Verify the change by reading it back: `gh api repos/MSKazemi/yazses/rulesets/20550886`.
Then run the validation in #462 on a disposable PR. A red blocking job must make `ci-gate`
fail. A green set must make it pass. A direct push to `main` from a non-bypass identity
must be rejected. Record the final ruleset JSON in #462.

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

**How the number is chosen.** Every job in every workflow declares one, set by the first
rule that fits, and its comment in the workflow says which:

1. **A job that waits for other workflows by design** (`checksums`, `publish-channels`'
   `wait-for-assets`, `release-complete`, `docker` on a release): the sum of its own wait
   deadlines plus 15 minutes, rounded up to 5. Its deadline decides what a slow build
   costs (`checksums` hashes what arrived rather than failing), so the runner must never
   cancel the job first. The `docker` job's limit also covers the Dockerfile's own 10-minute pip retry,
   which is not in a step shell, so the test cannot read it: change them together.
2. **A job that does its own work:** three times its slowest successful run among the last
   15, rounded up to 5, and never under 10 minutes.
3. **A job with no measured run of its real work yet** (a publish step still waiting on
   its credential, a dispatch-only job that has not run): 30 minutes, revisited once it
   has runs.

`test.yml` jobs also stay at or under 60. `tests/test_ci_job_timeouts.py` fails for any job
without a limit, and for a waiting job whose limit is less than 10 minutes above its own
deadlines. It reads those deadlines from the step shell (`SECONDS + N`, and `seq 1 N`
around a `sleep`), so lengthening a wait without the limit fails there, not on a release.

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

**The uv cache.** Every job that installs uv through `astral-sh/setup-uv`, directly or
through the composite below, also gets setup-uv's built-in cache: its `enable-cache` input
defaults to `auto`, which is on for GitHub-hosted runners. Read from setup-uv's source at
the pinned commit (`c18668ad`, v10.2.0, `src/cache/restore-cache.ts`), the key is
`setup-uv-2-<arch>-<platform>-<OS image>-<interpreter>-<hash of pyproject.toml, uv.lock
and requirements files>`, and it is restored by exact match only. There is no restore-key
prefix, so no entry can cross an architecture, OS image or interpreter. The uv version is
not in the key. This repository accepts that because uv keeps one versioned bucket per
cache format, and a different uv reads only its own buckets. A local cache read on
2026-10-30 held `wheels-v6` and `wheels-v7` side by side. Two jobs that sync different
extras share a key when they share an OS image and an interpreter. The first to save wins,
and a job that hits does not save, so the other job downloads its extra wheels again. That
costs time, not correctness. `tests/test_ci_composite_actions.py` fails if the composite
passes setup-uv any input besides `version` and `python-version`. Whoever changes that
also updates this paragraph and the test together.

**`actions/cache` steps** (1 on 2026-11-01, counted with `git grep`): the docs' mirrored
web fonts in `docs.yml`. It holds data, not built code. The font mirror runs on Linux
only, and its restore-key prefix can only match that one family. The LibriSpeech corpus
and Whisper checkpoint caches that `benchmark.yml` held (3 steps on 2026-10-30) left with
that workflow in 2.47.0.

### Artifact retention

An `actions/upload-artifact` step states `retention-days`. Without it the artifact lives
for the repository's setting, which was 90 days (the maximum) when read on 2026-10-30
with `gh api repos/MSKazemi/yazses/actions/permissions/artifact-and-log-retention`.
Nobody chose that number for any particular artifact. Pick the value by what the
artifact is for:

| Artifact | Retention | Examples today |
|---|---|---|
| A copy of a report that the same run also sends somewhere durable | 5 days | Scorecard SARIF, which also goes to code scanning |
| Build output a person downloads to try, or a periodic report | 14 days | macOS and Windows bundles, snaps, CI telemetry |
| Evidence someone may compare against weeks later | 30 days | eye-eval records, packs spike, traceability |

On 2026-10-30, 9 of the 15 upload steps stated a value, and 6 inherited the default. Those
6 are listed in `INHERITS_DEFAULT` in `tests/test_ci_artifact_retention.py`. The list
compares both ways, so a new upload without `retention-days` fails the suite. It also
fails when one of the 6 gains a value but keeps its entry. The test requires a literal
integer from 1 to 90.
The six are not changed here. One is the release `.deb`, and a lifetime is a storage and
release decision for its owner. `actions/upload-pages-artifact` is not covered by this
rule, because the Pages deploy consumes it in the same run.

### Reuse

Extract stable, non-secret setup first. Keep signing, publishing, and permission-sensitive
steps explicit until a reusable boundary can preserve their security model clearly.

The purpose of reuse is preventing policy drift, not minimizing line count.

**The rule for new Python jobs.** A new CI job that installs the project uses the
repository-owned composite action `.github/actions/setup-uv-python`. It installs uv, pins
the interpreter with `python-version` (required, never left to the runner image), and runs
`uv sync` with extra arguments in `sync-args`. The action holds no secret, no permission
block and no `actions/cache` step, so the calling job keeps every decision about tokens and
its own caches. setup-uv's built-in uv cache does apply ("Caches" above). A job that
cannot use the composite is listed, with the reason, in `DIRECT_SETUP_UV` in
`tests/test_ci_composite_actions.py`. A new direct call fails the suite until it is listed.

**The rule for caches, timeouts and retention.** A cache decision has one rule: the key
includes every property listed under "Caches" above, and it lives in the job that uses it.
A timeout decision has one rule: the numbered rule under "Timeouts" above. An artifact's
lifetime has one rule: the table under "Artifact retention" above. A job that deviates
from any of them states which property it changes in a comment beside the key, the limit
or the `retention-days`.

### Repeated setup

This is a measurement, not a standing fact: the counts are from 2026-10-30, on the tree
that migrated the second batch of jobs (base `origin/main` 4fda3403). Each count is the
number of matching lines across `.github/workflows/*.yml`. The file count is how many
files contain at least one. To repeat it:

```sh
git grep -h "uses: astral-sh/setup-uv@" -- .github/workflows | wc -l
git grep -l "uses: astral-sh/setup-uv@" -- .github/workflows | wc -l
git grep -hE '^\s*(- )?(run: )?uv sync' -- .github/workflows | wc -l   # commands, not comments
```

| Setup step | Before (4fda3403) | After | Status |
|---|---:|---:|---|
| `uses: ./.github/actions/setup-uv-python` | 3 lines, 2 files | 9 lines, 3 files | `test-linux`, `test`, the `docs` build, and now `repo-hygiene`, `gui`, `extras`, `windows-update-handoff` and `heavy-extras`. |
| `uses: astral-sh/setup-uv@` | 16 lines, 9 files | 10 lines, 7 files | `test.yml` has none left. Each remaining job is listed with its reason in `DIRECT_SETUP_UV` in `tests/test_ci_composite_actions.py`: release and build lanes, `macos-smoke.yml` (no sync step of its own), and `eye-eval-ci.yml` (its own test pins the setup step's shape; next to migrate). |
| `uv sync` as a command | 12 lines, 6 files | 6 lines, 4 files | The rest are in `eye-eval-ci.yml`, `packs-spike.yml` and `release.yml`. |
| `uses: actions/checkout@` | 49 lines, 33 files | unchanged | Not extracted. `fetch-depth` and `filter` differ per job, and the comments beside them explain why. |
| `sudo apt-get update` | 8 lines, 5 files | unchanged | Not extracted. Each job's package list differs. |
| `sudo apt-get install` | 10 lines, 6 files | unchanged | Not extracted, for the same reason. |
| `uses: actions/setup-python@` | 4 lines, 4 files | unchanged | Not extracted. These jobs (`fuzz`, `link-check`, `traceability`, `dependabot-sbom`) use pip or only the standard library, not uv. Moving them to uv would change behaviour, so it is not a setup extraction. |
| `uses: actions/cache@` | 3 lines, 2 files | unchanged | Not extracted. Keys are job-specific and stay beside the job that uses them ("Caches" above). |

The counts in this table are the 2026-10-30 measurement. `benchmark.yml` and the
`benchmark-harness` job left the repository in 2.47.0 and are no longer named in the
status column, so the "After" counts no longer hold. Run on 2026-11-01, the commands above give 10 lines in 4 files for the
composite, 9 lines in 6 files for direct `astral-sh/setup-uv@`, 5 lines in 3 files for
`uv sync` as a command, and 1 line in 1 file for `actions/cache@`.

**Why the second batch is the same uv and the same interpreter.** Those six jobs passed no
`version` to setup-uv, and five of them passed no `python-version` either. The composite
passes `latest` and, here, `"3.12"`. Their logs on `main` before the change show what they
resolved to. On run 40964872494 (4fda3403, 2026-10-29), `repo-hygiene`, `gui` (both OSes),
`extras` and `windows-update-handoff` each logged "Could not determine
uv version from uv.toml or pyproject.toml. Falling back to latest." and installed uv
0.13.6. `test-linux`, which passes `latest`, installed the same 0.13.6. `heavy-extras` (run
40312521603, 2026-10-26) logged the same fallback. setup-uv's resolver at the pinned commit
(`src/version/version-request-resolver.ts`) falls back to `latest` only when there is no
`version` input and neither `uv.toml` nor `pyproject.toml` names a uv version. Neither does.
The unpinned Linux jobs ran CPython 3.12.3 from `/usr/bin/python3`, the same interpreter
`test-linux` gets with `3.12`. The unpinned Windows `gui` leg ran CPython 3.12.10 from the
tool cache, the same as the pinned `windows-update-handoff`. One thing does change: the uv
cache key now names `3.12` instead of `3.12.3`, so these jobs share a cache entry with
`test-linux` ("Caches" above).

**Runtime evidence.** #537 asks for before/after timings. This change removes repeated
lines and resolves the same uv and interpreter as before, so no runtime change is
expected. That is a prediction, not a measurement, and it stays one until CI runs on the
change. Compare the setup steps of the six jobs on the first `main` run after it merges
against run 40964872494.

---

## 9. Flakes, reruns, advisory jobs, and experimental legs

Issue #538 set this policy. Contributors and agents have one response to a red check, and
a temporary exception cannot turn into a permanent gap that nobody sees.

Summary:

- a blocking failure is a failure until explained;
- one diagnostic rerun can distinguish an infrastructure/transient event from a
  deterministic failure;
- repeated blind reruns are not a fix;
- a test is not called flaky because it passed once on retry;
- a quarantine needs a linked issue, owner, reason, and expiry date;
- quarantined coverage stays visible;
- continue-on-error requires an explicit reason and a promotion/removal condition;
- flaky tests and runner/service incidents are tracked separately.

`tests/test_flake_policy.py` enforces the parts a machine can check (§9.3, §9.4). The
rules are in `tests/flake_policy.py`, a standard-library module, and the pytest side is
in `tests/quarantine_plugin.py`.

### 9.1 The response to a red blocking check

1. **Read the first failure.** Open the failed job and find the first failing test or
   step. Do not work from the count of red legs. When every OS fails in the same test, the
   cause is almost always one deterministic shared invariant (§13).
2. **Classify it** as one of:
   - **deterministic**: the change, or `main`, is broken. Fix it or revert. It is not
     flaky, and no rerun is needed to know that.
   - **runner/service incident**: the runner, network, package index or GitHub itself
     failed (a cancelled setup, an index 5xx, a lost runner, a download timeout before any
     test ran). See §9.5.
   - **suspected flake**: a test failed with no code change that explains it, and the
     failure is in the test or the code it exercises, not in infrastructure.
3. **One diagnostic rerun** is allowed for the second and third classes. Rerun **only the
   failed jobs**, once, and record what it showed. A pass after one rerun does not prove a
   flake. It proves only that the failure is not deterministic on that runner, so the
   failure still needs the issue in §9.2.
4. **No second blind rerun.** If the rerun fails again, treat it as deterministic until
   shown otherwise. If you rerun more than once, write down each attempt and what changed
   between attempts. Rerunning until green is not a fix, and agents must never do it
   (§14).
5. **Explain it before you merge.** A red blocking check is merged past only once it is
   explained. Write the explanation in the PR, or in the issue for a red `main`, with the
   run id. A rerun that came back green without an explanation counts as unexplained.

### 9.2 Calling a test flaky

A test is **flaky** only when the same commit both passed and failed it, and nothing in
the environment explains the difference. Record that evidence in an issue labelled
`ci:flaky-test` (the label is an owner step; see #538): both run ids, the failing
assertion, and the platform and interpreter. One green retry is not enough to call a test
flaky. Neither is "it passes on my machine".

The issue is the work item. A flake costs every later contributor time, and it teaches
people to ignore red, so it is fixed or quarantined, not left to recur.

### 9.3 Quarantine

A quarantine lets a known-flaky test run without blocking while its issue is worked on. A
quarantine is valid only if it has all of the following:

| Requirement | How it is enforced |
|---|---|
| a linked issue | the marker's `issue=` must be a positive issue number |
| an owner | `owner=` is the GitHub login that is responsible for closing it |
| a reason | `reason=` says what fails and how often |
| an expiry | `expires=` is an ISO date no more than 90 days ahead |
| registration | `tests/quarantine.toml` has an entry with the same four values |

```python
@pytest.mark.quarantine(issue=1234, owner="MSKazemi",
                        reason="times out about 1 run in 40 on windows-latest",
                        expires="2026-12-01")
def test_reads_the_socket(): ...
```

The marker is allowed only as a decorator on a test function or class. It is not allowed
in `pytestmark`, `pytest.param` or `add_marker`, because the registry must name exactly
what each quarantine covers.

**Quarantined coverage stays visible.** A quarantined test **still runs**. A failure in
its call phase is reported as `XFAIL` with its issue, owner and expiry. A pass is reported
as a pass. Setup and teardown errors are never downgraded. Each run that touches a
quarantined test ends with a `quarantined tests` section that lists each one and its
result. In CI the same table is appended to the job's step summary, so it shows on the run
page.

**An exception cannot become permanent.** `tests/test_flake_policy.py` fails the build in
any of these cases:

- a marker is expired, unregistered or missing a field;
- a marker and its registry entry disagree;
- an entry has no marker (the quarantine is over, so delete the entry);
- the expiry is more than 90 days away.

The plugin also refuses to honour an invalid quarantine, so on its expiry date the test
blocks again. To renew a quarantine, move the date in both places and give the reason in
the issue. A reviewer sees the renewal in the diff.

The registry starts empty on purpose. Add an entry only for a real, explained flake (§9.2),
never to make one PR green. A test that is merely slow, or depends on a platform, is not
flaky. Give it a `skipif` with a reason, or fix it.

### 9.4 `continue-on-error`

Every `continue-on-error` in `.github/workflows/` that can evaluate to true must have a
comment on the same line, or in the comment block directly above it, of the form:

```yaml
# PROMOTE WHEN: green on three consecutive pushes to main -- add it to ci-gate's needs.
continue-on-error: true
```

or `# REMOVE WHEN: <condition>`. If a step or job is advisory by design (a convenience
upload, a best-effort sync, an external-link check), it says so: `# PROMOTE WHEN: never --
<why>`. A literal `false` needs no comment. `tests/test_flake_policy.py` enforces this for
literal and expression values, at job and step level. It also checks its line scan against
a real YAML parse, so a flow-style key the scan cannot see fails the test instead of
passing it. To list the switches and their conditions:
`grep -n -A1 -e 'PROMOTE WHEN' -e 'REMOVE WHEN' .github/workflows/*.yml`.

When a promotion condition is met, promoting the job is a deliberate change with its own
PR, and `test_ci_gate.py` must agree with it (§6.1). A condition that has been met but not
acted on is an owner decision waiting to be made. It is not a reason to delete the comment.

Advisory coverage must remain honest. A green advisory job is useful evidence, but it is
not a blocking guarantee while the workflow allows it to fail.

### 9.5 Flakes and runner incidents are tracked separately

| | Flaky test | Runner / service incident |
|---|---|---|
| Cause | the test or the code it exercises | the runner, network, package index, GitHub Actions |
| Evidence | same commit passed and failed one test (§9.2) | failure before or outside any test, or a known outage |
| Label | `ci:flaky-test` | `ci:runner-incident` |
| Remedy | fix, or quarantine (§9.3) | retry once; repeated incidents mean a structural fix (pin, cache, timeout, wait-for-propagation), §8 and §13 |
| Never | quarantined because a runner was slow | "fixed" by quarantining a test |

Keeping the two apart keeps the numbers honest. A test is not quarantined for an outage of
a package index, and an outage is not counted as a flaky test. FreeBSD-specific
limitations stay tracked in #306 and are not hidden by retries.

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

### 11.1 Hugging Face publishing

`huggingface-publish.yml` is a release/publish-lane workflow. It is `workflow_dispatch` only
and never runs on a pull request. The `validate` job is read-only and holds no secrets and no
OIDC token. The `publish` job needs `validate`, runs only from `main` with `dry_run` false,
uses the `huggingface-publish` environment (where the owner can require an approval), and is
the only job that requests `id-token: write`, for a Hugging Face Trusted Publisher exchange.
There is no stored token, and no `--delete`.

Its policy surface is `huggingface/manifest.json`, enforced by `scripts/hf_preflight.py` and
`tests/test_hf_publish_workflow.py`: a destination is published only when it is both
`owner_approved` and `status: live`, set in a reviewed commit. Its timeouts are 30 minutes
until a real run exists (§8, rule 3). Nothing in the repository can create a Hub repository,
configure a Trusted Publisher, or approve a destination; those are owner actions.

### 11.2 A new publishing channel starts off

A job that publishes to a channel the project has never published to is outward-facing.
It lands **off**, and only the owner turns it on. Gate the job on a repository variable,
not on a missing secret:

```yaml
if: github.ref_type == 'tag' && vars.<CHANNEL>_PUBLISH == 'true'
```

An unset variable reads as the empty string, so a release made before the owner decides
publishes nothing, and the skipped job says why. A secret-presence check cannot do this
for a channel that authenticates with OIDC, because there is no secret to be missing.
Give the job its own `environment:` so the OIDC claim names it. Name the variable, where
to set it and how to turn it off in the job's comment and in `packaging/README.md`, and
add a test that pins the exact `if:` expression.

A new channel's job must not decide whether the release succeeded. Other workflows chain
on the `Release` run: `apt-repo.yml` acts only when it concludes `success`, and
`checksums.yml` waits while it is queued, in progress or `waiting`. So the job sets
`continue-on-error: true`, and its environment gets **no required reviewer**, because a
pending approval holds the run and everything chained on it. A channel that needs a human
approval belongs in its own workflow, not in `release.yml`.

The first job of this kind is `release.yml`'s `publish-mcp-registry` (ADR-032 §2, #639),
gated on `MCP_REGISTRY_PUBLISH` and tested by
`tests/test_release_publishes_mcp_registry.py`.

---

## 12. CI service-level objectives

The CI telemetry report (§12.1, #536) measures these daily. Until there is enough history,
they are targets rather than guarantees.

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

### 12.1 The CI telemetry report

`.github/workflows/ci-telemetry.yml` runs daily and on `workflow_dispatch`. It writes the
report to the run's job summary and uploads `ci-telemetry.json` and `ci-telemetry.md` as
the `ci-telemetry` artifact, kept for 14 days. To read it, open the newest
**CI telemetry** run in the Actions tab.

"CI telemetry" here means metadata about this repository's own GitHub Actions runs. It
has nothing to do with the product, which collects no telemetry (AGENTS.md rule 1).

| Part | Role |
|---|---|
| `scripts/ci_telemetry.py` | Pure aggregation. Takes the API's run and job JSON and returns the report. Opens no connection, reads no clock. |
| `scripts/ci-telemetry-report.py` | Thin fetcher. Read-only `GET`s, bounded, then writes the JSON and Markdown. |
| `tests/test_ci_telemetry.py` | Pins every metric on a synthetic fixture (`tests/fixtures/ci_telemetry/`). Also covers the privacy guards, the fetcher bounds through a fake transport, and the workflow contract. No network. |

**What it reports.** Runs by workflow and by event. Success, failure, cancelled and other
percentages. Job queue latency and run duration, p50 and p95, per workflow. Job-minutes
per workflow, which shows what is consuming CI. Superseded PR runs: how many there were,
the share cancelled, the cancellation delay, and which workflows let a superseded run
finish. The longest jobs. Workflows with no successful run, and active workflows with no
run at all. Repeated failures by workflow, job and first failed step. Workflows red on the
default branch, with how long they have been red. The table of §12 targets, each marked
`met`, `missed`, `no data` or `n/a`.

**Definitions.** The module docstring is the full contract. The ones that matter most:

- *Queue latency* is per job: `started_at - created_at`. A job with `needs:` is created
  when its dependencies finish, so this is time spent waiting for a runner. Skipped jobs
  are excluded.
- *Run duration* is the last job's `completed_at` minus `run_started_at`. It is never
  computed from `updated_at`, because GitHub rewrites `updated_at` on finished runs. On
  2026-10-16 it moved a dozen failed PR runs' `updated_at` up to 22 hours past their end.
- *Percentiles* are nearest-rank, so every reported value was actually observed.
- *Superseded*: a newer run of the same workflow for the same PR was created before this
  run finished. Runs that ended `action_required` never started, so they do not count.
- *Red*: the newest default-branch run that succeeded or failed is a failure. Cancelled
  and skipped runs do not break or extend the red streak. The 24-hour limit applies to
  most workflows; a streak made only of `schedule` runs gets the 7-day limit.

**Bounds.** The default window is 14 days (`--days`, at most 90). Runs are listed in
24-hour slices, because the runs API returns at most 1,000 results for a filtered query.
A slice that hit that ceiling is reported as truncated. `--max-runs` (default 5,000)
caps the listing. Job lists are fetched for at most `--max-job-runs` completed runs
(default 1,000), failures first. Fetching stops once fewer than `--rate-limit-reserve`
(default 200) requests remain. A repository `GITHUB_TOKEN` gets 1,000 requests an hour,
so the report cannot starve the other workflows. Every bound that applied is listed under
`coverage.notes` and at the top of the summary, so a partial report says it is partial.

**Privacy.** Every raw record is cut down to an explicit allow-list of fields as soon as
it is read. The report never contains PR titles or bodies, commit messages, author names
or emails, actor logins, branch or fork names, runner names, or log text. Logs are never
downloaded. A PR is identified only by an opaque grouping key, and that key is never
written out. The only text that remains is workflow, job and step names, events and
conclusions, plus numeric run ids so a reader can open a failing run. Names are escaped
before they become Markdown, because a pull request runs its own copy of the workflow
file and can choose its own job names. Two tests check this: one looks for the fixture's
personal values in the output, and one fails on any JSON key outside a reviewed
allow-list.

**What it does not do.** It changes no gate. A missed target does not turn it red. It
fails only when the API cannot be read. It is not in `test.yml`, is not a `ci-gate` need
and is not a required check. Two targets cannot be measured yet. *Fast PR gate execution*
waits for #535 to define the fast lane; until then the queue target is reported over all
PR jobs. *Without a linked issue* cannot be seen from Actions data, so the report gives
how long a workflow has been red and leaves the issue check to a person.

Run it locally (read-only; any token that can read the repository's Actions data works):

```sh
GH_TOKEN=$(gh auth token) python3 scripts/ci-telemetry-report.py \
  --repo MSKazemi/yazses --out-json ci-telemetry.json --out-md ci-telemetry.md
```

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
- #536 — CI telemetry and SLO reporting. The daily report is in source (`ci-telemetry.yml`,
  §12.1).
- #537 — reusable setup, cache rules, and timeouts.
- #538 — flake/rerun/quarantine policy. The policy, the quarantine registry and marker, and
  the `continue-on-error` condition guard are in source (§9). Creating the `ci:flaky-test`
  and `ci:runner-incident` labels is an owner step.
- #462 — stable aggregate gate and main ruleset hardening. The gate (`ci-gate`, §6.1) is in
  source. Requiring it in the live ruleset is the owner step in §6.2.
- #306 — FreeBSD advisory-job dependency/toolchain limitation.

The order matters: first stop obsolete work and move validation before deployment; then
classify changes; then optimize lanes; then enforce the stable gate at the repository
ruleset layer; measure the result throughout.
