"""Spoken structure → Markdown/org markup (pure) — ADR-v2-067.

Parse an explicit "list:"/"table columns…" utterance into a :class:`Structure`, then render it as
Markdown (default) or org. Deterministic and dependency-free; free-form structure is deferred.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_BULLET = re.compile(r"^(?:bullet(?:ed)?|bulleted)\s+list[:\-]?\s*(.+)$", re.IGNORECASE)
_NUMBERED = re.compile(r"^(?:numbered|ordered)\s+list[:\-]?\s*(.+)$", re.IGNORECASE)
_CHECK = re.compile(r"^(?:check(?:list)?|todo|task)\s+list[:\-]?\s*(.+)$", re.IGNORECASE)
_TABLE = re.compile(r"^table\s+columns?\s+(.+)$", re.IGNORECASE)


def _split_items(blob: str) -> tuple:
    parts = re.split(r"\s*;\s*|\s*,\s*", blob.strip())
    # keep only parts with real content (drops a stray separator like a bare ":")
    return tuple(p.strip() for p in parts if any(ch.isalnum() for ch in p))


@dataclass
class Structure:
    """A parsed document structure: bullets / numbered / checklist / table."""
    kind: str
    items: tuple = ()
    columns: tuple = ()
    rows: tuple = field(default_factory=tuple)


def parse_structure(text: str):
    """Parse a spoken structure intent into a :class:`Structure`, or ``None``. Pure."""
    t = (text or "").strip()
    for kind, pat in (("bullets", _BULLET), ("numbered", _NUMBERED), ("checklist", _CHECK)):
        m = pat.match(t)
        if m:
            items = _split_items(m.group(1))
            return Structure(kind, items=items) if items else None

    m = _TABLE.match(t)
    if m:
        # "Name, Age; row Alice, 30; row Bob, 25"  →  columns + rows
        segments = re.split(r"\s*;\s*", m.group(1).strip())
        columns = _split_items(segments[0])
        rows = []
        for seg in segments[1:]:
            seg = re.sub(r"^rows?\s+", "", seg.strip(), flags=re.IGNORECASE)
            cells = _split_items(seg)
            if cells:
                rows.append(cells)
        return Structure("table", columns=columns, rows=tuple(rows)) if columns else None
    return None


def render_markup(struct: Structure, flavor: str = "markdown") -> str:
    """Render a :class:`Structure` as Markdown (default) or org markup. Pure."""
    if struct.kind == "bullets":
        return "\n".join(f"- {it}" for it in struct.items)
    if struct.kind == "numbered":
        return "\n".join(f"{i}. {it}" for i, it in enumerate(struct.items, 1))
    if struct.kind == "checklist":
        box = "[ ]" if flavor == "markdown" else "[ ]"
        return "\n".join(f"- {box} {it}" for it in struct.items)
    # table
    cols = list(struct.columns)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [header, sep]
    for row in struct.rows:
        cells = list(row) + [""] * (len(cols) - len(row))
        lines.append("| " + " | ".join(cells[:len(cols)]) + " |")
    return "\n".join(lines)


def spoken_to_markup(text: str, flavor: str = "markdown"):
    """Convenience: parse then render, or ``None`` if nothing parses. Pure."""
    struct = parse_structure(text)
    return render_markup(struct, flavor) if struct else None
