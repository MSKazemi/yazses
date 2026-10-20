"""EYE-CAM-001 (#394) at the daemon boundary: the shared camera owner as the daemon holds it.

``tests/test_perception_source.py`` and ``tests/test_perception_source_concurrency.py``
prove the lifecycle on the source object itself -- one open for N leases, the last
release closes, start/stop/close are idempotent, failures are contained. Each of
those properties is only as good as the daemon that owns the source, so this file
asks the same questions of a real ``Daemon``, with fakes and no camera extra:

- a daemon with every camera feature off never imports or probes ``cv2`` or
  ``mediapipe`` -- not merely "opens no device", but "never asks whether it could";
- turning ``[perception]`` on with no camera feature still opens nothing;
- the daemon's teardown closes the camera even under a lease nobody released, and a source
  whose ``close`` raises does not stop the rest of the teardown;
- a source that cannot be built costs a log line, never a daemon that will not start.

The import tripwire is a ``sys.meta_path`` finder rather than a stub module in
``sys.modules``: a stub would satisfy ``import cv2`` silently, while the finder sees
both an ``import`` and an ``importlib.util.find_spec`` probe, which is the stronger
of the two claims the issue makes ("zero camera probes/opens").
"""
from __future__ import annotations

import dataclasses
import importlib.abc
import importlib.util
import sys
import types
from dataclasses import replace

import pytest

from yazses.config import Config, PerceptionConfig
from yazses.core.daemon import Daemon
from yazses.perception import PerceptionSample, SharedPerceptionSource, SourceState
from yazses.platform import get_platform

#: The camera stack's top-level modules. Any lookup of these from a default daemon is
#: a probe the issue says must not happen.
_CAMERA_MODULES = ("cv2", "mediapipe")


class _CameraImportTripwire(importlib.abc.MetaPathFinder):
    """Records every lookup of a camera module and refuses it, as a base install would."""

    def __init__(self) -> None:
        self.lookups: list[str] = []

    def find_spec(self, fullname, path=None, target=None):  # noqa: ARG002 - finder API
        top = fullname.partition(".")[0]
        if top in _CAMERA_MODULES:
            self.lookups.append(fullname)
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


@pytest.fixture
def tripwire(monkeypatch: pytest.MonkeyPatch) -> _CameraImportTripwire:
    wire = _CameraImportTripwire()
    for name in list(sys.modules):
        if name.partition(".")[0] in _CAMERA_MODULES:
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [wire, *sys.meta_path])
    return wire


def _daemon(cfg: Config) -> Daemon:
    return Daemon(config=cfg, platform=get_platform())


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch):
    """A daemon after the real ``_build_pipeline()``, minus the speech engine and injector.

    The camera builders run in ``_build_pipeline`` (``run()`` calls it), not in
    ``__init__``, so a test that only constructs a ``Daemon`` would pass without one
    camera builder having run. Driving the real method -- rather than a hand-written
    list of the builders it calls -- means a camera feature added there later is in
    this test without anyone remembering to add it.
    """
    import yazses.core.daemon as daemon_mod
    import yazses.inject.auto as inject_auto

    monkeypatch.setattr(daemon_mod, "build_engine", lambda stt: types.SimpleNamespace(name="stub"))
    # It exports the injector choice as process env vars, which is not this file's subject
    # and which the suite's env-leak guard rightly refuses to see left behind.
    monkeypatch.setattr(inject_auto, "apply_injection_config", lambda injection: None)
    platform = dataclasses.replace(
        get_platform(), injector_factory=lambda: types.SimpleNamespace(name="stub")
    )
    monkeypatch.setattr(platform.lifecycle, "clear_pid", lambda: None)
    made: list[Daemon] = []

    def build(cfg: Config) -> Daemon:
        daemon = Daemon(config=cfg, platform=platform)
        monkeypatch.setattr(daemon, "_announce_model_download", lambda cfg: None)
        made.append(daemon)
        daemon._build_pipeline()
        return daemon

    yield build
    for daemon in made:
        daemon._shutdown()


# --------------------------------------------------------------------------- #
# Fakes: a camera and a model that count what is done to them
# --------------------------------------------------------------------------- #


class _Capture:
    def __init__(self) -> None:
        self.opens = 0
        self.closes = 0

    def open(self) -> None:
        self.opens += 1

    def read(self) -> object | None:
        return None

    def close(self) -> None:
        self.closes += 1


class _Processor:
    name = "fake"

    def __init__(self) -> None:
        self.closes = 0

    def process(self, frame: object, timestamp_s: float) -> PerceptionSample | None:
        return None

    def close(self) -> None:
        self.closes += 1


class _IdleWorker:
    """A driver that never runs the loop body, so nothing here races a thread."""

    def join(self, timeout: float | None = None) -> None:
        return None

    def is_alive(self) -> bool:
        return False


