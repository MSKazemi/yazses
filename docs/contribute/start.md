---
title: Make your first contribution to YazSes
description: Pick one bounded task, finish it in 15–45 minutes, and get it merged. No permission needed, no setup for most tasks, coding agents welcome.
---

# Make your first contribution

**No permission needed. Nothing is assigned. Nobody has to reply before you start.**

Pick the row that matches what you have in front of you right now.

| What you have | Do this | Time |
|---|---|---|
| **A browser, nothing else** | [Translate the README into your language](https://github.com/MSKazemi/yazses/issues/18) — the intro and Quick Start alone is a complete pull request | 30–45 min |
| **A laptop, any OS** | [Install YazSes and report what happened](https://github.com/MSKazemi/yazses/issues/42) — working *or* broken, both are useful | 20 min |
| **A microphone you like** | [Add it to the known-good list](https://github.com/MSKazemi/yazses/issues/21) with its measured level | 15 min |
| **An editor or terminal you use daily** | [Share a config for it](https://github.com/MSKazemi/yazses/issues/43) | 30 min |
| **Python, and you want real code** | [Browse the task list](tasks.md) and take any `WIRE-*` or `QA-*` | 60–90 min |

Want to narrow it yourself instead? **[Filter the full list](find.md)** by what you have,
how long you've got, and whether you want to write code.

Still undecided? Take the second row. **Nobody can test YazSes on your machine but you**, and
that is the single most useful thing the project is missing — 297 environments are listed and
almost none are covered.

## The three rules

1. **Sign off your commit**: `git commit -s`. A check fails without it and prints the exact fix.
2. **Stay inside the task's files.** Each task lists what it may touch. If your change needs
   something else, say so in the pull request — that usually means we scoped the task wrong.
3. **Remove anything personal** before you push: your home path, hostname, email. `yazses
   doctor` output contains your username.

That is the whole contract. There is no CLA, no Discord to join, no account beyond GitHub.

## Check your own work before you push

```sh
uv run python scripts/check-task.py APP-014
```

It runs exactly what CI will — scope, personal data, and the task's own test — against your
working copy, and tells you what a human reviewer will look for. Run it and you will not be
surprised by a red check on your first pull request.

## Using a coding agent

**This is welcome and normal.** Claude Code, Codex, Cursor, Copilot, Gemini — all fine. Two
things stay true regardless: you are the author, and you are expected to have read what it
wrote. Say in the pull request that you used one; it changes how carefully we read it, never
whether we accept it.

Copy this, replacing the task ID:

```text
I'm making one contribution to the YazSes project. I remain the author and I will
read every line before it goes anywhere.

1. Read AGENTS.md and CONTRIBUTING.md in the repo root, completely.
2. Run: uv run python scripts/check-task.py <TASK-ID>
   It prints the task, the exact files I may touch, and the command that decides
   whether the work is done. Treat that output as the specification.
3. Restate the acceptance criteria back to me before changing anything.
4. Make the smallest change that satisfies the task. Do not tidy unrelated code,
   do not reformat files you did not otherwise change, do not add a dependency.
5. Never add a network call, telemetry, or a feature that is on by default —
   those are the three rules this project will not bend on.
6. Run the task's validation command and show me the real output, not a summary.
7. Show me the complete diff and explain every changed line in plain language.
8. Stop and tell me if the task needs evidence only a human can provide — that I
   actually observed something on my machine, or that a translation reads
   naturally. Do not invent either.
9. Do not commit or push until I say the diff is correct.
10. Then: git commit -s  (the sign-off is required)
```

Point 8 matters. A compatibility report or a translation that an agent produced without a
human checking it is a fabricated contribution, and it will be declined — not because AI was
used, but because nobody verified it. Everything else on the list, an agent can do well.

## What happens after you open the pull request

An automated check runs in about a minute and either says ready, or lists the exact fixes. A
human replies within a few days. We would rather merge a small imperfect change and polish it
afterwards than leave you waiting.

Once it lands you are added to the [contributors wall](https://github.com/MSKazemi/yazses#contributors),
and a weekly job checks that GitHub is actually crediting you — being uncredited is the one
failure people never report.

## If you get stuck

Say so on the issue, however half-finished it is. A stuck pull request that nobody hears
about is the only real failure mode here. The most common stall is `uv sync` on Linux, which
needs a C compiler: `sudo apt install build-essential python3-dev`. On macOS and Windows you
need nothing.
