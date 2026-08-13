"""The Qt worker that installs a capability's packages off the UI thread (#135).

Deliberately thin. Everything it decides — what to install, what happened, what
to say — lives in :mod:`yazses.settingsui.deps`, which has no Qt import and is
tested without a display. What is left here is the part that genuinely needs Qt:
moving the work to another thread and getting lines back to the widget safely.

PySide6 is imported inside the class body rather than at module scope so this
module can be imported (and its wiring inspected) on a machine with no Qt — the
same pattern `settingsui/app.py` already uses.
"""

from __future__ import annotations

from collections.abc import Sequence

from yazses.settingsui.deps import InstallPlan, InstallSummary, run_installs


def _qt_base():
    from PySide6.QtCore import QObject, Signal

    return QObject, Signal


try:  # pragma: no cover - exercised only where PySide6 exists
    _QObject, _Signal = _qt_base()
except Exception:  # pragma: no cover - headless/no-Qt import path
    _QObject, _Signal = object, None


class InstallWorker(_QObject):  # type: ignore[misc,valid-type]
    """Runs an install plan and reports progress. Lives on a worker thread.

    ``progress`` carries one human-readable line at a time — the installer's own
    output, routed through ``install_packages(echo=...)`` as the issue specifies,
    rather than a second subprocess of our own.

    ``finished`` carries the :class:`InstallSummary`, so the UI thread never has
    to re-derive what happened.
    """

    if _Signal is not None:  # pragma: no branch - class body runs once
        progress = _Signal(str)
        finished = _Signal(object)

    def __init__(self, plans: Sequence[InstallPlan], installer=None) -> None:
        super().__init__()
        self._plans = list(plans)
        # Injectable so the worker's own logic can be exercised with a fake that
        # neither touches the network nor takes minutes.
        self._installer = installer

    def run(self) -> None:
        """Execute the plan. Never raises into the Qt event loop."""
        # The installer is built here, not in __init__, so it closes over
        # `_emit`: `install_packages(echo=...)` is the streaming seam the issue
        # names, and routing it into `progress` is what puts the installer's own
        # output in front of the user instead of a bare spinner.
        installer = self._installer or _make_installer(self._emit)
        summary = run_installs(
            self._plans,
            install=installer,
            echo=self._emit,
            on_start=lambda plan: self._emit(
                f"Installing {' '.join(plan.packages)} for {plan.slug}…"
            ),
        )
        self._emit_finished(summary)

    # -- signal emission, guarded so the class is usable without Qt ----------

    def _emit(self, line: str) -> None:
        signal = getattr(self, "progress", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit(line)

    def _emit_finished(self, summary: InstallSummary) -> None:
        signal = getattr(self, "finished", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit(summary)


def _make_installer(echo):
    """An installer that streams the real pip output back through *echo*."""

    def _install(packages: Sequence[str]) -> bool:
        from yazses.system.deps import install_packages

        # Same call `yazses features enable` makes — one code path for both
        # front ends, so they cannot drift on what "installed" means.
        return install_packages(packages, echo=echo)

    return _install
