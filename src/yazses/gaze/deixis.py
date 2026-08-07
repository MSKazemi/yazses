"""Gaze deixis — resolve "close this / focus that" against the looked-at window (pure).

Multimodal deixis resolution (Bolt's "Put-That-There" lineage): a demonstrative in
a spoken command ("this", "that", "there") refers to whatever the eyes are on, not
to the keyboard focus. The daemon snapshots the gaze route decision at hold-start;
when a command-mode burst is a deixis phrase, the action targets that window.

This module is the pure half: the utterance parser and the confirm policy. The
side effects (xdotool window actions, the confirm toast) stay in the daemon and
desktop backend. Destructive actions ("close this") on a gaze-routed target are
confirm-gated per ``[gaze] confirm_destructive`` because webcam gaze is coarse
(ADR-v2-010's ``needs_confirm`` policy, wired here for the first time).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from yazses.gaze.route import RouteDecision, needs_confirm

# Actions whose misfire loses user state: confirm-gated when gaze-routed.
_DESTRUCTIVE = frozenset({"close"})

# verb → action. Each alternative must be followed by a demonstrative object —
# a bare "close" (no deixis) stays with the ordinary command grammar.
_VERBS = {
    "close": "close",
    "focus": "focus",
    "activate": "focus",
    "switch to": "focus",
    "go to": "focus",
    "minimize": "minimize",
    "minimise": "minimize",
}

_DEMONSTRATIVES = r"(?:this|that)(?:\s+(?:window|one|pane))?"

_PATTERN = re.compile(
    r"^(?P<verb>" + "|".join(re.escape(v) for v in _VERBS) + r")\s+"
    + _DEMONSTRATIVES + r"$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DeixisIntent:
    """A parsed deixis command: what to do with the looked-at window."""

    action: str          # "close" | "focus" | "minimize"
    raw_text: str

    @property
    def destructive(self) -> bool:
        return self.action in _DESTRUCTIVE


def parse_deixis(text: str) -> DeixisIntent | None:
    """Parse a whole-utterance deixis command, else None. Pure.

    Only whole utterances match ("close this", "focus that window", "switch to
    this one") so ordinary dictation containing "this/that" is never consumed.
    Outer punctuation is stripped the way the command grammar does.
    """
    cleaned = text.strip().strip(".,!?;:").strip().lower()
    m = _PATTERN.match(cleaned)
    if m is None:
        return None
    return DeixisIntent(action=_VERBS[m.group("verb")], raw_text=text)


def requires_confirm(
    intent: DeixisIntent, decision: RouteDecision, confirm_destructive: bool
) -> bool:
    """Whether this deixis action must be confirmed before executing. Pure.

    Applies ADR-v2-010's policy: only destructive actions actually routed by
    gaze confirm (coarse gaze can misroute); focus-fallback targets and
    non-destructive actions run frictionlessly. ``confirm_destructive`` off
    disables the gate entirely (the user accepted the risk in config).
    """
    if not confirm_destructive:
        return False
    return needs_confirm(decision, intent.destructive)
