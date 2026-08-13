"""``yazses-settings`` entry point — the settings window process.

Thin Qt shell around :mod:`yazses.settingsui.model` and
:mod:`yazses.settingsui.controller`: builds one group per feature category with a
checkbox per row, stages checkbox changes in memory, and writes them all when
Apply is clicked — mirroring `yazses features enable/disable`. Experimental
features are confirmed the moment you check them, before anything is staged.

All the bookkeeping (what is staged, what was confirmed, what landed) lives in
the pure :class:`~yazses.settingsui.controller.PendingChanges` /
:class:`~yazses.settingsui.controller.SettingsController` pair, so this file only
translates between those and widgets — and reports every outcome, including the
ones that failed.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

from yazses.settingsui.controller import ApplyReport, PendingChanges, SettingsController
from yazses.settingsui.launch import has_display, pyside_available
from yazses.settingsui.model import SettingRow, SettingsModel, build_settings_model

log = logging.getLogger(__name__)

_MISSING_PYSIDE_MSG = (
    "The settings window needs PySide6. Install it with:\n"
    "    uv sync --extra overlay      # or: pip install 'yazses[overlay]'\n"
    "Every setting is also available from the terminal: yazses features"
)
_NO_DISPLAY_MSG = (
    "The settings window needs a graphical session — no DISPLAY or WAYLAND_DISPLAY\n"
    "is set, so there is nothing to open it on (an SSH session without X forwarding,\n"
    "or a headless machine).\n"
    "Use the terminal instead:\n"
    "    yazses features                     list every capability and its state\n"
    "    yazses features enable <name>       turn one on\n"
    "    yazses features disable <name>      turn one off"
)


def run() -> None:
    """Entry point — `yazses-settings` console script / `yazses settings`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not pyside_available():
        print(_MISSING_PYSIDE_MSG, file=sys.stderr)
        sys.exit(1)
    if not has_display(os.environ):
        print(_NO_DISPLAY_MSG, file=sys.stderr)
        sys.exit(1)

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # installed but unusable (missing Qt libs on old distros)
        print(f"{_MISSING_PYSIDE_MSG}\n\nImport failed: {exc}", file=sys.stderr)
        sys.exit(1)

    from yazses.config import Config, load_config
    from yazses.platform import get_platform
    from yazses.system.configedit import set_config_key

    platform = get_platform()
    config_file = platform.paths.config_file

    def _load() -> Config:
        return load_config(config_file)

    def _write(section: str, key: str, value: object, quote: bool | None) -> None:
        set_config_key(config_file, section, key, value, quote=quote)

    controller = SettingsController(_load, _write)

    app = QApplication.instance() or QApplication(sys.argv)
    window = SettingsWindow(build_settings_model(_load()), controller)
    window.show()
    sys.exit(app.exec())


