"""``yazses-settings`` entry point — the settings window process.

Thin Qt shell around :mod:`yazses.settingsui.model` and
:mod:`yazses.settingsui.controller`: builds one collapsible group per feature
category with a checkbox per row, stages checkbox changes in memory, and writes
them all (via :class:`~yazses.settingsui.controller.SettingsController`) when
Apply is clicked — mirroring `yazses features enable/disable`. Experimental
features are confirmed the moment you check them, before anything is staged.
"""
from __future__ import annotations

import logging
import sys

from yazses.settingsui.controller import SettingsController
from yazses.settingsui.model import SettingRow, SettingsModel, build_settings_model

log = logging.getLogger(__name__)

_MISSING_PYSIDE_MSG = (
    "The settings window needs PySide6. Install the extra:\n"
    "    uv sync --extra overlay      # or: pip install 'yazses[overlay]'"
)


def run() -> None:
    """Entry point — `yazses-settings` console script / `yazses settings`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(_MISSING_PYSIDE_MSG, file=sys.stderr)
        sys.exit(1)

    from yazses.config import load_config
    from yazses.platform import get_platform
    from yazses.system.configedit import set_config_key

    platform = get_platform()
    config_file = platform.paths.config_file

    def _load() -> object:
        return load_config(config_file)

    def _write(section: str, key: str, value: object, quote: bool | None) -> None:
        set_config_key(config_file, section, key, value, quote=quote)

    controller = SettingsController(_load, _write)

    app = QApplication.instance() or QApplication([])
    window = SettingsWindow(build_settings_model(_load()), controller)
    window.show()
    app.exec()


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
        self._original: dict[str, bool] = {}
        # slug -> desired on/off, staged until Apply. Only holds rows the user
        # actually changed from their loaded state (see _on_toggled).
        self._pending: dict[str, bool] = {}

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
        cb.stateChanged.connect(lambda state, r=row: self._on_toggled(r, bool(state)))
        self._checkboxes[row.slug] = cb
        self._original[row.slug] = row.enabled
        top.addWidget(cb)
        line.addLayout(top)
        subtitle = QLabel(row.tier_label)
        subtitle.setStyleSheet("color: gray; margin-left: 24px;")
        line.addWidget(subtitle)
        return line

    def _on_toggled(self, row: SettingRow, checked: bool) -> None:
        if not row.toggleable:
            return
        if checked and row.experimental and not self._confirm_experimental(row):
            # Declined: revert without staging a change.
            self._checkboxes[row.slug].blockSignals(True)
            self._checkboxes[row.slug].setChecked(False)
            self._checkboxes[row.slug].blockSignals(False)
            return
        if checked == self._original[row.slug]:
            self._pending.pop(row.slug, None)
        else:
            self._pending[row.slug] = checked
        self._hint.setText(
            f"{len(self._pending)} change(s) staged — click Apply, then restart the daemon."
            if self._pending else ""
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
        applied = 0
        for slug in list(self._pending):
            result = self._controller.toggle(slug, confirmed=True)
            if result.ok:
                self._original[slug] = result.enabled
                applied += 1
        self._pending.clear()
        self._hint.setText(
            f"Applied {applied} change(s). Restart the daemon to apply: yazses restart"
            if applied else "Nothing to apply."
        )

    def show(self) -> None:
        self._win.show()
