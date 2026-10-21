---
title: "The start-up budget: a feature that is off costs nothing"
description: "How YazSes keeps every new feature from making the base app heavier or slower to start, which tests enforce it, and the patterns that keep a contribution inside the budget."
---

# The start-up budget

YazSes has around 150 feature packages under `src/yazses/`, and every one of them ships
switched off. Off-by-default is what a user *sees*. This page is about what they *pay*: a
feature whose code is imported when the daemon or the CLI starts is loaded on every start,
by every user, whether or not they ever turn it on. Nothing breaks. Start-up just gets a
little slower with every feature, and no functional test ever notices.

So the rule is:

> **A feature that is disabled costs a default start no import.** Its package, and the
> libraries it uses, are imported by the code that runs once the user turns it on — not by
> `yazses.core.daemon`, not by `yazses.cli`, and not by anything those import at module scope.

## What is enforced, and where

| What | Enforced by | Fails when |
|---|---|---|
| A disabled-by-default feature package is imported by `import yazses.main` (the daemon entry point) or by `yazses --help` | `tests/test_base_weight_budget.py` | A package that is not on its `KNOWN_EAGER` list appears in `sys.modules` |
| The `KNOWN_EAGER` list goes stale | same file | A listed package is no longer imported. Delete the line, so the list can only shrink |
| `yazses.*` modules loaded by each path | same file, `MAX_YAZSES_MODULES` | The count goes over the ceiling |
| A module either path loads imports a `yazses` module under a module-scope OS or Python-version branch | same file, `test_the_module_count_cannot_depend_on_the_os` | Such an import exists, which would make the ceiling mean something different on Windows or macOS |
| `asyncio`, the `urllib`/`http`/`ssl` network stack, `cryptography`, `sqlite3`, `importlib.metadata` at a default start | same file, `NOT_LOADED_BY` | One of them is loaded again |
| `yazses --version` or `yazses --help` imports `yazses.config` | same file, `CLI_ENTRY_PROBES` | `cli.main()` needs the config module again |
| A default daemon's `Daemon.__init__` or `_build_pipeline` imports a disabled-by-default feature package | `tests/test_dormant_features_stay_unimported.py` | `__init__` imports any; `_build_pipeline` imports one not on its `KNOWN_AT_START` list, or a listed one stops being imported |
| Opt-in feature packages, heavy third-party packages | `tests/test_default_start_stays_light.py` | Listed packages are imported at start |
| A module from an optional extra imported at module scope anywhere | `tests/test_no_module_imports_an_extra_at_module_scope.py` | An extra's import sits at module scope |
| Base dependency growth, eager extra imports, daemon import time | `scripts/check_dependency_budget.py` (CI `repo-hygiene`) | A new base dependency, or import time over 1.5× the recorded budget (CI only, advisory on a laptop) |

**The set of feature packages is derived, not listed.** It is every `[section]` of
`yazses.config.Config` whose default has `enabled = False` and whose name is also a package
under `src/yazses/`. A feature added tomorrow is covered without anyone remembering to
register it.

The guards count and name modules instead of timing them. Whether a module is in
`sys.modules` after a fresh `import` gives the same answer on a busy CI runner and on a
laptop. A wall-clock threshold does not. Timing is measured by `check_dependency_budget.py`
with a wide tolerance and only fails in CI.

**The module-count ceilings mean the same thing on every OS.** They were measured on Linux
and the test job also runs on Windows and macOS, so they are built not to depend on the
runner:

- Modules under `platform/<os>/` are not counted. That is where AGENTS.md says OS
  differences live, and how many modules a backend needs is a property of the OS. The set
  of backends is read from where `platform/factory.py` imports `build_platform`, so a new
  OS is excluded the day it is registered.
- Everything else either probe loads must import the same `yazses` modules on every OS.
  An AST check enforces this: no loaded module may import a `yazses` module inside a
  module-scope `if` that tests `sys.platform`, `os.name`, `platform.system()` or
  `sys.version_info`.
- The ceiling is the Linux count plus 3. The headroom covers the one case the AST check
  cannot see, a function called at import time that imports something on one OS only. It
  is a review signal, not an allowance.

A separate per-OS baseline was rejected. It would need a number measured on each runner,
and no run measures it, so it would be a guess that goes stale without anyone noticing.

## How to stay inside it

1. **Import inside the function that runs when the feature is on.** Do not import at the top
   of the file.

    ```python
    def build_widget(cfg: WidgetConfig) -> Widget | None:
        if not cfg.enabled:
            return None
        from yazses.widget.engine import Widget  # paid only by users who turned it on
        return Widget(cfg)
    ```

2. **A type you only use in annotations goes under `if TYPE_CHECKING:`.** With
   `from __future__ import annotations` the name is never evaluated at runtime.
3. **Keep the daemon's seam thin.** When the daemon must hold a slot for your feature, keep
   the imported module to a small factory that returns `None` or a null object when the
   feature is off (as `learning.capture.build_writer` and `tts.factory.build_tts` do). The
   engine stays behind it.
4. **Watch the transitive imports.** A small pure module that imports `asyncio`,
   `urllib.request` or `cryptography` at the top makes every start pay for them. Import
   those inside the method that opens the connection or the cipher, as
   `remote/local_proxy.py`, `postprocess/llm_cleanup.py` and `learning/crypto.py` do.
5. **Do not compute a module-level constant from a feature package** in a core module. That
   import runs at start. When a core table must hold a value owned by a feature, store a
   function and resolve it on first lookup. `configcheck._ENUMS` does this for the
   face-gesture names (`_ClosedSets`). It reads like a dict, and only reading the value of
   `facegesture.gesture` imports `yazses.facegesture`.
