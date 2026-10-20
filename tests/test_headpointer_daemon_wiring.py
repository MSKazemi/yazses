"""The Head-Pointer is reachable -- and only as reachable as it honestly is (#404, #405).

Four claims, each of which has been false somewhere in this programme before:

* **The registry tells the truth.** `headpointer` leaves ``_UNWIRED`` only because the daemon
  now builds, starts and stops it, and the entry point it is reached through is tested here,
  not assumed. (``tests/test_feature_wiring_honesty.py`` recomputes reachability from the
  entry points on every run; this file asserts the *behaviour* behind the import.)
* **A default install is unchanged.** `[headpointer]` ships off, so the daemon builds an
  inert runtime: no pointer sink, no camera lease, no thread, no IPC side effect.
* **Shutdown order is the ADR's.** Actions are suppressed first (the global gate), the
  Head-Pointer is stopped next, and only then is the shared camera closed -- never the
  reverse, which would leave a pointer driven by a camera that is being torn out from under it.
* **The Linux pointer is honest about Wayland.** XTEST reaches XWayland only, so on a native
  Wayland session the platform says "unsupported" instead of handing back a sink that accepts
  every move and shows the user nothing.

Nothing here opens a camera, a display or a socket.
"""
from __future__ import annotations

import dataclasses
import inspect
import sys

import pytest

from tests.pointer_fake import FakePointerSink
from yazses.config import Config
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.pointer.base import PointerUnsupportedError
from yazses.system.features import _registry, feature_status, unwired_slugs


class _Source:
    """Just enough of a shared source for the builder: it hands out leases."""

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


def _daemon(cfg: Config | None = None, platform=None):
    from yazses.core.daemon import Daemon

    return Daemon(config=cfg or Config(), platform=platform or get_platform())


# --------------------------------------------------------------------------- #
# Registry honesty
# --------------------------------------------------------------------------- #
def test_headpointer_is_no_longer_advertised_as_unwired():
    assert "headpointer" not in unwired_slugs()
    feature = next(f for f in feature_status(Config()) if f.slug == "headpointer")
    assert feature.wired is True


def test_enabling_and_disabling_the_feature_touch_exactly_one_key():
    """One switch for the user; `disable` undoes `enable` exactly."""
    definition = next(d for d in _registry() if d.slug == "headpointer")
    assert {(s, k, v) for s, k, v, _ in definition.on_writes} == {
        ("headpointer", "enabled", "true"),
    }
    assert {(s, k, v) for s, k, v, _ in definition.off_writes} == {
        ("headpointer", "enabled", "false"),
    }


def test_the_pointer_implies_the_shared_camera_so_there_is_no_second_switch_to_find():
    from yazses.perception import SharedPerceptionSource

    off = Config()
    assert _daemon(off)._build_perception_source(off) is None  # a default install: nothing

    on = Config()
    on.headpointer.enabled = True
    assert on.perception.enabled is False  # the user never touched [perception]
    source = _daemon(on)._build_perception_source(on)
    assert isinstance(source, SharedPerceptionSource)
    assert on.perception.enabled is False  # and building it did not rewrite their config


def test_the_documented_camera_dependencies_are_the_ones_the_runtime_needs():
    from yazses.system.features import _FEATURE_DEPS

    assert _FEATURE_DEPS["headpointer"] == _FEATURE_DEPS["gaze"]


# --------------------------------------------------------------------------- #
# A default install is unchanged
# --------------------------------------------------------------------------- #
def test_a_default_daemon_builds_an_inert_head_pointer():
    built: list[int] = []
    platform = dataclasses.replace(
        get_platform(), pointer_factory=lambda: built.append(1)  # type: ignore[arg-type,return-value]
    )
    daemon = _daemon(platform=platform)
    runtime = daemon._build_headpointer(Config())
    assert runtime.runner is None and runtime.reason == ""
    assert built == []  # no pointer session was asked for
    daemon._headpointer = runtime
    assert daemon._handle_headpointer(Request("headpointer", {"action": "status"})) == {
        "ok": True, "active": False, "reason": "",
    }


