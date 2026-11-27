"""Run a blocking call off the GUI thread and hand its result back on it.

One call per key at a time: a poll of a daemon that has stopped answering is dropped
rather than queued behind the one already waiting, so a hung daemon costs one thread and
never a frozen window.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class Background:
    def __init__(self, parent: Any) -> None:
        from PySide6.QtCore import QObject, Qt, Signal, Slot

        busy: set[str] = set()

        class _Relay(QObject):
            finished = Signal(str, object, object)

            @Slot(str, object, object)
            def deliver(self, key: str, done: Any, value: Any) -> None:
                busy.discard(key)
                done(value)

        self._busy = busy
        self._relay = _Relay(parent)
        # Queued on purpose: the worker thread emits, the GUI thread runs `done`.
        self._relay.finished.connect(self._relay.deliver, Qt.ConnectionType.QueuedConnection)

    def running(self, key: str) -> bool:
        return key in self._busy

    def run(self, key: str, fn: Callable[[], Any], done: Callable[[Any], None]) -> bool:
        """Start *fn* unless *key* is in flight. *done* gets its result, or ``None``."""
        if key in self._busy:
            return False
        self._busy.add(key)

        def _work() -> None:
            try:
                value = fn()
            except Exception:  # noqa: BLE001 - the page shows "no answer"
                log.debug("background call %s failed", key, exc_info=True)
                value = None
            try:
                self._relay.finished.emit(key, done, value)
            except RuntimeError:  # the window is already gone
                pass

        threading.Thread(target=_work, name=f"yazses-ui-{key}", daemon=True).start()
        return True
