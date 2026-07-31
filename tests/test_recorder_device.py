"""AudioRecorder honours a pinned input device (name -> PortAudio index)."""
from yazses.audio import recorder
from yazses.audio.devices import InputDevice
from yazses.audio.recorder import AudioRecorder


def _fake_stream(mocker):
    return mocker.MagicMock()


def test_default_device_passes_none(mocker):
    stream = _fake_stream(mocker)
    factory = mocker.patch.object(recorder.sd, "InputStream", return_value=stream)
    mocker.patch("yazses.audio.devices.current_default_input_name", return_value="default")
    rec = AudioRecorder()  # no pin
    rec.start()
    assert factory.call_args.kwargs["device"] is None
    assert rec.current_device_name == "default"


def test_pinned_name_resolves_to_index(mocker):
    stream = _fake_stream(mocker)
    factory = mocker.patch.object(recorder.sd, "InputStream", return_value=stream)
    mocker.patch(
        "yazses.audio.devices.list_input_devices",
        return_value=[
            InputDevice(0, "monitor audio", 2),
            InputDevice(7, "USB PnP Audio Device", 1),
        ],
    )
    mocker.patch.object(
        recorder.sd, "query_devices", return_value={"name": "USB PnP Audio Device"}
    )
    rec = AudioRecorder(device="usb")
    rec.start()
    assert factory.call_args.kwargs["device"] == 7
    assert rec.current_device_name == "USB PnP Audio Device"


def test_explicit_int_device_passed_through(mocker):
    stream = _fake_stream(mocker)
    factory = mocker.patch.object(recorder.sd, "InputStream", return_value=stream)
    mocker.patch.object(recorder.sd, "query_devices", return_value={"name": "dev3"})
    rec = AudioRecorder(device=3)
    rec.start()
    assert factory.call_args.kwargs["device"] == 3


def test_unresolvable_name_falls_back_to_default(mocker):
    stream = _fake_stream(mocker)
    factory = mocker.patch.object(recorder.sd, "InputStream", return_value=stream)
    mocker.patch("yazses.audio.devices.list_input_devices", return_value=[])
    mocker.patch("yazses.audio.devices.current_default_input_name", return_value="default")
    rec = AudioRecorder(device="nonexistent-mic")
    rec.start()
    assert factory.call_args.kwargs["device"] is None  # no match -> OS default
