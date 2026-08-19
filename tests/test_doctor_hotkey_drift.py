"""The daemon binds its hotkey at start, and `doctor` printed `[OK]` on the other one.

`yazses hotkey set <k>` writes the config. It does not reach a daemon that is already
running -- the daemon reads `[hotkey] key` once, at start, and never again. So there is
a state where you hold the key you just configured, nothing is typed, and the command
you are told to run for exactly this situation answers that everything is fine.

Both facts were already in front of `doctor`: the configured key on the `Hotkey` row,
and the daemon's own resolved key inside the `status` payload it reads the PID, state
and model from two rows above. Nothing compared them.

Found by running the product, not by reading it -- on the maintainer's own machine, in
the same minute, `yazses doctor` said `Hotkey: right_alt` while `yazses status` said
`hotkey: right_ctrl`, with a daemon up since 15:39.

The version twin of this check is `test_doctor_stale_daemon.py`, and the failure is
identical in shape: two true statements on adjacent rows and no comparison between them.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from yazses.config import Config, HotkeyConfig
from yazses.system import doctor

# ---- the pure rule ---------------------------------------------------------


def test_agreement_says_nothing():
    """Silent in the normal case, or it becomes one more line to dismiss."""
    assert doctor.hotkey_drift_note("right_ctrl", "right_ctrl", default="right_alt") is None


def test_a_mismatch_names_both_keys_and_the_fix():
    note = doctor.hotkey_drift_note("right_alt", "right_ctrl", default="right_alt")
    assert note is not None
    assert "right_alt" in note and "right_ctrl" in note, (
        f"the warning must name the key you configured and the one being listened on — got {note!r}"
    )
    assert "yazses restart" in note, "a warning with no fix is a warning to dismiss"


def test_auto_is_resolved_before_comparing():
    """Otherwise every machine on the platform default reports drift against itself.

    `[hotkey] key = "auto"` is a real, documented value; the daemon reports the key it
    actually resolved. Comparing the literal string `"auto"` to `"right_alt"` would make
    this check fire on a correctly configured machine, which is worse than not having it.
    """
    assert doctor.hotkey_drift_note("auto", "right_alt", default="right_alt") is None
    assert doctor.hotkey_drift_note("auto", "right_ctrl", default="right_alt") is not None


@pytest.mark.parametrize("running", [None, ""])
def test_no_running_daemon_is_not_drift(running):
    """No daemon, or IPC that did not answer, is an absence of evidence -- not a mismatch."""
    assert doctor.hotkey_drift_note("right_alt", running, default="right_alt") is None


# ---- the wiring ------------------------------------------------------------


def _summary(tmp_path: Path, *, key: str, live: str) -> dict[str, tuple[str, str]]:
    cfg = replace(Config(), hotkey=HotkeyConfig(key=key))
    config_file = tmp_path / "config.toml"
    config_file.write_text(f'[hotkey]\nkey = "{key}"\n', encoding="utf-8")
    rows = doctor._config_summary(
        cfg, config_file, live_hotkey=live, platform_default="right_alt"
    )
    return {name: (status, detail) for name, status, detail in rows}


def test_the_row_actually_turns_yellow(tmp_path):
    """The rule existing is not the point -- the row a user reads has to change.

    A pure function nothing calls is how the previous version of this bug survived:
    both facts were available and simply never met.
    """
    status, detail = _summary(tmp_path, key="right_alt", live="right_ctrl")["Hotkey"]
    assert status == "WARN", f"a hotkey that does nothing must not print OK — got [{status}] {detail}"
    assert "right_ctrl" in detail


def test_the_row_stays_green_when_they_agree(tmp_path):
    status, _ = _summary(tmp_path, key="right_ctrl", live="right_ctrl")["Hotkey"]
    assert status == "OK"


def test_the_row_stays_green_with_no_daemon(tmp_path):
    """`doctor` runs with the daemon stopped more often than with it running."""
    status, _ = _summary(tmp_path, key="right_alt", live="")["Hotkey"]
    assert status == "OK"