def _source() -> tuple[SharedPerceptionSource, _Capture, _Processor]:
    capture, processor = _Capture(), _Processor()
    source = SharedPerceptionSource(
        lambda: capture, lambda: processor, spawn=lambda body, name: _IdleWorker()
    )
    return source, capture, processor


# --------------------------------------------------------------------------- #
# Dormancy: every camera feature off means zero camera probes and zero opens
# --------------------------------------------------------------------------- #


def test_the_tripwire_sees_both_an_import_and_a_probe(tripwire) -> None:
    """Without this, an empty ``lookups`` below could mean the wire was never live."""
    with pytest.raises(ModuleNotFoundError):
        import cv2  # noqa: F401
    with pytest.raises(ModuleNotFoundError):
        importlib.util.find_spec("mediapipe")
    assert tripwire.lookups == ["cv2", "mediapipe"]


def test_a_default_daemon_never_imports_or_probes_a_camera_library(tripwire, built) -> None:
    """ADR-v2-145 invariant 2, end to end, through every camera builder the daemon runs."""
    cfg = Config()
    assert not (
        cfg.perception.enabled or cfg.gaze.enabled or cfg.facegesture.enabled
        or cfg.headpointer.enabled or cfg.gesture.enabled
    ), "this test is about the shipped default, where every camera feature is off"

    daemon = built(cfg)

    assert daemon._perception is None
    assert daemon._gaze_targeter is None
    assert tripwire.lookups == [], (
        f"a daemon with every camera feature off looked up {tripwire.lookups}"
    )


def test_perception_on_with_no_camera_feature_builds_a_source_that_opens_nothing(
    tripwire, built,
) -> None:
    """The lifecycle is consumer-driven: switching on the owner alone takes no lease."""
    cfg = replace(Config(), perception=replace(PerceptionConfig(), enabled=True))

    daemon = built(cfg)

    assert daemon._perception is not None
    status = daemon._perception.status()
    assert (status.state, status.opens, status.consumers) == (SourceState.DORMANT, 0, ())
    assert tripwire.lookups == [], (
        f"building the shared source with no consumer looked up {tripwire.lookups}"
    )


# --------------------------------------------------------------------------- #
# Containment: the camera owner never takes the daemon with it
# --------------------------------------------------------------------------- #


def test_a_source_that_cannot_be_built_costs_a_log_line_not_the_daemon(monkeypatch, built) -> None:
    import yazses.perception as perception_pkg

    def explode(*args, **kwargs):
        raise RuntimeError("no camera stack on this machine")

    monkeypatch.setattr(perception_pkg, "build_perception_source", explode)
    cfg = replace(Config(), perception=replace(PerceptionConfig(), enabled=True))

    daemon = built(cfg)  # must finish: dictation does not depend on a webcam

    assert daemon._perception is None
    assert daemon._engine is not None and daemon._injector is not None


@pytest.fixture
def quiet_shutdown(monkeypatch: pytest.MonkeyPatch):
    """``_shutdown`` ends by clearing the pid file; a test has no business near the real one.

    ``_shutdown`` is the teardown ``run()`` reaches in its ``finally``; the public
    ``shutdown()`` only signals the loop to leave, so it is not what closes the camera.
    """

    def prepare(daemon: Daemon) -> Daemon:
        monkeypatch.setattr(daemon._platform.lifecycle, "clear_pid", lambda: None)
        return daemon

    return prepare


def test_shutdown_closes_the_camera_under_a_lease_nobody_released(quiet_shutdown) -> None:
    daemon = quiet_shutdown(_daemon(Config()))
    source, capture, processor = _source()
    forgotten = source.consumer("gaze")
    forgotten.start()
    source.consumer("headpointer").start()
    assert (capture.opens, source.status().state) == (1, SourceState.RUNNING)
    daemon._perception = source

    daemon._shutdown()

    assert (capture.closes, processor.closes) == (1, 1)
    status = source.status()
    assert (status.state, status.consumers, status.opens) == (SourceState.DORMANT, (), 1)
    assert forgotten.active is False
    assert forgotten.latest() is None

    daemon._shutdown()  # a second teardown closes nothing twice
    assert (capture.closes, processor.closes) == (1, 1)


def test_a_source_close_that_raises_does_not_stop_the_rest_of_shutdown(quiet_shutdown) -> None:
    class _ExplodingSource:
        def close(self) -> None:
            raise RuntimeError("camera driver wedged")

    class _Recorder:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    daemon = quiet_shutdown(_daemon(Config()))
    daemon._perception = _ExplodingSource()  # type: ignore[assignment]
    later = _Recorder()
    daemon._corpus = later  # torn down after the camera in `shutdown`

    daemon._shutdown()  # must not raise

    assert later.stopped, "a camera close that raised cut the daemon's teardown short"
