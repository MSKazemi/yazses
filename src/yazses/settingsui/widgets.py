"""Small Qt building blocks the app pages share. PySide6 is imported inside functions."""
from __future__ import annotations

from typing import Any

from yazses.settingsui.theme import mute_label


def card(*, level: str = "", hero: bool = False) -> tuple[Any, Any]:
    """A rounded panel and its vertical layout.

    It draws a normal styled frame under ``system`` and the theme's card under violet.
    """
    from PySide6.QtWidgets import QFrame, QVBoxLayout

    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    frame.setProperty("card", "true")
    if level:
        frame.setProperty("level", level)
    if hero:
        frame.setProperty("hero", "true")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    return frame, layout


def label(text: str = "", *, muted: bool = False, heading: bool = False) -> Any:
    """A wrapping, selectable label."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    # Plain text: device names, error messages and transcripts must never be markup.
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if heading:
        widget.setStyleSheet("font-size: 12pt; font-weight: 600;")
    if muted:
        mute_label(widget)
    return widget


def button(text: str, on_click: Any = None, *, primary: bool = False) -> Any:
    from PySide6.QtWidgets import QPushButton

    widget = QPushButton(text)
    if primary:
        widget.setProperty("primary", "true")
    if on_click is not None:
        widget.clicked.connect(lambda _checked=False: on_click())
    return widget


def restyle(widget: Any, **properties: str) -> None:
    """Set dynamic properties and re-apply the stylesheet rules that select on them."""
    for name, value in properties.items():
        widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def row(*items: Any, stretch: bool = True) -> Any:
    from PySide6.QtWidgets import QHBoxLayout

    line = QHBoxLayout()
    line.setSpacing(10)
    for item in items:
        line.addWidget(item)
    if stretch:
        line.addStretch(1)
    return line


def page_widget() -> tuple[Any, Any]:
    """The bare container of a page body and its layout."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    return widget, layout


def waveform(bars: int = 48) -> Any:
    """A row of bars drawn in the theme's accent.

    ``push(level)`` adds the newest level (0..1); ``rest()`` flattens it. Purely a
    picture of numbers the daemon reported: it never opens the microphone.
    """
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QPainter, QPalette
    from PySide6.QtWidgets import QSizePolicy, QWidget

    class _Waveform(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.levels = [0.0] * bars
            self.setMinimumHeight(56)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.setAccessibleName("Microphone activity")

        def push(self, level: float) -> None:
            self.levels = [*self.levels[1:], max(0.0, min(1.0, level))]
            self.update()

        def rest(self) -> None:
            if any(self.levels):
                self.levels = [0.0] * bars
                self.update()

        def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt's name
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.palette().color(QPalette.ColorRole.Link))
            slot = self.width() / bars
            width = max(2.0, slot * 0.45)
            middle = self.height() / 2
            for index, level in enumerate(self.levels):
                height = 3 + level * (self.height() - 8)
                painter.drawRoundedRect(
                    QRectF(index * slot, middle - height / 2, width, height), 1.5, 1.5
                )
            painter.end()

    return _Waveform()
