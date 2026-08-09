"""Style-rules file loading (ADR-v2-109) — config-driven rules source.

Reads a user ``style-rules.toml`` (sibling of ``config.toml`` by default) of
``preferred`` → ``variants`` entries and turns it into the flat ``pattern``/
``replacement`` rules the pure core in :mod:`yazses.styleguard.rules` applies.
Impure (filesystem + parsing); the core stays pure.
"""
from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from yazses.styleguard.rules import Rule, load_stylerules

log = logging.getLogger(__name__)


def load_rules_file(path: Path | str | None) -> list[Rule]:
    """Load a style-rules.toml into a flat list of :class:`Rule`.

    A missing file yields no rules. A single bad entry is skipped (logged),
    never raised — a broken style sheet must not break the daemon. An
    unparseable file yields no rules plus one logged error.
    """
    if path is None:
        return []
    p = Path(path)
    if not p.exists():
        return []
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        log.error("could not parse style-rules file %s: %s", p, exc)
        return []

    items = []
    for entry in data.get("rule", []):
        preferred = entry.get("preferred", "")
        variants = entry.get("variants", [])
        if not preferred or not isinstance(variants, list) or not variants:
            log.warning("skipping invalid style rule entry: %r", entry)
            continue
        for variant in variants:
            if not variant:
                continue
            items.append({
                "pattern": variant,
                "replacement": preferred,
                "ignore_case": bool(entry.get("ignore_case", True)),
                "regex": bool(entry.get("regex", False)),
            })
    return load_stylerules(items)


def build_style_rules(config, config_dir: Path | str) -> list[Rule] | None:
    """Return the loaded rules, or ``None`` when ``[styleguard]`` is disabled."""
    sg = config.styleguard
    if not sg.enabled:
        return None
    p = Path(sg.path)
    if not p.is_absolute():
        p = Path(config_dir) / p
    return load_rules_file(p)
