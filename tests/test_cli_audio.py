"""`yazses audio devices / use` CLI group."""
from typer.testing import CliRunner

from yazses import cli
from yazses.audio.devices import InputDevice

runner = CliRunner()
_ENV = {"COLUMNS": "220", "TERM": "dumb"}


def test_audio_devices_lists_with_markers(mocker):
    mocker.patch(
        "yazses.audio.devices.list_input_devices",
        return_value=[
            InputDevice(1, "AT Translated Set 2 keyboard", 2, is_default=True),
            InputDevice(7, "USB PnP Audio Device", 1),
        ],
    )
    r = runner.invoke(cli.app, ["audio", "devices"], env=_ENV)
    assert r.exit_code == 0
    assert "AT Translated Set 2 keyboard" in r.output
    assert "USB PnP Audio Device" in r.output
    assert "●" in r.output  # default marker


def test_audio_use_writes_config(mocker):
    set_key = mocker.patch("yazses.system.configedit.set_config_key", return_value="added")
    mocker.patch(
        "yazses.audio.devices.list_input_devices",
        return_value=[InputDevice(1, "AT Translated Set 2 keyboard", 2)],
    )
    r = runner.invoke(cli.app, ["audio", "use", "AT Translated"], env=_ENV)
    assert r.exit_code == 0
    section, key, value = set_key.call_args.args[1:4]
    assert (section, key, value) == ("audio", "device", "AT Translated")
    assert "restart" in r.output.lower()


def test_audio_use_clear_unpins(mocker):
    set_key = mocker.patch("yazses.system.configedit.set_config_key", return_value="updated")
    r = runner.invoke(cli.app, ["audio", "use", "--clear"], env=_ENV)
    assert r.exit_code == 0
    section, key, value = set_key.call_args.args[1:4]
    assert (section, key, value) == ("audio", "device", "")
    assert "default" in r.output.lower()


def test_audio_use_requires_name(mocker):
    set_key = mocker.patch("yazses.system.configedit.set_config_key")
    r = runner.invoke(cli.app, ["audio", "use"], env=_ENV)
    assert r.exit_code == 2
    set_key.assert_not_called()


# ---- `audio use` confirmed pins it had not checked meant anything ------------
#
# It called the resolver only to ask "did anything match?", then echoed back the string
# the user typed. Two names it accepted without a word cannot deliver what pinning
# promises: one that several devices answer to, and one that names a route.

_THREE = [
    InputDevice(0, "sof-hda-dsp: - (hw:0,0)", 2),
    InputDevice(4, "sof-hda-dsp: - (hw:0,6)", 2),
    InputDevice(5, "sof-hda-dsp: - (hw:0,7)", 2),
]


def test_audio_use_refuses_a_name_several_devices_answer_to(mocker):
    set_key = mocker.patch("yazses.system.configedit.set_config_key")
    mocker.patch("yazses.audio.devices.list_input_devices", return_value=_THREE)
    r = runner.invoke(cli.app, ["audio", "use", "sof-hda-dsp"], env=_ENV)
    assert r.exit_code == 2
    for dev in _THREE:
        assert dev.name in r.output, "every candidate has to be shown to choose between them"
    assert set_key.call_count == 0, (
        "an ambiguous pin must not be written -- it would resolve by enumeration order "
        "and look like a guarantee"
    )


def test_audio_use_names_the_device_it_resolved_not_the_string_you_typed(mocker):
    mocker.patch("yazses.system.configedit.set_config_key", return_value="added")
    mocker.patch("yazses.audio.devices.list_input_devices", return_value=_THREE)
    r = runner.invoke(cli.app, ["audio", "use", "hw:0,7"], env=_ENV)
    assert r.exit_code == 0
    assert "sof-hda-dsp: - (hw:0,7)" in r.output, (
        "a substring pin is loose by design; naming the device it caught is the only "
        "confirmation the user gets"
    )


def test_audio_use_says_a_routing_alias_cannot_hold_capture_in_place(mocker):
    """`audio status` already refuses to advise an alias; `audio use` took one silently."""
    mocker.patch("yazses.system.configedit.set_config_key", return_value="added")
    mocker.patch(
        "yazses.audio.devices.list_input_devices",
        return_value=[InputDevice(10, "default", 64, is_default=True)],
    )
    r = runner.invoke(cli.app, ["audio", "use", "default"], env=_ENV)
    assert r.exit_code == 0, "still pinned — it is not destructive, just not a guarantee"
    assert "route" in r.output.lower()
    assert "yazses audio devices" in r.output


def test_audio_use_still_pins_a_device_that_is_not_plugged_in_yet(mocker):
    """The deliberate case: pin now, plug in later. It must survive the new checks."""
    set_key = mocker.patch("yazses.system.configedit.set_config_key", return_value="added")
    mocker.patch("yazses.audio.devices.list_input_devices", return_value=_THREE)
    r = runner.invoke(cli.app, ["audio", "use", "Yeti"], env=_ENV)
    assert r.exit_code == 0
    assert set_key.call_args.args[1:4] == ("audio", "device", "Yeti")
    assert "appears later" in r.output


def test_audio_use_does_not_warn_about_routes_on_a_real_microphone(mocker):
    mocker.patch("yazses.system.configedit.set_config_key", return_value="added")
    mocker.patch(
        "yazses.audio.devices.list_input_devices",
        return_value=[InputDevice(2, "USB PnP Audio Device", 1)],
    )
    r = runner.invoke(cli.app, ["audio", "use", "USB"], env=_ENV)
    assert r.exit_code == 0
    assert "route" not in r.output.lower()

