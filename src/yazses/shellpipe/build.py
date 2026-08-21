"""Spoken stages → rendered shell pipeline (pure) — ADR-v2-082.

Split spoken stages, map each to a command (curated read-only vocab + quoted grep/filter), and
join into a pipeline. Renders text only; nothing executes. Pure and deterministic.
"""
from __future__ import annotations

import re
import shlex

_SPLIT = re.compile(r"\s*(?:,|\bpipe\s+to\b|\bpipe\b|\band\s+then\b|\bthen\b)\s*", re.IGNORECASE)

# Curated read-only stage phrases → commands.
_STAGE = {
    "list files": "ls", "list all files": "ls -a", "long list": "ls -l",
    "word count": "wc -l", "count lines": "wc -l", "count words": "wc -w",
    "sort": "sort", "sort them": "sort", "unique": "uniq", "deduplicate": "uniq",
    "reverse": "tac", "first ten": "head", "last ten": "tail",
    "number them": "nl", "trim spaces": "tr -s ' '",
}
# Mutating tools → their dry-run form (for `dryrun_wrap`).
_DRYRUN = {"rm": "rm -i", "rsync": "rsync --dry-run", "mv": "mv -i", "git clean": "git clean -n"}


def parse_stages(text: str):
    """Split a spoken pipeline into stage phrases. Pure."""
    parts = _SPLIT.split(text or "")
    return [p.strip() for p in parts if p.strip()]


#: A search stage: a verb, any number of connecting words, then the pattern.
#:
#: The connectives are the fix. The old alternation listed ``search for`` but not
#: ``grep for``, so the most natural phrasing of all put the connective **into the
#: pattern**: "grep for error" rendered ``grep 'for error'``, which matches nothing,
#: and "find lines matching error" rendered ``grep 'lines matching error'``. Only the
#: stilted "grep error" worked.
#:
#: The trailing ``\s+`` after the connective group is what keeps this safe: for
#: "grep forbidden" the alternative ``for`` matches the prefix, then the required
#: whitespace does not, so it backtracks and the whole word survives as the pattern.
_SEARCH = re.compile(
    r"(?:grep|search|filter|find|matching)"
    r"(?:\s+(?:for|in|on|lines|matching|containing|with))*"
    r"\s+(.+)$"
)


def _stage_cmd(phrase: str):
    p = (phrase or "").lower().strip()
    m = _SEARCH.match(p)
    if m:
        return f"grep {shlex.quote(m.group(1).strip())}"
    return _STAGE.get(p)


def render_pipeline(stages):
    """Render stage phrases into a shell pipeline string, or ``None`` if any is unknown. Pure."""
    cmds = []
    for phrase in stages or ():
        cmd = _stage_cmd(phrase)
        if cmd is None:
            return None
        cmds.append(cmd)
    return " | ".join(cmds) if cmds else None


def dryrun_wrap(pipeline: str) -> str:
    """Swap a mutating leading tool for its dry-run form. Pure (text only)."""
    if not pipeline:
        return pipeline or ""
    for tool, safe in _DRYRUN.items():
        if pipeline.startswith(tool + " ") or pipeline == tool:
            return safe + pipeline[len(tool):]
    return pipeline
