"""Capability cards that mirror the Features page's checkboxes.

A card holds no state of its own. Clicking it calls ``setChecked`` on the Features
checkbox for the same capability, so the experimental confirmation, staging, the sidebar
dot, Apply and the dependency install are one code path however the switch was reached.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yazses.settingsui.widgets import card, label


class SwitchHub:
    def __init__(self, rows: Mapping[str, Any], checkboxes: Mapping[str, Any]) -> None:
        self._rows = rows
        self._checkboxes = checkboxes
        self._buttons: list[tuple[str, Any]] = []

    def card(self, slug: str) -> Any:
        """A card for *slug*, or ``None`` for a capability this build does not have."""
        row, box = self._rows.get(slug), self._checkboxes.get(slug)
        if row is None or box is None:
            return None
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout

        frame, layout = card()
        line = QHBoxLayout()
        text = QVBoxLayout()
        text.addWidget(label(row.label, heading=True))
        if row.why:
            text.addWidget(label(row.why, muted=True))
        notes = []
        if row.experimental:
            notes.append("Experimental")
        if row.packages and not row.enabled:
            notes.append("Installs extra libraries when applied")
        if notes:
            text.addWidget(label(" · ".join(notes), muted=True))
        line.addLayout(text, 1)

        toggle = QPushButton()
        toggle.setCheckable(True)
        toggle.setMinimumWidth(110)
        toggle.clicked.connect(lambda _checked=False, s=slug: self._flip(s))
        line.addWidget(toggle)
        layout.addLayout(line)
        self._buttons.append((slug, toggle))
        self._paint(slug, toggle)
        box.toggled.connect(lambda _checked: self.sync())
        return frame

    def buttons(self, slug: str, within: Any = None) -> list[Any]:
        return [
            b for s, b in self._buttons
            if s == slug and (within is None or within.isAncestorOf(b))
        ]

    def sync(self) -> None:
        """Repaint every card from its checkbox."""
        for slug, toggle in self._buttons:
            self._paint(slug, toggle)

    def _flip(self, slug: str) -> None:
        box = self._checkboxes[slug]
        if box.isEnabled():
            box.setChecked(not box.isChecked())
        # A declined confirmation reverts the box silently, so read it back.
        self.sync()

    def _paint(self, slug: str, toggle: Any) -> None:
        from yazses.settingsui.widgets import restyle

        row, box = self._rows[slug], self._checkboxes[slug]
        on = box.isChecked()
        toggle.setChecked(on)
        toggle.setEnabled(box.isEnabled())
        if not box.isEnabled():
            text = "Always on" if on else "Not available"
        else:
            text = "On" if on else "Turn on"
        toggle.setText(text)
        toggle.setAccessibleName(f"{row.label}: {'on' if on else 'off'}")
        restyle(toggle, primary="true" if on else "false")
