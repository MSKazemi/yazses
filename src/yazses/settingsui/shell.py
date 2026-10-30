"""The settings window's frame: a sidebar of pages, the page on show, and the footer.

Thin Qt painting of :mod:`yazses.settingsui.pages` — which pages exist, what their labels
say, which hold unsaved changes. It owns no setting and runs no apply logic; ``app.py``
builds each page's contents and hands them over, so the 1,700-line window class keeps
exactly the behaviour it had and only its layout assembly moves here.

PySide6 is imported inside functions, like the rest of ``settingsui/``, so the module
imports on a machine without Qt.
"""
from __future__ import annotations

from typing import Any

from yazses.settingsui.pages import PAGES, PageSpec, page_label
from yazses.settingsui.theme import mute_label

#: Sidebar width. Wide enough for "Hands-free •" at a large system font, narrow enough
#: that the content area keeps most of a 760 px window.
SIDEBAR_WIDTH = 168

_SIDEBAR_STYLE = (
    "QListWidget { border: 0; background: transparent; outline: 0; padding-top: 8px; }"
    "QListWidget::item { padding: 9px 12px; border-radius: 6px; margin: 1px 4px; }"
    "QListWidget::item:selected { background: palette(highlight);"
    " color: palette(highlighted-text); }"
    "QListWidget::item:hover:!selected { background: palette(midlight); }"
)

#: Text shown as the tooltip on a sidebar entry that holds unapplied changes.
DIRTY_TOOLTIP = "This page has changes you have not applied yet — click Apply."


def hairline(*, vertical: bool) -> Any:
    """A 1 px divider in the theme's own ``midlight``, not a drawn ``QFrame`` line.

    A ``Sunken`` ``VLine``/``HLine`` paints a dark and a light line side by side, which on
    the Windows 11 style reads as one heavy 2 px bar. The feature list's row dividers
    already use ``palette(midlight)`` (``app.py``'s ``_ROW_STYLE``), so the frame's own
    edges now match them, in light and in dark.
    """
    from PySide6.QtWidgets import QFrame

    line = QFrame()
    line.setFrameShape(QFrame.Shape.NoFrame)
    line.setStyleSheet("background: palette(midlight);")
    if vertical:
        line.setFixedWidth(1)
    else:
        line.setFixedHeight(1)
    return line


def build_page(spec: PageSpec, content: Any, *, scrollable: bool) -> Any:
    """A page: a heading, a one-line description, then *content*.

    *scrollable* wraps the content in a frameless scroll area. The Features page passes
    ``False`` because it scrolls its own list beside a fixed category column — nesting a
    second scroll area around it is how the list got squeezed into 70 px to begin with.
    """
    from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(16, 12, 16, 8)

    title = QLabel(spec.title)
    title.setStyleSheet("font-size: 15pt; font-weight: 600;")
    title.setAccessibleName(f"{spec.title} page")
    layout.addWidget(title)

    blurb = QLabel(spec.blurb)
    blurb.setWordWrap(True)
    mute_label(blurb, "margin-bottom: 6px;")
    layout.addWidget(blurb)

    if scrollable:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(content)
        layout.addWidget(area, 1)
    else:
        layout.addWidget(content, 1)
    return page


class SettingsShell:
    """Sidebar + stacked pages + footer, laid out inside *central*."""

    def __init__(self, central: Any, win: Any) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence, QShortcut
        from PySide6.QtWidgets import (
            QFrame,
            QHBoxLayout,
            QListWidget,
            QListWidgetItem,
            QStackedWidget,
            QVBoxLayout,
        )

        self._labels = {spec.key: spec.label for spec in PAGES}
        self._index = {spec.key: i for i, spec in enumerate(PAGES)}

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Above the sidebar on purpose: a missing microphone permission matters more than
        # any page, and must not be hidden by the page you happen to be on.
        self.banner_layout = QVBoxLayout()
        self.banner_layout.setContentsMargins(8, 8, 8, 0)
        outer.addLayout(self.banner_layout)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(SIDEBAR_WIDTH)
        self.sidebar.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar.setStyleSheet(_SIDEBAR_STYLE)
        self.sidebar.setAccessibleName("Settings sections")
        self.sidebar.setAccessibleDescription(
            "Choose a page. Ctrl+1 to Ctrl+6 jump to one; Ctrl+F searches the features."
        )
        self.sidebar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for i, spec in enumerate(PAGES, start=1):
            item = QListWidgetItem(spec.label)
            item.setData(Qt.ItemDataRole.UserRole, spec.key)
            item.setToolTip(f"{spec.title} (Ctrl+{i})")
            self.sidebar.addItem(item)
        body.addWidget(self.sidebar)

        self.sidebar_rule = hairline(vertical=True)
        body.addWidget(self.sidebar_rule)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)

        self.footer_rule = hairline(vertical=False)
        outer.addWidget(self.footer_rule)
        self.footer_layout = QVBoxLayout()
        self.footer_layout.setContentsMargins(12, 8, 12, 10)
        outer.addLayout(self.footer_layout)

        # Ctrl+1..6 on the window, not the list: a shortcut on the list works only while
        # the list has focus, which is exactly when you do not need one.
        self._shortcuts = []
        for i, spec in enumerate(PAGES, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i}"), win)
            shortcut.activated.connect(lambda key=spec.key: self.select(key))
            self._shortcuts.append(shortcut)

    def add_page(self, page: Any) -> None:
        """Append a built page; call once per entry of :data:`PAGES`, in order."""
        self.stack.addWidget(page)

    def finish(self) -> None:
        """Open on the first page. Call after every page has been added."""
        if self.banner_layout.count() == 0:
            # No banner: the strip reserved for one would be an 8 px gap above the sidebar
            # and the divider, which then start below the top of the window.
            self.banner_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar.setCurrentRow(0)

    def select(self, key: str) -> None:
        """Show the page *key*; an unknown key is ignored."""
        row = self._index.get(key)
        if row is not None:
            self.sidebar.setCurrentRow(row)

    def current_key(self) -> str:
        item = self.sidebar.currentItem()
        return str(item.data(self._qt_user_role())) if item is not None else ""

    def mark(self, dirty: frozenset[str]) -> None:
        """Show which pages hold unapplied changes. Idempotent, cheap, safe to over-call."""
        for key, row in self._index.items():
            item = self.sidebar.item(row)
            if item is None:
                continue
            is_dirty = key in dirty
            text = page_label(self._labels[key], dirty=is_dirty)
            if item.text() != text:
                item.setText(text)
            tip = DIRTY_TOOLTIP if is_dirty else f"{PAGES[row].title} (Ctrl+{row + 1})"
            if item.toolTip() != tip:
                item.setToolTip(tip)

    @staticmethod
    def _qt_user_role() -> Any:
        from PySide6.QtCore import Qt

        return Qt.ItemDataRole.UserRole
