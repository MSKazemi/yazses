"""Pure input-device enumeration + name resolution (no audio backend touched)."""
from yazses.audio.devices import (
    InputDevice,
    default_input_name,
    list_input_devices,
    resolve_input_device,
)

# A representative PortAudio device list (mixed input/output), as query_devices returns.
_RAW = [
    {"name": "sof-hda-dsp: playback", "max_input_channels": 0, "max_output_channels": 2},
    {"name": "AT Translated Set 2 keyboard", "max_input_channels": 2, "max_output_channels": 0},
    {"name": "USB PnP Audio Device", "max_input_channels": 1, "max_output_channels": 0},
    {"name": "default", "max_input_channels": 32, "max_output_channels": 32},
]


def test_list_input_devices_filters_and_preserves_index():
    devices = list_input_devices(query=lambda: _RAW, default_index=2)
    # Only capture-capable entries; the output-only device 0 is dropped.
    assert [d.index for d in devices] == [1, 2, 3]
    assert [d.name for d in devices] == [
        "AT Translated Set 2 keyboard",
        "USB PnP Audio Device",
        "default",
    ]
    # The PortAudio index (position in the FULL list) is preserved for InputStream.
    usb = next(d for d in devices if "USB" in d.name)
    assert usb.index == 2 and usb.is_default is True


def test_list_input_devices_default_by_name_when_index_unset():
    # Some ALSA setups leave the default index unset but expose a named "default".
    devices = list_input_devices(query=lambda: _RAW, default_index=None, default_name="default")
    default = [d for d in devices if d.is_default]
    assert len(default) == 1 and default[0].name == "default"


def test_default_input_name():
    devices = list_input_devices(query=lambda: _RAW, default_index=1)
    assert default_input_name(devices) == "AT Translated Set 2 keyboard"
    assert default_input_name([]) is None


def _devs():
    return [
        InputDevice(1, "AT Translated Set 2 keyboard", 2),
        InputDevice(2, "USB PnP Audio Device", 1),
        InputDevice(11, "default", 32),
    ]


def test_resolve_substring_case_insensitive():
    assert resolve_input_device("usb", _devs()) == 2
    assert resolve_input_device("AT TRANSLATED", _devs()) == 1


def test_resolve_exact_name_wins_over_substring():
    devs = [InputDevice(1, "Microphone", 2), InputDevice(2, "Microphone (USB)", 2)]
    # "Microphone" exactly matches device 1 even though it is a substring of device 2.
    assert resolve_input_device("Microphone", devs) == 1


def test_resolve_survives_index_shift():
    # After a hotplug the same mic moves from index 2 to 5; name resolution follows it.
    before = resolve_input_device("USB", _devs())
    shifted = [
        InputDevice(0, "new monitor audio", 2),
        InputDevice(5, "USB PnP Audio Device", 1),
    ]
    after = resolve_input_device("USB", shifted)
    assert before == 2 and after == 5


def test_resolve_blank_or_no_match_is_none():
    assert resolve_input_device("", _devs()) is None
    assert resolve_input_device("   ", _devs()) is None
    assert resolve_input_device("bluetooth headset", _devs()) is None
