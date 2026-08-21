"""One door for the spoken capabilities that turn a phrase into text — ADR-v2-131.

Six capabilities shipped a designed, unit-tested core and no caller: phonetic
spelling, spoken maths, spoken code, snippets, spoken regex and voice timers.
Each needed the same three things — a way to say "this utterance is mine", a
config flag, and somewhere on the hold-release path to run — and wiring six of
them separately into `core/daemon.py` would have put six more branches into the
function that already carries the guards, the staged buffer and the injector.

So the door is built once and they register at it. What that buys is not tidiness:

* **Anchoring is enforced, not remembered.** Every trigger here is built by
  :func:`prefixed`, which anchors ``^…$`` itself. The one documented way to get
  this wrong is a `re.search` that swallows an ordinary sentence containing the
  verb — "click undo" typed nothing, four of six test phrases, in an earlier PR.
  A handler cannot opt out of the anchor because it never writes the pattern.
* **`math` cannot reach dictation.** `math/latex.py` carries a warning in its own
  docstring: its keywords are ordinary English, so "she squared her shoulders"
  becomes "she^{2} her shoulders". Routing every one of these through a required
  leading verb *in command mode only* is what makes that module safe to call at
  all, and the rule holds for the five beside it rather than being remembered
  once per feature.
* **The refusal is uniform.** A handler returns ``None`` for "not mine" and the
  router falls through to the next, so an unrecognised phrase behaves exactly as
  it did before any of this existed.

Deliberately pure: no daemon, no injector, no config object. The daemon decides
*whether* to call it and what to do with the result; this module decides only
which capability owns a phrase and what text that capability produces.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SpokenResult:
    """What a capability produced from the phrase it claimed.

    ``text`` is typed at the cursor. ``message`` is shown to the user and typed
    nowhere — a timer being set has to be able to report itself without putting
    "timer set for 25 minutes" into the document. ``action`` is a name and its
    argument for a capability that *does* something rather than producing text;
    it stays a plain tuple so this module keeps no opinion about how the daemon
    carries it out, and so a handler can be tested without one.
    """

    slug: str
    text: str | None = None
    message: str | None = None
    action: tuple[str, object] | None = None


@dataclass(frozen=True)
class SpokenHandler:
    """One capability's claim on an utterance.

    ``match`` returns a :class:`SpokenResult` when the phrase is its own and
    ``None`` when it is not. ``types`` is False for a handler that only reports,
    which is what lets the daemon run it even when no editable target is focused.
    """

    slug: str
    match: Callable[[str], "SpokenResult | None"]
    types: bool = True


def prefixed(
    slug: str,
    verbs: Sequence[str],
    convert: Callable[[str], "str | None"],
    *,
    types: bool = True,
) -> SpokenHandler:
    """Build a handler that claims ``"<verb> <body>"`` and nothing else.

    The pattern is anchored at both ends here, once, so no capability can ship an
    unanchored trigger. ``convert`` receives the body and returns the text to
    type, or ``None`` to decline — declining matters even after the verb matched,
    because "regex asdf" parses to nothing and must fall through rather than type
    an empty string.
    """
    if not verbs:
        raise ValueError(f"{slug}: a handler needs at least one trigger verb")
    alternatives = "|".join(re.escape(v) for v in sorted(verbs, key=len, reverse=True))
    pattern = re.compile(rf"^(?:{alternatives})\s+(.+)$", re.IGNORECASE)

    def match(text: str) -> SpokenResult | None:
        hit = pattern.match(tidy(text))
        if hit is None:
            return None
        produced = convert(hit.group(1).strip())
        if not produced:
            return None
        return SpokenResult(slug=slug, text=produced)

    return SpokenHandler(slug=slug, match=match, types=types)


#: Trailing punctuation Whisper adds to a short utterance ("Spell alpha bravo.").
#: Stripped from both ends before matching, exactly as `commands/grammar.py` does
#: — an anchored pattern is otherwise defeated by a full stop the user never said.
_OUTER = " \t\r\n.,!?;:\"'`…"


def tidy(text: str) -> str:
    """Strip whitespace and the outer punctuation Whisper adds. Pure.

    Public because a handler that matches the *whole* utterance rather than a
    ``verb + body`` shape (`spreadsheet`) has to normalise exactly as :func:`prefixed`
    does, and a second implementation of "strip the full stop the user never said"
    is precisely the kind of near-duplicate that drifts.
    """
    return (text or "").strip().strip(_OUTER).strip()


def route(
    text: str,
    handlers: Iterable[SpokenHandler],
    *,
    can_type: bool = True,
) -> SpokenResult | None:
    """First handler to claim ``text`` wins; ``None`` means nobody did. Pure.

    A typing handler is skipped entirely when ``can_type`` is False rather than
    being run and discarded: its result would be text with nowhere to go, and the
    daemon's own note on that branch is that copying a *command* to the clipboard
    helps nobody.
    """
    if not tidy(text):
        return None
    for handler in handlers:
        if handler.types and not can_type:
            continue
        result = handler.match(text)
        if result is not None:
            return result
    return None
