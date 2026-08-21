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


def test_a_routing_alias_is_not_a_microphone_name():
    """`default` names a route, not a device, and that breaks change detection.

    On this machine PortAudio reports the default input as index 10, name
    `default` — an entry in the device list alongside the physical
    `sof-hda-dsp: - (hw:0,0)`. On ALSA/PipeWire it is a virtual route: whatever
    microphone it points at, the name it reports is always `default`.

    `DeviceMonitor` detects a change by comparing that name over time, so on the
    most common Linux audio stack it compares `default` with `default` for ever
    and the proactive half of the mic guard cannot fire. Seeing through the alias
    needs a PipeWire or PulseAudio client library, which this project does not
    take on; naming the limitation where a user looks is what is available.

    The streak-based half is unaffected — it counts outcomes, not device names.
    """
    from yazses.audio.devices import is_routing_alias

    assert is_routing_alias("default") is True
    assert is_routing_alias("pipewire") is True
    assert is_routing_alias("sysdefault") is True
    assert is_routing_alias("pulse") is True
    assert is_routing_alias("Default") is True, "PortAudio casing varies"

    assert is_routing_alias("sof-hda-dsp: - (hw:0,0)") is False
    assert is_routing_alias("USB PnP Audio Device") is False
    assert is_routing_alias("") is False
    assert is_routing_alias(None) is False


WPCTL_SAMPLE = """\
 ├─ Sources:
 │      59. Raptor Lake-P/U/H cAVS Headphones Stereo Microphone [vol: 1.00]
 │  *   60. Raptor Lake-P/U/H cAVS Digital Microphone [vol: 0.65]
 │  
 ├─ Source endpoints:
 │  
 └─ Streams:
"""


def test_the_default_source_behind_the_alias_is_read_from_wpctl():
    """`default` is unhelpful on the one screen you open when dictation stops.

    Taken verbatim from a machine where every dictation decoded to nothing: the
    alias pointed at the internal digital mic array at 65% gain, while a second
    source sat at 100%. Nothing in YazSes could say that, so the diagnosis had to
    be done by hand outside the tool.

    Shelling out to `wpctl` matches how this project already gets `notify-send`,
    `xdotool` and `wl-copy` -- a tool that is present on the system, used
    best-effort, never required.
    """
    from yazses.audio.devices import parse_wpctl_default_source

    got = parse_wpctl_default_source(WPCTL_SAMPLE)
    assert got == ("Raptor Lake-P/U/H cAVS Digital Microphone", 0.65), got


def test_no_starred_source_is_not_a_guess():
    """With nothing marked default, saying which one it is would be invention."""
    from yazses.audio.devices import parse_wpctl_default_source

    without_star = WPCTL_SAMPLE.replace("*", " ")
    assert parse_wpctl_default_source(without_star) is None
    assert parse_wpctl_default_source("") is None
    assert parse_wpctl_default_source("wpctl: command not found") is None


def test_a_source_named_like_a_sink_is_not_picked_up():
    """Only the Sources block counts — Sinks carry the same shape and a star."""
    from yazses.audio.devices import parse_wpctl_default_source

    text = (
        " ├─ Sinks:\n"
        " │  *   41. Built-in Audio Speaker [vol: 0.80]\n"
        " │  \n"
        " ├─ Sources:\n"
        " │  *   60. Real Microphone [vol: 0.65]\n"
    )
    assert parse_wpctl_default_source(text) == ("Real Microphone", 0.65)
