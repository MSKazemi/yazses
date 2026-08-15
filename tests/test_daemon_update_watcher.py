"""The daemon's update watcher: gated off by default, and unable to hurt dictation.

Exercised against the real `Daemon` methods with a stand-in `self`, so the wiring
(the config gate, the swallowed failures, the once-per-version state) is what is
under test rather than a copy of it.
"""
from __future__ import annotations

import threading
import types

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.system import update_notify as un
from yazses.system.updater import UpdateStatus


def _fake_daemon(tmp_path, *, update_check: bool, stop: threading.Event | None = None):
    config = Config()
    config.general.update_check = update_check
    config.general.update_check_interval_hours = 24
    return types.SimpleNamespace(
        _config=config,
        _stop_event=stop or threading.Event(),
        _platform=types.SimpleNamespace(paths=types.SimpleNamespace(data_dir=tmp_path)),
        _version=lambda: "1.0.0",
        _watch_for_updates=lambda: None,
    )


# ---- the gate --------------------------------------------------------------

def test_no_thread_is_started_when_the_check_is_off(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(threading, "Thread", lambda **kw: started.append(kw) or _NoThread())
    Daemon._start_update_watcher(_fake_daemon(tmp_path, update_check=False))
    assert started == [], "the update check must stay dormant until it is turned on"


def test_a_thread_is_started_when_the_check_is_on(tmp_path, monkeypatch):
    started = []

    def _thread(**kw):
        started.append(kw)
        return _NoThread()

    monkeypatch.setattr("yazses.core.daemon.threading.Thread", _thread)
    Daemon._start_update_watcher(_fake_daemon(tmp_path, update_check=True))
    assert len(started) == 1
    assert started[0]["daemon"] is True  # never blocks shutdown


class _NoThread:
    def start(self):
        return None


# ---- the loop --------------------------------------------------------------

def _run_one_tick(fake, monkeypatch, check_update):
    """Run exactly one iteration of the watcher loop, then let it exit."""
    calls = {"n": 0}

    def _wait(_timeout):
        calls["n"] += 1
        return calls["n"] > 1  # False once (one iteration), then True (stop)

    fake._stop_event.wait = _wait
    monkeypatch.setattr("yazses.system.updater.check_update", check_update)
    Daemon._watch_for_updates(fake)
    return calls["n"]


def test_an_available_update_notifies_once_and_is_remembered(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr("yazses.system.notify.notify", lambda t, b, **kw: sent.append((t, b)))
    fake = _fake_daemon(tmp_path, update_check=True)
    _run_one_tick(
        fake, monkeypatch,
        lambda current: UpdateStatus(
            method="pip", current=current, latest="2.0.0", available=True,
            command=["pip", "install", "--upgrade", "yazses"],
        ),
    )
    assert len(sent) == 1
    assert "2.0.0" in sent[0][0]
    # Remembered, so tomorrow's tick does not repeat the same announcement.
    assert un.read_state(tmp_path / un.STATE_NAME).notified_version == "2.0.0"


def test_a_blocked_check_is_a_silent_no_op(tmp_path, monkeypatch):
    # Someone who firewalls YazSes must keep a working daemon and a quiet desktop:
    # no toast, no error, no crashed thread -- just a check that finds nothing.
    sent = []
    monkeypatch.setattr("yazses.system.notify.notify", lambda t, b, **kw: sent.append((t, b)))
    fake = _fake_daemon(tmp_path, update_check=True)
    _run_one_tick(
        fake, monkeypatch,
        lambda current: UpdateStatus(
            method="pip", current=current, latest=None, available=False,
            command=None, note="could not reach PyPI",
        ),
    )
    assert sent == []


def test_a_raising_check_cannot_escalate_out_of_the_thread(tmp_path, monkeypatch):
    def _boom(current):
        raise RuntimeError("DNS exploded")

    fake = _fake_daemon(tmp_path, update_check=True)
    # No exception must escape: this thread dying loudly is not worth a single
    # interrupted dictation.
    _run_one_tick(fake, monkeypatch, _boom)
