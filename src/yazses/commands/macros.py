"""Say-Macro — user-programmable voice macro expansion.

A macro maps a spoken *trigger phrase* to an *expansion* (boilerplate text or a
code snippet). The table is matched as a Tier-1 lookup that runs before the regex
grammar (see ``commands/grammar.py``), gated by **whole-utterance exact match** so
a trigger appearing inside ordinary prose never fires mid-dictation.

Off by default per ADR-011: ``build_macro_table`` returns ``None`` unless
``[macros] enabled = true``. Spec: ``design/specs/say-macro.md``.

P1 ships ``text`` and ``snippet`` expansions. ``actions`` (OS/app key chains) are
parsed but dormant until P2.
"""
from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from yazses import tomlio

log = logging.getLogger(__name__)

_VALID_TYPES = ("text", "snippet", "actions")
_CURSOR = "${cursor}"
_VAR_NAMES = ("clipboard", "date", "time", "author")
_VAR_RE = re.compile(r"\$\{(\w+)\}")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Macro:
    """One macro: a normalized trigger mapped to an expansion."""
    trigger: str               # normalized trigger phrase (lookup key)
    type: str                  # "text" | "snippet" | "actions"
    template: str = ""         # text/snippet body (with optional placeholders)
    actions: tuple = ()        # P2: OS/app action chain (parsed, dormant in P1)


@dataclass
class MacroContext:
    """Dynamic values resolved into placeholders at expansion time."""
    clipboard: str = ""
    date: str = ""
    time: str = ""
    author: str = ""


def normalize(text: str) -> str:
    """Normalize a phrase for whole-utterance matching.

    Lowercase, collapse internal whitespace, strip trailing sentence punctuation.
    Shared by trigger definitions and incoming bursts so the comparison is exact.
    """
    t = _WS_RE.sub(" ", text.strip().lower())
    return t.rstrip(".?!,").strip()


class MacroTable:
    """Immutable lookup of normalized-trigger -> Macro."""

    def __init__(self, macros: dict[str, Macro]):
        self._macros = macros

    def __len__(self) -> int:
        return len(self._macros)

    def match(self, text: str) -> Macro | None:
        """Return the macro whose trigger equals the whole (normalized) burst."""
        return self._macros.get(normalize(text))

    def get(self, trigger: str) -> Macro | None:
        """Look up by an already-normalized trigger (used by the dispatcher)."""
        return self._macros.get(trigger)


def _resolve_vars(s: str, ctx: MacroContext) -> str:
    """Replace ${clipboard|date|time|author}; leave unknown tokens literal."""
    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name in _VAR_NAMES:
            return getattr(ctx, name)
        return m.group(0)
    return _VAR_RE.sub(repl, s)


def expand(macro: Macro, ctx: MacroContext) -> tuple[str, int]:
    """Resolve a macro template into (text, cursor_offset).

    ``cursor_offset`` is the number of characters the caret must move left from
    the end so it lands where the first ``${cursor}`` marker was. 0 if absent.
    """
    template = macro.template
    if _CURSOR in template:
        idx = template.index(_CURSOR)
        before = _resolve_vars(template[:idx], ctx)
        # Any FURTHER ${cursor} markers are dropped, not carried through. Only the first
        # positions the caret -- as documented -- but the rest used to survive into the
        # output and get typed into the user's document verbatim:
        #
        #     "a${cursor}b${cursor}c"  ->  typed "ab${cursor}c"
        #
        # Stripping them before measuring `after` keeps the offset right: the caret still
        # lands where the first marker was, now against the text actually injected.
        after = _resolve_vars(template[idx + len(_CURSOR):], ctx).replace(_CURSOR, "")
        return before + after, len(after)
    resolved = _resolve_vars(template, ctx)
    return resolved, 0


def load_macros(path: Path | str | None) -> MacroTable:
    """Load and validate a macros.toml into a MacroTable.

    A missing file yields an empty table. A single bad entry is skipped (logged),
    never raised — a broken macro must not break the daemon. An unparseable file
    yields an empty table plus one logged error.
    """
    macros: dict[str, Macro] = {}
    if path is None:
        return MacroTable(macros)
    p = Path(path)
    if not p.exists():
        return MacroTable(macros)
    try:
        data = tomlio.read(p)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        log.error("could not parse macros file %s: %s", p, exc)
        return MacroTable(macros)

    # `[[macro]]` is an array of tables, but nothing stops a file writing `macro = "x"`
    # or `[macro]`. TOML then hands back a string or a dict, and iterating either used to
    # reach `entry.get`, which raises out of `Daemon.__init__` -- so a typo in a file
    # `configcheck` never sees stopped the daemon starting. This function's own docstring
    # says a broken macro must not break the daemon; these are the two gaps in that.
    entries = data.get("macro", [])
    if not isinstance(entries, list):
        log.error(
            "macros file %s: `macro` should be a list of [[macro]] tables, got %s; "
            "ignoring the file", p, type(entries).__name__,
        )
        return MacroTable(macros)

    for entry in entries:
        if not isinstance(entry, dict):
            log.warning("skipping macro entry that is not a table: %r", entry)
            continue
        trigger = entry.get("trigger", "")
        mtype = entry.get("type", "")
        # A non-string trigger reached `normalize`, which strips it. Checked here rather
        # than there so `normalize` stays a pure text function with one job.
        if not isinstance(trigger, str) or not isinstance(mtype, str):
            log.warning("skipping macro entry with a non-string trigger/type: %r", entry)
            continue
        if not trigger or mtype not in _VALID_TYPES:
            log.warning("skipping invalid macro entry: %r", entry)
            continue
        norm = normalize(trigger)
        if not norm:
            log.warning("skipping macro with empty normalized trigger: %r", trigger)
            continue
        if norm in macros:
            log.warning("duplicate macro trigger %r ignored (first wins)", trigger)
            continue
        if mtype == "actions":
            macros[norm] = Macro(trigger=norm, type=mtype,
                                 actions=tuple(_parse_actions(entry.get("actions", []))))
        else:
            macros[norm] = Macro(trigger=norm, type=mtype,
                                 template=entry.get(mtype, ""))
    return MacroTable(macros)


def _parse_actions(raw: list) -> list[tuple[str, str]]:
    """Flatten action dicts to (kind, value) pairs. Parsed but dormant in P1."""
    out: list[tuple[str, str]] = []
    for a in raw:
        if isinstance(a, dict):
            for k, v in a.items():
                out.append((k, str(v)))
    return out


def build_macro_table(config, config_dir: Path | str) -> MacroTable | None:
    """Return a loaded table, or None when the feature is disabled (dormant)."""
    mc = config.macros
    if not mc.enabled:
        return None
    p = Path(mc.path)
    if not p.is_absolute():
        p = Path(config_dir) / p
    return load_macros(p)
