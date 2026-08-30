"""The mic-change watcher could not fire on the setup most Linux users have.

`DeviceMonitor` decides that the microphone changed by comparing the default input
device's *name* between polls. On ALSA/PipeWire, PortAudio answers `default` — a
route, not a microphone — so it compared `default` with `default` for ever. Unplug a
headset, let a monitor's built-in microphone take over capture, and the watcher that
exists to say so stayed silent.

The limitation was documented rather than hidden, which is why it survived: the
reason given was that reading through the alias would need a PipeWire or PulseAudio
client library, "a dependency this project does not take on". That was true when it
was written and had stopped being true. `default_source_behind_alias` reads through
the alias by shelling out to `wpctl` — the same mechanism as `notify-send` and
`wl-copy`, no new dependency — and was added for `yazses audio status` and `doctor`.
The capability arrived for the diagnostics and the watcher was never moved onto it.

`effective_default_input_name` is that move, and this module pins the three things
that make it safe rather than merely working:

* a real device name still costs one PortAudio query and is never sent to `wpctl`;
* a **volume** change is not a device change — the resolver returns `(name, volume)`
  and comparing the pair would make turning the gain down look like somebody
  unplugging the microphone;
* a host that cannot see behind the alias reports "unknown", not the alias string,
  so an intermittent `wpctl` cannot make the comparison oscillate between the two
  spellings and announce a change on every flap.
"""

from __future__ import annotations

from yazses.audio.device_monitor import DeviceMonitor, device_changed
from yazses.audio.devices import effective_default_input_name, is_routing_alias


def _monitor(names, on_change, *, idle=True):
    """A DeviceMonitor driven by a scripted sequence of polled names."""
    seq = iter(names)
    return DeviceMonitor(
        poll_fn=lambda: next(seq),
        is_idle=lambda: idle,
        on_change=on_change,
    )


def test_a_real_device_name_is_returned_unchanged_and_costs_no_resolution():
    """The common non-alias case must not pay for, or depend on, `wpctl`."""
    called = []

    def resolver():
        called.append(1)
        raise AssertionError("the resolver was consulted for a real device name")

    assert effective_default_input_name(poll=lambda: "Yeti Nano", behind=resolver) == "Yeti Nano"
    assert not called


def test_an_alias_is_resolved_to_the_microphone_behind_it():
    got = effective_default_input_name(
        poll=lambda: "default", behind=lambda: ("Raptor Lake cAVS Digital Microphone", 0.47)
    )
    assert got == "Raptor Lake cAVS Digital Microphone", (
        "the alias was not resolved, so the watcher is comparing a route again"
    )
    assert is_routing_alias("default"), "the predicate that triggers resolution changed"


def test_a_volume_change_is_not_a_device_change():
    """The specific trap in reusing the diagnostic's return value.

    `parse_wpctl_default_source` yields `(name, volume)`. Comparing the pair would
    fire the "your microphone changed" notification — naming a device that did not
    change — every time the user moved the input gain.
    """
    quiet = effective_default_input_name(poll=lambda: "default", behind=lambda: ("Mic A", 0.10))
    loud = effective_default_input_name(poll=lambda: "default", behind=lambda: ("Mic A", 0.95))
    assert quiet == loud == "Mic A"
    assert not device_changed(quiet, loud), "a gain change would be reported as a new device"


def test_an_unreadable_alias_reports_unknown_rather_than_the_alias():
    """"Cannot tell" must not be spelled `default`.

    On a host where `wpctl` is absent or intermittent, returning the alias would make
    the compared value flip between `default` and the real name, and every flap would
    announce a device change that never happened. `device_changed` already treats
    None as no opinion, so unknown stays quiet.
    """
    for broken in (lambda: None, lambda: (_ for _ in ()).throw(OSError("no wpctl"))):
        got = effective_default_input_name(poll=lambda: "default", behind=broken)
        assert got is None, f"an unreadable alias returned {got!r}"
    assert not device_changed(None, "Mic A")
    assert not device_changed("Mic A", None)


def test_the_watcher_now_fires_on_a_switch_behind_the_alias():
    """End to end through `DeviceMonitor`, which is the thing that was inert.

    Same PortAudio answer (`default`) on every poll — exactly the sequence that used
    to produce nothing at all.
    """
    fired = []
    resolved = iter([("Yeti Nano", 0.5), ("Yeti Nano", 0.9), ("Laptop Microphone", 0.5)])
    seq = iter(["default", "default", "default"])
    monitor = DeviceMonitor(
        poll_fn=lambda: effective_default_input_name(
            poll=lambda: next(seq), behind=lambda: next(resolved)
        ),
        is_idle=lambda: True,
        on_change=lambda prev, cur: fired.append((prev, cur)),
    )
    assert monitor.poll_once() is False, "the first poll must only establish a baseline"
    assert monitor.poll_once() is False, "a volume-only change fired a notification"
    assert monitor.poll_once() is True, "the microphone changed and nothing was reported"
    assert fired == [("Yeti Nano", "Laptop Microphone")]


def test_the_old_behaviour_would_have_failed_this():
    """The guard is only meaningful if the previous code could not pass it.

    Comparing PortAudio's answer directly is what shipped; drive `DeviceMonitor` with
    it over the same switch and confirm it stays silent.
    """
    fired = []
    seq = iter(["default", "default", "default"])
    monitor = _monitor(seq, lambda prev, cur: fired.append((prev, cur)))
    for _ in range(3):
        monitor.poll_once()
    assert not fired, (
        "comparing the raw PortAudio name now detects a change, which means either "
        "the alias handling moved or this test no longer reproduces the old code"
    )
