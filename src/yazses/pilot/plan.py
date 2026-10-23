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

# "check" and "uncheck" run the same backend action as "toggle" -- AT-SPI has no "set
# checked" -- so the state they ask for is kept separately, and :func:`decide` acts only
# when the control's *read* state differs from it. Without this, "uncheck X" on an
# already-unchecked box clicked it, and so checked it.
_WANT_CHECKED = {"check": True, "uncheck": False}

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
    # Whether the control is checked, as the accessibility tree reported it; ``None``
    # when it is not a checkable control or its state could not be read.
    checked: bool | None = None
    # The snapshot id the backend acts on (``SemanticCandidate.entity_id``). Empty for a
    # hand-built element; :func:`decide` never needs it, the service that acts does.
    entity_id: str = ""


@dataclass(frozen=True)
class PilotCommand:
    action: str
    target: str
    ordinal: int | None = None
    # The state "check" (True) or "uncheck" (False) asks for; ``None`` for every other
    # verb, including "toggle", which flips whatever the state is.
    want_checked: bool | None = None


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
    return PilotCommand(action=action, target=target, ordinal=ordinal,
                        want_checked=_WANT_CHECKED.get(words[0]))


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
ALREADY = "already"    # "check"/"uncheck" on a control already in that state: do nothing

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
    ``weak``, ``no_match``, ``ordinal_out_of_range``, ``state_unknown`` (a "check" or
    "uncheck" whose control's checked state could not be read), and -- with verdict
    ALREADY -- ``already_checked`` / ``already_unchecked``. :func:`redecide_held` adds
    ``confirmed`` (ACT) and ``target_gone`` / ``target_ambiguous`` / ``state_lost``
    (NO_MATCH). ``matches`` counts the candidates at or above the threshold, so a message
    can say "3 controls match".
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

    **"check" and "uncheck" are idempotent.** Their backend action is a toggle, so the
    chosen control's read state (:attr:`Element.checked`) decides. Already in the asked
    state is ALREADY: nothing is done, whatever the match quality, because confirming it
    would flip the box the wrong way. The other state goes on exactly as above. An
    unreadable state (``None``) is never ACT -- an exact match becomes CONFIRM with reason
    ``state_unknown`` -- because a toggle on a guess can do the opposite of what was said
    (ADR-021: act only on a specific, checkable signal). "toggle" flips regardless.
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
        if cmd.want_checked is not None:
            if elem.checked is cmd.want_checked:
                return PilotDecision(
                    ALREADY, "already_checked" if cmd.want_checked else "already_unchecked",
                    cmd, elem, None, score, len(cands))
            if elem.checked is None and verdict == ACT:
                verdict, reason = CONFIRM, "state_unknown"
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


# --------------------------------------------------------------------------- #
# A held "check"/"uncheck", re-decided at confirm time.
# --------------------------------------------------------------------------- #
#
# A "check X" held for "confirm" (state unreadable, a partial match, a tie) may wait up
# to 30 s. In that time the user can click the box themselves, or the window can change
# under it, and a toggle run on the old reading then does the opposite of what was said.
# So the confirm re-reads the window and decides again, on the *new* reading. Snapshot
# ids are per-snapshot, so the held control is found again by what does not change
# between reads: its label, its role, and an action able to carry out the verb.

#: Reasons :func:`redecide_held` gives with verdict NO_MATCH: nothing is performed.
HELD_GONE = "target_gone"            # no control with that label and role any more
HELD_AMBIGUOUS = "target_ambiguous"  # the number of such controls changed: which one?
HELD_STATE_LOST = "state_lost"       # it was read at hold time and cannot be read now


def _identity(elem: Element) -> tuple[str, str]:
    """What finds the same control again in a later snapshot: label and role."""
    return (" ".join((elem.label or "").split()).casefold(),
            " ".join((elem.role or "").split()).casefold())


@dataclass(frozen=True)
class HeldTarget:
    """A held "check"/"uncheck", described by attributes that survive a re-read. Pure data.

    ``occurrence`` is the held control's index among the actionable controls sharing its
    label and role, in reading order, and ``occurrences`` how many there were -- so the
    second of two identical "Notify" boxes is found again only while there are still
    exactly two. ``checked`` is the state read when it was held.
    """

    command: PilotCommand
    label: str
    role: str
    occurrence: int = 0
    occurrences: int = 1
    checked: bool | None = None


def _same_controls(cmd: PilotCommand, ident: tuple[str, str], elements) -> list[Element]:
    return [e for e in elements
            if _identity(e) == ident and resolve_action_name(cmd.action, e.actions)]


def held_target(decision: PilotDecision, elements) -> HeldTarget | None:
    """The :class:`HeldTarget` for a CONFIRM *decision* made over *elements*. Pure.

    ``None`` when the decision is not a held "check"/"uncheck" (every other held click
    keeps acting on the node it matched) or its element is not among *elements*.
    """
    elem = decision.element
    if (decision.verdict != CONFIRM or elem is None
            or decision.command.want_checked is None):
        return None
    same = _same_controls(decision.command, _identity(elem), elements)
    index = next((i for i, e in enumerate(same) if e is elem), None)
    if index is None:
        index = next((i for i, e in enumerate(same) if e == elem), None)
    if index is None:
        return None
    return HeldTarget(command=decision.command, label=elem.label, role=elem.role,
                      occurrence=index, occurrences=len(same), checked=elem.checked)


def redecide_held(held: HeldTarget, elements) -> PilotDecision:
    """Decide a confirmed "check"/"uncheck" again on a fresh read, *elements*. Pure.

    The user said "confirm" to a prompt about the window as it was. This acts only if
    the same control is still specifically there and still in the other state:

    * **NO_MATCH** ``target_gone`` -- no actionable control with that label and role.
    * **NO_MATCH** ``target_ambiguous`` -- the number of such controls changed, so which
      one was meant cannot be told (ADR-021: never a guess).
    * **ALREADY** -- it is now in the asked state (the user, or the app, changed it
      during the hold); a toggle would undo that.
    * **NO_MATCH** ``state_lost`` -- its state was read at hold time and cannot be read
      now; the prompt promised a check, and a blind toggle might uncheck it.
    * **ACT** -- otherwise: the state still differs from the asked one, or it was
      unreadable then and is now (the prompt said "toggle" and the user confirmed that).
      ``element`` is the control in the *new* read, carrying its new snapshot id.
    """
    cmd = held.command
    want = cmd.want_checked
    ident = _identity(Element(label=held.label, role=held.role))
    same = _same_controls(cmd, ident, elements)
    if not same:
        return PilotDecision(NO_MATCH, HELD_GONE, cmd)
    if len(same) != held.occurrences or not 0 <= held.occurrence < len(same):
        return PilotDecision(NO_MATCH, HELD_AMBIGUOUS, cmd, matches=len(same))
    elem = same[held.occurrence]
    if want is not None and elem.checked is want:
        return PilotDecision(ALREADY, "already_checked" if want else "already_unchecked",
                             cmd, elem, None, 1.0, len(same))
    if elem.checked is None and held.checked is not None:
        return PilotDecision(NO_MATCH, HELD_STATE_LOST, cmd, elem, None, 1.0, len(same))
    return PilotDecision(ACT, "confirmed", cmd, elem,
                         resolve_action_name(cmd.action, elem.actions), 1.0, len(same))
