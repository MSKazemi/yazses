"""Paint the window with a theme from ``palette.py``; ``system`` puts the desktop's back."""
from __future__ import annotations

from typing import Any

from yazses.settingsui.palette import Palette, palette_for, window_stylesheet
from yazses.settingsui.theme import MUTED_PROPERTY, muted_stylesheet, palette_colors

#: The application attributes holding what to restore for ``system``.
_SAVED = "_yazses_system_look"


def _qpalette(colours: Palette) -> Any:
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    role = QPalette.ColorRole
    for roles, value in (
        ((role.Window,), colours.bg),
        ((role.Base,), colours.card),
        ((role.AlternateBase, role.Button, role.ToolTipBase), colours.card2),
        ((role.WindowText, role.Text, role.ButtonText, role.ToolTipText), colours.text),
        ((role.Midlight, role.Mid), colours.line),
        ((role.Highlight,), colours.primary),
        ((role.HighlightedText, role.BrightText), colours.on_primary),
        ((role.Link, role.LinkVisited), colours.accent),
        ((role.PlaceholderText,), colours.muted),
    ):
        for one in roles:
            palette.setColor(one, QColor(value))
    for one in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, one, QColor(colours.muted))
    return palette


def _remute(window: Any) -> None:
    """Recompute secondary-text colours, which were derived from the previous palette."""
    from PySide6.QtWidgets import QApplication, QLabel

    class _App:
        def palette(self) -> Any:
            return QApplication.palette()

    text, background = palette_colors(_App())
    for widget in window.findChildren(QLabel):
        extra = widget.property(MUTED_PROPERTY)
        if extra is not None:
            widget.setStyleSheet(muted_stylesheet(text, background, str(extra)))


def apply_theme(app: Any, window: Any, theme: object) -> None:
    """Apply *theme* to *app*, and to *window* when there already is one."""
    from PySide6.QtGui import QPalette

    from yazses.settingsui.check_style import STYLE_NAME, violet_style

    saved = getattr(app, _SAVED, None)
    if saved is None:
        saved = (QPalette(app.palette()), app.style().objectName())
        setattr(app, _SAVED, saved)

    colours = palette_for(theme)
    if colours is None:
        palette, style = saved
        if app.style().objectName() == STYLE_NAME:
            app.setStyle(style or "Fusion")
        app.setPalette(palette)
    else:
        # Fusion honours every palette role; native styles ignore several.
        if app.style().objectName() != STYLE_NAME:
            app.setStyle(violet_style())
        app.setPalette(_qpalette(colours))
    if window is not None:
        window.setStyleSheet(window_stylesheet(colours))
        _remute(window)
