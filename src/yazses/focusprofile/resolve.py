"""Focus classification + profile resolution (pure) — ADR-v2-094.

Map a focused window's class/title to a dictation grammar profile. Pure and deterministic; the
platform layer supplies the window title/class.
"""
from __future__ import annotations

_CLASS_KEYWORDS = {
    "terminal": ("term", "konsole", "alacritty", "kitty", "tmux", "xterm", "wezterm", "foot", "iterm"),
    "editor": ("code", "vim", "nvim", "emacs", "sublime", "jetbrains", "idea", "pycharm", "gedit",
               "kate", "zed"),
    "browser": ("firefox", "chrome", "chromium", "brave", "edge", "safari", "vivaldi"),
    "chat": ("slack", "discord", "telegram", "signal", "teams", "element", "matrix"),
    "office": ("libreoffice", "word", "excel", "writer", "calc", "onlyoffice", "wps"),
}
_CLASS_PROFILE = {
    "terminal": "shell",
    "editor": "code",
    "browser": "prose",
    "chat": "prose",
    "office": "prose",
}


def classify_focus(app_class: str) -> str:
    """Return a coarse focus class from an app/window class string. Pure."""
    a = (app_class or "").lower()
    for cls, keys in _CLASS_KEYWORDS.items():
        if any(k in a for k in keys):
            return cls
    return "unknown"


def resolve_profile(window_title: str, app_class: str, rules=None):
    """Resolve the dictation profile for a focused window, or ``None``. Pure.

    ``rules`` (an iterable of ``(substring, profile)``) win over the per-class default; matching is
    case-insensitive against ``"<app_class> <window_title>"``.
    """
    hay = f"{app_class or ''} {window_title or ''}".lower()
    for pattern, profile in (rules or ()):
        if pattern and pattern.lower() in hay:
            return profile
    return _CLASS_PROFILE.get(classify_focus(app_class))
