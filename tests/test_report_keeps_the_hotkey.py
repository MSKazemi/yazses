"""The diagnostic bundle must carry both halves of the hotkey comparison.

`yazses report` redacted `[hotkey] key` and `command_key`, because the key-name filter
matches on substrings and `command_key` contains `key`. The bundle already carries
`daemon.hotkey` -- the key the running daemon is *actually* listening on -- so a report
from a machine whose daemon never re-read a changed config held both halves of the one
comparison that explains "the hotkey does nothing", and blanked one of them.

Redacting it bought nothing either: the same value is printed in full by `doctor`,
`status`, `quickstart`, `hotkey show` and the tray tooltip, and the twelve names are
listed in the CLI's own `--help`.
"""

from __future__ import annotations

import pytest

from yazses.hotkeys.names import SETTABLE_HOTKEYS
from yazses.system.report import redact_config


def test_a_configured_hotkey_survives_the_bundle():
    out = redact_config({"hotkey": {"key": "right_alt", "command_key": "right_ctrl"}})
    assert out["hotkey"] == {"key": "right_alt", "command_key": "right_ctrl"}


def test_the_bundle_carries_both_halves_of_the_hotkey_comparison():
    """The whole point: a reader can see the two disagree."""
    config = redact_config({"hotkey": {"key": "right_alt"}})
    daemon = {"hotkey": "right_ctrl"}  # what `collect` copies from the IPC status
    assert config["hotkey"]["key"] != daemon["hotkey"]
    assert "<redacted>" not in (config["hotkey"]["key"], daemon["hotkey"])


@pytest.mark.parametrize("name", sorted(SETTABLE_HOTKEYS))
def test_every_settable_hotkey_name_survives(name):
    """Pinned to the published set, so the allowlist cannot drift away from it."""
    assert redact_config({"hotkey": {"key": name}})["hotkey"]["key"] == name


def test_a_key_named_key_in_another_section_is_still_redacted():
    """The allowlist is keyed by (section, key), so a future `[api] key` is not a hole."""
    out = redact_config({"api": {"key": "sk-live-0123456789"}})
    assert out["api"]["key"] == "<redacted>"
    assert "sk-live" not in str(out)


def test_a_secret_that_collides_with_a_hotkey_name_is_still_redacted():
    """The test above passes even on a bare-key-name allowlist, because its value is not
    a hotkey name -- the membership gate hides the defect. This is the collision the
    section key exists to prevent, and only a section-keyed lookup survives it."""
    assert redact_config({"api": {"key": "space"}})["api"]["key"] == "<redacted>"
    assert redact_config({"vault": {"command_key": "right_alt"}})["vault"][
        "command_key"] == "<redacted>"


def test_an_unrecognised_hotkey_value_is_redacted():
    """Gated on membership: the case where nobody knows what the value is stays hidden."""
    out = redact_config({"hotkey": {"key": "/home/someone/secret-note.txt"}})
    assert out["hotkey"]["key"] == "<redacted>"


def test_the_neighbouring_redactions_are_untouched():
    out = redact_config({"remote": {"key_file": "/home/x/.ssh/id_ed25519",
                                    "default_host": "buildbox.example"}})
    assert out["remote"] == {"key_file": "<redacted>", "default_host": "<redacted>"}
