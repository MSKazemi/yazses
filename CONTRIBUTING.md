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

```sh
git clone https://github.com/MSKazemi/yazses
cd yazses
uv sync
uv run python -m pytest tests/ -v   # run the test suite  (must be green)
uv run ruff check src tests         # lint                (must be green)
uv run mypy src                     # type checking       (advisory — see below)
```

**pytest and ruff must pass** — if they are green locally, CI will be green. You do **not**
need a working microphone, a Whisper model, or the optional extras to contribute: the test
suite is fully offline and mocks the audio and model layers, and runs in about 15 seconds.

**mypy is advisory.** There are ~135 pre-existing type errors, so a clean run is not
expected of you. Just don't add new ones to the files you touch. (Chipping away at that
number, one module per PR, is a genuinely useful contribution — say so in the PR and we'll
take it.)

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

## Before opening a pull request

- Run the test suite and confirm it passes.
- For new features, add tests.
- Keep PRs focused — one concern per PR.
- Describe the *why* in the PR body, not just the *what*.

## Reporting bugs

Open an issue at https://github.com/MSKazemi/yazses/issues and include:
- OS and version
- `yazses --version` output
- Steps to reproduce
- Relevant lines from `yazses logs`

## Platform support

If you are adding support for a new platform or injection backend, implement all relevant Protocol interfaces and add a test. See `src/yazses/platform/base.py` for the interface contracts.

## Using an AI coding assistant

That is fine, and increasingly common — but the PR is yours, so please read and understand
every line before you open it, and confirm the tests pass locally rather than assuming.
[`AGENTS.md`](AGENTS.md) gives your assistant the project conventions, the gates, and the two
rules it is most likely to break (**no network calls or telemetry**, and **new features ship
off by default**). Mention in the PR body if a change was largely AI-generated; it only
changes how carefully we review, never whether we accept it.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
