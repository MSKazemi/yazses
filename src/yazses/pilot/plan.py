"""AT-SPI Voice Pilot planning (pure) — ADR-v2-007.

Parse a spoken UI command ("click Save", "focus the terminal", "toggle dark
mode") and match its target against a list of accessibility-tree elements,
resolving ambiguity by a spoken ordinal ("the third") or flagging it for a
confirm. Actions are limited to a safe verb set. The pyatspi tree reader +
actioner are heavy + Linux-only and opt-in; this layer is fully testable with
plain data — no desktop, no screenshots.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Spoken verb → canonical, safe action.
_ACTIONS = {
    "click": "activate", "press": "activate", "activate": "activate", "tap": "activate",
    "focus": "focus", "select": "focus",
    "toggle": "toggle", "check": "toggle", "uncheck": "toggle",
}

_ORDINALS = {
    "first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4,
    "1st": 0, "2nd": 1, "3rd": 2, "4th": 3, "5th": 4,
}

# Filler words dropped from the target/label so "click the Save button" → "save".
_STOP = frozenset("the a an button on to of my item option".split())


@dataclass(frozen=True)
class Element:
    label: str
    role: str = ""
    actions: tuple[str, ...] = ()     # supported actions (empty = unknown/any)
    # The snapshot id the backend acts on (``SemanticCandidate.entity_id``). Empty for a
    # hand-built element; :func:`decide` never needs it, the service that acts does.
    entity_id: str = ""


@dataclass(frozen=True)
class PilotCommand:
    action: str
    target: str
    ordinal: int | None = None


@dataclass(frozen=True)
class PilotPlan:
    action: str
    element: Element
    ambiguous: bool                   # a runner-up tied the top → confirm/ordinal
    score: float


def _content_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOP}


def parse_command(phrase) -> PilotCommand | None:
    """Parse a spoken UI command into ``(action, target, ordinal)`` or ``None``."""
    norm = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (phrase or "").lower())).strip()
    if not norm:
        return None
    words = norm.split()
    action = _ACTIONS.get(words[0])
    if action is None:
        return None
    ordinal: int | None = None
    kept: list[str] = []
    for w in words[1:]:
        if w in _ORDINALS and ordinal is None:
            ordinal = _ORDINALS[w]
        else:
            kept.append(w)
    target = " ".join(w for w in kept if w not in _STOP).strip()
    if not target:
        return None
    return PilotCommand(action=action, target=target, ordinal=ordinal)


def _score(target: str, label: str) -> float:
    """Jaccard token overlap in [0, 1] between the target and an element label."""
    t, lab = _content_tokens(target), _content_tokens(label)
    if not t or not lab:
        return 0.0
    return len(t & lab) / len(t | lab)


def match_elements(target, elements, *, threshold: float = 0.5):
    """Return ``(element, score)`` candidates scoring ≥ threshold, best first."""
    scored = [(e, _score(target, e.label)) for e in elements]
    scored = [(e, s) for e, s in scored if s >= threshold]
    scored.sort(key=lambda es: es[1], reverse=True)
    return scored


def plan_action(phrase, elements, *, threshold: float = 0.5) -> PilotPlan | None:
    """Plan a UI action from a spoken command + the current element list.

    Returns ``None`` if the phrase isn't a pilot command or nothing matches. A
    spoken ordinal selects the Nth candidate; otherwise the top candidate is used
    and ``ambiguous`` is True when a runner-up ties the top score (so the caller
    asks for a confirm/ordinal). Pure and deterministic.
    """
    cmd = parse_command(phrase)
    if cmd is None:
        return None
    cands = match_elements(cmd.target, elements, threshold=threshold)
    if not cands:
        return None
    if cmd.ordinal is not None:
        if cmd.ordinal >= len(cands):
            return None
        elem, score = cands[cmd.ordinal]
        return PilotPlan(action=cmd.action, element=elem, ambiguous=False, score=score)
    top_elem, top_score = cands[0]
    ambiguous = len(cands) > 1 and abs(cands[1][1] - top_score) < 1e-9
    return PilotPlan(action=cmd.action, element=top_elem, ambiguous=ambiguous, score=top_score)


# --------------------------------------------------------------------------- #
# Deciding whether to act (ADR-021): act only on a specific, checkable match.
# --------------------------------------------------------------------------- #

#: Verdicts :func:`decide` returns.
ACT = "act"            # one exact, safe match: carry it out
CONFIRM = "confirm"    # a plausible match that must be confirmed out loud first
NO_MATCH = "none"      # nothing to act on; say so and do nothing

#: Backend action names that carry out each canonical verb, in preference order.
#: AT-SPI names them per toolkit ("click" in GTK, "press" in Qt, "jump" on a link);
#: ``focus`` is the backend's pseudo-action for grabbing keyboard focus.
_BACKEND_ACTIONS: dict[str, tuple[str, ...]] = {
    "activate": ("click", "press", "activate", "jump", "open", "invoke"),
    "toggle": ("toggle", "click", "press", "activate"),
    "focus": ("focus",),
}

#: Label words that make activating a control hard to undo from the keyboard: a sent
#: message, a deleted file, a purchase, an ended session. A closed list matched as whole
#: words, because ADR-021 holds a guard only on a specific, checkable signal. Words that
#: also name harmless controls are left out on purpose -- "Format" is a menu, "Replace"
#: is undone by Ctrl+Z, "Trash" is a sidebar folder -- since a prompt on "click Format"
#: teaches the user to say "confirm" without reading, and then it protects nothing.
_DESTRUCTIVE_WORDS = frozenset({
    "delete", "remove", "discard", "erase", "wipe", "destroy", "purge",
    "uninstall", "reset", "overwrite",
    "send", "submit", "publish", "post", "pay", "purchase", "buy", "checkout",
    "quit", "exit", "terminate", "kill", "shutdown", "reboot", "restart",
    "revoke", "unsubscribe", "logout", "signout",
})
#: Two-word forms: "Don't Save" / "Do not save" discard, "Log out" ends a session.
_DESTRUCTIVE_PAIRS = frozenset({
    ("t", "save"), ("not", "save"), ("dont", "save"),
    ("log", "out"), ("sign", "out"), ("shut", "down"), ("power", "off"),
    ("empty", "trash"), ("to", "trash"), ("close", "without"),
})

#: A score this close to 1.0 is an exact match: every content word of the spoken
#: target is in the label and the label has no other content word.
_EXACT = 1.0 - 1e-9


def resolve_action_name(action: str, available) -> str | None:
    """The backend action that carries out canonical *action* on a node, or ``None``. Pure.

    ``None`` when the node offers none of them -- a node that cannot be clicked is not a
    candidate for "click", however well its label matches.
    """
    offered = {str(a).strip().lower() for a in (available or ()) if a}
    for name in _BACKEND_ACTIONS.get(action, ()):
        if name in offered:
            return name
    return None


def is_destructive_label(label: str) -> bool:
    """Whether activating a control labelled *label* is hard to undo. Pure."""
    words = re.findall(r"[a-z0-9]+", (label or "").lower())
    if any(w in _DESTRUCTIVE_WORDS for w in words):
        return True
    return any(pair in _DESTRUCTIVE_PAIRS for pair in zip(words, words[1:], strict=False))


@dataclass(frozen=True)
class PilotDecision:
    """What to do with one spoken pilot command, and why. Pure data.

    ``reason`` is one of ``exact``, ``ordinal``, ``destructive``, ``ambiguous``,
    ``weak``, ``no_match``, ``ordinal_out_of_range``. ``matches`` counts the candidates
    at or above the threshold, so a message can say "3 controls match".
    """

    verdict: str
    reason: str
    command: PilotCommand
    element: Element | None = None
    action_name: str | None = None
    score: float = 0.0
    matches: int = 0


def decide(phrase, elements, *, threshold: float = 0.5,
           confirm_ambiguous: bool = True) -> PilotDecision | None:
    """Decide whether a spoken command may act on one of *elements*. Pure.

    ``None`` when *phrase* is not a pilot command at all. Otherwise:

    * **ACT** only for a *specific, checkable* match: exactly one actionable element whose
      label is an exact match for the spoken target (or the Nth exact match, when the
      user said an ordinal), and whose label is not destructive.
    * **CONFIRM** when the best match is only partial ("click save" with only "Save As"
      on screen), when several elements match equally (the first, in reading order, is
      the one offered), or when the label is destructive. With
      ``confirm_ambiguous=False`` a tie is refused (NO_MATCH) instead of offered.
    * **NO_MATCH** when no actionable element reaches *threshold*.

    Only elements that offer an action able to carry out the verb are considered, so a
    static label that happens to read "Save" is never picked over the button. Focusing
    a control changes nothing, so ``focus`` never needs the destructive confirmation.
    """
    cmd = parse_command(phrase)
    if cmd is None:
        return None
    usable = [e for e in elements if resolve_action_name(cmd.action, e.actions)]
    cands = match_elements(cmd.target, usable, threshold=threshold)
    if not cands:
        return PilotDecision(NO_MATCH, "no_match", cmd)
    exact = [(e, s) for e, s in cands if s >= _EXACT]

    def outcome(elem: Element, score: float, verdict: str, reason: str) -> PilotDecision:
        if verdict == ACT and cmd.action != "focus" and is_destructive_label(elem.label):
            verdict, reason = CONFIRM, "destructive"
        return PilotDecision(verdict, reason, cmd, elem,
                             resolve_action_name(cmd.action, elem.actions),
                             score, len(cands))

    if cmd.ordinal is not None:
        # The Nth *exact* match when there is one -- "the second Save" -- else the Nth
        # partial one, which is only ever offered for confirmation.
        pool = exact or cands
        if cmd.ordinal >= len(pool):
            return PilotDecision(NO_MATCH, "ordinal_out_of_range", cmd, matches=len(cands))
        elem, score = pool[cmd.ordinal]
        if exact:
            return outcome(elem, score, ACT, "ordinal")
        return outcome(elem, score, CONFIRM, "weak")
    if len(exact) == 1:
        elem, score = exact[0]
        return outcome(elem, score, ACT, "exact")
    top_elem, top_score = cands[0]
    tied = len(exact) > 1 or (len(cands) > 1 and abs(cands[1][1] - top_score) < 1e-9)
    if tied:
        if not confirm_ambiguous:
            return PilotDecision(NO_MATCH, "ambiguous", cmd, matches=len(cands))
        return outcome(top_elem, top_score, CONFIRM, "ambiguous")
    return outcome(top_elem, top_score, CONFIRM, "weak")
