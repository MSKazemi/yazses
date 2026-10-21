"""The Settings window's *About and updates* box: Check for updates, and Install now.

The decisions and the wording are in :mod:`yazses.settingsui.maintenance` (no Qt). This
module owns the widgets, the dialogs and the threads, and wires them to the functions
the tray and the CLI already use. It implements no update or install logic of its own:

* **Check for updates** runs ``tray.updates.check_updates`` and
  ``installer_update.one_click_offer`` on a worker thread (the check reaches PyPI or
  GitHub, and the Windows package-manager offer shells ``choco``/``winget``/``scoop``).
* **Install update…** on a one-click channel follows ADR-027 for a surface that is not
  the tray: confirm with ``installer_update.confirmation_prompt``, hand off with
  ``tray.updates.hand_off_outside_tray`` on a worker thread (this process is among the
  PIDs the update waits for, by default), then quit this window's ``QApplication``. On
  uv/pipx/pip it runs ``updater.run_upgrade_checked`` on a worker thread and offers the
  daemon restart through the window's own ``_offer_restart``.
* **Install now** beside each switched-on, dormant feature runs
  ``system.ondemand.install_one`` (the transactional install) -- or, in a frozen build
  whose pack runtime is supported, ``packs.manage.install`` (ADR-028) -- on a worker
  thread, then offers the restart.

Nothing that waits on the network or an installer runs on the UI thread. PySide6 is
imported inside functions, like the rest of ``settingsui/``, so the module imports on a
machine without Qt.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yazses.settingsui import maintenance as m

log = logging.getLogger(__name__)

#: How long the "closing to install" line stays up before the window quits. The update
#: job waits for this process, so a short pause costs nothing and lets it be read.
HANDOFF_QUIT_DELAY_MS = 3000


# ---- the effects, injectable -------------------------------------------------


def _default_version() -> str:
    from yazses import branding

    return branding.version()


def _default_check():
    """``(status, offer, launcher)``. Blocking; runs on a worker thread. Never raises."""
    from yazses.cli import _update_launcher
    from yazses.system.installer_update import one_click_offer
    from yazses.tray.updates import check_updates

    status = check_updates()
    launcher = _update_launcher()
    offer = one_click_offer(status, launcher)
    if offer is None and status.available and status.command:
        # The command that keeps the enabled features' libraries, resolved before it is
        # shown so what the window says is what runs (`yazses update` does the same;
        # `run_upgrade_checked` applies it again, idempotently).
        from yazses.system.updater import preserve_enabled_features

        status = preserve_enabled_features(status)
    return status, offer, launcher


def _default_hand_off(status, launcher, progress):
    from yazses.cli import _request_daemon_shutdown, _running_tray_pid
    from yazses.tray.updates import hand_off_outside_tray

    return hand_off_outside_tray(
        status,
        launcher,
        tray_pid=_running_tray_pid,
        request_daemon_shutdown=_request_daemon_shutdown,
        progress=progress,
    )


def _default_upgrade(status):
    from yazses.system.updater import UpgradeOutcome, run_upgrade_checked

    try:
        return run_upgrade_checked(status)
    except Exception:  # noqa: BLE001 - reported as a failed upgrade, never raised at Qt
        log.exception("settings-window upgrade failed")
        return UpgradeOutcome(
            code=1, before=status.current, after=None, expected=status.latest,
            method=status.method, command=status.command,
        )


def _default_open_page() -> bool:
    from yazses.system.browser import open_url
    from yazses.system.updater import RELEASES_URL

    return bool(open_url(RELEASES_URL))


def _size_note(item) -> tuple[str, str]:
    try:
        from yazses.system.depsize import download_note, format_mb, marginal_download_mb

        missing = list(item.missing)
        return download_note(item.slug, missing), format_mb(marginal_download_mb(item.slug, missing))
    except Exception:  # noqa: BLE001 - a size is a courtesy, never a failure
        return "", ""


def _pack_lookups():
    """``(pack_status, pack_entry)`` for a frozen build with packs, else ``(None, None)``.

    The same routing ``yazses features enable`` uses (``cli._enable_via_pack``): only a
    frozen build whose pack runtime is supported, only a feature this build publishes an
    add-on for, and only when packs can be installed -- or when the refusal is the
    elevation one, which is worth saying. Everything else keeps the dormant feature's own
    answer (for a frozen bundle, "install YazSes from PyPI instead").
    """
    if not getattr(sys, "frozen", False):
        return None, None
    from yazses.packs.context import load_context
    from yazses.packs.manage import feature_pack_status

    ctx = load_context()
    if not (ctx.frozen and ctx.runtime.supported()):
        return None, None
    usable = ctx.capability.ok or ctx.capability.code == "elevated"
    if not usable or ctx.index is None:
        return None, None
    index = ctx.index

    def pack_status(slug: str):
        if index.for_feature(slug) is None:
            return None
        return feature_pack_status(ctx, slug, config_on=True)

    return pack_status, index.for_feature


def default_scan(controller) -> list[m.FeatureInstallRow]:
    """Every switched-on feature whose libraries are missing, routed. Local probes only.

    Uses the window's own config loader and dependency probes, so the window and this box
    cannot disagree about what is installed, and a test window built on fakes scans
    nothing on the host.
    """
    from yazses.system.dormant import dormant_features

    items = dormant_features(
        controller.load_config(),
        missing=getattr(controller, "_deps_probe", None),
        blocked=getattr(controller, "_blocked_probe", None),
    )
    if not items:
        return []
    pack_status, pack_entry = _pack_lookups()
    return m.install_rows(
        items, size_note=_size_note, pack_status=pack_status, pack_entry=pack_entry,
    )


def _default_install_pip(row: m.FeatureInstallRow, echo) -> bool:
    from yazses.system.ondemand import install_one

    return install_one(row.item, echo=echo)


def _default_install_pack(row: m.FeatureInstallRow, progress):
    from yazses.packs.context import load_context
    from yazses.packs.manage import install

    return install(load_context(), row.item, progress=progress)


def _default_quit() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.quit()


@dataclass
class Services:
    """Every effect the box has. Production defaults; tests pass fakes."""

    version: Callable[[], str] = _default_version
    check: Callable[[], Any] = _default_check
    hand_off: Callable[..., Any] = _default_hand_off
    upgrade: Callable[[Any], Any] = _default_upgrade
    open_page: Callable[[], bool] = _default_open_page
    scan: Callable[[Any], list] = default_scan
    install_pip: Callable[..., bool] = _default_install_pip
    install_pack: Callable[..., Any] = _default_install_pack
    quit_app: Callable[[], None] = _default_quit


# ---- running work off the UI thread -----------------------------------------


_QT_CLASSES: tuple | None = None


def _qt_classes():
    global _QT_CLASSES
    if _QT_CLASSES is None:
        from PySide6.QtCore import QObject, QThread, Signal, Slot

        class _Task(QObject):
            progress = Signal(str)
            finished = Signal(object)

            def __init__(self, fn) -> None:
                super().__init__()
                self._fn = fn

            def run(self) -> None:
                try:
                    result = self._fn(self.progress.emit)
                except Exception as exc:  # noqa: BLE001 - never raise into a QThread
                    log.exception("settings-window background task failed")
                    result = exc
                self.finished.emit(result)

        class _Relay(QObject):
            """Lives on the UI thread, so the task's signals reach it queued."""

            def __init__(self, on_progress, on_done) -> None:
                super().__init__()
                self._on_progress = on_progress
                self._on_done = on_done

            @Slot(str)
            def progress(self, line: str) -> None:
                self._on_progress(line)

            @Slot(object)
            def done(self, result) -> None:
                self._on_done(result)

        _QT_CLASSES = (_Task, _Relay, QThread)
    return _QT_CLASSES


