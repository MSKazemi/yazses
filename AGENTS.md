# AGENTS.md — project conventions for coding agents

A short, machine-readable brief for AI coding assistants working in this repository.
Humans should read [CONTRIBUTING.md](.github/CONTRIBUTING.md) instead; this file exists so an
agent-assisted contribution arrives correct on the first try.

**This file is canonical for every tool** — Codex, Claude Code, Gemini CLI, Cursor,
Copilot, Aider and anything else. There is deliberately no per-tool instruction file in
this repository: three copies of the setup commands become three different sets of setup
commands. If your tool looks for its own filename and finds nothing, read this one.

The human who opens the PR is responsible for it. Do not open a PR the author has not read.

## What this project is

YazSes is a cross-platform, **fully offline** hold-to-talk voice dictation daemon for Linux,
macOS, and Windows, plus offline file transcription (`yazses transcribe`) and whole-meeting
capture (`yazses meeting`). Speech-to-text is `faster-whisper` on CPU (int8). Python 3.11+,
managed with `uv`.

## Setup and gates

```sh
uv sync
uv run python -m pytest tests/ -v   # tests  (note: python -m pytest, not `uv run pytest`)
uv run ruff check src tests scripts # lint — same targets CI uses
uv run mypy src                     # types — clean today, advisory, see below
```

**pytest and ruff must be green.** Run them before claiming anything works — do not infer
success from a change looking correct. The suite is offline and mocks audio and model
layers, so no microphone, network, or Whisper model download is required.

**mypy is clean and advisory.** `uv run mypy src` currently reports **no issues across 433
source files**, so if it reports an error, you almost certainly just introduced it — fix it
rather than reporting it as pre-existing. It is not a CI gate (only `ruff` and `pytest`
are), but do not leave the count above zero.

The `[tool.mypy]` section in `pyproject.toml` silences the imports of optional backends a
base install deliberately omits. Those are absent by design, not bugs — do not "fix" them.

If you change any CLI command, flag, or config key, regenerate the reference docs or the
sync test will fail:

```sh
uv run python scripts/gen-docs.py   # rewrites docs/features.md, configuration.md, command-index.md
```

Useful narrower runs:

```sh
uv run python -m pytest tests/test_foo.py -v
uv run python -m pytest -k "pattern"
```

## Non-negotiable project rules

1. **Nothing leaves the machine.** Do not add network calls, telemetry, analytics, crash
   reporting, or a cloud API dependency. Offline-first is the product, not a preference.
2. **New features ship off by default.** Add a config section in `src/yazses/config.py`
   with `enabled = False` (or an equivalent dormant default) so an existing install is
   unchanged until the user opts in.
3. **Heavy dependencies are optional extras.** Anything large (torch, ONNX runtimes, LLM
   runtimes, Qt) goes in `[project.optional-dependencies]` in `pyproject.toml` and is
   **imported lazily**, inside the function that needs it — never at module top level.
   A fresh install with no extras must import and run.
4. **Use the latest stable version** of any dependency you add, with a `>=` floor.
5. **Keep the pure logic pure.** Business logic goes in dependency-free modules that are
   unit-tested directly; heavy backends are injected. Follow the existing split — e.g.
   `meeting/segmenter.py` (pure) vs `meeting/silero_vad.py` (backend).
6. **Platform code goes behind the Protocols** in `src/yazses/platform/base.py`. To add an
   OS, implement every Protocol under `src/yazses/platform/<os>/` and register it in
   `platform/factory.py`.
7. **Tests come with the change**, in the same PR. New behaviour without a test is not done.
8. **No attribution lines** in commit messages — no `Co-Authored-By` trailers and no
   "generated with" footers.

## Where things live

| Area | Path |
|---|---|
| Daemon orchestration + state machine | `src/yazses/core/daemon.py` |
| Config dataclasses (every `[section]`) | `src/yazses/config.py` |
| CLI commands | `src/yazses/cli.py` |
| OS abstraction (Protocols + per-OS impls) | `src/yazses/platform/` |
| Audio capture, VAD, device handling | `src/yazses/audio/` |
| Speech-to-text + filters | `src/yazses/stt/` |
| Text post-processing | `src/yazses/postprocess/` |
| Voice-command grammar + dispatch | `src/yazses/commands/` |
| Keystroke injection backends | `src/yazses/inject/` |
| Meeting Mode | `src/yazses/meeting/` |
| File transcription + diarization | `src/yazses/recimport/` |
| Tests | `tests/` |

[`docs/architecture.md`](docs/architecture.md) holds the fuller architecture reference —
read it before making a structural change.

### The four things an agent gets wrong here

**Generated files — never hand-edit.** Edit the source and re-run the generator, or a test
fails and your change is reverted anyway.

| File | Regenerate with |
|---|---|
| `docs/features.md`, `docs/configuration.md`, `docs/command-index.md`, `docs/cli-reference.md` | `uv run python scripts/gen-docs.py` |
| `man/yazses.1` | `uv run python scripts/gen-man.py` |
| `campaign/generated/**`, `campaign/schemas/**` | `uv run python scripts/campaign.py --generate` |
| The contributor wall in `README.md` + every `README.<code>.md` | `npx all-contributors-cli generate` |

**Pure modules — test these directly, no mocks needed.** The house pattern is dependency-free
logic beside an injected heavy backend: `meeting/segmenter.py` (pure) vs `meeting/silero_vad.py`
(backend); `gaze/zones.py` vs `gaze/mediapipe_backend.py`; `recimport/align.py` vs
`recimport/diarizer.py`. Put new logic on the pure side and the test is trivial.

**Platform seams.** Every OS difference goes behind a Protocol in
`src/yazses/platform/base.py`, implemented under `platform/<os>/` and registered in
`platform/factory.py`. Injection backends sit behind `inject/base.py`. Do not branch on
`sys.platform` anywhere else.

**Public interfaces — changing these is L3 work.** The IPC methods in `src/yazses/ipc/`,
the config keys in `src/yazses/config.py`, the CLI surface in `src/yazses/cli.py`, and the
semantic contract in `contract/`. A change here needs a maintainer and possibly an ADR.

(A maintainer's checkout may also carry root-level assistant config files. Those are
deliberately **not** in the repository, so never assume one is present and never tell a
contributor to read one — this file is the brief every agent is guaranteed to have.)

## Documentation expectations

A change that affects users must update the matching surface in the same PR:

- `CHANGELOG.md` — under `[Unreleased]`
- `docs/cli-reference.md` and `docs/command-index.md` — for CLI changes (these are partly
  generated; see `scripts/gen-docs.py`)
- `docs/features.md` — for a new user-visible feature
- `docs/configuration.md` — for a new config key
- `README.md` — only for something a newcomer must know

## Pull requests

- One concern per PR. A refactor and a feature are two PRs.
- Explain *why* in the body, not just *what*.
- Do not reformat unrelated files, bump unrelated dependencies, or "tidy" code you did not
  otherwise touch — it makes review disproportionately expensive.
- If you could not get a gate to pass, say so explicitly in the PR body. An honest
  "mypy fails on X, I could not resolve it" is welcome; a silent failure is not.
