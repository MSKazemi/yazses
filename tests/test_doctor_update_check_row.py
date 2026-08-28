"""`yazses doctor` must say the update watcher exists, without nagging about it.

The watcher (`system/update_notify.py`) ships off by default — it is the one
feature that opens an outbound connection (ADR-011). That default is correct, but
until this row existed it was also unobservable: nothing outside the ~60-row
`yazses features` table ever mentioned the watcher, so a user on a build with a
since-fixed bug had no path from "something is wrong" to "a newer release exists".

These tests pin the two properties that make the row worth having and keep it from
becoming noise: it must carry the exact enabling command when off, and it must not
be a WARN — a deliberate, documented default is not a problem, and a report that
warns about non-problems trains people to skim past the real failures in it.
"""
from __future__ import annotations

import pytest

from yazses.system.doctor import _update_check_check


def test_off_names_the_exact_command_to_turn_it_on() -> None:
    name, status, detail = _update_check_check(False)
    assert name == "Update check"
    # The whole point of the row: a user must be able to act on it without
    # going to look anything up.
    assert "yazses features enable update-check" in detail


def test_off_is_skip_not_warn() -> None:
    """Off is the documented default, so it is dim information, not an alarm."""
    _, status, _ = _update_check_check(False)
    assert status == "SKIP"
    assert status != "WARN"


def test_on_reports_ok_and_does_not_repeat_the_enable_command() -> None:
    _, status, detail = _update_check_check(True)
    assert status == "OK"
    # Telling someone how to enable what they already enabled is noise.
    assert "features enable update-check" not in detail


@pytest.mark.parametrize("enabled", [True, False])
def test_never_claims_anything_about_the_user_is_sent(enabled: bool) -> None:
    """ADR-011 is the product's headline promise; this row must not muddy it."""
    _, _, detail = _update_check_check(enabled)
    low = detail.lower()
    if enabled:
        assert "sends nothing about you" in low
    else:
        assert "nothing reaches the network" in low


def test_the_command_line_is_indented_so_doctor_highlights_it() -> None:
    """`_format_check` bolds a detail line whose stripped form starts with
    `yazses `. A command run together with prose on one line loses that, and the
    one action the row exists to offer stops standing out."""
    _, _, detail = _update_check_check(False)
    command_lines = [ln for ln in detail.split("\n") if ln.strip().startswith("yazses ")]
    assert command_lines, detail
    assert command_lines[0] != command_lines[0].strip(), "command line must be indented"


def test_row_is_actually_wired_into_the_report() -> None:
    """A pure check nothing calls is a check that never runs — the failure mode
    `tests/test_orphan_modules.py` exists for, applied to one function."""
    import inspect

    from yazses.system import doctor

    src = inspect.getsource(doctor.run_doctor)
    assert "_update_check_check(" in src
