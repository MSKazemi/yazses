"""Replacing ``[[facegesture.switches]]`` from the settings panel without damaging the config.

The single-key editor cannot write an array of tables. This is the one extra primitive the
panel needs, and the failure it must not have is the one `quote_toml_string`'s docstring
describes: a config that no longer parses silently resets *every* setting, which for a
hands-free user is the loss of their input method.
"""
from __future__ import annotations

import tomllib

import pytest

from yazses.system.configedit import _replace_table_array, set_config_table_array

NAME = "facegesture.switches"
ONE = [(("gesture", "smile"), ("intent", "hold_to_command"))]


def _write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _switches(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))["facegesture"].get("switches", [])


def test_adds_a_table_to_a_file_that_has_none(tmp_path):
    path = _write(tmp_path, "[facegesture]\nenabled = true\n\n[audio]\ndevice = \"mic\"\n")
    set_config_table_array(path, NAME, ONE)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["facegesture"]["switches"] == [{"gesture": "smile", "intent": "hold_to_command"}]
    assert data["facegesture"]["enabled"] is True and data["audio"]["device"] == "mic"


def test_creates_the_file_when_there_is_none(tmp_path):
    path = tmp_path / "config.toml"
    set_config_table_array(path, NAME, ONE)
    assert _switches(path) == [{"gesture": "smile", "intent": "hold_to_command"}]


def test_replaces_every_existing_table_and_keeps_everything_else_byte_for_byte(tmp_path):
    before = (
        "# my notes\n[facegesture]\nenabled = true  # keep this comment\n\n"
        "[[facegesture.switches]]\ngesture = \"smile\"\nintent = \"hold_to_talk\"\n\n"
        "[[facegesture.switches]]\ngesture = \"brow_raise\"\nintent = \"none\"\n\n"
        "# the audio section\n[audio]\ndevice = \"mic\"\n"
    )
    path = _write(tmp_path, before)
    set_config_table_array(path, NAME, ONE)
    after = path.read_text(encoding="utf-8")
    assert _switches(path) == [{"gesture": "smile", "intent": "hold_to_command"}]
    for kept in ("# my notes", "enabled = true  # keep this comment",
                 "# the audio section", "[audio]", 'device = "mic"'):
        assert kept in after
    assert "hold_to_talk" not in after and "brow_raise" not in after


def test_an_empty_list_removes_the_tables(tmp_path):
    path = _write(
        tmp_path,
        "[facegesture]\nenabled = true\n\n[[facegesture.switches]]\ngesture = \"smile\"\nintent = \"select\"\n",
    )
    set_config_table_array(path, NAME, [])
    assert _switches(path) == []
    assert "enabled = true" in path.read_text(encoding="utf-8")


def test_values_are_escaped_so_the_file_still_parses(tmp_path):
    path = _write(tmp_path, "[facegesture]\nenabled = true\n")
    set_config_table_array(path, NAME, [(("gesture", 'a"b\\c'), ("intent", "x"))])
    assert _switches(path)[0]["gesture"] == 'a"b\\c'


def test_an_inline_array_of_the_same_name_is_refused_and_the_file_is_untouched(tmp_path):
    before = '[facegesture]\nswitches = [{gesture = "smile", intent = "select"}]\n'
    path = _write(tmp_path, before)
    with pytest.raises(ValueError, match="edit it by hand"):
        set_config_table_array(path, NAME, ONE)
    assert path.read_text(encoding="utf-8") == before


def test_a_failed_write_leaves_no_temp_file_behind(tmp_path):
    path = _write(tmp_path, '[facegesture]\nswitches = [{gesture = "smile", intent = "select"}]\n')
    with pytest.raises(ValueError):
        set_config_table_array(path, NAME, ONE)
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")) == []


def test_a_second_write_replaces_the_first_rather_than_stacking(tmp_path):
    path = _write(tmp_path, "[facegesture]\nenabled = true\n")
    set_config_table_array(path, NAME, ONE)
    set_config_table_array(path, NAME, [(("gesture", "jaw_open"), ("intent", "none"))])
    assert _switches(path) == [{"gesture": "jaw_open", "intent": "none"}]


def test_the_pure_replacement_is_idempotent():
    text = "[facegesture]\nenabled = true\n"
    once = _replace_table_array(text, NAME, ONE)
    assert _replace_table_array(once, NAME, ONE) == once


def test_a_comment_between_the_keys_of_one_entry_goes_with_the_entry(tmp_path):
    """Otherwise the key after the comment would be orphaned into the table above it."""
    path = _write(
        tmp_path,
        "[facegesture]\nenabled = true\n\n[[facegesture.switches]]\ngesture = \"smile\"\n"
        "# which action\nintent = \"select\"\n\n[audio]\ndevice = \"mic\"\n",
    )
    set_config_table_array(path, NAME, ONE)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["facegesture"] == {
        "enabled": True, "switches": [{"gesture": "smile", "intent": "hold_to_command"}],
    }
    assert "intent" not in data["facegesture"]


def test_a_file_with_no_trailing_newline_is_handled(tmp_path):
    path = _write(
        tmp_path,
        "[facegesture]\nenabled = true\n[[facegesture.switches]]\ngesture = \"smile\"\nintent = \"select\"",
    )
    set_config_table_array(path, NAME, ONE)
    assert _switches(path) == [{"gesture": "smile", "intent": "hold_to_command"}]
