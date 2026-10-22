"""A disabled feature stays unimported past the daemon's *start*, not only its import.

`tests/test_base_weight_budget.py` asks what ``import yazses.main`` loads -- the
module-scope half. The other half is what `Daemon.__init__` and `_build_pipeline` load
when they run with every feature at its default: an import moved from the top of
`core/daemon.py` into an unconditional call inside `__init__` would pass the budget and
still cost every user that import on every start.

So this drives a real default daemon through both and records every ``import``
statement `core/daemon.py` itself executes for a disabled-by-default feature package --
the set the budget derives from `Config`, so a feature added tomorrow is covered -- and
holds the result to the same ratchet: a package not in `KNOWN_AT_START` fails, and an
entry that stops being true fails until it is deleted. Then it turns each feature that
was made lazy on 2026-10-21 back on, to prove the recorder sees the import when it is
meant to happen and that the feature is still built, which is the "behaviour identical"
half.

**How it records, and why not a ``sys.meta_path`` finder.** The first version deleted
the watched modules from ``sys.modules`` so a finder would see them re-imported. That
left the suite with two copies of ~30 modules -- `monkeypatch` put the old objects back in
``sys.modules`` but the packages' attributes kept pointing at the new ones -- and 95
gaze, perception and head-pointer tests later in the run failed against the copy their
patches did not reach. Wrapping ``builtins.__import__`` touches no module state, and
filtering on the *calling* module makes the answer independent of what earlier tests
happened to import: an ``import`` statement in `core/daemon.py` runs (and calls
``__import__``) whether or not its target is already cached. What a feature package
imports in turn is the budget's question, answered in a fresh interpreter there.
"""
from __future__ import annotations

import builtins
import dataclasses
import types
from dataclasses import replace

import pytest

from tests.test_base_weight_budget import disabled_by_default_packages
from yazses.config import Config, EarconConfig, LearningConfig, StyleguardConfig, TtsConfig
from yazses.core.daemon import Daemon, _SilentEarcon
from yazses.platform import get_platform

#: Disabled-by-default packages a default daemon's `_build_pipeline` imports directly,
#: measured 2026-10-21, each with the call site. None of them is imported by
#: `__init__` or by ``import yazses.main``; each is a builder that imports before it
#: checks whether its feature is on. Debts, not permissions -- delete a line when it
#: stops being true, which this file enforces.
KNOWN_AT_START: dict[str, str] = {
    "gesture": "`_build_gesture` imports `gesture.runtime.GestureRuntime` before checking "
    "`[gesture] enabled`, because it always returns a runtime so `yazses gesture status` "
    "can say why nothing happens. `gesture/runtime.py` imports "
    "`facegesture.switches` at module scope, so `facegesture` loads with it.",
    "perception": "`_build_perception_source` imports `yazses.perception` before deciding "
    "whether any camera feature is on. `perception/derive.py` imports `gaze.confidence` "
    "at module scope, so `gaze` loads with it.",
    "handsfree": "`_build_handsfree_safety` imports `handsfree.safety.gate_from_config` "
    "unconditionally; the gate it builds is inert while `[handsfree_safety]` is off.",
    "headpointer": "`_build_handsfree_safety` imports `headpointer.controller.SOURCE_NAME`, "
    "a string constant, unconditionally.",
}


