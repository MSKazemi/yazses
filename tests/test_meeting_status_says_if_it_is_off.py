"""`yazses meeting status` never said whether Meeting Mode was on.

Run on a machine with the feature off — its `[meeting]` section absent, so every field
at its default — the whole output was:

    Speaker labels are on but the diarization extra is not installed, so transcripts
    will not be attributed. Install it with `yazses features enable meeting` …
    Recent meetings:
      20260819-033515  not diarized  …

Two things are wrong with that as a status report. Nothing is "on": `MeetingConfig.enabled`
defaults to **False** while `diarize` defaults to **True**, so the diarization advice fires
on a machine that will never record anything. And a list of past meetings under a
labels-only complaint reads as a working feature with one missing extra — the reader's
conclusion is "install the extra", when the fact that decides everything else is that
nothing is running.

The daemon already publishes `meeting_enabled` on its general `status` payload — the tray
needed it for exactly this reason, because the feature is off by default and no state value
can express that. The handler whose entire job is to report Meeting Mode did not send it.

`diarization_status` is deliberately left alone: it is shared with `yazses transcribe
--diarize`, where `diarize` genuinely *is* the request and there is no `enabled` to consult.
The caller is what knows the feature is off, so the caller is what stops asking.
"""

from __future__ import annotations

import pytest
import typer

from yazses import cli

DIAR_OFF = {
    "requested": True, "backend": "sherpa",
    "extra_installed": False, "models_present": False, "ready": False,
}
RECENT = [{"id": "20260819-033515", "dir": "/m/20260819-033515", "speakers": None}]


class _Client:
    def __init__(self, payload):
        self._payload = payload

    def call(self, method):
        assert method == "meeting_status"
        return self._payload


class _Platform:
    def __init__(self, payload):
        self.paths = type("P", (), {"ipc_socket": "/tmp/sock"})()
        self.ipc_client_factory = lambda _s: _Client(payload)


@pytest.fixture
def status(monkeypatch, capsys):
    def run(payload):
        monkeypatch.setattr(cli, "get_platform", lambda: _Platform(payload))
        cli.meeting_status()
        return capsys.readouterr().out

    return run


def test_a_disabled_feature_says_so_first(status):
    out = status({"ok": True, "enabled": False, "active": False, "finalizing": False,
                  "recent": RECENT, "diarization": DIAR_OFF})
    assert "Meeting Mode is off" in out
    assert "yazses features enable meeting" in out


def test_a_disabled_feature_does_not_complain_about_speaker_labels(status):
    """The advice opens "Speaker labels are on but…" on a machine where nothing is on,
    and prescribes the same command already printed above it."""
    out = status({"ok": True, "enabled": False, "active": False, "finalizing": False,
                  "recent": RECENT, "diarization": DIAR_OFF})
    assert "Speaker labels are on" not in out


def test_past_meetings_are_still_listed_but_not_as_current(status):
    """They are real files on disk; hiding them would lose information. What changes is
    that they are labelled as history rather than as the state of a live feature."""
    out = status({"ok": True, "enabled": False, "active": False, "finalizing": False,
                  "recent": RECENT, "diarization": DIAR_OFF})
    assert "20260819-033515" in out
    assert "recorded earlier" in out
    assert "Recent meetings:" not in out


def test_an_enabled_feature_is_unchanged(status):
    out = status({"ok": True, "enabled": True, "active": False, "finalizing": False,
                  "recent": RECENT, "diarization": DIAR_OFF})
    assert "Meeting Mode is off" not in out
    assert "Speaker labels are on" in out
    assert "Recent meetings:" in out


def test_an_older_daemon_that_omits_the_key_behaves_exactly_as_before(status):
    """Absence is unknown, not off. Claiming "off" from a missing key would invent a
    fact — and this is the mixed-version case: a new CLI against a daemon started
    before the upgrade, which is every machine mid-update."""
    out = status({"ok": True, "active": False, "finalizing": False,
                  "recent": RECENT, "diarization": DIAR_OFF})
    assert "Meeting Mode is off" not in out
    assert "Speaker labels are on" in out


def test_a_running_meeting_is_reported_as_running_whatever_the_flag_says(status):
    """`active` wins: a meeting that is recording is the more immediate fact."""
    out = status({"ok": True, "enabled": False, "active": True, "finalizing": False,
                  "id": "20260820-000000", "elapsed_s": 12.0, "line_count": 3,
                  "live_lines": []})
    assert "Recording 20260820-000000" in out
    assert "Meeting Mode is off" not in out


def test_no_daemon_still_exits_nonzero(monkeypatch):
    from yazses.ipc.client import IpcUnreachableError

    class _Dead:
        def call(self, _m):
            raise IpcUnreachableError("nope")

    plat = type("P", (), {"paths": type("Q", (), {"ipc_socket": "/tmp/s"})(),
                          "ipc_client_factory": staticmethod(lambda _s: _Dead())})()
    monkeypatch.setattr(cli, "get_platform", lambda: plat)
    with pytest.raises(typer.Exit) as exc:
        cli.meeting_status()
    assert exc.value.exit_code == 1
