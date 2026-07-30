"""Persistent acronym glossary (JSON file) — ADR-v2-114.

A durable ``{ACR: full name}`` map stored next to ``config.toml`` as ``acronyms.json``,
so the acronym glossary (previously an in-memory ``AcronymState`` with no runtime entry
point) survives across invocations. Managed with ``yazses acronyms add/list/remove/expand``.
Pure filesystem/logic — unit-testable with ``tmp_path``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def glossary_path(config_dir) -> Path:
    return Path(config_dir) / "acronyms.json"


def _key(acr: str) -> str:
    """Canonical acronym key: strip spaces/hyphens, upper-case."""
    return re.sub(r"[\s\-]", "", (acr or "")).upper()


def load_glossary(path) -> dict:
    """Return the stored ``{ACR: full}`` map (empty if absent/unreadable)."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _write(path, glossary: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(dict(sorted(glossary.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def add_entry(path, acr: str, full: str) -> dict:
    """Register ``acr`` → ``full`` (acronym normalised); returns the full glossary."""
    acr = _key(acr)
    full = (full or "").strip()
    if not acr or not full:
        raise ValueError("both an acronym and its full form are required")
    glossary = load_glossary(path)
    glossary[acr] = full
    _write(path, glossary)
    return glossary


def remove_entry(path, acr: str) -> dict:
    """Remove ``acr`` (case-insensitive); returns the remaining glossary."""
    glossary = load_glossary(path)
    glossary.pop(_key(acr), None)
    _write(path, glossary)
    return glossary
