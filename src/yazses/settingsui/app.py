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
