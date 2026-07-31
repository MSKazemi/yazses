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
