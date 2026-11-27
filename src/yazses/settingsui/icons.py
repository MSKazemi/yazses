"""The sidebar's line icons and the brand mark, drawn with ``QPainter``.

Drawn rather than shipped as files: no asset to package into the frozen builds, and each
icon takes its colour from the palette at paint time, so a theme change needs no redraw.
The geometry is plain data on a 24 by 24 grid.
"""
from __future__ import annotations

from typing import Any

Point = tuple[float, float]
#: ``("line", points)`` is a polyline; ``("circle", (cx, cy, r))`` an outline.
Shape = tuple[str, Any]

ICONS: dict[str, tuple[Shape, ...]] = {
    "overview": (("line", ((3, 11), (12, 3), (21, 11))),
                 ("line", ((5, 10), (5, 21), (19, 21), (19, 10)))),
    "dictation": (("line", ((9, 5), (12, 3), (15, 5), (15, 12), (12, 14), (9, 12), (9, 5))),
                  ("line", ((5, 11), (7, 16), (12, 18), (17, 16), (19, 11))),
                  ("line", ((12, 18), (12, 21)))),
    "meetings": (("circle", (9, 8, 3.5)), ("line", ((2, 20), (4, 15), (9, 14), (14, 15), (16, 20))),
                 ("circle", (17, 8, 2.5)), ("line", ((17, 14), (21, 16), (22, 19)))),
    "files": (("line", ((6, 3), (14, 3), (19, 8), (19, 21), (6, 21), (6, 3))),
              ("line", ((9, 13), (16, 13))), ("line", ((9, 17), (16, 17)))),
    "commands": (("line", ((4, 6), (10, 12), (4, 18))), ("line", ((12, 19), (20, 19)))),
    "features": (("line", ((4, 4), (10, 4), (10, 10), (4, 10), (4, 4))),
                 ("line", ((14, 4), (20, 4), (20, 10), (14, 10), (14, 4))),
                 ("line", ((4, 14), (10, 14), (10, 20), (4, 20), (4, 14))),
                 ("line", ((14, 14), (20, 14), (20, 20), (14, 20), (14, 14)))),
    "accessibility": (("circle", (12, 12, 10)), ("circle", (12, 7, 0.8)),
                      ("line", ((7, 10), (12, 11), (17, 10))),
                      ("line", ((9, 18), (12, 13), (15, 18))), ("line", ((12, 11), (12, 13)))),
    "speech": (("line", ((12, 3), (21, 8), (12, 13), (3, 8), (12, 3))),
               ("line", ((3, 12), (12, 17), (21, 12))), ("line", ((3, 16), (12, 21), (21, 16)))),
    "audio": (("line", ((3, 10), (3, 14))), ("line", ((7.5, 7), (7.5, 17))),
              ("line", ((12, 3), (12, 21))), ("line", ((16.5, 7), (16.5, 17))),
              ("line", ((21, 10), (21, 14)))),
    "general": (("line", ((3, 7), (21, 7))), ("circle", (9, 7, 2.5)),
                ("line", ((3, 17), (21, 17))), ("circle", (15, 17, 2.5))),
    "handsfree": (("circle", (12, 12, 9)), ("circle", (12, 12, 3))),
    "updates": (("line", ((12, 3), (12, 15))), ("line", ((7, 10), (12, 15), (17, 10))),
                ("line", ((4, 20), (20, 20)))),
}


def _draw(painter: Any, shapes: tuple[Shape, ...]) -> None:
    from PySide6.QtCore import QPointF

    for kind, data in shapes:
        if kind == "line":
            painter.drawPolyline([QPointF(x, y) for x, y in data])
        else:
            x, y, radius = data
            painter.drawEllipse(QPointF(x, y), radius, radius)


def sidebar_icon(key: str) -> Any:
    """The icon for the page *key*, or an empty icon for a page without one."""
    from PySide6.QtCore import QRect, QRectF, Qt
    from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPalette, QPen, QPixmap
    from PySide6.QtWidgets import QApplication

    if key not in ICONS:
        return QIcon()
    shapes: tuple[Shape, ...] = ICONS[key]

    class _Engine(QIconEngine):
        def paint(self, painter: Any, rect: Any, mode: Any, state: Any) -> None:
            role = (QPalette.ColorRole.HighlightedText if mode == QIcon.Mode.Selected
                    else QPalette.ColorRole.WindowText)
            pen = QPen(QApplication.palette().color(role), 1.7)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            area = QRectF(rect)
            painter.translate(area.topLeft())
            painter.scale(area.width() / 24, area.height() / 24)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            _draw(painter, shapes)
            painter.restore()

        def pixmap(self, size: Any, mode: Any, state: Any) -> Any:
            canvas = QPixmap(size)
            canvas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(canvas)
            self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
            painter.end()
            return canvas

        def clone(self) -> Any:
            return _Engine()

    return QIcon(_Engine())


def brand_mark(size: int = 40) -> Any:
    """A label showing the YazSes mark: a "Y" over a listening wave on a violet badge."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import QLabel

    scale = 2  # drawn at twice the size so it stays sharp on a high-density screen
    canvas = QPixmap(size * scale, size * scale)
    canvas.setDevicePixelRatio(scale)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 52, size / 52)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#6d3fd9"))
    painter.drawRoundedRect(QRectF(0, 0, 52, 52), 12, 12)
    pen = QPen(QColor("#ffffff"), 4.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawPolyline([QPointF(16, 11), QPointF(26, 23), QPointF(36, 11)])
    painter.drawLine(QPointF(26, 23), QPointF(26, 30))
    pen.setWidthF(2.2)
    painter.setPen(pen)
    for x, half in ((12, 1), (17, 3), (22, 5), (26, 6), (30, 5), (35, 3), (40, 1)):
        painter.drawLine(QPointF(x, 41 - half), QPointF(x, 41 + half))
    painter.end()
    widget = QLabel()
    widget.setPixmap(canvas)
    widget.setAccessibleName("YazSes")
    return widget