6. **Check `enabled` before importing, not after.** A factory that returns `None` when its
   feature is off is still an import if the caller imports it first. The daemon gates
   `build_writer`, `build_tts` and `build_style_rules` on the feature's `enabled`, and when
   `[earcon]` is off it holds a no-op `_SilentEarcon` instead of an `EarconPlayer(False)`.
7. **Do not derive at start what you can generate.** `cli.main()` escapes `[section]`
   names in help text on every invocation. It used to derive them from `Config`, which
   imported the whole of `yazses.config` (about 66 ms) even for `--version`. It now reads
   `src/yazses/config_sections.py`, which `scripts/gen-docs.py` writes and
   `tests/test_gen_docs.py` keeps in sync.

## Measuring your change

```sh
# What a cold daemon import loads, and what each import costs (stderr, microseconds):
uv run python -X importtime -c "import yazses.main" 2>&1 | grep yazses.<your_package>

# Who imported it: the importer is the next line below with less indentation.
uv run python -X importtime -c "import yazses.main" 2>&1 | grep -A8 yazses.<your_package>

# The guards:
uv run python -m pytest tests/test_base_weight_budget.py tests/test_default_start_stays_light.py \
  tests/test_dormant_features_stay_unimported.py -q
uv run python scripts/check_dependency_budget.py
```

## When the guard fails

- **"now imports disabled-by-default feature package(s)":** find the module-scope import
  with the `importtime` command above and move it inside the function that needs it. Do
  not add the package to `KNOWN_EAGER` to get past the test. That list records debts that
  existed when the budget was introduced, each with its reason.
- **"no longer imported … delete them from KNOWN_EAGER":** you made something lazy. Delete
  the line, which keeps the improvement from being lost later.
- **"over its budget":** something at module scope gained an import. If the growth is
  deliberate (a new core module every start genuinely needs), raise `MAX_YAZSES_MODULES`
  in the test and explain why in the pull request.
- **"import yazses modules under an OS branch":** a module-scope `if sys.platform …:`
  imports a `yazses` module, so the count differs by OS. Move the import behind
  `platform/<os>/` or into the function that needs it.
- **"`_build_pipeline` now imports disabled-by-default feature package(s)":** a builder
  imports its feature before it checks `enabled`. Check first, then import. The
  `KNOWN_AT_START` entries in that test show the shape to avoid.
- **"src/yazses/config_sections.py is stale":** you added, renamed or removed a config
  section. Run `uv run python scripts/gen-docs.py` and commit the result.

## The numbers when the budget was introduced

Measured on 2026-10-21 on a base install (`uv sync`, no extras) on Linux with CPython 3.14.
Method: a fresh interpreter per sample, `python -X importtime`, the fastest of 9 runs, with
the before and after trees run interleaved.

| Start path | Before | After |
|---|---|---|
| `import yazses.main` (daemon) | 425 modules, 92 of them `yazses.*`, 283 ms | 333 modules, 92 `yazses.*`, 260 ms |
| `import yazses.cli` | 197 modules, 22 `yazses.*`, 76 ms | 184 modules, 22 `yazses.*`, 71 ms |
| `yazses --help` | 374 modules, 32 `yazses.*`, 191 ms | 374 modules, 32 `yazses.*`, 196 ms (unchanged) |

The base dependency closure on that machine was 40 distributions, 419 MB installed. Most of
that is the speech engine (`faster-whisper`, `ctranslate2`, `onnxruntime`, `av`) and `numpy`.
Treat these as a dated measurement, not a current fact. Re-measure before you quote them.

## The follow-up the same day

Also measured on 2026-10-21, with the same method on the same machine. The "before" tree
is the start of the follow-up, which had already grown to 94 `yazses.*` modules on the
daemon path. The machine was busy (load average about 7), so timings are noisier than the
counts.

| Start path | Before | After |
|---|---|---|
| `import yazses.main` (daemon) | 340 modules, 94 `yazses.*`, 352 ms | 306 modules, 73 `yazses.*`, 346 ms |
| `yazses --version` | 237 modules, 32 `yazses.*`, 186 ms, imports `yazses.config` | 225 modules, 25 `yazses.*`, 112 ms, no `yazses.config` |
| `yazses --help` | 374 modules, 32 `yazses.*`, 250 ms | 364 modules, 25 `yazses.*`, 192 ms |
| `import yazses.cli` | 184 modules, 22 `yazses.*`, 104 ms | 184 modules, 22 `yazses.*`, 106 ms (unchanged, as expected) |

The 34 modules that left the daemon path (`earcon`, `facegesture`, `learning`, `styleguard`,
`tts`, three `system.*` modules only `tts` needed, and `sqlite3`, `tempfile`, `random`,
`wave`) cost 15 ms in import self-time, summed and taken as the fastest of 9. The
whole-import difference on a loaded machine is smaller than the run-to-run noise, so read the
daemon row for its module counts. The CLI rows are clear. `yazses.config` alone was 66 to 68 ms of
`--version` (importtime's cumulative column, varying from run to run).

Two disabled packages are still imported by `import yazses.main`, `cmdsafety` and `staged`.
The reason for each is in `KNOWN_EAGER`. A default daemon's `_build_pipeline` also imports
`gesture`, `perception`, `handsfree`, `headpointer` and `polyglot` directly, and
`facegesture` and `gaze` through them. Those are listed in
`tests/test_dormant_features_stay_unimported.py` as the next things to make lazy.
