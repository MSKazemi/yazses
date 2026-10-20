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
| `asyncio`, the `urllib`/`http`/`ssl` network stack, `cryptography`, `importlib.metadata` at a default start | same file, `NOT_LOADED_BY` | One of them is loaded again |
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
   import runs at start. `configcheck.py` deriving the face-gesture names is the remaining
   example, and it is listed in `KNOWN_EAGER`.

## Measuring your change

```sh
# What a cold daemon import loads, and what each import costs (stderr, microseconds):
uv run python -X importtime -c "import yazses.main" 2>&1 | grep yazses.<your_package>

# Who imported it: the importer is the next line below with less indentation.
uv run python -X importtime -c "import yazses.main" 2>&1 | grep -A8 yazses.<your_package>

# The guards:
uv run python -m pytest tests/test_base_weight_budget.py tests/test_default_start_stays_light.py -q
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
