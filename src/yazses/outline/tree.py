"""Outline op-application + rendering (pure) — ADR-v2-124.

An outline is a flat list of (level, text, collapsed) items plus a cursor. Every op returns a NEW
state; rendering emits Markdown bullets or OPML. Pure and deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class OutlineItem:
    text: str
    level: int = 0
    collapsed: bool = False


def new_outline() -> dict:
    """Empty outline state: no items, no cursor. Pure."""
    return {"items": [], "cursor": -1}


def apply_outline_op(state: dict, op: str, text: str = "") -> dict:
    """Apply a spoken outline op → a NEW state (input never mutated). Unknown ops are no-ops. Pure.

    Ops: ``add`` (new item after the cursor, same level), ``indent`` (max one deeper than the
    previous item), ``promote`` (one shallower, floor 0), ``collapse``/``expand``, ``up``/``down``.
    """
    items = list(state.get("items", []))
    cur = state.get("cursor", -1)
    verb = (op or "").strip().lower()
    if verb == "add" and text:
        level = items[cur].level if 0 <= cur < len(items) else 0
        items.insert(cur + 1, OutlineItem(text, level))
        return {"items": items, "cursor": cur + 1}
    if not (0 <= cur < len(items)):
        return {"items": items, "cursor": cur}
    if verb == "indent":
        cap = items[cur - 1].level + 1 if cur > 0 else 0
        items[cur] = replace(items[cur], level=min(items[cur].level + 1, cap))
    elif verb == "promote":
        items[cur] = replace(items[cur], level=max(items[cur].level - 1, 0))
    elif verb == "collapse":
        items[cur] = replace(items[cur], collapsed=True)
    elif verb == "expand":
        items[cur] = replace(items[cur], collapsed=False)
    elif verb == "up":
        cur = max(cur - 1, 0)
    elif verb == "down":
        cur = min(cur + 1, len(items) - 1)
    return {"items": items, "cursor": cur}


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render(state: dict, fmt: str = "markdown") -> str:
    """Render the outline → Markdown bullets (collapsed subtrees hidden) or OPML (full). Pure."""
    items = state.get("items", [])
    if fmt == "opml":
        out = ['<opml version="2.0"><body>']
        stack: list[int] = []
        for item in items:
            while stack and stack[-1] >= item.level:
                out.append("</outline>")
                stack.pop()
            out.append(f'<outline text="{_escape(item.text)}">')
            stack.append(item.level)
        out.extend("</outline>" for _ in stack)
        out.append("</body></opml>")
        return "".join(out)
    lines = []
    hide_deeper: int | None = None
    for item in items:
        if hide_deeper is not None and item.level > hide_deeper:
            continue
        hide_deeper = item.level if item.collapsed else None
        lines.append("  " * item.level + "- " + item.text)
    return "\n".join(lines)
