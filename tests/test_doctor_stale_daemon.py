"""An upgrade does not restart the daemon, and `doctor` could not see that.

Upgrading replaces files on disk. It does not touch a process that is already
running, so the daemon keeps executing the build it started with until `yazses
restart`. Until this check, `doctor` printed the **CLI's** version on one line and
the daemon's **liveness** on the next, compared them never, and concluded "Good to
go" — so the surface a user opens to ask *is everything fine* answered yes while
dictation ran last week's code.

This was not hypothetical when it was written: the maintainer's own machine had a
daemon up 8.6 hours, hours older than the v2.23.0 tag it reported.

It is the same shape as [[feedback_exit_zero_is_not_proof_of_upgrade]] — the upgrade
command succeeded, and nothing checked that anything actually moved.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import pytest

from yazses.system import doctor


@pytest.fixture
def installed(monkeypatch):
    monkeypatch.setattr(doctor, "_pkg_version", lambda _name: "2.24.0")
    return "2.24.0"


def test_a_matching_daemon_says_nothing(installed):
    """The check must be silent in the normal case or it becomes noise to dismiss."""
    assert doctor._stale_daemon_note("2.24.0") == ""


def test_a_different_version_names_both(installed):
    note = doctor._stale_daemon_note("2.23.0")
    assert "2.23.0" in note and "2.24.0" in note, (
        "the warning must say which version is running and which is installed — "
        f"got {note!r}"
    )
    assert "yazses restart" in note, "a warning with no fix is a warning to dismiss"


def test_a_daemon_too_old_to_report_is_evidence_not_an_unknown(installed):
    """Silence is the answer here, not a missing one.

    The `version` field is new, so a daemon that does not send one is necessarily
    older than the CLI reading it. Treating that as "cannot tell" would hide the
    single most common case: the daemon that has been up since before the upgrade.
    """
    note = doctor._stale_daemon_note("")
    assert note, "an unreporting daemon was treated as fine"
    assert "restart" in note


def test_no_installed_metadata_is_not_reported_here(monkeypatch):
    """`_version_check` already warns about that; two warnings for one fault is noise."""
    def _missing(_name):
        raise PackageNotFoundError("yazses")

    monkeypatch.setattr(doctor, "_pkg_version", _missing)
    assert doctor._stale_daemon_note("2.23.0") == ""


def test_the_daemon_actually_puts_its_version_in_the_status_payload():
    """The check above is inert unless the daemon sends the field.

    Guards the two halves being wired together rather than each being right alone —
    which is this repo's most common defect shape.
    """
    from yazses.core.daemon import _running_version

    assert _running_version(), "the daemon cannot report a version at all"

    import inspect

    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon._handle_status)
    assert '"version": _running_version()' in source, (
        "the status payload does not carry the version, so doctor's comparison "
        "can never fire against a real daemon"
    )
