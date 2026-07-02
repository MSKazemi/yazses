"""Style-rule loading + application (pure) — ADR-v2-109.

Load literal/regex style rules and apply them to text, reporting the changes made. Pure regex; no
dependency.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """A style rule: ``pattern`` → ``replacement`` (literal word unless ``regex``)."""
    pattern: str
    replacement: str
    ignore_case: bool = True
    regex: bool = False


@dataclass(frozen=True)
class Change:
    """One applied substitution."""
    before: str
    after: str


def load_stylerules(items) -> list:
    """Build a list of :class:`Rule` from dict items (pattern/replacement[/ignore_case/regex]). Pure."""
    rules = []
    for it in items or ():
        rules.append(Rule(
            pattern=it["pattern"],
            replacement=it["replacement"],
            ignore_case=bool(it.get("ignore_case", True)),
            regex=bool(it.get("regex", False)),
        ))
    return rules


def apply_style(text: str, rules):
    """Apply ``rules`` to ``text`` → ``(rewritten, [Change,…])``. Pure."""
    s = text or ""
    changes = []
    for r in rules or ():
        pat = r.pattern if r.regex else r"\b" + re.escape(r.pattern) + r"\b"
        flags = re.IGNORECASE if r.ignore_case else 0

        def _repl(m, _rep=r.replacement):
            changes.append(Change(m.group(0), _rep))
            return _rep

        s = re.sub(pat, _repl, s, flags=flags)
    return s, changes
