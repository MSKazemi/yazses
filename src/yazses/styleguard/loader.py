"""Style-rules file loading (ADR-v2-109) — config-driven rules source.

Reads a user ``style-rules.toml`` (sibling of ``config.toml`` by default) of
``preferred`` → ``variants`` entries and turns it into the flat ``pattern``/
``replacement`` rules the pure core in :mod:`yazses.styleguard.rules` applies.
Impure (filesystem + parsing); the core stays pure.

Every rule that survives loading is one this file has already **proved usable** —
its types are right and, when ``regex`` is set, its pattern compiles. That matters
because the rules are applied inside the dictation hot path: a rule that only
fails at ``re.sub`` time would throw away the burst the user just spoke, once per
burst, with nothing but a log line to explain it. Rejecting it here costs one
warning at startup and keeps every other rule working (cf. the config loader's
"repair what you can, name what you dropped" contract, issue #52).
"""
from __future__ import annotations

import logging
import re
import tomllib
from pathlib import Path

from yazses import tomlio
from yazses.styleguard.rules import Rule, load_stylerules

log = logging.getLogger(__name__)


def _usable(item: dict) -> bool:
    """Is this rule safe to hand to ``apply_style`` on the dictation path?

    Rejects what would otherwise raise per-burst: a non-string pattern or
    replacement (``re.escape``/``re.sub`` want ``str``) and a ``regex`` pattern
    that does not compile.
    """
    pattern, replacement = item["pattern"], item["replacement"]
    if not isinstance(pattern, str) or not isinstance(replacement, str):
        log.warning(
            "skipping style rule %r -> %r: both must be strings", pattern, replacement
        )
        return False
    if item["regex"]:
        try:
            re.compile(pattern)
        except re.error as exc:
            log.warning("skipping style rule with an invalid regex %r: %s", pattern, exc)
            return False
    return True


def load_rules_file(path: Path | str | None) -> list[Rule]:
    """Load a style-rules.toml into a flat list of :class:`Rule`.

    A missing file yields no rules. A bad entry is skipped (logged), never raised
    — a broken style sheet must not break the daemon, and must not cost the user
    the rules that *are* valid. An unparseable file yields no rules plus one
    logged error.
    """
    if path is None:
        return []
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = tomlio.read(p)
    except (tomllib.TOMLDecodeError, OSError, ValueError) as exc:
        log.error("could not parse style-rules file %s: %s", p, exc)
        return []

    entries = data.get("rule", [])
    if not isinstance(entries, list):
        # `rule = "…"` instead of `[[rule]]` — a plausible hand-editing slip, and one
        # that used to propagate out of the daemon's constructor and stop it starting.
        log.error(
            "style-rules file %s: `rule` must be a list of [[rule]] tables, got %s",
            p, type(entries).__name__,
        )
        return []

    items = []
    for entry in entries:
        if not isinstance(entry, dict):
            log.warning("skipping invalid style rule entry: %r", entry)
            continue
        preferred = entry.get("preferred", "")
        variants = entry.get("variants", [])
        if not preferred or not isinstance(variants, list) or not variants:
            log.warning("skipping invalid style rule entry: %r", entry)
            continue
        for variant in variants:
            if not variant:
                continue
            item = {
                "pattern": variant,
                "replacement": preferred,
                "ignore_case": bool(entry.get("ignore_case", True)),
                "regex": bool(entry.get("regex", False)),
            }
            if _usable(item):
                items.append(item)
    return load_stylerules(items)


def build_style_rules(config, config_dir: Path | str) -> list[Rule] | None:
    """Return the loaded rules, or ``None`` when ``[styleguard]`` is disabled.

    Called from the daemon's constructor, so it never raises: a style sheet the
    user mistyped degrades to "no rules", never to a daemon that won't start.
    """
    sg = config.styleguard
    if not sg.enabled:
        return None
    try:
        p = Path(sg.path)
        if not p.is_absolute():
            p = Path(config_dir) / p
        return load_rules_file(p)
    except Exception:  # noqa: BLE001 — a style sheet must never block startup
        log.exception("could not load style rules from %r; continuing without them", sg.path)
        return []
