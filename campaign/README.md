# Contributor task inventory

A place to find one bounded, useful thing to do — with the exact files you may touch, the
command that decides whether it is done, and an honest estimate of how long it takes.

**Start here: [`generated/open-tasks.md`](generated/open-tasks.md).**

Nothing is assigned and you do not need permission. Pick a task, say so on the issue it
came from so nobody doubles up, and open the pull request. A coding agent is welcome —
you remain the author, and you are expected to have read every line you send.

## How this is put together

| File | What it is |
|---|---|
| `tasks.json` | The inventory. Hand-maintained; the source of truth. |
| `schemas/task.schema.json` | **Generated.** Derived from `FIELD_SPEC` in `scripts/campaign.py`. |
| `generated/open-tasks.md` | **Generated.** The browsable list. |
| `generated/stats.json` | **Generated.** Counts, and the review cost if everything merged. |
| `generated/dashboard.md` | **Generated.** What contributors have actually built, by category. |
| `incident-response.md` | Spam, fabricated evidence, plagiarism, leaked data, harassment. |

```sh
uv run python scripts/check-task.py APP-014    # ← contributors: check your work before pushing
uv run python scripts/check-task.py            # list the open tasks

uv run python scripts/campaign.py --check      # validate (a test runs this too)
uv run python scripts/campaign.py --generate   # rewrite the generated files
uv run python scripts/campaign_stats.py        # measure the funnel (read-only)
uv run python scripts/campaign_queue.py        # who is waiting on a human
uv run python scripts/campaign_queue.py --claims   # claims that have lapsed
uv run python scripts/check-compatibility.py   # validate SHOWCASE.md reports
uv run python scripts/check-app-profile.py     # validate examples/*.toml
```

`check-app-profile.py` compares every key against the real dataclasses in
`src/yazses/config.py`. That matters because the config loader is deliberately total — it
drops unknown keys and carries on (issue #52), which is right for a user's own config and
wrong for a shipped example: a typo'd key does nothing, reports nothing, and the person
who copied it concludes the feature is broken.

Claims lapse — 48 hours for L0/L1, seven days for L2 — so a task nobody finished returns to
the pool instead of staying locked forever. **That is not a judgement on anyone.** The
wording says the task is free again, thanks them, and leaves their branch and any PR alone.

`check-task.py` runs the same three checks CI will — scope, personal data, and the task's
own validation command — against your working tree, so you find out while the work is
still in front of you rather than from a red check on your first PR. It exits non-zero, so
it works as a pre-push hook.

`campaign_stats.py --attribution-gaps` is the one to run after a merge wave: it lists
people whose work is in `main` but who the contributors API does not credit, almost always
because their commit email is not connected to their GitHub account. That is a bug in the
project, not in them.

Do not hand-edit anything under `generated/` or `schemas/` — a test fails if they stop
matching `tasks.json`. Edit `tasks.json`, regenerate, commit both.

There is deliberately **no GitHub issue per task**. A hundred bot-filed issues would bury
the human ones and read as spam. Tasks live here; the umbrella issues they came from
(#18, #21, #42, #43, #164) stay the place to talk.

## Risk lanes

`risk` says who reviews a change, not how hard it is.

| Lane | Typical task | Review |
|---|---|---|
| **L0** | A compatibility record, a microphone row, a semantic vector | ~4 min |
| **L1** | An app config, a translated section, a troubleshooting page | ~7 min |
| **L2** | Wiring a capability, a regression test | ~15 min |
| **L3** | Privacy, IPC, dependencies, public interfaces | Maintainer, plus an ADR if needed |

**L3 is never advertised as an open first task**, and a check enforces that.

## What a machine may and may not decide

Preflight (`scripts/campaign_preflight.py`) runs on every PR that names a task. It checks
that the task exists, that the diff stayed inside the task's `allowed_paths`, and that no
home path, email or token slipped into the diff. It produces one summary, not a wall of
logs, and a PR that names no task passes untouched.

It **cannot** decide that a translation reads naturally to a native speaker, that hardware
behaved the way a report claims, or that an architectural change is right. Those stay
human, permanently. `cloud_agent_ready` is false for every compatibility, measurement and
localization task for exactly this reason, and the validator rejects the row if someone
sets it true.

## Running a session, or reviewing

- [`sprint-kit.md`](sprint-kit.md) — everything needed to run a 90-minute contribution
  session, written for an organizer who has never spoken to the maintainer.
- [`../REVIEWING.md`](../REVIEWING.md) — the review lanes, the responses, and how to
  become a reviewer without needing repository permissions first.
- [`incident-response.md`](incident-response.md) — what to do about fabricated evidence,
  plagiarism, PR floods, coordinated activity and leaked personal data. Its governing bias:
  act on the contribution, not the person, because almost every bad first PR is a
  misunderstanding or a badly written task rather than bad faith.

## Adding a task

Append to `tasks.json`, run `--generate`, commit both. The validator will refuse a task
that has no stated value, no bounded paths, no validation command, a duplicate id, or an
estimate longer than one sitting. Those refusals are the point: an unbounded task is one a
newcomer cannot finish and a reviewer cannot cheaply check.
