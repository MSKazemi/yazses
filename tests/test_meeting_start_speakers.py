"""`yazses meeting start --speakers N`: the good path had to be reachable.

Meeting Mode's speaker count is the setting that decides whether the transcript is
readable — 84.09% DER at auto against 28.55% when the count is given, on the AMI test
split (ADR-v2-133). Until now the only way to supply it was to edit
`[meeting] max_speakers` in `config.toml` and restart the daemon.

Nobody does that between two meetings with different numbers of people in the room,
so the setting that mattered most was the one nobody would ever reach. A per-meeting
flag is what makes the measurement actionable rather than merely published.

It is deliberately **not** persisted. Writing it to config would make the next
meeting — a one-to-one, a standup, a call with the whole team — inherit a count that
is now wrong, and an exact cluster count that is wrong invents or merges speakers
rather than degrading gently.

The handler is exercised directly rather than through a socket: what is being guarded
is that the number reaches `MeetingConfig`, that a bad one is refused before anything
starts recording, and that omitting it changes nothing.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from yazses.config import MeetingConfig
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request


def _daemon(cfg: MeetingConfig):
    """A Daemon whose only real parts are the ones this handler touches.

    Built with `object.__new__` rather than the constructor because constructing one
    loads a model, opens a socket and installs signal handlers -- none of which the
    parameter contract depends on. It is left *not ready* on purpose: the handler must
    reach its ordinary readiness check, which is how "no count given" is told apart
    from "bad count given".
    """
    import threading

    daemon = object.__new__(Daemon)
    daemon._config = SimpleNamespace(meeting=cfg)
    daemon._lock = threading.RLock()
    daemon._state = SimpleNamespace(ready=False, state=None)
    daemon._engine = None
    return daemon


def test_the_parameter_is_declared_on_the_cli_and_reaches_the_ipc_call():
    """A flag that is parsed and then dropped is worse than no flag: the user
    believes they set the count and gets the auto-clustering result."""
    import inspect

    from yazses import cli

    src = inspect.getsource(cli.meeting_start)
    assert '"--speakers"' in src
    assert 'client.call("meeting_start", speakers=speakers)' in src


def test_the_handler_reads_speakers_and_overrides_only_that_field():
    import inspect

    src = inspect.getsource(Daemon._handle_meeting_start)
    assert '.get("speakers"' in src, "the handler ignores the parameter the CLI sends"
    assert "dataclasses.replace(cfg, max_speakers=speakers)" in src, (
        "the override must be a per-call replace on the meeting config; anything that "
        "mutates self._config would leak into the next meeting"
    )
    assert "set_config_key" not in src and "save" not in src, (
        "the count must not be written to config.toml — the next meeting has a "
        "different number of people in it"
    )


@pytest.mark.parametrize("bad", ["two", None, "", "3.5", -1])
def test_a_bad_count_is_refused_before_anything_records(bad):
    """Refused, not coerced. A silently-clamped count produces a wrong-but-plausible
    transcript, and the recording it was taken from is deleted after the post-pass."""
    daemon = _daemon(dataclasses.replace(MeetingConfig(), enabled=True))
    result = Daemon._handle_meeting_start(daemon, Request(
        method="meeting_start", params={"speakers": bad}, id=1))
    if bad in (None, ""):
        # Absent is not invalid: it means "use the configured value", and the handler
        # must fall through to the ordinary readiness checks rather than refuse.
        assert result["ok"] is False
        assert "speakers" not in str(result.get("reason", ""))
    else:
        assert result["ok"] is False
        assert "speakers" in str(result["reason"]), result


def test_the_hint_goes_quiet_once_a_count_is_supplied():
    """The advisory and the flag are two halves of one change; if the hint kept
    firing after the user acted on it, they would stop reading it."""
    from yazses.recimport.factory import speaker_count_advice

    cfg = dataclasses.replace(MeetingConfig(), diarize=True)
    assert speaker_count_advice(cfg, "x") is not None
    assert speaker_count_advice(dataclasses.replace(cfg, max_speakers=4), "x") is None
