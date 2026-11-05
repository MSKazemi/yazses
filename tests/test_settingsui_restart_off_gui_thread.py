"""Apply-then-restart must not run its blocking work on the GUI thread.

`yazses restart` is a subprocess with a 90 s timeout, and the wait for the daemon to
answer polls for up to 30 s more. Run on the Qt thread, that is a settings window that
neither repaints nor takes a click for as long as the model takes to load.

The tests pin the invariant, not a duration: the restart runner and the readiness probe
are stubs that record the thread they ran on, and the runner is held on an Event so the
test can observe the window while the restart is still "in flight".
"""

from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402
from yazses.settingsui.restart import (  # noqa: E402
    RestartState,
    decide_restart,
    perform_restart,
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class _Rec:
    def load(self):
        return Config()

    def write(self, section, key, value, quote):
        pass

    def probe(self, modules):
        return []


def _window(qapp, *, run_restart, status=lambda: {"state": "idle"}):
    rec = _Rec()
    win = SettingsWindow(
        build_settings_model(Config()), SettingsController(rec.load, rec.write, rec.probe)
    )
    win._warn = lambda title, body: None  # type: ignore[method-assign]
    win._daemon_running = lambda: True  # type: ignore[method-assign]
    win._confirm_restart = lambda: True  # type: ignore[method-assign]
    win._run_restart = run_restart  # type: ignore[method-assign]
    win._daemon_status = status  # type: ignore[method-assign]
    return win


def _pump_until(qapp, predicate, limit_s: float = 20.0) -> bool:
    """Process events until *predicate*; the limit only bounds a failing run."""
    end = time.monotonic() + limit_s
    while time.monotonic() < end:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_the_restart_runs_on_a_worker_thread_and_the_result_returns_to_the_gui_thread(qapp):
    main = threading.current_thread()
    ran_on: dict[str, threading.Thread] = {}

    def run_restart():
        ran_on["restart"] = threading.current_thread()
        return True, ""

    def status():
        ran_on["status"] = threading.current_thread()
        return {"state": "idle"}

    win = _window(qapp, run_restart=run_restart, status=status)
    landed_on: list[threading.Thread] = []
    original = win._on_restart_finished

    def _record(outcome):
        landed_on.append(threading.current_thread())
        original(outcome)

    win._on_restart_finished = _record  # type: ignore[method-assign]

    win._offer_restart("Saved.")
    assert _pump_until(qapp, lambda: win._restart_thread is None)

    assert ran_on["restart"] is not main
    assert ran_on["status"] is not main
    assert landed_on == [main], "the outcome must be shown from the GUI thread"
    assert "Restarted." in win._hint.text()
    assert win._hint.text().startswith("Saved.")


def test_the_window_is_usable_and_says_so_while_the_restart_is_in_flight(qapp):
    release = threading.Event()
    started = threading.Event()

    def run_restart():
        started.set()
        release.wait(30)
        return True, ""

    win = _window(qapp, run_restart=run_restart)
    try:
        win._offer_restart("Saved.")
        # Control came back although the restart has not finished: that is the point.
        assert _pump_until(qapp, started.is_set)
        assert win._restart_thread is not None
        assert not win._apply_button.isEnabled()
        assert "Restarting" in win._hint.text()
    finally:
        release.set()
    assert _pump_until(qapp, lambda: win._restart_thread is None)
    assert win._apply_button.isEnabled()
    assert "Restarting" not in win._hint.text()


def test_a_failed_restart_is_reported_and_apply_comes_back(qapp):
    win = _window(qapp, run_restart=lambda: (False, "boom"))
    win._offer_restart("Saved.")
    assert _pump_until(qapp, lambda: win._restart_thread is None)
    assert win._apply_button.isEnabled()
    assert "Restart failed" in win._hint.text() and "boom" in win._hint.text()


def test_a_restart_runner_that_raises_still_reports_and_re_enables_apply(qapp):
    def run_restart():
        raise RuntimeError("spawn failed")

    win = _window(qapp, run_restart=run_restart)
    win._offer_restart("")
    assert _pump_until(qapp, lambda: win._restart_thread is None)
    assert win._apply_button.isEnabled()
    assert "spawn failed" in win._hint.text()


def test_declining_or_nothing_to_restart_never_starts_a_worker(qapp):
    win = _window(qapp, run_restart=lambda: pytest.fail("must not restart"))
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    win._offer_restart("Saved.")
    assert win._restart_thread is None
    assert win._restart_pending is True
    assert win._apply_button.isEnabled()

    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._offer_restart("Saved.")
    assert win._restart_thread is None


# ---- the two halves, without Qt ---------------------------------------------------


def test_decide_restart_ends_the_flow_without_calling_the_slow_half():
    assert (
        decide_restart(is_running=lambda: False, confirm=lambda: True).state  # type: ignore[union-attr]
        is RestartState.NOT_RUNNING
    )
    assert (
        decide_restart(is_running=lambda: True, confirm=lambda: False).state  # type: ignore[union-attr]
        is RestartState.PENDING
    )
    assert decide_restart(is_running=lambda: True, confirm=lambda: True) is None


def test_perform_restart_reports_ready_once_status_answers():
    answers = iter([None, None, {"state": "idle"}])
    outcome = perform_restart(
        restart=lambda: (True, ""), status=lambda: next(answers), sleep=lambda _s: None
    )
    assert outcome.state is RestartState.RESTARTED
