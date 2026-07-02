"""Spoken row parsing + delimited output + cadence plan (pure) — ADR-v2-091.

Turn "row: Ada, 1815, London" into cells, delimited lines, or a Tab/Enter injection plan. Pure and
deterministic; the injector executes the plan.
"""
from __future__ import annotations

import re

_ROW_MARK = re.compile(r"^\s*(?:row|entry|record)\s*[:\-]?\s*", re.IGNORECASE)
_CELL_SPLIT = re.compile(r"\s*[,;]\s*|\s+and\s+")
_ROW_SPLIT = re.compile(r"\bnext\s+row\b|\n", re.IGNORECASE)


def parse_row(text: str):
    """Split one spoken row into cell strings (leading "row:" marker stripped). Pure."""
    body = _ROW_MARK.sub("", text or "")
    return [c.strip() for c in _CELL_SPLIT.split(body) if c.strip()]


def rows_to_delimited(text: str, sep: str = ","):
    """Split multi-row spoken text into delimited lines (one per row). Pure."""
    lines = []
    for chunk in _ROW_SPLIT.split(text or ""):
        cells = parse_row(chunk)
        if cells:
            lines.append(sep.join(cells))
    return lines


def row_plan(cells, cell_key: str = "Tab", row_end: str = "Return"):
    """Emit an injection plan for one row: type each cell, Tab between, Enter after. Pure.

    Returns a list of ``("type", text)`` / ``("key", keyname)`` steps.
    """
    plan = []
    for i, cell in enumerate(cells or ()):
        if i:
            plan.append(("key", cell_key))
        plan.append(("type", cell))
    if plan:
        plan.append(("key", row_end))
    return plan