class QtRunner:
    """Run ``fn(progress)`` on a ``QThread``; deliver progress and the result on the UI thread.

    The callbacks are connected through a ``QObject`` that lives on the UI thread, so Qt
    queues them there. Connecting a worker's signal straight to a plain Python callable
    would run it on the worker thread, where touching a widget is undefined behaviour.
    """

    def __init__(self, parent=None) -> None:
        self._parent = parent
        self._live: list[tuple] = []

    def run(self, fn, on_progress, on_done) -> None:
        Task, Relay, QThread = _qt_classes()
        thread = QThread(self._parent)
        task = Task(fn)
        relay = Relay(on_progress, on_done)
        task.moveToThread(thread)
        thread.started.connect(task.run)
        task.progress.connect(relay.progress)
        task.finished.connect(relay.done)
        task.finished.connect(thread.quit)
        entry = (thread, task, relay)
        # Strong references until the thread has finished: a QThread collected mid-run
        # takes the work with it.
        self._live.append(entry)

        def _forget() -> None:
            if entry in self._live:
                self._live.remove(entry)
            task.deleteLater()

        thread.finished.connect(_forget)
        thread.start()

    @property
    def running(self) -> int:
        return len(self._live)


# ---- the box ----------------------------------------------------------------


class MaintenancePanel:
    """Builds the box and runs its two flows. Only imports Qt when instantiated."""

    def __init__(self, window, *, services: Services | None = None, runner=None) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        from yazses.settingsui.theme import muted_style_for

        self._window = window
        self._svc = services or Services()
        self._runner = runner or QtRunner(getattr(window, "_win", None))
        self._busy = False
        self._status: Any = None
        self._offer: Any = None
        self._launcher: Any = None
        self._view = m.UpdateView("")
        self._rows: list[m.FeatureInstallRow] = []
        self._row_buttons: dict[str, Any] = {}

        self.widget = QGroupBox("About and updates")
        layout = QVBoxLayout(self.widget)

        self._current = self._safe_version()
        self.update_label = QLabel(m.idle_text(self._current))
        self.update_label.setWordWrap(True)
        # Selectable: the manual steps are commands and URLs to copy.
        self.update_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.update_label)

        buttons = QHBoxLayout()
        self.check_button = QPushButton(m.CHECK_LABEL)
        self.check_button.setToolTip(
            "Look up the newest version for the way YazSes was installed. "
            "Nothing is downloaded until you confirm an update."
        )
        self.check_button.clicked.connect(self.on_check)
        buttons.addWidget(self.check_button)
        self.action_button = QPushButton("")
        self.action_button.clicked.connect(self.on_action)
        self.action_button.setVisible(False)
        buttons.addWidget(self.action_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.features_label = QLabel("")
        self.features_label.setWordWrap(True)
        layout.addWidget(self.features_label)
        self._rows_holder = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_holder)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._rows_holder)
        self.install_label = QLabel("")
        self.install_label.setWordWrap(True)
        self.install_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.install_label.setStyleSheet(muted_style_for(self.install_label))
        layout.addWidget(self.install_label)

        self._QLabel, self._QPushButton, self._QHBoxLayout, self._QWidget = (
            QLabel, QPushButton, QHBoxLayout, QWidget,
        )
        self.refresh_features()

    # -- shared --------------------------------------------------------------

    def _safe_version(self) -> str:
        try:
            return str(self._svc.version())
        except Exception:  # noqa: BLE001
            return "unknown"

    def _window_busy(self) -> bool:
        """The window's own install or language worker is running (Apply is disabled)."""
        button = getattr(self._window, "_apply_button", None)
        return button is not None and not button.isEnabled()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.check_button.setEnabled(not busy)
        self.action_button.setEnabled(not busy)
        for slug, button in self._row_buttons.items():
            row = next((r for r in self._rows if r.slug == slug), None)
            button.setEnabled(not busy and row is not None and row.installable)
        # One package/network job at a time across the whole window: Apply also installs.
        apply = getattr(self._window, "_apply_button", None)
        if apply is not None:
            apply.setEnabled(not busy)

    def confirm(self, title: str, text: str) -> bool:
        """A Yes/No box. Anything but an explicit Yes is a no."""
        from PySide6.QtWidgets import QMessageBox

        try:
            answer = QMessageBox.question(
                getattr(self._window, "_win", None), title, text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
        except Exception:  # noqa: BLE001 - a box that cannot be shown is a no
            log.warning("could not show the confirmation", exc_info=True)
            return False
        return answer == QMessageBox.StandardButton.Yes

    def _warn(self, title: str, body: str) -> None:
        warn = getattr(self._window, "_warn", None)
        if callable(warn):
            warn(title, body)

    def _offer_restart(self, summary: str) -> None:
        offer = getattr(self._window, "_offer_restart", None)
        if callable(offer):
            offer(summary)

    def _show_view(self, view: m.UpdateView) -> None:
        self._view = view
        self.update_label.setText(view.text)
        visible = view.action is not m.UpdateAction.NONE
        self.action_button.setVisible(visible)
        if visible:
            self.action_button.setText(view.label)

    # -- updates -------------------------------------------------------------

    def on_check(self) -> None:
        if self._busy:
            return
        if self._window_busy():
            self.update_label.setText(
                "Packages are being installed; check again when that has finished."
            )
            return
        self._set_busy(True)
        self.action_button.setVisible(False)
        self.update_label.setText(m.checking_text(self._current))
        self._runner.run(lambda _progress: self._svc.check(), lambda _line: None,
                         self._on_checked)

    def _on_checked(self, result) -> None:
        self._set_busy(False)
        if isinstance(result, BaseException):
            self._show_view(m.UpdateView(
                f"Installed: {self._current}\nCould not check for updates — {result}. "
                "YazSes keeps working."
            ))
            return
        self._status, self._offer, self._launcher = result
        self._show_view(m.plan_update(self._status, self._offer))

    def on_action(self) -> None:
        if self._busy:
            return
        action = self._view.action
        if action is m.UpdateAction.OPEN_PAGE:
            self._open_page()
        elif action is m.UpdateAction.ONE_CLICK:
            self._start_one_click()
        elif action is m.UpdateAction.UPGRADE:
            self._start_upgrade()

    def _open_page(self) -> None:
        from yazses.system.updater import RELEASES_URL

        try:
            opened = bool(self._svc.open_page())
        except Exception:  # noqa: BLE001
            opened = False
        if not opened:
            self.update_label.setText(
                f"{self._view.text}\n\nCould not open your browser. Download page: "
                f"{RELEASES_URL}"
            )

    def _start_one_click(self) -> None:
        from yazses.system.installer_update import confirmation_prompt

        if self._window_busy():
            self.update_label.setText(
                "Packages are being installed; update when that has finished."
            )
            return
        status, launcher = self._status, self._launcher
        try:
            title, text = confirmation_prompt(status)
        except Exception:  # noqa: BLE001
            log.warning("could not word the update confirmation", exc_info=True)
            return
        text += m.unapplied_note(len(getattr(self._window, "_pending", ()) or ()))
        if not self.confirm(title, text):
            self.update_label.setText(
                f"{self._view.text}\n\nUpdate skipped. Nothing was downloaded."
            )
            return
        self._set_busy(True)
        self.update_label.setText("Preparing the update…")

        def work(emit):
            return self._svc.hand_off(
                status, launcher, lambda msg, frac: emit(m.progress_line(msg, frac)),
            )

        self._runner.run(work, self.update_label.setText, self._on_handed_off)

    def _on_handed_off(self, result) -> None:
        if isinstance(result, BaseException):
            self._set_busy(False)
            self._show_view(m.UpdateView(
                f"Update not installed: {result}. YazSes keeps running.",
                m.UpdateAction.OPEN_PAGE, m.OPEN_PAGE_LABEL,
            ))
            return
        view = m.describe_handoff(result)
        self._show_view(view)
        if not result.ok:
            self._set_busy(False)
            return
        # The update job is waiting for this process to exit (ADR-027). Stay busy:
        # nothing else may start now.
        self.action_button.setVisible(False)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(HANDOFF_QUIT_DELAY_MS, self._svc.quit_app)

    def _start_upgrade(self) -> None:
        if self._window_busy():
            self.update_label.setText(
                "Packages are being installed; update when that has finished."
            )
            return
        status = self._status
        title, text = m.upgrade_confirmation(status)
        if not self.confirm(title, text):
            self.update_label.setText(f"{self._view.text}\n\nUpdate skipped.")
            return
        self._set_busy(True)
        self.update_label.setText(
            f"Installing the update: {' '.join(status.command or [])}…"
        )
        self._runner.run(lambda _emit: self._svc.upgrade(status), lambda _l: None,
                         self._on_upgraded)

    def _on_upgraded(self, outcome) -> None:
        self._set_busy(False)
        if isinstance(outcome, BaseException):
            self._show_view(m.UpdateView(
                f"The upgrade failed: {outcome}. Run `yazses update` in a terminal to "
                "see why."
            ))
            return
        text, restart = m.describe_upgrade(outcome)
        self._show_view(m.UpdateView(text))
        if restart:
            self._offer_restart(text)

    # -- dormant features ------------------------------------------------------

    def refresh_features(self) -> None:
        """Rebuild the dormant-feature rows. Local probes only, so it runs inline."""
        try:
            rows = list(self._svc.scan(getattr(self._window, "_controller", None)))
        except Exception:  # noqa: BLE001 - a diagnostic must not stop the window
            log.debug("dormant-feature scan failed", exc_info=True)
            rows = []
        self._rows = rows
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._row_buttons = {}
        self.features_label.setText(m.summary_counts(rows))
        self.features_label.setVisible(bool(rows))
        self._rows_holder.setVisible(bool(rows))
        for row in rows:
            holder = self._QWidget()
            line = self._QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            label = self._QLabel(row.detail)
            label.setWordWrap(True)
            line.addWidget(label, 1)
            button = self._QPushButton(row.button_label)
            if row.installable:
                button.setToolTip(row.size or f"Install the libraries {row.name} needs.")
            else:
                # Disabled, with the reason: a button that cannot work is worse than
                # none, but the reason is what tells the user what would.
                button.setToolTip(row.detail)
            button.setEnabled(row.installable and not self._busy)
            button.clicked.connect(lambda _checked=False, r=row: self.on_install(r))
            line.addWidget(button)
            self._row_buttons[row.slug] = button
            self._rows_layout.addWidget(holder)

    def on_install(self, row: m.FeatureInstallRow) -> None:
        if self._busy or not row.installable:
            return
        if self._window_busy():
            self.install_label.setText(
                "Another install is running; try again when it has finished."
            )
            return
        self._set_busy(True)
        self.install_label.setText(m.install_start_text(row))

        if row.route == m.PACK:
            def work(emit):
                return m.pack_result(
                    row,
                    self._svc.install_pack(
                        row, lambda msg, frac: emit(m.progress_line(msg, frac)),
                    ),
                )
        else:
            def work(emit):
                lines: list[str] = []

                def echo(line) -> None:
                    text = str(line)
                    lines.append(text)
                    emit(text.strip().splitlines()[-1] if text.strip() else text)

                ok = bool(self._svc.install_pip(row, echo))
                return m.pip_result(row, ok, lines)

        self._runner.run(work, self._on_install_progress, self._on_installed)

    def _on_install_progress(self, line: str) -> None:
        if line:
            self.install_label.setText(line[:400])

    def _on_installed(self, result) -> None:
        self._set_busy(False)
        if isinstance(result, BaseException):
            self.install_label.setText(f"The install failed: {result}")
            self._warn("Install failed", str(result))
            return
        self.install_label.setText(result.message)
        self.refresh_features()
        if not result.ok:
            title = (
                "The install was not fully undone"
                if result.rollback is m.Rollback.INCOMPLETE
                else f"{result.name} could not be installed"
            )
            self._warn(title, result.message)
            return
        self._offer_restart(result.message)


def attach_maintenance(window, *, services: Services | None = None, runner=None):
    """Build the box for *window*, keep it on ``window._maintenance``, return its widget."""
    panel = MaintenancePanel(window, services=services, runner=runner)
    window._maintenance = panel
    return panel.widget
