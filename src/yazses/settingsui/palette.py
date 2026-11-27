"""The window's colour themes, as data. Pure: no Qt, no I/O.

``violet-dark`` (the default) and ``violet-light`` are the app design's two themes;
``system`` applies nothing, so the window keeps whatever the desktop supplies. Every text
colour is checked against every surface at WCAG AA in
``tests/test_settingsui_palette.py``, so a new shade cannot quietly become unreadable.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_THEME = "violet-dark"
THEMES: tuple[str, ...] = ("violet-dark", "violet-light", "system")

#: ``(label, value)`` for the picker, in the order of :data:`THEMES`.
THEME_CHOICES: tuple[tuple[str, str], ...] = (
    ("Dark violet", "violet-dark"),
    ("Light violet", "violet-light"),
    ("Match my desktop", "system"),
)


@dataclass(frozen=True)
class Palette:
    bg: str
    side: str
    card: str
    card2: str
    line: str
    #: The edge of a field you type or pick in: 3:1 against what is behind it.
    control: str
    text: str
    muted: str
    accent: str
    primary: str
    on_primary: str
    ok: str
    warn: str
    bad: str


_PALETTES: dict[str, Palette] = {
    "violet-dark": Palette(
        bg="#0f0d1a", side="#131120", card="#1a1729", card2="#221e36", line="#363052",
        control="#6f679c",
        text="#f4f1ff", muted="#aca5c8", accent="#b184ff", primary="#6d3fd9",
        on_primary="#ffffff", ok="#5ee08b", warn="#ffd36b", bad="#ff8f9e",
    ),
    "violet-light": Palette(
        bg="#f6f4fc", side="#ffffff", card="#ffffff", card2="#f3f0fb", line="#ddd7ee",
        control="#857bb0",
        text="#1c1733", muted="#575073", accent="#6531c9", primary="#6d3fd9",
        on_primary="#ffffff", ok="#13692f", warn="#744a00", bad="#a81c30",
    ),
}


def normalise_theme(value: object) -> str:
    """*value* when it names a theme, else the default. Never raises."""
    return value if isinstance(value, str) and value in THEMES else DEFAULT_THEME


def palette_for(theme: object) -> Palette | None:
    """The colours for *theme*; ``None`` for ``system``, meaning "paint nothing"."""
    return _PALETTES.get(normalise_theme(theme))


def window_stylesheet(colours: Palette | None) -> str:
    """The rules a palette cannot express: cards, buttons, badges and the sidebar.

    Widgets opt in with a dynamic property (``card``, ``primary``, ``hero``, ``level``),
    so a widget that sets none of them is drawn by the style from the palette alone.
    """
    if colours is None:
        return ""
    c = colours
    return f"""
QFrame[card="true"] {{ background: {c.card}; border: 1px solid {c.line}; border-radius: 14px; }}
QFrame[card="true"][level="warn"] {{ border: 2px solid {c.warn}; }}
QFrame[card="true"][level="bad"] {{ border: 2px solid {c.bad}; }}
QFrame[card="true"][hero="true"] {{ border: 1px solid {c.primary}; }}
QFrame[card="true"] QLabel, QFrame[card="true"] QCheckBox {{ background: transparent; }}
QLabel[level="ok"] {{ color: {c.ok}; }}
QLabel[level="warn"] {{ color: {c.warn}; }}
QLabel[level="bad"] {{ color: {c.bad}; }}
QLabel[keycap="true"] {{ background: {c.card2}; border: 2px solid {c.accent};
    border-radius: 12px; padding: 10px 26px; font-size: 18pt; font-weight: 700; }}
QPushButton {{ background: {c.card2}; color: {c.text}; border: 1px solid {c.line};
    border-radius: 8px; padding: 7px 16px; }}
QPushButton:hover {{ border-color: {c.accent}; }}
QPushButton:focus {{ border: 2px solid {c.text}; }}
QPushButton:disabled {{ color: {c.muted}; }}
QPushButton[primary="true"] {{ background: {c.primary}; color: {c.on_primary};
    border-color: {c.primary}; font-weight: 600; }}
QPushButton[primary="true"]:focus {{ border: 2px solid {c.text}; }}
QPushButton[primary="true"]:disabled {{ background: {c.card2}; color: {c.muted}; }}
QLineEdit {{ background: {c.card}; color: {c.text}; border: 1px solid {c.control};
    border-radius: 7px; padding: 5px 8px; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 2px solid {c.accent}; }}
QPlainTextEdit, QTextBrowser, QListWidget#yzList {{ background: {c.card}; color: {c.text};
    border: 1px solid {c.control}; border-radius: 10px; padding: 6px; }}
/* The sidebar draws its own focus ring; this drops the style's second, inner one. */
QListWidget#yzSidebar {{ background: {c.side}; outline: 0; }}
QProgressBar {{ background: {c.card2}; border: 0; border-radius: 5px; max-height: 10px; }}
QProgressBar::chunk {{ background: {c.accent}; border-radius: 5px; }}
""".strip()
