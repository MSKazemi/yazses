"""Qt rendering for the Voice Mouse Grid (ADR-v2-030) — numbered, click-through cells.

Like :mod:`yazses.overlay.widget`, a frameless, translucent, always-on-top tool window that
never takes focus and lets every mouse event through, so a click the grid asks for lands on
the application underneath rather than on the grid. It paints whatever
:class:`~yazses.overlay.grid.GridSnapshot` it is handed; the layout comes from
:func:`~yazses.overlay.grid.grid_cells`, which numbers cells exactly as the daemon does.

Imported only by ``overlay/app.py`` inside ``run()``, and only when ``[mousegrid]`` is on.
Smoke-tested headlessly with ``QT_QPA_PLATFORM=offscreen``.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from yazses.overlay.grid import GridSnapshot, grid_cells


class GridWidget(QWidget):
    """A see-through window over the grid region that draws the numbered cells."""

    def __init__(self, accent: str) -> None:
        super().__init__()
        self._accent = QColor(accent)
        if not self._accent.isValid():
            from yazses.config import OverlayConfig

            self._accent = QColor(OverlayConfig().accent)
        self._snap = GridSnapshot()
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

    def show_grid(self, snap: GridSnapshot) -> None:
        """Draw *snap*; hide the window when it is inactive. Repaints only on change."""
        if not snap.active or snap.region is None:
            self._snap = GridSnapshot()
            if self.isVisible():
                self.hide()
            return
        if snap != self._snap:
            self._snap = snap
            x, y, w, h = snap.region
            self.setGeometry(int(x), int(y), max(1, int(round(w))), max(1, int(round(h))))
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
        snap = self._snap
        if not snap.active or snap.region is None:
            return
        ox, oy = snap.region[0], snap.region[1]
        line = QColor(self._accent)
        line.setAlpha(200)
        pen = QPen(line)
        pen.setWidthF(1.5)
        cells = grid_cells(snap)
        smallest = min(min(c[1][2], c[1][3]) for c in cells) if cells else 0.0
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(8, min(48, int(smallest * 0.35))))
        painter.setFont(font)
        for number, (cx, cy, cw, ch) in cells:
            rect = QRectF(cx - ox, cy - oy, cw, ch)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            # A dark halo under the label keeps it readable on any background.
            painter.setPen(QColor(0, 0, 0, 170))
            painter.drawText(rect.translated(1.0, 1.0), Qt.AlignmentFlag.AlignCenter, str(number))
            painter.setPen(line)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(number))
