"""Silent-streak tracker + default-device change detection (pure, no threads)."""
from yazses.audio.device_monitor import (
    DeviceMonitor,
    SilentStreakTracker,
    device_changed,
)


def test_silent_streak_counts_and_resets():
    t = SilentStreakTracker()
    assert t.streak == 0
    assert t.record_silent() == 1
    assert t.record_silent() == 2
    assert t.streak == 2
    t.record_success()
    assert t.streak == 0


def test_silent_streak_should_notify_threshold():
    t = SilentStreakTracker()
    t.record_silent()
    t.record_silent()
    assert t.should_notify(3) is False
    t.record_silent()
    assert t.should_notify(3) is True
    # A zero/negative threshold never fires.
    assert t.should_notify(0) is False


def test_device_changed_only_between_known_names():
    assert device_changed("A", "B") is True
    assert device_changed("A", "A") is False
    assert device_changed(None, "A") is False  # establishing a baseline is quiet
    assert device_changed("A", None) is False


def test_monitor_baseline_then_change():
    seq = iter(["MicA", "MicA", "MicB"])
    fired: list[tuple] = []
    mon = DeviceMonitor(
        poll_fn=lambda: next(seq),
        is_idle=lambda: True,
        on_change=lambda prev, cur: fired.append((prev, cur)),
    )
    assert mon.poll_once() is False  # baseline "MicA", no fire
    assert mon.poll_once() is False  # still "MicA"
    assert mon.poll_once() is True  # -> "MicB" fires
    assert fired == [("MicA", "MicB")]


def test_monitor_skips_polling_while_not_idle():
    calls = {"n": 0}

    def poll():
        calls["n"] += 1
        return "MicA"

    mon = DeviceMonitor(poll_fn=poll, is_idle=lambda: False, on_change=lambda p, c: None)
    assert mon.poll_once() is False
    assert calls["n"] == 0  # never touched the audio backend during "recording"


def test_monitor_swallows_poll_errors():
    def boom():
        raise RuntimeError("backend gone")

    mon = DeviceMonitor(poll_fn=boom, is_idle=lambda: True, on_change=lambda p, c: None)
    assert mon.poll_once() is False  # error is contained, no raise