class SettingsWindow:
    """The settings window itself. Only imports Qt when instantiated."""

    def __init__(self, model: SettingsModel, controller: SettingsController) -> None:
        from PySide6.QtWidgets import (
            QCheckBox,
            QGroupBox,
            QLabel,
            QMainWindow,
            QPushButton,
            QScrollArea,
            QVBoxLayout,
            QWidget,
        )

        self._controller = controller
        self._checkboxes: dict[str, QCheckBox] = {}
        self._pending = PendingChanges(
            {row.slug: row.enabled for group in model.groups for row in group.rows}
        )

        self._win = QMainWindow()
        self._win.setWindowTitle("YazSes Settings")
        self._win.resize(640, 720)

        central = QWidget()
        outer = QVBoxLayout(central)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)

        for group in model.groups:
            box = QGroupBox(group.category)
            box_layout = QVBoxLayout(box)
            if group.blurb:
                blurb = QLabel(group.blurb)
                blurb.setWordWrap(True)
                blurb.setStyleSheet("color: gray;")
                box_layout.addWidget(blurb)
            for row in group.rows:
                box_layout.addLayout(self._build_row(row))
            body_layout.addWidget(box)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: gray;")
        outer.addWidget(self._hint)

        apply_btn = QPushButton("Apply")
        self._apply_button = apply_btn
        # Dependency-install state (#135). `_auto_install` mirrors the CLI's
        # --no-install; the thread/worker refs keep Qt from collecting a
        # running QThread out from under the install.
        self._auto_install = True
        # Typed as Any: PySide6 has no stubs in this tree (mypy already ignores
        # its imports repo-wide), so a precise QThread annotation would be an
        # error rather than documentation.
        self._restart_pending = False
        self._install_thread: Any = None
        self._install_worker: Any = None
        apply_btn.clicked.connect(self._on_apply)
        outer.addWidget(apply_btn)

        self._win.setCentralWidget(central)

    def _build_row(self, row: SettingRow):
        from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout

        line = QVBoxLayout()
        top = QHBoxLayout()
        cb = QCheckBox(row.label)
        cb.setChecked(row.enabled)
        cb.setEnabled(row.toggleable)
        cb.toggled.connect(lambda checked, r=row: self._on_toggled(r, checked))
        self._checkboxes[row.slug] = cb
        top.addWidget(cb)
        line.addLayout(top)
        subtitle = QLabel(row.tier_label)
        subtitle.setStyleSheet("color: gray; margin-left: 24px;")
        line.addWidget(subtitle)
        return line

    def _on_toggled(self, row: SettingRow, checked: bool) -> None:
        if not row.toggleable:
            return
        if checked and row.experimental and not self._pending.is_confirmed(row.slug):
            if not self._confirm_experimental(row):
                # Declined: put the box back without staging anything.
                self._set_checked_silently(row.slug, self._pending.baseline(row.slug))
                return
            self._pending.confirm(row.slug)
        self._pending.stage(row.slug, checked)
        self._show_staged()

    def _set_checked_silently(self, slug: str, checked: bool) -> None:
        """Move a checkbox without re-entering :meth:`_on_toggled`."""
        cb = self._checkboxes[slug]
        cb.blockSignals(True)
        cb.setChecked(checked)
        cb.blockSignals(False)

    def _show_staged(self) -> None:
        count = len(self._pending)
        self._hint.setText(
            f"{count} change(s) staged — click Apply, then restart the daemon."
            if count else ""
        )

    def _confirm_experimental(self, row: SettingRow) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.warning(
            self._win,
            "Experimental feature",
            f"{row.label} is experimental — {row.why}\n\nEnable it anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_apply(self) -> None:
        report = self._controller.apply(self._pending)

        # Re-sync every checkbox with what actually landed: a row that failed
        # keeps its staged position (so Apply can be retried) but must not be
        # left claiming a state the config file does not have.
        still_staged = {slug for slug, _ in self._pending.items()}
        for slug in self._checkboxes:
            if slug not in still_staged:
                self._set_checked_silently(slug, self._pending.baseline(slug))

        self._hint.setText(self._summarise(report))
        if report.errors:
            self._warn("Some settings were not saved", "\n".join(report.errors))

        # Install the optional packages the newly-enabled capabilities need (#135).
        # Off the UI thread: a `mediapipe` or `speechbrain` install takes minutes,
        # and on the main thread that is indistinguishable from a hang.
        self._install_missing(report.missing_packages)

        # Then close the loop: config is read at startup, so until the daemon is
        # restarted the window is showing settings that are not in effect (#61).
        if report.applied:
            self._offer_restart()

    def _offer_restart(self) -> None:
        """Ask, restart, and report what the daemon actually says afterwards.

        The decision logic is `settingsui/restart.py`; this method only supplies
        the dialog and the IPC/subprocess effects, so the honest-state rules are
        unit-tested without Qt.
        """
        from yazses.settingsui.restart import apply_and_restart

        outcome = apply_and_restart(
            is_running=self._daemon_running,
            confirm=self._confirm_restart,
            restart=self._run_restart,
            status=self._daemon_status,
        )
        self._hint.setText(outcome.message)
        self._restart_pending = outcome.needs_restart_hint

    def _confirm_restart(self) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self._win,
            "Restart YazSes now?",
            "Your changes are saved. YazSes reads its configuration at startup, so "
            "they take effect after a restart.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _daemon_running(self) -> bool:
        try:
            from yazses.platform import get_platform

            return bool(get_platform().lifecycle.is_running())
        except Exception:
            logging.getLogger(__name__).debug("daemon check failed", exc_info=True)
            return False

    def _daemon_status(self):
        try:
            from yazses.platform import get_platform

            platform = get_platform()
            return platform.ipc_client_factory(platform.paths.ipc_socket).call("status")
        except Exception:
            return None

    @staticmethod
    def _run_restart() -> tuple[bool, str]:
        """The same path as `yazses restart`, as a subprocess.

        Shelling out rather than importing the CLI keeps the window out of the
        daemon's lifecycle: `restart` stops every daemon including detached ones,
        and doing that in-process from a GUI is how you end up killing yourself.
        """
        import subprocess
        import sys

        try:
            result = subprocess.run(
                [sys.executable, "-m", "yazses.cli", "restart"],
                capture_output=True, text=True, timeout=90,
            )
        except Exception as exc:  # noqa: BLE001 - reported to the user
            return False, str(exc)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "").strip()[:200]
        return True, ""

    def _install_missing(self, missing_by_slug) -> None:
        """Start the dependency install for whatever Apply just enabled.

        Decisions live in `settingsui/deps.py`; this method owns only the thread
        and the widgets, which is the split the rest of `settingsui/` uses.
        """
        from yazses.settingsui.deps import describe_skipped, plan_installs

        if not missing_by_slug:
            return
        if not self._auto_install:
            self._hint.setText(describe_skipped(missing_by_slug))
            return
        plans = plan_installs(missing_by_slug, auto_install=True)
        if not plans:
            return
        if self._install_thread is not None:
            # An install is already running; the button is disabled, but a queued
            # signal could still land here.
            return
        self._start_install_worker(plans)

    def _start_install_worker(self, plans) -> None:
        from PySide6.QtCore import QThread

        from yazses.settingsui.worker import InstallWorker

        self._apply_button.setEnabled(False)
        self._hint.setText(
            f"Installing packages for {', '.join(p.slug for p in plans)}… "
            "this can take a few minutes."
        )

        thread = QThread(self._win)
        worker = InstallWorker(plans)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_install_progress)
        worker.finished.connect(self._on_install_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Keep strong references: a QThread garbage-collected mid-run takes the
        # install with it and Qt warns about a destroyed running thread.
        self._install_thread, self._install_worker = thread, worker
        thread.start()

    def _on_install_progress(self, line: str) -> None:
        self._hint.setText(line)

    def _on_install_finished(self, summary) -> None:
        from yazses.settingsui.deps import describe_summary

        self._install_thread = self._install_worker = None
        self._apply_button.setEnabled(True)
        message = describe_summary(summary)
        if message:
            self._hint.setText(message)
        if summary.failed:
            # The config key stands on a failed install (see settingsui/deps.py);
            # saying so is the whole point, otherwise the toggle looks inert.
            self._warn(
                "Some packages could not be installed",
                "\n".join(f.slug + ": " + (f.error or "install failed")
                           for f in summary.failed),
            )

    def _summarise(self, report: ApplyReport) -> str:
        parts: list[str] = []
        if report.applied:
            parts.append(
                f"Applied {report.applied} change(s). "
                "Restart the daemon to apply: yazses restart"
            )
        elif not report.errors and not report.unconfirmed:
            parts.append("Nothing to apply.")
        if report.errors:
            parts.append(f"{len(report.errors)} change(s) failed — still staged.")
        if report.unconfirmed:
            parts.append(
                f"{len(report.unconfirmed)} experimental change(s) need confirming."
            )
        for slug, packages in report.missing_packages.items():
            parts.append(
                f"{slug} needs packages that are not installed ({' '.join(packages)}). "
                f"Install them with: yazses features enable {slug}"
            )
        return "  ".join(parts)

    def _warn(self, title: str, body: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(self._win, title, body, QMessageBox.StandardButton.Ok)

    def show(self) -> None:
        self._win.show()
