# Contributing

YazSes is built by a small group of people, most of whom arrived, did one useful thing, and
were credited for it. **One contribution is a real contribution** — a doc fix, a config you
already use, a microphone that worked, or a bug report with `yazses doctor` output.

This page is the short version for people arriving from the docs. The authoritative guide is
[`CONTRIBUTING.md`](https://github.com/MSKazemi/yazses/blob/main/CONTRIBUTING.md) in the
repository, and it is the one to trust if these ever disagree.

## Start here

**[Issue #22](https://github.com/MSKazemi/yazses/issues/22)** is the front door — everything
open, grouped by what you enjoy, with every link checked.

## No code required

These are genuinely useful and need no Python:

| | |
|---|---|
| 🌍 **[Translate the README](https://github.com/MSKazemi/yazses/issues/18)** | One language each — 24 listed, any other welcome. No install needed. |
| 🎙️ **[Add your microphone](https://github.com/MSKazemi/yazses/issues/21)** | Run `yazses mic-level`, add one row to [known-good microphones](known-good-microphones.md). **Bad results are wanted too.** |
| ⚙️ **[Share a config](https://github.com/MSKazemi/yazses/issues/43)** | The settings that work for your editor or app. |
| 🖥️ **[Add your setup](https://github.com/MSKazemi/yazses/issues/42)** | A line in `SHOWCASE.md` — a genuine two-minute pull request. |
| 🧪 **Run it and report** | On [macOS](https://github.com/MSKazemi/yazses/issues/24), [Windows](https://github.com/MSKazemi/yazses/issues/66), or the [snap](https://github.com/MSKazemi/yazses/issues/142). Telling us what broke is how most bugs here get found. |

Those four at the top hold **many contributors at once** — one entry each, nothing to claim,
nothing to wait for.

## If you do want to write code

```sh
git clone https://github.com/MSKazemi/yazses
cd yazses
uv sync
uv run python -m pytest tests/ -v
```

!!! warning "On Linux, install a compiler first"

    `uv sync` fails with a wall of compiler errors otherwise.
    [`evdev`](https://pypi.org/project/evdev/) — the keyboard hook — publishes **no wheels**,
    only a source archive, so it is built against your Python and kernel headers.

    ```sh
    sudo apt install -y build-essential python3-dev git   # Debian / Ubuntu
    sudo dnf install -y gcc python3-devel git             # Fedora / RHEL
    sudo pacman -S --needed base-devel git                # Arch
    ```

    **macOS and Windows need none of this** — every dependency there ships a prebuilt wheel.

**You do not need a microphone, a Whisper model, or a GPU.** The test suite is fully offline,
mocks the audio and model layers, and runs in about 30 seconds.

`ruff` and `pytest` are the gates that must be green; `mypy` is advisory. If you changed a CLI
command, flag or config key, run `uv run python scripts/gen-docs.py` or the doc-sync test will
fail.

## What to expect

We would rather merge a small imperfect pull request and polish it afterwards than leave you
waiting, and we aim to reply within a few days. Red CI on your first push is normal — say so
and we will help you read it.

Every contributor is credited on the wall in the
[README](https://github.com/MSKazemi/yazses#contributors), including for work with no commit
behind it — design review, research and bug reports count, and a script checks nobody with
merged work is missing.

## The rules that will not bend

Two commitments a contribution cannot change without a superseding decision record: **nothing
leaves the machine by default**, and **new features ship off by default** so nothing changes
someone's setup until they opt in. [`GOVERNANCE.md`](https://github.com/MSKazemi/yazses/blob/main/GOVERNANCE.md)
covers the rest, including how a module becomes yours to review.

**Using an AI assistant is fine** — increasingly normal — but the pull request is yours, so
please read every line and confirm the tests pass rather than assuming.
[`AGENTS.md`](https://github.com/MSKazemi/yazses/blob/main/AGENTS.md) gives your assistant the
conventions and the two rules it is most likely to break.

## Questions

Ask in [Q&A discussions](https://github.com/MSKazemi/yazses/discussions/categories/q-a) — run
`yazses doctor` first and paste the output. Feature *ideas* go in
[Ideas](https://github.com/MSKazemi/yazses/discussions/categories/ideas) where everyone can
vote; *bugs* go in [issues](https://github.com/MSKazemi/yazses/issues), with a reproducer.

No question is too small.
