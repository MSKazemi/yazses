"""Smart-paste surface classification + format policy (pure) — ADR-v2-036.

Classify the target surface from local window/role hints and adapt injected text syntax to
it. Pure and deterministic; the window metadata comes from the existing introspection path.
"""
from __future__ import annotations

import re

_TERMINAL = ("terminal", "konsole", "xterm", "alacritty", "kitty", "gnome-terminal", "tmux")
_CODE = ("code", "vscode", "vim", "nvim", "emacs", "sublime", "intellij", "pycharm", "goland")
_EMAIL = ("mail", "thunderbird", "outlook", "gmail", "geary", "evolution")
_MARKDOWN = ("obsidian", "typora", "logseq", "markdown", "joplin", "zettlr")


def classify_surface(app_hint: str, role_hint: str = "") -> str:
    """Map window/role hints to a surface label. Pure.

    Returns one of ``terminal|code|email|markdown|rich|plain`` — the most specific match on
    the app hint wins, then the role hint, else ``plain``.
    """
    a = (app_hint or "").lower()
    r = (role_hint or "").lower()
    if any(k in a for k in _TERMINAL):
        return "terminal"
    if any(k in a for k in _CODE):
        return "code"
    if any(k in a for k in _EMAIL):
        return "email"
    if any(k in a for k in _MARKDOWN):
        return "markdown"
    if "terminal" in r:
        return "terminal"
    if "document" in r or "rich" in r:
        return "rich"
    return "plain"


def adapt(text: str, surface: str) -> str:
    """Adapt ``text`` syntax to ``surface``. Pure.

    - ``markdown``/``rich``: normalize a leading ``•``/``*`` bullet to ``- `` and autolink a
      bare URL (``<url>``).
    - ``code``/``terminal``/``email``/``plain``: returned unchanged (no prose rewriting).
    """
    if not text:
        return text
    if surface in ("markdown", "rich"):
        out = re.sub(r"^(\s*)[•*]\s+", r"\1- ", text)
        out = re.sub(r"(?<![<(])\b(https?://\S+)", r"<\1>", out)
        return out
    return text
