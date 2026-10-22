"""Qt rendering for the Mouth-Sound Switch scan strip (ADR-v2-097) — click-through cells.

Like :mod:`yazses.overlay.grid_widget`, a frameless, translucent, always-on-top tool window
that never takes focus and lets every mouse event through, so a "Click" the scan selects
lands on the application underneath rather than on the strip. It paints whatever
:func:`~yazses.overlay.scanstrip.strip_layout` returns: one cell per item, the lit one filled
with the accent colour.

Imported only by ``overlay/app.py`` inside ``run()``, and only when ``[mouthswitch]`` is on.
Smoke-tested headlessly with ``QT_QPA_PLATFORM=offscreen``.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from yazses.overlay.scanstrip import StripLayout, strip_layout


class ScanWidget(QWidget):
    """A see-through strip at the top of the screen that shows the scan and its highlight."""

    def __init__(self, accent: str) -> None:
        super().__init__()
        self._accent = QColor(accent)
        if not self._accent.isValid():
            from yazses.config import OverlayConfig

            self._accent = QColor(OverlayConfig().accent)
        self._layout: StripLayout | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def show_scan(
        self, labels: tuple[str, ...], index: int, screen: tuple[int, int, int, int]
    ) -> None:
        """Draw the strip with ``index`` lit; hide the window when no scan runs."""
        layout = strip_layout(labels, index, screen)
        if layout is None:
            self._layout = None
            if self.isVisible():
                self.hide()
            return
        if layout != self._layout:
            self._layout = layout
            x, y, w, h = layout.window
            self.setGeometry(x, y, w, h)
            self.update()
        if not self.isVisible():
            self.show()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        layout = self._layout
        if layout is None:
            return
        font = QFont()
        font.setBold(True)
        font.setPixelSize(22)
        painter.setFont(font)
        for label, (x, y, w, h), lit in layout.cells:
            rect = QRectF(x, y, w, h)
            fill = QColor(self._accent) if lit else QColor(0, 0, 0, 170)
            if lit:
                fill.setAlpha(235)
            pen = QPen(QColor(self._accent))
            pen.setWidthF(4.0 if lit else 1.5)
            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 10.0, 10.0)
            # Dark text on the lit cell, light text on the rest: readable either way.
            painter.setPen(QColor(0, 0, 0) if lit else QColor(255, 255, 255))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label.capitalize())
