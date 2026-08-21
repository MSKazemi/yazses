"""The daemon must not die when the speech model cannot be downloaded (#310).

Reported from a Windows machine behind a personal firewall: the first-run model
fetch was blocked, huggingface_hub raised, and the exception travelled all the
way out of `main()` — which on the PyInstaller bundle is a modal "Failed to
execute script" dialog. `run()` wrapped `_build_pipeline()` in try/*finally*
with no `except`, so every startup failure escaped.

The daemon now holds itself in ERROR state with the reason attached, so the
tray, `yazses status` and the log can all explain it.
"""

from __future__ import annotations

import threading

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.platform.base import TrayState
from yazses.stt.errors import ModelUnavailableError

_CAUSE = (
    "[WinError 10013] An attempt was made to access a socket in a way "
    "forbidden by its access permissions"
)


def _daemon() -> Daemon:
    return Daemon(config=Config(), platform=get_platform())


def test_error_state_carries_the_actionable_reason(mocker):
    d = _daemon()
    mocker.patch("yazses.system.notify.notify")
    exc = ModelUnavailableError("base.en", _CAUSE)

    d._stop_event.set()  # don't block: pretend shutdown was already requested
    d._await_shutdown_in_error(exc)

    assert d._state.state is TrayState.ERROR
    assert d._state.ready is False
    assert "yazses model download base.en" in (d._state.last_error or "")


def test_it_stays_resident_until_shutdown_is_requested(mocker):
    """Exiting would take the tray down with it, leaving a closed window and no
    statement of why. It must wait for a real stop."""
    d = _daemon()
    mocker.patch("yazses.system.notify.notify")
    returned = threading.Event()

    def _hold():
        d._await_shutdown_in_error(ModelUnavailableError("base.en", _CAUSE))
        returned.set()

    threading.Thread(target=_hold, daemon=True).start()

    # Still blocked while nothing has asked it to stop.
    assert not returned.wait(timeout=0.3)
    assert d._state.state is TrayState.ERROR

    d._stop_event.set()
    assert returned.wait(timeout=5), "did not return once shutdown was requested"


def test_a_failed_notification_does_not_mask_the_error(mocker):
    """The toast is a nicety; on a headless box it can raise. The state must
    still be set and the call must still return."""
    d = _daemon()
    mocker.patch("yazses.system.notify.notify", side_effect=OSError("no notify-send"))
    d._stop_event.set()

    d._await_shutdown_in_error(ModelUnavailableError("base.en", _CAUSE))

    assert d._state.state is TrayState.ERROR
    assert "base.en" in (d._state.last_error or "")


def test_notification_names_the_command_that_fixes_it(mocker):
    d = _daemon()
    notify = mocker.patch("yazses.system.notify.notify")
    d._stop_event.set()

    d._await_shutdown_in_error(ModelUnavailableError("small.en", _CAUSE))

    body = " ".join(str(a) for a in notify.call_args.args)
    assert "yazses model download small.en" in body


def test_run_catches_the_error_instead_of_letting_it_escape(mocker):
    """The regression itself: a raising _build_pipeline must not propagate out
    of run(), because nothing above it can render an exception usefully."""
    d = _daemon()
    # Not incidental: the real one attaches a RotatingFileHandler to the ROOT
    # logger pointing at the user's actual ~/.local/state/yazses log, and never
    # removes it -- so every later test in the session logged into it. One full
    # run put 44 KB of fake recorders and deliberate OSErrors into the file
    # `yazses logs` shows and `yazses report` bundles.
    mocker.patch.object(d, "_configure_logging")
    mocker.patch.object(d, "_acquire_instance_lock", return_value=True)
    mocker.patch.object(d, "_install_signal_handlers")
    mocker.patch.object(d, "_start_ipc_server")
    mocker.patch.object(d, "_shutdown")
    mocker.patch.object(
        d, "_build_pipeline",
        side_effect=ModelUnavailableError("base.en", _CAUSE),
    )
    held = mocker.patch.object(d, "_await_shutdown_in_error")
    mocker.patch.object(d._platform.lifecycle, "write_pid")

    d.run()  # must return, not raise

    held.assert_called_once()
    assert isinstance(held.call_args.args[0], ModelUnavailableError)


def test_an_unexpected_error_is_still_not_swallowed(mocker):
    """Only the fixable, foreseeable failure is caught. A genuine bug must keep
    surfacing rather than being hidden behind a friendly ERROR state."""
    import pytest

    d = _daemon()
    mocker.patch.object(d, "_configure_logging")  # see the note above: real
    # logging attaches a root handler on the user\'s actual log and never removes it.
    mocker.patch.object(d, "_acquire_instance_lock", return_value=True)
    mocker.patch.object(d, "_install_signal_handlers")
    mocker.patch.object(d, "_start_ipc_server")
    mocker.patch.object(d, "_shutdown")
    mocker.patch.object(d, "_build_pipeline", side_effect=RuntimeError("real bug"))
    mocker.patch.object(d._platform.lifecycle, "write_pid")

    with pytest.raises(RuntimeError, match="real bug"):
        d.run()
