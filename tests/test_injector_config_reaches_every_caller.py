"""`[injection] backend` reached the injector only when the daemon built it.

`platform.injector_factory` is a zero-argument protocol implemented by every OS, so the
two `[injection]` settings reach the backend through environment variables that
`inject.auto.get_injector` reads. That is a sound design with one consequence nobody
wired: **only `core/daemon.py` set them.**

The three commands that build an injector outside the daemon are, all three of them, the
commands whose stated job is to test the injector:

* `yazses inject "..."` — *"Type text into the focused window without recording (tests
  the injector)."*
* `yazses test` — the local-injection fallback when no daemon is reachable.
* `yazses verify --type` — the command whose claim is that it runs the daemon's chain.

Each built `auto`. On this machine, with `backend = "clipboard"` configured, `auto`
selects `XdotoolInjector` — so a user who switched to clipboard-paste *because typing
does not reach their app* had all three diagnostics prove the backend they had rejected,
and `verify --type` certify one the daemon would not use.

The second half is what those commands then *said*. `LinuxInjector` is a selector, not a
backend; `type(injector).__name__` is "LinuxInjector" on every Linux box whatever it
chose. The daemon already preferred `backend_name` so `status` and `doctor` name the real
one — the CLI printed the wrapper, so its answer could not even be compared with theirs.

Both halves now go through `inject/auto.py`, and the guard is structural: every function
in the tree that builds an injector must apply the bridge first.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

from yazses.config import InjectionConfig
from yazses.inject.auto import apply_injection_config, describe_injector

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "yazses"

#: Non-vacuity: four builders exist today (three CLI commands and the daemon).
_MIN_BUILDERS = 4


def _builders() -> list[tuple[str, str, bool]]:
    """Every function that calls `injector_factory()`, and whether it bridges first."""
    out = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            calls = {
                (c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", ""))
                for c in ast.walk(fn)
                if isinstance(c, ast.Call)
            }
            if "injector_factory" in calls:
                out.append((
                    f"{path.relative_to(SRC.parent.parent)}:{fn.name}",
                    fn.name,
                    "apply_injection_config" in calls,
                ))
    return out


_BRIDGED = ("YAZSES_INJECTOR", "YAZSES_INJECT_FALLBACK")


@pytest.fixture(autouse=True)
def _clean_env():
    """Start clean **and** hand the environment back.

    `monkeypatch.delenv(name, raising=False)` looks like it does the second half and
    does not: when the variable is absent -- the normal case -- `delitem` records
    nothing to undo, so the fixture is inert and anything set during the test
    survives teardown. Every test here calls `apply_injection_config`, which writes
    both variables straight into `os.environ`, so every one of them leaked. Running
    the suite in reverse file order turned four assertions in `test_auto_inject.py`
    red: they asked for an xdotool injector and got this file's clipboard one.
    """
    saved = {name: os.environ.get(name) for name in _BRIDGED}
    for name in _BRIDGED:
        os.environ.pop(name, None)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


# --- every builder, not the three that were wrong -------------------------------


def test_there_are_builders_to_check():
    assert len(_builders()) >= _MIN_BUILDERS


def test_every_injector_is_built_from_the_configured_backend():
    unbridged = sorted(where for where, _, ok in _builders() if not ok)
    assert not unbridged, (
        f"these build an injector without applying [injection]: {unbridged} -- they get "
        "`auto` whatever the user configured. Call "
        "inject.auto.apply_injection_config(cfg.injection) first."
    )


def test_the_daemon_is_one_of_them():
    """It is the reference behaviour; a guard that stopped covering it proves nothing."""
    assert any(name == "_build_pipeline" for _, name, _ in _builders())


# --- the bridge -----------------------------------------------------------------


def test_a_configured_backend_reaches_the_selector():
    apply_injection_config(InjectionConfig(backend="clipboard"))
    import os

    assert os.environ["YAZSES_INJECTOR"] == "clipboard"


def test_auto_does_not_clobber_an_exported_override(monkeypatch):
    """`YAZSES_INJECTOR` in the shell is the documented one-run override."""
    monkeypatch.setenv("YAZSES_INJECTOR", "wtype")
    apply_injection_config(InjectionConfig(backend="auto"))
    import os

    assert os.environ["YAZSES_INJECTOR"] == "wtype"


@pytest.mark.parametrize("flag,expected", [(True, "1"), (False, "0")])
def test_the_clipboard_fallback_is_bridged_too(flag, expected):
    apply_injection_config(InjectionConfig(fallback_to_clipboard=flag))
    import os

    assert os.environ["YAZSES_INJECT_FALLBACK"] == expected


def test_it_survives_a_config_object_without_the_section():
    """A duck-typed config must not break a diagnostic command."""
    apply_injection_config(object())
    import os

    assert os.environ["YAZSES_INJECT_FALLBACK"] == "1"


def test_the_bridge_actually_changes_which_backend_is_selected():
    """The point of all of it: the env var is a means, the selection is the end."""
    from yazses.inject.auto import get_injector

    apply_injection_config(InjectionConfig(backend="clipboard"))
    assert type(get_injector()).__name__ == "ClipboardInjector"


# --- what the command prints ----------------------------------------------------


def test_the_concrete_backend_is_named_not_the_wrapper():
    class Wrapper:
        backend_name = "XdotoolInjector"

    assert describe_injector(Wrapper()) == "XdotoolInjector"


def test_a_backend_with_no_wrapper_names_itself():
    class ClipboardInjector:
        pass

    assert describe_injector(ClipboardInjector()) == "ClipboardInjector"


def test_an_empty_backend_name_falls_back_rather_than_printing_nothing():
    class Wrapper:
        backend_name = ""

    assert describe_injector(Wrapper()) == "Wrapper"


def test_no_command_prints_the_wrapper_class_instead_of_the_backend():
    """`type(injector).__name__` is the spelling that produced the useless answer."""
    cli = (SRC / "cli.py").read_text(encoding="utf-8")
    tree = ast.parse(cli)
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        calls = {
            (c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", ""))
            for c in ast.walk(fn)
            if isinstance(c, ast.Call)
        }
        if "injector_factory" not in calls:
            continue
        source = ast.get_source_segment(cli, fn) or ""
        if "type(injector).__name__" in source:
            offenders.append(fn.name)
    assert not offenders, (
        f"{offenders} print the selector wrapper rather than the backend it chose -- "
        "use inject.auto.describe_injector, as `status` and `doctor` already do"
    )
