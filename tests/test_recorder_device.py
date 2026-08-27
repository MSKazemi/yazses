"""AudioRecorder honours a pinned input device (name -> PortAudio index)."""
import pytest

from yazses.audio import recorder
from yazses.audio.devices import InputDevice
from yazses.audio.recorder import AudioRecorder


@pytest.fixture()
def sd(mocker):
    """Stand in for the sounddevice module the recorder imports on first use.

    See tests/test_recorder.py for why this is patched at the `_sd` seam.
    """
    fake = mocker.MagicMock(name="sounddevice")
    mocker.patch.object(recorder, "_sd", return_value=fake)
    return fake


def _fake_stream(mocker):
    return mocker.MagicMock()


def test_default_device_passes_none(mocker, sd):
    sd.InputStream.return_value = _fake_stream(mocker)
    mocker.patch("yazses.audio.devices.current_default_input_name", return_value="default")
    rec = AudioRecorder()  # no pin
    rec.start()
    assert sd.InputStream.call_args.kwargs["device"] is None
    assert rec.current_device_name == "default"


def test_pinned_name_resolves_to_index(mocker, sd):
    sd.InputStream.return_value = _fake_stream(mocker)
    mocker.patch(
        "yazses.audio.devices.list_input_devices",
        return_value=[
            InputDevice(0, "monitor audio", 2),
            InputDevice(7, "USB PnP Audio Device", 1),
        ],
    )
    sd.query_devices.return_value = {"name": "USB PnP Audio Device"}
    rec = AudioRecorder(device="usb")
    rec.start()
    assert sd.InputStream.call_args.kwargs["device"] == 7
    assert rec.current_device_name == "USB PnP Audio Device"


def test_explicit_int_device_passed_through(mocker, sd):
    sd.InputStream.return_value = _fake_stream(mocker)
    sd.query_devices.return_value = {"name": "dev3"}
    rec = AudioRecorder(device=3)
    rec.start()
    assert sd.InputStream.call_args.kwargs["device"] == 3


def test_unresolvable_name_falls_back_to_default(mocker, sd):
    sd.InputStream.return_value = _fake_stream(mocker)
    mocker.patch("yazses.audio.devices.list_input_devices", return_value=[])
    mocker.patch("yazses.audio.devices.current_default_input_name", return_value="default")
    rec = AudioRecorder(device="nonexistent-mic")
    rec.start()
    assert sd.InputStream.call_args.kwargs["device"] is None  # no match -> OS default
