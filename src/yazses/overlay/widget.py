"""Qt rendering for the sonar overlay.

This is the only module that touches PySide6. It is deliberately thin: a
frameless, translucent, click-through, always-on-top window that paints whatever
:class:`~yazses.overlay.animation.Ripple` list it is given. All timing and
geometry decisions live in the pure modules; the widget just draws.

Smoke-tested headlessly with ``QT_QPA_PLATFORM=offscreen``.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from yazses.overlay.animation import Ripple


class SonarWidget(QWidget):
    """A borderless glow window that renders expanding sonar rings."""

    def __init__(self, size_px: int, accent: str) -> None:
        super().__init__()
        self._size = size_px
        self._accent = QColor(accent)
        if not self._accent.isValid():
            # The documented default, read from the config dataclass rather than
            # re-typed. A second literal here is a second source of truth: change
            # `[overlay] accent`'s default and this fallback silently keeps the old
            # colour, so a user with a malformed accent sees a different ring from
            # a user with none.
            from yazses.config import OverlayConfig

            self._accent = QColor(OverlayConfig().accent)
        self._ripples: list[Ripple] = []
        self._core_intensity = 0.0

        self.setFixedSize(size_px, size_px)
        # Frameless, floating tool window that never takes focus and always
        # stays on top. ``Tool`` keeps it off the taskbar.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        # Per-pixel transparency (needs a compositor for true see-through) and
        # full click-through so it never interrupts what you're typing into.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def set_ripples(self, ripples: list[Ripple], core_intensity: float) -> None:
        """Replace the rings to draw and the centre-dot brightness; schedule a repaint."""
        self._ripples = ripples
        self._core_intensity = min(1.0, max(0.0, core_intensity))
        self.update()

    def move_to(self, top_left: tuple[int, int]) -> None:
        self.move(top_left[0], top_left[1])

    # -- rendering ----------------------------------------------------------

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        half = self._size / 2.0
        cx = cy = half
        max_radius = half * 0.92

        for ripple in self._ripples:
            radius = ripple.radius_frac * max_radius
            if radius <= 0.5:
                continue
            alpha = int(ripple.alpha * 200)
            color = QColor(self._accent)
            color.setAlpha(max(0, min(255, alpha)))
            pen = QPen(color)
            pen.setWidthF(1.5 + 3.0 * ripple.intensity)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        # Pulsing glow core at the centre — radial gradient that brightens with voice.
        core_r = half * (0.10 + 0.10 * self._core_intensity)
        if core_r > 0.5:
            gradient = QRadialGradient(cx, cy, core_r)
            inner = QColor(self._accent)
            inner.setAlpha(int(120 + 135 * self._core_intensity))
            outer = QColor(self._accent)
            outer.setAlpha(0)
            gradient.setColorAt(0.0, inner)
            gradient.setColorAt(1.0, outer)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))
