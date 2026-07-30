"""Persistent outline state (JSON file) — ADR-v2-124.

A durable outline (flat ``[(level, text, collapsed)]`` + cursor) stored next to
``config.toml`` as ``outline.json``, so ``yazses outline`` builds an outline
incrementally across invocations (the ``outline.tree`` ops are otherwise pure state with
no runtime entry point). (De)serialises :class:`~yazses.outline.tree.OutlineItem`. Pure
filesystem/logic — unit-testable with ``tmp_path``.
"""
from __future__ import annotations

import json
from pathlib import Path

from yazses.outline.tree import OutlineItem, new_outline


def outline_path(config_dir) -> Path:
    return Path(config_dir) / "outline.json"


def _to_json(state: dict) -> dict:
    return {
        "items": [
            {"text": it.text, "level": it.level, "collapsed": it.collapsed}
            for it in state.get("items", [])
        ],
        "cursor": int(state.get("cursor", -1)),
    }


def _from_json(data: dict) -> dict:
    items = [
        OutlineItem(str(d.get("text", "")), int(d.get("level", 0)), bool(d.get("collapsed", False)))
        for d in data.get("items", [])
        if isinstance(d, dict)
    ]
    return {"items": items, "cursor": int(data.get("cursor", -1))}


def load_outline(path) -> dict:
    """Load the outline state, or an empty one if absent/unreadable."""
    p = Path(path)
    if not p.exists():
        return new_outline()
    try:
        return _from_json(json.loads(p.read_text(encoding="utf-8")))
    except (ValueError, OSError, TypeError, KeyError):
        return new_outline()


def save_outline(path, state: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_to_json(state), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
