"""Gesture Chords are reachable -- and only as reachable as they honestly are (#408).

The claims, each of which has been false somewhere in this programme before:

* **The registry tells the truth.** `gesture` leaves ``_UNWIRED`` only because the daemon now
  builds, starts and stops it; ``tests/test_feature_wiring_honesty.py`` recomputes reachability
  from the entry points, and this file asserts the behaviour behind the import.
* **A default install is unchanged**: off, nothing built, nothing leased, an inert IPC reply.
* **Enabling the feature binds nothing.** The empty mapping is the safe default.
* **Shutdown order is the ADR's**: actions suppressed first, chords stopped, then the shared
  camera closed.
* **A chord can only name an abstract action**, and the destructive ones go through the
  activation policy (no prompt is wired for chords, so they are refused).

Nothing here opens a camera, a display or a socket.
"""
from __future__ import annotations

import inspect

from yazses.config import Config
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.system.features import _registry, feature_status, unwired_slugs


def _daemon(cfg: Config | None = None):
    from yazses.core.daemon import Daemon

    return Daemon(config=cfg or Config(), platform=get_platform())


class _Source:
    def __init__(self) -> None:
        self.leases: list[str] = []

    def consumer(self, name: str):
        self.leases.append(name)

        class Lease:
            def start(self) -> None:
                raise AssertionError("building the runtime must not lease the camera")

            def stop(self) -> None:
                pass

            def latest(self):
                return None

        return Lease()


# --------------------------------------------------------------------------- #
# Registry honesty
# --------------------------------------------------------------------------- #
def test_gesture_is_no_longer_advertised_as_unwired():
    assert "gesture" not in unwired_slugs()
    feature = next(f for f in feature_status(Config()) if f.slug == "gesture")
    assert feature.wired is True


def test_enabling_and_disabling_the_feature_touch_exactly_one_key():
    definition = next(d for d in _registry() if d.slug == "gesture")
    assert {(s, k, v) for s, k, v, _ in definition.on_writes} == {("gesture", "enabled", "true")}
    assert {(s, k, v) for s, k, v, _ in definition.off_writes} == {("gesture", "enabled", "false")}


def test_the_documented_camera_dependencies_are_the_ones_the_runtime_needs():
    from yazses.system.features import _FEATURE_DEPS

    assert _FEATURE_DEPS["gesture"] == _FEATURE_DEPS["gaze"]


def test_the_registry_does_not_promise_a_binding_that_does_not_exist():
    from yazses.system.features import _EXAMPLES, _USE_CASES

    text = f"{_EXAMPLES['gesture']} {_USE_CASES['gesture']}".lower()
    assert "hotkey" not in text and "profile" not in text and "send" not in text


# --------------------------------------------------------------------------- #
# A default install is unchanged
# --------------------------------------------------------------------------- #
def test_a_default_daemon_builds_an_inert_runtime_and_answers_status():
    daemon = _daemon()
    runtime = daemon._build_gesture(Config())
    assert runtime.runner is None and runtime.reason == ""
    daemon._gesture = runtime
    assert daemon._handle_gesture(Request("gesture", {"action": "status"})) == {
        "ok": True, "active": False, "reason": "", "problems": [],
    }


def test_a_default_daemon_asks_for_no_camera_and_registers_no_gate_source():
    cfg = Config()
    assert _daemon(cfg)._build_perception_source(cfg) is None
    cfg.handsfree_safety.enabled = True
    gate = _daemon(cfg)._build_handsfree_safety(cfg)
    assert [s.name for s in gate.status().sources] == ["headpointer"]


def test_the_ipc_method_is_registered():
    source = inspect.getsource(type(_daemon()))
    assert 'server.register("gesture", self._handle_gesture)' in source


def test_the_daemon_starts_and_stops_the_runtime():
    from yazses.core.daemon import Daemon

    run = inspect.getsource(Daemon.run)
    assert "self._start_gesture()" in run
    assert "self._gesture.stop()" in inspect.getsource(Daemon._shutdown)