def test_the_daemon_has_no_safety_gate_unless_the_user_opted_in():
    daemon = _daemon()
    assert daemon._build_handsfree_safety(Config()) is None
    cfg = Config()
    cfg.handsfree_safety.enabled = True
    gate = daemon._build_handsfree_safety(cfg)
    assert gate is not None
    assert gate.gate("headpointer").allowed is False  # starts PAUSED: nothing armed it


def test_enabled_but_without_the_shared_camera_the_reason_is_kept_for_status():
    daemon = _daemon()
    cfg = Config()
    cfg.headpointer.enabled = True
    daemon._perception = None  # the source could not be built
    runtime = daemon._build_headpointer(cfg)
    assert runtime.runner is None
    assert "shared camera source" in runtime.reason
    daemon._headpointer = runtime
    reply = daemon._handle_headpointer(Request("headpointer", {"action": "status"}))
    assert reply["active"] is False and "shared camera source" in str(reply["reason"])
    daemon._start_headpointer()  # logs why; starts nothing; does not raise


def test_enabled_with_everything_present_builds_a_runner_without_leasing_the_camera():
    daemon = _daemon()
    sink = FakePointerSink()
    source = _Source()
    daemon._perception = source  # type: ignore[assignment]
    daemon._platform = dataclasses.replace(get_platform(), pointer_factory=lambda: sink)
    cfg = Config()
    cfg.headpointer.enabled = True
    runtime = daemon._build_headpointer(cfg)
    assert runtime.runner is not None
    assert source.leases == ["headpointer"]  # a lease object exists...
    # ...and constructing it started nothing (the fake lease raises if start() is called).


def test_a_pointer_backend_that_will_not_open_never_stops_the_daemon_building():
    daemon = _daemon()
    daemon._perception = _Source()  # type: ignore[assignment]

    def refuse():
        raise PointerUnsupportedError("no X server")

    daemon._platform = dataclasses.replace(get_platform(), pointer_factory=refuse)
    cfg = Config()
    cfg.headpointer.enabled = True
    runtime = daemon._build_headpointer(cfg)
    assert runtime.runner is None and "no X server" in runtime.reason


def test_building_the_shared_source_wires_the_camera_lazily():
    """`[perception]` on gives a source with the real backends -- and still opens nothing."""
    from yazses.perception import SharedPerceptionSource, SourceState

    cfg = Config()
    cfg.perception.enabled = True
    source = _daemon(cfg)._build_perception_source(cfg)
    assert isinstance(source, SharedPerceptionSource)
    assert source.status().state is SourceState.DORMANT
    assert source.status().opens == 0


# --------------------------------------------------------------------------- #
# The command surface is on the IPC server
# --------------------------------------------------------------------------- #
def test_the_headpointer_method_is_registered_on_the_ipc_server():
    class Server:
        def __init__(self) -> None:
            self.methods: dict[str, object] = {}

        def register(self, name: str, handler) -> None:
            self.methods[name] = handler

        def serve_in_thread(self) -> None:
            pass

    server = Server()
    platform = dataclasses.replace(get_platform(), ipc_server_factory=lambda _p: server)
    daemon = _daemon(platform=platform)
    daemon._start_ipc_server()
    assert server.methods["headpointer"] == daemon._handle_headpointer


def test_a_command_that_raises_is_contained_and_reported():
    daemon = _daemon()

    class Exploding:
        def command(self, action, params):
            raise RuntimeError("boom")

    daemon._headpointer = Exploding()
    reply = daemon._handle_headpointer(Request("headpointer", {"action": "recenter"}))
    assert reply["ok"] is False and "RuntimeError" in str(reply["reason"])


def test_a_daemon_that_never_built_one_answers_politely():
    daemon = _daemon()
    daemon._headpointer = None
    reply = daemon._handle_headpointer(Request("headpointer", {"action": "pause"}))
    assert reply["ok"] is False


# --------------------------------------------------------------------------- #
# Shutdown order: suppress, then stop the pointer, then close the camera
# --------------------------------------------------------------------------- #
def test_shutdown_suppresses_actions_before_stopping_the_pointer_before_closing_the_camera():
    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon._shutdown)
    gate = source.index("self._handsfree_safety.shutdown")
    pointer = source.index("self._headpointer.stop")
    camera = source.index("self._perception.close")
    assert gate < pointer < camera


