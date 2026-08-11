# Contributing to YazSes

Thank you for your interest in contributing. YazSes is a **Python** project on the `main`
branch — that is where every contribution goes. (An early-stage Rust prototype is parked on
`archive/rust-hci-v1`; it is not built, installed, or maintained, and you can safely ignore
it.)

**New here?** Pick a [good first issue](https://github.com/MSKazemi/yazses/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
and say hi on it — several need no Python at all (docs, an example config, testing on your
hardware). We aim to respond to issues and PRs within a few days, and we would rather merge
a small imperfect PR and polish it afterwards than leave you waiting.

## Getting started

**Want to skip setup entirely?** The repo ships a
[Dev Container](.devcontainer/devcontainer.json), so
[opening it in GitHub Codespaces](https://codespaces.new/MSKazemi/yazses) gives you a
working environment in the browser with `uv sync` already done — no compiler, no Python,
no clone. Docs, config examples, tests, and pure-logic changes are fully doable there.
What it cannot give you is a real microphone, a hotkey device, or window focus, so
anything that needs *observed* dictation behaviour needs a local machine.

**On Linux, install a C compiler first.** This is the one step that bites people, and it
fails at `uv sync` with a wall of compiler errors rather than a helpful message:
[`evdev`](https://pypi.org/project/evdev/) (the keyboard hook) publishes **no wheels at
all** — only a source archive — so pip has to build it against your Python and kernel
headers.

```sh
sudo apt install -y build-essential python3-dev git   # Debian / Ubuntu / Mint / Pop!_OS
sudo dnf install -y gcc python3-devel git             # Fedora / RHEL
sudo pacman -S --needed base-devel git                # Arch / Manjaro
```

**On macOS and Windows you need none of this** — every dependency there ships a prebuilt
wheel, so `uv sync` just works. (`evdev` is Linux-only and is not installed on your
machine.)

Then:

```sh
git clone https://github.com/MSKazemi/yazses
cd yazses
uv sync
uv run python -m pytest tests/ -v   # run the test suite  (must be green)
uv run ruff check src tests scripts # lint                (must be green)
uv run mypy src                     # type checking       (advisory — see below)
```

**pytest and ruff must pass** — if they are green locally, CI will be green. You do **not**
need a working microphone, a Whisper model, or the optional extras to contribute: the test
suite is fully offline and mocks the audio and model layers, and runs in about 15 seconds.

**mypy is clean and advisory.** `uv run mypy src` currently reports **no issues across 433
source files**, so if you see an error, you almost certainly just introduced it. It is not
a CI gate — only `ruff` and `pytest` are — so nobody will block your PR on it, but please
run it once before pushing and don't leave the count above zero.

The `[tool.mypy]` section in `pyproject.toml` silences the imports of optional backends
that a base install deliberately omits — those are absent by design, not bugs, and no PR
should try to "fix" them.

Changed a CLI command, flag, or config key? Regenerate the reference docs, or the doc-sync
test will fail:

```sh
uv run python scripts/gen-docs.py
```

## How we decide what to build

Feature direction is driven in the open:

- 💡 **[Ideas discussions](https://github.com/MSKazemi/yazses/discussions/categories/ideas)** —
  suggest a feature and **upvote (👍) the ones you want**. The most-upvoted ideas rise to the
  top and are what we build next. Start with the *frustration*, not the solution.
- 🗺️ **[ROADMAP.md](ROADMAP.md)** — what's shipped, in progress, and planned.
- 🙏 **[Q&A discussions](https://github.com/MSKazemi/yazses/discussions/categories/q-a)** —
  setup help and "how do I…" questions (run `yazses doctor` first and paste the output).

Two principles act as tiebreakers: **on-device wins** (YazSes never sends audio anywhere;
cloud-dependent ideas are welcome to discuss but on-device is the default), and **new
features ship off by default** so nothing changes your setup until you opt in. Please open
*bugs* as [issues](https://github.com/MSKazemi/yazses/issues) — bugs need a reproducer;
feature *ideas* belong in Discussions where everyone can vote.

## Who decides what

[`GOVERNANCE.md`](GOVERNANCE.md) is the short version: what you can merge yourself,
what needs an ADR, how **module stewardship** works (two non-trivial PRs to a module
and it is yours to review), and the handful of things — no telemetry, offline by
default, off by default, honesty about what exists — that a PR cannot change without
a superseding ADR. Worth two minutes before you propose anything structural.

## Before opening a pull request

- Run the test suite and confirm it passes.
- For new features, add tests.
- Keep PRs focused — one concern per PR.
- Describe the *why* in the PR body, not just the *what*.
- **Commit with `git commit -s`.** Every commit needs a `Signed-off-by` line or the
  [DCO](DCO.md) check fails — see [License and sign-off](#license-and-sign-off) below.
  Already committed without it? `git commit --amend --signoff` (or
  `git rebase --signoff main` for several) then `git push --force-with-lease`.

## The dependency budget

18 base dependencies, 140+ features — heavy capabilities live behind an extra in
`[project.optional-dependencies]` and are imported lazily, inside the function that
needs them, so a plain-dictation install never downloads mediapipe or llama-cpp. CI
enforces this with `scripts/check_dependency_budget.py` (part of the `repo-hygiene`
job):

- Adding a name to `[project.dependencies]` fails the PR unless it carries the
  `dependency-budget-override` label — ask a maintainer for it if the addition is
  deliberate, then run `uv run python scripts/check_dependency_budget.py
  --record-baseline` and commit the updated `scripts/dependency_budget_baseline.json`.
  Growth is measured against the baseline **on the base branch**, so re-recording it
  in your own PR does not get you past the label; that is the point of the label.
- A top-level `import` of anything from an extra, anywhere in
  `yazses.core.daemon`'s import graph, fails the PR outright — that one doesn't need
  an override, it needs the import moved inside the function that uses it.
- Adding an extra to `[project.optional-dependencies]` means adding it to
  `EXTRA_MODULES` in that script too (extra → the top-level modules its packages
  import as), or to `EXEMPT_EXTRAS` with the reason a base install is expected to have
  them importable. CI fails on an extra the check has never heard of, because an
  unmapped extra is enforced by nothing.
- Cold-start import time is measured and printed on every run. It only *fails* in CI,
  where the recorded budget and the runner are the same kind of machine — locally it
  prints a note instead, so don't re-record the shared budget from your laptop.

Run it yourself before pushing: `uv run python scripts/check_dependency_budget.py`.

## Reporting bugs

Open an issue at https://github.com/MSKazemi/yazses/issues and include:
- OS and version
- `yazses --version` output
- Steps to reproduce
- Relevant lines from `yazses logs`

## Platform support

If you are adding support for a new platform or injection backend, implement all relevant Protocol interfaces and add a test. See `src/yazses/platform/base.py` for the interface contracts.

## Contributing to the Android app

The Android port is a separate, **community-built** programme with its own architecture,
its own decision records and its own contribution ladder. As of 2026-08-07 there is **no
Android code yet** — the design was written first, on purpose, so that many people can build
it at once. That means the ground floor is open.

- **Start here:** [`docs/mobile/index.md`](docs/mobile/index.md) — what we are building, why
  Android before iOS, and the M0–M4 milestones.
- **Before your first PR:** [`docs/mobile/architecture.md`](docs/mobile/architecture.md)
  (module map, pipeline, testing) and
  [`docs/mobile/contributing.md`](docs/mobile/contributing.md) (roles, claiming, review bar).
- **Why things are the way they are:**
  [the ten mobile ADRs](docs/mobile/adr/README.md) — each one ends with a *Rejected* section
  that tells you which arguments have already been had.
- **Find work:** issues labelled [`android`](https://github.com/MSKazemi/yazses/labels/android),
  coordinated by [the Android epic, #81](https://github.com/MSKazemi/yazses/issues/81).
  Comment to claim one. The two M0 tasks
  ([#82](https://github.com/MSKazemi/yazses/issues/82),
  [#83](https://github.com/MSKazemi/yazses/issues/83)) are Python and are open right now.

Two things worth knowing before you decide it is not for you:

**You do not need an Android phone, or Kotlin, to help.** The first milestone (M0) is
*Python* work in this repository: building the golden test vectors that define shared
behaviour for every platform (see [`docs/mobile/contract.md`](docs/mobile/contract.md)). And
the Kotlin `:core:*` modules are plain JVM modules — `./gradlew :core:postprocess:test`
needs no emulator, no microphone and no model.

**The privacy rules are enforced, not advisory.** No analytics, no crash-reporting SDK, no
Firebase, no `AccessibilityService`, and `INTERNET` in exactly one module. CI fails the
build otherwise. If your AI assistant suggests any of those — and it will — that is the
suggestion to ignore.

## Translating the README

Translations are tracked in [#18](https://github.com/MSKazemi/yazses/issues/18) — one
language each, one PR each, no permission needed. Two things worth knowing before you start:

- **Translating the lede through Quick Start is a complete contribution.** It is roughly the
  first 120 lines of a 581-line file. That is what the Hindi translation did, and it was
  merged. Leaving the rest in English is expected, not unfinished — say where you stopped in
  the status banner at the top of your file so the next reader and the next translator know.
- **Some things are never translated:** command names (`yazses start`), config keys
  (`[stt] model`), file paths, code blocks, and the project name *YazSes*.

Translated prose is allowed to lag the English and you are not signing up to maintain it
forever. The one part that may **not** drift is the contributor wall — it is generated markup,
identical in every language, and a stale copy quietly drops a real person from the surface
people actually look at. A test enforces that, so copy that block across verbatim.

## Using an AI coding assistant

That is fine, and increasingly common — but the PR is yours, so please read and understand
every line before you open it, and confirm the tests pass locally rather than assuming.
[`AGENTS.md`](AGENTS.md) gives your assistant the project conventions, the gates, and the two
rules it is most likely to break (**no network calls or telemetry**, and **new features ship
off by default**). Mention in the PR body if a change was largely AI-generated; it only
changes how carefully we review, never whether we accept it.

## License and sign-off

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.

**There is no CLA.** YazSes uses a [Developer Certificate of Origin](DCO.md) — the same one the Linux
kernel uses. There is nothing to sign, no account to create, and nothing for your employer's legal team
to review. You simply certify that you wrote the change and are allowed to submit it, by adding one
line to your commit:

```
Signed-off-by: Your Name <your.email@example.com>
```

Git writes it for you with `-s`:

```bash
git commit -s -m "your message"
```

Forgot it? `git commit --amend --signoff && git push --force-with-lease`. Want it always on?
`git config --global format.signOff true`.

**You keep the copyright in your work.** YazSes is Apache-2.0 and stays that way.
