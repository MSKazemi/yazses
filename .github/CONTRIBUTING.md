# Contributing to YazSes

Thank you for your interest in contributing. YazSes is a **Python** project on the `main`
branch — that is where every contribution goes. (An early-stage Rust prototype is parked on
`archive/rust-hci-v1`; it is not built, installed, or maintained, and you can safely ignore
it.)

**Want a concrete task rather than an issue to interpret?**
[`campaign/generated/open-tasks.md`](../campaign/generated/open-tasks.md) lists 130 open tasks
— each with the exact files it may touch, the command that decides it is done, and an
honest time estimate. Run `uv run python scripts/check-task.py <ID>` before you push and it
tells you what CI will say.

**New here?** Pick a [good first issue](https://github.com/MSKazemi/yazses/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
and say hi on it — several need no Python at all (docs, an example config, testing on your
hardware). We aim to respond to issues and PRs within a few days, and we would rather merge
a small imperfect PR and polish it afterwards than leave you waiting.

## Getting started

**Want to skip setup entirely?** The repo ships a
[Dev Container](../.devcontainer/devcontainer.json), so
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
suite is fully offline and mocks the audio and model layers, and runs in about 30 seconds.

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
- 🗺️ **[ROADMAP.md](../ROADMAP.md)** — what's shipped, in progress, and planned.
- 🙏 **[Q&A discussions](https://github.com/MSKazemi/yazses/discussions/categories/q-a)** —
  setup help and "how do I…" questions (run `yazses doctor` first and paste the output).

Two principles act as tiebreakers: **on-device wins** (YazSes never sends audio anywhere;
cloud-dependent ideas are welcome to discuss but on-device is the default), and **new
features ship off by default** so nothing changes your setup until you opt in. Please open
*bugs* as [issues](https://github.com/MSKazemi/yazses/issues) — bugs need a reproducer;
feature *ideas* belong in Discussions where everyone can vote.

## Who decides what

Reviewing someone else's PR — including as your own next step after a first merge — is
[`REVIEWING.md`](../REVIEWING.md). It describes the lanes, what a machine may never decide,
and a path into reviewing that does not start with repository permissions.

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

**There is nothing to sign.** No CLA, no sign-off line, no bot to authorise, no
account beyond GitHub. Open the pull request and you are done — many tasks here
never need you to leave the browser.

## The dependency budget

16 base dependencies, 140+ features — heavy capabilities live behind an extra in
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

- **Start here:** [`docs/mobile/index.md`](../docs/mobile/index.md) — what we are building, why
  Android before iOS, and the M0–M4 milestones.
- **Before your first PR:** [`docs/mobile/architecture.md`](../docs/mobile/architecture.md)
  (module map, pipeline, testing) and
  [`docs/mobile/contributing.md`](../docs/mobile/contributing.md) (roles, claiming, review bar).
- **Why things are the way they are:**
  [the ten mobile ADRs](../docs/mobile/adr/README.md) — each one ends with a *Rejected* section
  that tells you which arguments have already been had.
- **Find work:** issues labelled [`android`](https://github.com/MSKazemi/yazses/labels/android),
  coordinated by [the Android epic, #81](https://github.com/MSKazemi/yazses/issues/81).
  Comment to claim one. The two M0 tasks
  ([#82](https://github.com/MSKazemi/yazses/issues/82),
  [#83](https://github.com/MSKazemi/yazses/issues/83)) are Python and are open right now.

Two things worth knowing before you decide it is not for you:

**You do not need an Android phone, or Kotlin, to help.** The first milestone (M0) is
*Python* work in this repository: building the golden test vectors that define shared
behaviour for every platform (see [`docs/mobile/contract.md`](../docs/mobile/contract.md)). And
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

Every translation carries one line of sync metadata — an HTML comment under the language
switcher that records which English commit it was translated from, what it covers, and
whether a native speaker has reviewed it:

```html
<!-- yazses-l10n: locale=ru; source=README.md; source_sha=96711bc; scope=full; status=active -->
```

[`docs/localization/STATUS.md`](../docs/localization/STATUS.md) explains each field, lists every
translation, and shows how to find what changed in English since your `source_sha`. Before
opening a PR, run:

```bash
uv run python scripts/check-translations.py
```

It is **read-only** — it never rewrites your text. It checks that the switcher links resolve,
that you link back to the English README, and that commands and URLs were copied verbatim
rather than translated. That last one is the check that matters: `yazses диагностика` is not
a command, and a reader who types it gets an error instead of a working tool.

Translated prose is allowed to lag the English and you are not signing up to maintain it
forever. The one part that may **not** drift is the contributor wall — it is generated markup,
identical in every language, and a stale copy quietly drops a real person from the surface
people actually look at. A test enforces that, so copy that block across verbatim.

## Using an AI coding assistant

That is fine, and increasingly common — but the PR is yours, so please read and understand
every line before you open it, and confirm the tests pass locally rather than assuming.
[`AGENTS.md`](../AGENTS.md) gives your assistant the project conventions, the gates, and the two
rules it is most likely to break (**no network calls or telemetry**, and **new features ship
off by default**). Mention in the PR body if a change was largely AI-generated; it only
changes how carefully we review, never whether we accept it.

## After it is merged — please take the credit publicly

Two things happen without you asking: you are added to
[CONTRIBUTORS.md](../CONTRIBUTORS.md), and to the contributor wall in `README.md` **and in every
translation of it**. Both are permanent and both carry your name and your avatar.

**Sharing your merged pull request is worth more to you than it is to us, and that is the
reason we would rather you did it.** A merged PR is a public, permanent, linkable artifact
with your name on the commit — a link to a real diff in a real project says something a
bullet point on a CV cannot, because anyone can open it and read what you actually wrote.

It also happens to be the only distribution this project has. There is no company behind
YazSes and no ad budget; everyone who has found it found it because somebody said something.
A post from the person who built a piece of it travels further than anything the maintainer
can say about his own repository — and it puts *your* work at the front of the sentence.

Something to paste and edit, if a blank box is the obstacle:

> I contributed [what you did] to **YazSes**, an open-source offline voice-dictation daemon
> for Linux, macOS and Windows — hold a key, speak, release, and the text is typed into
> whatever app you are in. It all runs on your own CPU: no cloud, no API key, no
> subscription.
>
> My pull request: [link to your merged PR]
> The project: https://github.com/MSKazemi/yazses

Worth linking alongside it, whichever platform you use: the
[documentation site](https://mskazemi.com/yazses/), the
[40-second demo](https://www.youtube.com/watch?v=nn8WUKsCvZ4) if you want something people
will actually click, and [#18](https://github.com/MSKazemi/yazses/issues/18) (translations)
or [#22](https://github.com/MSKazemi/yazses/issues/22) (everything open) if you would like to
bring somebody with you. Releases are archived on Zenodo under a DOI
([10.5281/zenodo.21856271](https://doi.org/10.5281/zenodo.21856271)), so if you ever need a
citable reference for a thesis, a grant, or a portfolio, there is a real one to cite.

None of this is expected, none of it is a condition of anything, and nobody will ask you a
second time. **What this project will never do is manufacture the signal** — no star-for-star,
no reciprocal-follow arrangements, no asking anyone to post something they do not mean. If
the contribution was not a good experience, please tell us that instead; it is worth more to
us than a post.

## License

**There is nothing to sign — no CLA, and no DCO sign-off line.**

YazSes is Apache-2.0, and section 5 of that licence already covers contributions:

> Unless You explicitly state otherwise, any Contribution intentionally submitted for
> inclusion in the Work by You to the Licensor shall be under the terms and conditions
> of this License, without any additional terms or conditions.

So opening the pull request *is* the licence grant. Nothing to sign, no account to create,
nothing for an employer's legal team to review, and no extra commit trailer to remember.

**You keep the copyright in your work.** YazSes is Apache-2.0 and stays that way.
