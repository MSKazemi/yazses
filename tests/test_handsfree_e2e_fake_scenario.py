"""One end-to-end scenario on fakes: the T7 workflow shape, driven by the preset's own config.

Not a substitute for the human run -- `VALIDATION_MATRIX.md` T7 is a person doing this on a real
desktop, and nothing here claims that evidence. What this proves is that the *composition* holds
together: the config the preset resolves, handed to the real builders, yields a pointer, a global
stop and a recovery rule that behave as ADR-v2-148 says through the whole sequence:

    1. enable the preset (one switch, resolved by the config loader);
    2. the global state starts PAUSED, and the first arm needs a fresh signal;
    3. gaze picks a window; the pointer moves; holding still commits (dwell);
    4. the camera goes dark -> the pointer stops, nothing is replayed, no phantom click;
    5. the stop path works from that FAULTED state;
    6. re-arm is explicit and the first frame back never acts;
    7. "close this" with gaze unavailable closes nothing and says so;
    8. disabling releases everything and cannot be re-armed from a stale reference.

Fake perception source, fake pointer sink, fabricated clock. No camera, no display, no socket.
"""
from __future__ import annotations

from dataclasses import replace

from tests.pointer_fake import FakePointerSink, PointerActionKind
from yazses.config import Config, GazeConfig, load_config_checked
from yazses.gaze.route import RouteDecision, route_target
from yazses.handsfree.safety import SafetyState, gate_from_config
from yazses.headpointer.controller import SOURCE_NAME
from yazses.headpointer.runtime import build_headpointer
from yazses.perception.signals import HeadPoseSignal, PerceptionSample
from yazses.platform import get_platform


class _Camera:
    """A scripted shared camera: the test sets what the newest observation is."""

    def __init__(self) -> None:
        self.sample: PerceptionSample | None = None

    def consumer(self, name):
        camera = self

        class Lease:
            def start(self):
                pass

            def stop(self):
                pass

            def latest(self):
                return camera.sample

        return Lease()

    def show(self, t: float, yaw: float, pitch: float = 0.0) -> None:
        self.sample = PerceptionSample(t, head_pose=HeadPoseSignal(t, yaw, pitch, 0.0, 1.0))


def _clicks(sink: FakePointerSink) -> int:
    return sum(1 for a in sink.actions if a.kind is PointerActionKind.BUTTON_PRESS)


def _moved(sink: FakePointerSink) -> bool:
    return any(a.kind is PointerActionKind.MOVE_RELATIVE for a in sink.actions)


def test_the_hands_free_workflow_end_to_end_on_fakes(tmp_path, mocker):
    # 1 -- one switch, resolved to ordinary config by the loader.
    path = tmp_path / "config.toml"
    path.write_text("[handsfree]\nenabled = true\n", encoding="utf-8")
    cfg = load_config_checked(path).config
    assert cfg.headpointer.enabled and cfg.handsfree_safety.enabled and cfg.gaze.enabled

    clock = [1000.0]  # milliseconds, for the gate; the pointer reads seconds
    gate = gate_from_config(cfg, [SOURCE_NAME], clock=lambda: clock[0])
    assert gate is not None
    camera, sink = _Camera(), FakePointerSink()
    runtime = build_headpointer(
        cfg.headpointer, perception=camera, pointer_factory=lambda: sink, safety=gate,
        dwell_feedback_available=True, clock=lambda: clock[0] / 1000.0, thread=False,
    )
    assert runtime.active and runtime.notice == "", runtime.reason
    runner = runtime.runner
    assert runner is not None
    runner.start()

    def tick(yaw=0.0, pitch=0.0, *, new_frame=True, dt_ms=33.0):
        clock[0] += dt_ms
        if new_frame:
            camera.show(clock[0] / 1000.0, yaw, pitch)
            gate.sample(SOURCE_NAME, at_ms=clock[0])
        runner.pump()

    # 2 -- nothing acts before the user arms it.
    tick(0.0)
    assert gate.status().state is SafetyState.PAUSED and not _moved(sink)
    assert gate.resume().ok
    assert gate.status().state is SafetyState.ACTIVE

    # 3 -- gaze chooses a window; the head moves the pointer; holding still commits.
    decision = route_target("editor", 0.9, "terminal", confidence_min=cfg.gaze.confidence_min)
    assert decision.used_gaze and decision.target == "editor"
    tick(0.0)  # the neutral pose
    for _ in range(3):
        tick(0.2)
    assert _moved(sink)
    for _ in range(cfg.headpointer.dwell_ms // 33 + 5):  # the ticks are 33 ms apart
        tick(0.0)  # the head back at neutral: the pointer rests, and resting is the commit
    assert _clicks(sink) == 1, "dwell is the commit the preset wires"

    # 4 -- the camera goes dark: motion stops, nothing is replayed, no phantom click.
    before = len(sink.actions)
    for _ in range(40):
        tick(new_frame=False, dt_ms=33.0)
    assert len(sink.actions) == before
    assert gate.status().state is SafetyState.FAULTED

    # 5 -- the stop works from FAULTED, and the system stays stopped when the camera returns.
    gate.pause("user")
    assert gate.status().state is SafetyState.PAUSED
    for _ in range(5):
        tick(0.2)
    assert len(sink.actions) == before

    # 6 -- re-arm is explicit; the first frame back only observes.
    assert gate.resume().ok
    tick(0.2)
    assert len(sink.actions) == before, "the first frame after re-arm must not act"

    # 7 -- "close this" with gaze unavailable closes nothing and says so.
    notify = mocker.patch("yazses.system.notify.notify")
    from yazses.core.daemon import Daemon

    daemon = Daemon(
        config=replace(Config(), gaze=replace(GazeConfig(), enabled=True, **{
            "deixis": cfg.gaze.deixis,
            "refuse_destructive_fallback": cfg.gaze.refuse_destructive_fallback,
            "confirm_destructive": cfg.gaze.confirm_destructive,
        })),
        platform=get_platform(),
    )

    class _Targeter:
        last_decision = RouteDecision(target="terminal", used_gaze=False, confident=False)
        actions: list = []

        def window_action(self, action, target):
            self.actions.append((action, target))
            return True

    daemon._gaze_targeter = _Targeter()
    assert daemon._try_deixis("close this", {}) is True
    assert _Targeter.actions == [] and notify.called

    # 8 -- disabling releases everything, and a stale reference cannot re-arm it.
    gate.shutdown("preset disabled")
    runtime.stop()
    assert sink.actions[-1].kind is PointerActionKind.CLOSE, "the pointer backend is released"
    assert gate.resume().ok is False
    released = len(sink.actions)
    tick(0.4)
    assert len(sink.actions) == released, "nothing acts after the preset is disabled"
