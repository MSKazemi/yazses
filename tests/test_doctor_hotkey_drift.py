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


# ---- the verdict line, which is the part a user acts on ---------------------
#
# The row above was fixed first, and that was not enough. `doctor` prints one closing
# line -- the summary, the last thing read, the only sentence carrying a command -- and
# it kept building the "hold X to dictate" hint out of the config file. So a run could
# WARN that the configured key does nothing and then close with
#
#     ▲ Good to go (3 optional warnings above) — you're all set — hold right_alt to dictate.
#
# naming the dead key as the closing instruction, one line below the warning, and filing
# it under *optional* next to a missing AT-SPI package. Found the same way as the row
# itself: by running the product with the drift still live on the maintainer's machine.

import types


def _verdict(*, key: str, live: str, running: bool = True) -> str:
    """Build the real verdict line from the real rows."""
    cfg = replace(Config(), hotkey=HotkeyConfig(key=key))
    hotkey_status = "WARN" if doctor.hotkey_drift_note(key, live, default="right_alt") else "OK"
    checks = [
        ("Daemon", "OK", f"{doctor._RUNNING_PREFIX}(PID 1, state idle, model base.en)")
        if running else ("Daemon", "WARN", "not running"),
        ("Hotkey", hotkey_status, f"{key} (hold 500 ms)"),
    ]
    platform = types.SimpleNamespace(default_hotkey="right_alt")
    return doctor._verdict_line(checks, cfg, platform)


def test_the_verdict_does_not_close_by_naming_the_dead_key_as_the_instruction():
    line = _verdict(key="right_alt", live="right_ctrl")
    assert "you're all set" not in line, (
        "dictation does nothing until the daemon is restarted — got: " + line
    )
    assert "yazses restart" in line
    # The configured key is still named, because it *is* the key to hold -- after the
    # restart. What must not happen is naming it as the thing to do *now*.
    assert line.index("yazses restart") < line.index("hold right_alt"), (
        "the restart has to come before the key in the sentence, or the reader acts on "
        "the wrong half: " + line
    )


def test_the_verdict_does_not_file_a_dead_hotkey_under_optional():
    """"Good to go (3 optional warnings)" is right for a missing AT-SPI package. It is
    wrong for a keyboard shortcut that does nothing, and lumping them together is what
    teaches a user to skim past both."""
    line = _verdict(key="right_alt", live="right_ctrl")
    assert "optional warning" not in line
    assert "Dictation will not work until you restart" in line


def test_a_machine_with_no_drift_is_still_told_it_is_fine():
    """The warning has to be rare to be read. A correctly configured machine keeps its
    green line, and a merely-cosmetic warning keeps the old wording."""
    line = _verdict(key="right_ctrl", live="right_ctrl")
    assert "Everything looks good" in line
    assert "you're all set" in line, (
        "the no-drift wording, asserted positively: checking only that the *green* half "
        "is present passes just as well when every machine is told to restart — which is "
        "exactly what a `drifted = True` mutation does, and what this test missed once"
    )
    assert "yazses restart" not in line
    assert "hold right_ctrl to dictate" in line


def test_a_stopped_daemon_is_told_to_start_not_to_restart():
    """No daemon means no drift to detect -- and `restart` is the wrong verb for a
    machine that has never started one."""
    line = _verdict(key="right_alt", live="", running=False)
    assert "yazses start" in line and "yazses restart" not in line