def test_the_class_level_defaults_survive_a_partial_daemon():
    from yazses.core.daemon import Daemon

    bare = Daemon.__new__(Daemon)  # no __init__: a daemon that failed early
    assert bare._headpointer is None and bare._handsfree_safety is None


def test_run_starts_the_head_pointer_after_the_pipeline_is_ready():
    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon.run)
    assert source.index("self._build_pipeline()") < source.index("self._start_headpointer()")
    assert source.index("self._start_headpointer()") < source.index("self._hotkey.run()")


# --------------------------------------------------------------------------- #
# Linux: an honest pointer factory
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the Linux platform bundle")
class TestLinuxPointerFactory:
    def test_the_platform_bundle_carries_a_lazy_factory(self):
        from yazses.platform.linux import build_platform

        assert build_platform().pointer_factory is not None  # a factory, not a live sink

    def test_a_native_wayland_session_is_unsupported_rather_than_a_silent_sink(self, monkeypatch):
        from yazses.platform import linux

        opened: list[int] = []
        monkeypatch.setattr(linux, "build_pointer_sink", lambda: opened.append(1))
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        with pytest.raises(PointerUnsupportedError, match="Wayland"):
            linux._pointer_factory()
        assert opened == []  # XTEST was never touched

    def test_an_x11_session_builds_the_x11_sink(self, monkeypatch):
        from yazses.platform import linux

        sentinel = object()
        monkeypatch.setattr(linux, "build_pointer_sink", lambda: sentinel)
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        assert linux._pointer_factory() is sentinel
        monkeypatch.delenv("XDG_SESSION_TYPE")
        assert linux._pointer_factory() is sentinel


# --------------------------------------------------------------------------- #
# What `status` carries for the overlay and the tray
# --------------------------------------------------------------------------- #
def test_status_has_no_headpointer_block_unless_it_is_running():
    daemon = _daemon()
    daemon._headpointer = None
    assert daemon._headpointer_payload() is None
    from yazses.headpointer.runtime import HeadPointerRuntime

    daemon._headpointer = HeadPointerRuntime(reason="off")
    assert daemon._headpointer_payload() is None  # byte-for-byte the old reply for everyone else


def test_status_carries_dwell_progress_but_no_pose_or_position():
    daemon = _daemon()
    sink = FakePointerSink()
    daemon._perception = _Source()  # type: ignore[assignment]
    daemon._platform = dataclasses.replace(get_platform(), pointer_factory=lambda: sink)
    cfg = Config()
    cfg.headpointer.enabled = True
    daemon._headpointer = daemon._build_headpointer(cfg)
    payload = daemon._headpointer_payload()
    assert payload is not None and payload["active"] is True
    assert "dwell_progress" in payload
    assert not {"yaw", "pitch", "roll", "x", "y", "position"} & set(payload)


def test_the_status_reply_lists_the_headpointer_key():
    from yazses.core.daemon import Daemon

    assert '"headpointer": self._headpointer_payload()' in inspect.getsource(Daemon._handle_status)


def test_the_hands_free_health_counts_the_head_pointer_as_a_camera_consumer():
    import types

    from yazses.core.daemon import Daemon
    from yazses.headpointer.runtime import HeadPointerRuntime

    cfg = Config()
    cfg.headpointer.enabled = True
    sink = FakePointerSink()

    def fake(headpointer):
        ns = types.SimpleNamespace(
            _config=cfg, _gaze_targeter=None, _extra_activations=[], _headpointer=headpointer,
        )
        return Daemon._handsfree_payload(ns)

    running = HeadPointerRuntime(runner=_Runner(sink))  # type: ignore[arg-type]
    assert fake(running)["perception_state"] == "running"
    assert fake(running)["perception_consumers"] == 1
    assert fake(HeadPointerRuntime(reason="off"))["perception_state"] != "running"
    # A daemon that never assigned the attribute (older stand-ins) must still answer.
    bare = types.SimpleNamespace(_config=cfg, _gaze_targeter=None, _extra_activations=[])
    assert Daemon._handsfree_payload(bare)["perception_consumers"] == 0


class _Runner:
    """Stands in for a runner: only its presence matters to the health payload."""

    def __init__(self, sink) -> None:
        self.sink = sink
