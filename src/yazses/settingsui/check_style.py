"""Fusion with a check box that can be seen on the violet themes.

Fusion outlines an unchecked box with a darkened window colour, which on a near-black
window is invisible. This draws the box from the palette instead: an outline in the
secondary text colour, filled in the highlight colour with a tick when checked.
"""
from __future__ import annotations

from typing import Any

STYLE_NAME = "yazses-violet"


def violet_style() -> Any:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QPainter, QPalette, QPen
    from PySide6.QtWidgets import QProxyStyle, QStyle

    class _VioletStyle(QProxyStyle):
        def drawPrimitive(self, element: Any, option: Any, painter: Any,  # noqa: N802
                          widget: Any = None) -> None:
            if element not in (QStyle.PrimitiveElement.PE_IndicatorCheckBox,
                               QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck):
                super().drawPrimitive(element, option, painter, widget)
                return
            state, palette, role = option.state, option.palette, QPalette.ColorRole
            enabled = bool(state & QStyle.StateFlag.State_Enabled)
            on = bool(state & QStyle.StateFlag.State_On)
            focused = bool(state & QStyle.StateFlag.State_HasFocus)
            muted = palette.color(role.PlaceholderText)
            fill = (palette.color(role.Highlight) if enabled else muted) if on else \
                palette.color(role.Base)
            edge = palette.color(role.Text) if focused else (fill if on else muted)
            box = QRectF(option.rect).adjusted(1, 1, -1, -1)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(edge, 2 if focused else 1.4))
            painter.setBrush(fill)
            painter.drawRoundedRect(box, 3.5, 3.5)
            if on:
                tick = QPen(palette.color(role.HighlightedText), 2)
                tick.setCapStyle(Qt.PenCapStyle.RoundCap)
                tick.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(tick)
                x, y, w, h = box.x(), box.y(), box.width(), box.height()
                painter.drawPolyline([
                    QPointF(x + w * 0.22, y + h * 0.52),
                    QPointF(x + w * 0.43, y + h * 0.73),
                    QPointF(x + w * 0.78, y + h * 0.30),
                ])
            painter.restore()

    style = _VioletStyle("Fusion")
    style.setObjectName(STYLE_NAME)
    return style
