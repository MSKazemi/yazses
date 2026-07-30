"""Persistent clipboard history (JSON file) — ADR-v2-060.

A durable, newest-first clipboard ring stored next to ``config.toml`` as
``cliphistory.json``, so ``yazses cliphistory`` accumulates and recalls across
invocations (the ``ClipboardRing`` core is otherwise in-memory with no runtime entry
point). Reuses ``ClipboardRing`` for the dedup/cap semantics. Pure filesystem/logic —
unit-testable with ``tmp_path``.
"""
from __future__ import annotations

import json
from pathlib import Path

from yazses.cliphistory.history import ClipboardRing

DEFAULT_CAPACITY = 20


def cliphistory_path(config_dir) -> Path:
    return Path(config_dir) / "cliphistory.json"


def load_items(path) -> list[str]:
    """Return the history, newest first (empty if absent/unreadable)."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


def _save(path, items: list[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_item(path, text: str, capacity: int = DEFAULT_CAPACITY) -> list[str]:
    """Record a copied string (dedup/cap via :class:`ClipboardRing`); return newest-first."""
    ring = ClipboardRing(capacity)
    for it in reversed(load_items(path)):  # replay oldest→newest so order is preserved
        ring.add(it)
    ring.add(text)
    items = ring.items()
    _save(path, items)
    return items
