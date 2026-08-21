"""The tray restarts a daemon that died, and relays toasts the daemon can't show.

Two Windows resilience gaps, both of which also close on macOS:

* **Crash recovery.** systemd (`Restart=on-failure`) and launchd (`KeepAlive`)
  restart a crashed daemon. The Windows autostart is an `HKCU\\Run` value that
  fires once at login and never again, so a daemon that died at 10am stayed dead
  until the user logged out — the tray watched it, coloured itself red, and did
  nothing. It is the one process already polling and already holding the
  lifecycle handle.
* **Notification relay.** `system/notify.py` is `notify-send`-only, so every
  self-healing event (the mic auto-heal, a VAD retune, a silent streak) was
  log-only on Windows and macOS. The daemon now queues them onto its `status`
  reply for the tray to show natively.
"""

from __future__ import annotations

import pytest

from yazses.platform.base import TrayState
from yazses.tray.app import (
    _RECONNECT_GRACE_S,
    MAX_DAEMON_RELAUNCHES,
    RELAUNCH_COOLDOWN_S,
    _show_notifications,
    unreachable_decision,
)

_PAST_GRACE = _RECONNECT_GRACE_S + 1


class TestCrashRecovery:
    def test_a_dead_daemon_is_restarted(self) -> None:
        d = unreachable_decision(True, _PAST_GRACE, daemon_running=False)
        assert d.relaunch is True
        assert d.state is TrayState.ERROR
        assert not d.give_up

    def test_a_wedged_daemon_is_reported_not_respawned(self) -> None:
        """It still holds the single-instance lock, so a replacement would just exit."""
        d = unreachable_decision(True, _PAST_GRACE, daemon_running=True)
        assert d.relaunch is False
        assert d.state is TrayState.ERROR
        assert d.last_error == "daemon not responding"

    def test_a_brief_outage_is_not_a_crash(self) -> None:
        """`yazses restart` drops the socket for a second; that must not respawn."""
        d = unreachable_decision(True, _RECONNECT_GRACE_S - 0.1, daemon_running=False)
        assert d.relaunch is False
        assert d.state is TrayState.IDLE

    def test_relaunches_are_spaced_by_a_cooldown(self) -> None:
        """The loop ticks every second; a booting daemon needs longer than that."""
        d = unreachable_decision(
            True, _PAST_GRACE, daemon_running=False,
            relaunches=1, since_relaunch_s=RELAUNCH_COOLDOWN_S - 1,
        )
        assert d.relaunch is False
        d = unreachable_decision(
            True, _PAST_GRACE, daemon_running=False,
            relaunches=1, since_relaunch_s=RELAUNCH_COOLDOWN_S + 1,
        )
        assert d.relaunch is True

    def test_a_daemon_that_keeps_dying_is_given_up_on_but_still_polled(self) -> None:
        """Respawning forever would bury the real error and never fix it."""
        d = unreachable_decision(
            True, _PAST_GRACE, daemon_running=False,
            relaunches=MAX_DAEMON_RELAUNCHES, since_relaunch_s=999,
        )
        assert d.relaunch is False
        assert "not restarting again" in (d.last_error or "")
        # Must NOT give up polling: the tray owns the single-instance lock, so a
        # tray that stops leaves the user with no icon and no way to get one back.
        assert d.give_up is False

    def test_boot_failure_still_gives_up_without_respawning(self) -> None:
        """A daemon that never answered was already spawned once by the tray."""
        d = unreachable_decision(False, 999, daemon_running=False)
        assert d.give_up is True
        assert d.relaunch is False

    def test_default_is_the_old_no_recovery_behaviour(self) -> None:
        """Callers that don't pass liveness must not start spawning processes."""
        assert unreachable_decision(True, _PAST_GRACE).relaunch is False


class TestNotificationRelay:
    class _Tray:
        def __init__(self) -> None:
            self.shown: list[tuple[str, str]] = []

        def notify(self, title: str, body: str) -> None:
            self.shown.append((title, body))

    def test_relays_each_queued_toast(self) -> None:
        tray = self._Tray()
        _show_notifications(
            tray, [{"title": "Microphone changed", "body": "Switched back to Yeti."}]
        )
        assert tray.shown == [("Microphone changed", "Switched back to Yeti.")]

    def test_a_backend_that_cannot_toast_is_silent_not_fatal(self) -> None:
        class Mute:
            pass

        _show_notifications(Mute(), [{"title": "x", "body": "y"}])  # must not raise

    def test_one_bad_entry_does_not_lose_the_others(self) -> None:
        tray = self._Tray()
        _show_notifications(
            tray, ["not a dict", {"body": "kept"}, {"title": "no body"}]
        )
        assert tray.shown == [("YazSes", "kept")]

    @pytest.mark.parametrize("raw", [None, "nonsense", 42, {}])
    def test_tolerates_an_older_daemon_sending_no_list(self, raw: object) -> None:
        """This crosses an IPC boundary; a shape surprise must not break polling."""
        tray = self._Tray()
        _show_notifications(tray, raw)
        assert tray.shown == []

    def test_a_raising_backend_does_not_break_the_poll_loop(self) -> None:
        class Broken:
            def notify(self, title: str, body: str) -> None:
                raise RuntimeError("no notification service")

        _show_notifications(Broken(), [{"title": "x", "body": "y"}])  # must not raise


class TestNotifyFallbackSink:
    def test_notify_hands_off_when_libnotify_is_absent(self) -> None:
        """The Windows/macOS path: no notify-send, so the sink must receive it."""
        from yazses.system import notify as notify_mod

        got: list[tuple[str, str]] = []
        notify_mod.set_fallback_sink(lambda t, b: got.append((t, b)))
        try:
            notify_mod.notify("Mic changed", "Switched back.", available=False)
        finally:
            notify_mod.set_fallback_sink(None)
        assert got == [("Mic changed", "Switched back.")]

    def test_no_sink_registered_is_still_safe(self) -> None:
        from yazses.system import notify as notify_mod

        notify_mod.set_fallback_sink(None)
        notify_mod.notify("t", "b", available=False)  # must not raise

    def test_a_raising_sink_never_reaches_the_caller(self) -> None:
        """notify() is called from the dictation hot path; it must never raise."""
        from yazses.system import notify as notify_mod

        def boom(_t: str, _b: str) -> None:
            raise RuntimeError("queue is broken")

        notify_mod.set_fallback_sink(boom)
        try:
            notify_mod.notify("t", "b", available=False)
        finally:
            notify_mod.set_fallback_sink(None)

    def test_linux_with_notify_send_does_not_use_the_sink(self) -> None:
        """Otherwise the user gets the same toast twice."""
        from yazses.system import notify as notify_mod

        got: list[tuple[str, str]] = []
        notify_mod.set_fallback_sink(lambda t, b: got.append((t, b)))
        try:
            notify_mod.notify("t", "b", available=True, runner=lambda *a, **k: None)
        finally:
            notify_mod.set_fallback_sink(None)
        assert got == []
