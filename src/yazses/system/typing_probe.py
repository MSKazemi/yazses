"""The window ``typing_canary`` types into: one text box, and a report of what it holds.

Run as a child process (``python -m yazses.system.typing_probe``) so a Qt event loop never
shares a process with the daemon, and so a probe that wedges is killed rather than waited
on. It speaks a two-line protocol on stdout::

    FOCUSED                 the window became the active window (once)
    TEXT "<json string>"    the box's whole content, after every change

The protocol functions are pure and tested directly; the Qt half is imported lazily
(AGENTS.md rule 3 — a base install with no desktop extra must still import this module).
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Mapping

FOCUSED = "FOCUSED"
TEXT = "TEXT"
#: A probe that is never closed must not outlive its purpose by much.
MAX_LIFETIME_S = 20.0


def encode_event(kind: str, value: str = "") -> str:
    """One protocol line, without the newline."""
    if kind == TEXT:
        return f"{TEXT} {json.dumps(value, ensure_ascii=False)}"
    return kind


def decode_event(line: str) -> tuple[str, str] | None:
    """Parse one line; ``None`` for anything that is not ours (Qt prints its own noise)."""
    line = line.rstrip("\r\n")
    if line == FOCUSED:
        return (FOCUSED, "")
    if line.startswith(TEXT + " "):
        try:
            value = json.loads(line[len(TEXT) + 1 :])
        except ValueError:
            return None
        return (TEXT, value) if isinstance(value, str) else None
    return None


def probe_available(env: Mapping[str, str] | None = None) -> str | None:
    """``None`` when a probe window can open here, else the reason it cannot."""
    import importlib.util

    from yazses.system.graphical import has_graphical_session

    if importlib.util.find_spec("PySide6") is None:
        return "PySide6 is not installed (the `desktop` extra provides it)"
    if not has_graphical_session(env if env is not None else os.environ):
        return "there is no graphical session"
    return None


class SubprocessProbe:
    """Parent-side handle on the probe window. Implements ``typing_canary.Probe``."""

    def __init__(self, argv: list[str] | None = None) -> None:
        # Native platform on purpose: the bug this exists to catch only happens on a real
        # Wayland session, so forcing xcb here would test a path nobody types through.
        # `argv` exists so the parent-side logic is testable against a stub child.
        self._proc = subprocess.Popen(
            argv or [sys.executable, "-m", "yazses.system.typing_probe"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._events: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._focused = False
        self._text = ""
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            event = decode_event(line)
            if event is not None:
                self._events.put(event)
        self._events.put(None)  # EOF: the child exited

    def _drain(self, timeout: float) -> bool:
        """Apply one event if it arrives within ``timeout``. False on timeout or EOF."""
        try:
            event = self._events.get(timeout=max(timeout, 0.0))
        except queue.Empty:
            return False
        if event is None:
            return False
        kind, value = event
        if kind == FOCUSED:
            self._focused = True
        elif kind == TEXT:
            self._text = value
        return True

    def wait_focused(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while not self._focused:
            if not self._drain(deadline - time.monotonic()):
                break
        return self._focused

    def wait_text(self, expected: str, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while self._text != expected:
            if not self._drain(deadline - time.monotonic()):
                break
        return self._text

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:  # pragma: no cover - a wedged child
                self._proc.kill()


def open_probe() -> SubprocessProbe:
    reason = probe_available()
    if reason is not None:
        raise RuntimeError(reason)
    return SubprocessProbe()


def main() -> int:  # pragma: no cover - needs a display; exercised on a real session
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLineEdit

    app = QApplication(sys.argv[:1])
    box = QLineEdit()
    box.setWindowTitle("YazSes typing check")
    box.setPlaceholderText("YazSes is checking that typing reaches this window…")
    box.resize(460, 56)
    state = {"focused": False}

    def emit(kind: str, value: str = "") -> None:
        sys.stdout.write(encode_event(kind, value) + "\n")
        sys.stdout.flush()

    def poll() -> None:
        if not state["focused"] and box.isActiveWindow() and box.hasFocus():
            state["focused"] = True
            emit(FOCUSED)

    box.textChanged.connect(lambda t: emit(TEXT, t))
    box.show()
    box.activateWindow()
    box.setFocus()
    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(40)
    QTimer.singleShot(int(MAX_LIFETIME_S * 1000), app.quit)
    return int(app.exec())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