class _DaemonImports:
    """Records the watched packages named by ``import`` statements in `core/daemon.py`."""

    def __init__(self, watched: frozenset[str]) -> None:
        self.watched = watched
        self.names: list[str] = []
        self._real = builtins.__import__

    def __call__(self, name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if level == 0 and (globals or {}).get("__name__") == "yazses.core.daemon":
            wanted = [name] + [f"{name}.{item}" for item in (fromlist or ())]
            for full in wanted:
                parts = full.split(".")
                if len(parts) >= 2 and parts[0] == "yazses" and parts[1] in self.watched:
                    self.names.append(full)
        return self._real(name, globals, locals, fromlist, level)

    def packages(self) -> set[str]:
        return {full.split(".")[1] for full in self.names}

    @property
    def lookups(self) -> list[str]:
        return self.names


@pytest.fixture
def tripwire(monkeypatch: pytest.MonkeyPatch) -> _DaemonImports:
    recorder = _DaemonImports(disabled_by_default_packages())
    monkeypatch.setattr(builtins, "__import__", recorder)
    return recorder


def test_the_recorder_sees_a_cached_import_and_ignores_other_callers(tripwire) -> None:
    """Red-green for the recorder itself: an already-imported module still counts when
    the daemon names it, and the same statement in any other module does not."""
    import yazses.tts.factory  # noqa: F401 - cached before the daemon asks

    exec("from yazses.tts.factory import build_tts", {"__name__": "yazses.core.daemon"})
    exec("from yazses.earcon.play import EarconPlayer", {"__name__": "somewhere.else"})
    assert tripwire.packages() == {"tts"}


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch):
    """`(build)`: a daemon after `__init__` and the real `_build_pipeline()`.

    The same stubs as `tests/test_perception_daemon_lifecycle.py::built`, for the same
    reasons: no speech model, no OS hotkey listener, no injector env vars left behind.
    """
    import yazses.core.daemon as daemon_mod
    import yazses.inject.auto as inject_auto

    monkeypatch.setattr(daemon_mod, "build_engine", lambda stt: types.SimpleNamespace(name="stub"))
    monkeypatch.setattr(inject_auto, "apply_injection_config", lambda injection: None)
    platform = dataclasses.replace(
        get_platform(),
        injector_factory=lambda: types.SimpleNamespace(name="stub"),
        hotkey_factory=lambda *args: types.SimpleNamespace(run=lambda: None, stop=lambda: None),
    )
    monkeypatch.setattr(platform.lifecycle, "clear_pid", lambda: None)
    made: list[Daemon] = []

    def build(cfg: Config, *, pipeline: bool = True) -> Daemon:
        daemon = Daemon(config=cfg, platform=platform)
        made.append(daemon)
        if pipeline:
            monkeypatch.setattr(daemon, "_announce_model_download", lambda cfg: None)
            daemon._build_pipeline()
        return daemon

    yield build
    for daemon in made:
        daemon._shutdown()


def test_constructing_a_default_daemon_imports_no_disabled_feature(tripwire, started) -> None:
    daemon = started(Config(), pipeline=False)
    assert tripwire.lookups == [], (
        f"`Daemon.__init__` with every feature off imported {sorted(tripwire.packages())}. "
        "Import a feature inside the branch that runs when it is enabled -- see "
        "docs/contribute/startup-budget.md."
    )
    # And the slots hold what they always held while the feature is off.
    assert isinstance(daemon._earcon, _SilentEarcon)
    assert daemon._earcon.enabled is False
    assert daemon._style_rules is None


def test_no_new_disabled_feature_is_imported_by_the_pipeline(tripwire, started) -> None:
    daemon = started(Config())
    new = sorted(tripwire.packages() - set(KNOWN_AT_START))
    assert not new, (
        f"a default daemon's `_build_pipeline` now imports disabled-by-default feature "
        f"package(s) {new}. Check the feature's `enabled` before importing it -- see "
        "docs/contribute/startup-budget.md."
    )
    assert daemon._corpus is None
    assert daemon._tts is None


def test_the_known_at_start_list_only_shrinks(tripwire, started) -> None:
    started(Config())
    stale = sorted(set(KNOWN_AT_START) - tripwire.packages())
    assert not stale, (
        f"{stale} are no longer imported by a default daemon's start -- well done. Delete "
        "them from KNOWN_AT_START so they cannot quietly come back."
    )
    not_features = sorted(set(KNOWN_AT_START) - disabled_by_default_packages())
    assert not not_features, f"{not_features} are not disabled-by-default feature packages"


def test_the_silent_earcon_is_a_no_op_with_the_players_signature() -> None:
    silent = _SilentEarcon()
    assert silent.play("recording_start") is None
    assert silent.play("error", confidence=0.2) is None


@pytest.mark.parametrize(
    ("section", "value", "built"),
    [
        ("earcon", EarconConfig(enabled=True),
         lambda d: d._earcon.enabled is True and not isinstance(d._earcon, _SilentEarcon)),
        ("styleguard", StyleguardConfig(enabled=True), lambda d: d._style_rules is not None),
        ("tts", TtsConfig(enabled=True), lambda d: d._tts is not None),
        ("learning", LearningConfig(enabled=True), lambda d: d._corpus is not None),
    ],
)
def test_an_enabled_feature_is_still_imported_and_built(
    tripwire, started, section, value, built
) -> None:
    """The positive control: the tripwire sees the import, and the feature still exists.

    Without it, the tests above could pass because the tripwire saw nothing at all.
    """
    daemon = started(replace(Config(), **{section: value}))
    assert section in tripwire.packages(), (
        f"[{section}] is enabled but yazses.{section} was never imported"
    )
    assert built(daemon), f"[{section}] is enabled but the daemon did not build it"