def test_shutdown_stops_the_chords_before_the_shared_camera_is_closed():
    from yazses.core.daemon import Daemon

    text = inspect.getsource(Daemon._shutdown)
    order = [text.index(marker) for marker in (
        "self._handsfree_safety.shutdown", "self._gesture.stop()", "self._perception.close()",
    )]
    assert order == sorted(order)


# --------------------------------------------------------------------------- #
# Enabled
# --------------------------------------------------------------------------- #
def test_enabling_the_feature_binds_nothing_and_says_so():
    cfg = Config()
    cfg.gesture.enabled = True
    daemon = _daemon(cfg)
    runtime = daemon._build_gesture(cfg)
    assert runtime.runner is None and "no chords are bound" in runtime.reason
    daemon._gesture = runtime
    reply = daemon._handle_gesture(Request("gesture", {"action": "pause"}))
    assert reply["ok"] is False and "no chords are bound" in reply["reason"]


def test_the_shared_camera_is_implied_but_the_users_config_is_not_rewritten():
    from yazses.perception import SharedPerceptionSource

    cfg = Config()
    cfg.gesture.enabled = True
    assert cfg.perception.enabled is False
    source = _daemon(cfg)._build_perception_source(cfg)
    assert isinstance(source, SharedPerceptionSource)
    assert cfg.perception.enabled is False


def test_the_gate_registers_the_gesture_source_only_when_chords_can_run():
    cfg = Config()
    cfg.handsfree_safety.enabled = True
    cfg.gesture.enabled = True                 # but no chord: nothing would ever sample it
    names = [s.name for s in _daemon(cfg)._build_handsfree_safety(cfg).status().sources]
    assert names == ["headpointer"]
    cfg.gesture.chords = {"nod": "recenter"}
    names = [s.name for s in _daemon(cfg)._build_handsfree_safety(cfg).status().sources]
    assert names == ["gesture", "headpointer"]


def test_a_bound_chord_builds_a_runner_that_leases_nothing_until_started():
    cfg = Config()
    cfg.gesture.enabled = True
    cfg.gesture.chords = {"jaw_open+nod": "command:undo"}
    daemon = _daemon(cfg)
    daemon._perception = _Source()
    runtime = daemon._build_gesture(cfg)
    assert runtime.runner is not None, runtime.reason
    assert daemon._perception.leases == ["gesture"]    # a lease object, not a started lease
    assert runtime.command("status")["chords"] == 1


def test_a_daemon_that_cannot_build_it_stays_up(monkeypatch):
    cfg = Config()
    cfg.gesture.enabled = True
    cfg.gesture.chords = {"nod": "recenter"}
    import yazses.gesture.runtime as rt

    def boom(*a, **k):
        raise RuntimeError("builder bug")

    monkeypatch.setattr(rt, "build_gesture", boom)
    runtime = _daemon(cfg)._build_gesture(cfg)
    assert runtime.runner is None and "RuntimeError" in runtime.reason


def test_a_command_chord_runs_through_the_daemons_own_grammar_and_policy():
    """`command:` actions reach `commands.grammar.classify` and the activation policy."""
    cfg = Config()
    cfg.gesture.enabled = True
    cfg.gesture.chords = {"nod": "command:undo", "tilt": "command:save"}
    daemon = _daemon(cfg)
    daemon._perception = _Source()
    dispatched: list[str] = []
    daemon._gesture_dispatch = lambda intent: dispatched.append(intent.action)  # type: ignore[method-assign]
    runtime = daemon._build_gesture(cfg)
    engine = runtime.runner.engine
    engine.pulse("nod", 1.0)                   # undo: reversible, runs
    engine.press("tilt", 5.0)                  # save: irreversible, no prompt, refused
    assert dispatched == ["undo"]
