"""The Voice commands page: searchable examples and the command capabilities."""
from __future__ import annotations

from yazses.settingsui import commands_view
from yazses.settingsui.context import PageContext
from yazses.settingsui.widgets import card, label, page_widget

SWITCH_SLUGS = ("commands", "snippets", "macros", "cmdsafety")


class CommandsPage:
    def __init__(self, ctx: PageContext) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

        self.widget, layout = page_widget()
        panel, body = card(hero=True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search commands, for example “undo” or “navigation”")
        self.search.setAccessibleName("Search voice commands")
        self.search.setClearButtonEnabled(True)
        body.addWidget(self.search)

        self._rows: list[tuple[commands_view.Example, QWidget]] = []
        holder = QVBoxLayout()
        holder.setSpacing(6)
        for example in commands_view.EXAMPLES:
            line = QWidget()
            inner = QHBoxLayout(line)
            inner.setContentsMargins(0, 2, 0, 2)
            inner.addWidget(label(f"“{example.phrase}”", heading=True), 3)
            inner.addWidget(label(example.meaning), 4)
            inner.addWidget(label(example.group, muted=True), 2)
            holder.addWidget(line)
            self._rows.append((example, line))
        body.addLayout(holder)
        self._empty = label("No command matches that.", muted=True)
        self._empty.hide()
        body.addWidget(self._empty)
        body.addWidget(label(
            "A phrase counts as a command when it is all you said while holding the key.",
            muted=True,
        ))
        self.search.textChanged.connect(self._filter)
        layout.addWidget(panel)

        layout.addWidget(label("Command capabilities", heading=True))
        for slug in SWITCH_SLUGS:
            switch = ctx.switches.card(slug)
            if switch is not None:
                layout.addWidget(switch)
        layout.addStretch(1)
        self._visible = len(self._rows)

    def visible_count(self) -> int:
        return self._visible

    def _filter(self, query: str) -> None:
        shown = set(commands_view.search(query))
        for example, line in self._rows:
            line.setVisible(example in shown)
        self._visible = len(shown)
        self._empty.setVisible(not shown)
