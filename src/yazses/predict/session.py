"""Predictive completion — the pending-suggestion lifecycle (pure) — ADR-v2-016.

Everything the daemon has to *decide* about a suggestion lives here, with no thread,
no model and no clock of its own, so every rule is a plain unit test:

* **What the model sees.** A rolling context of the dictation this session has typed,
  capped, and reset when the focused application changes — a suggestion built from
  the e-mail you were writing must not be offered in the terminal you switched to.
* **Which result is still wanted.** Every request carries an *epoch*. A new burst
  starting, new text being typed, or anything else that changes what is on screen
  bumps the epoch, and a generator result for an older epoch is dropped unseen. That
  is how a slow model can never surface a suggestion about text that is no longer the
  last thing you said.
* **What the next utterance means.** A suggestion is only ever *offered*. The next
  burst resolves it: an anchored accept phrase types it, an anchored decline phrase
  drops it, and anything else drops it silently and is dictated as usual. Nothing is
  typed without an explicit accept, and the daemon is never modal — forgetting the
  word costs one suggestion, not a stuck dictation path.
* **How long an offer stands.** :data:`SUGGESTION_TTL_S`. An accept that arrives
  after that does not type a suggestion the user may no longer be looking at; it is
  still consumed for a short grace period (:data:`LATE_GRACE_S`) so the word "accept"
  is not typed into the document instead.

Per ADR-021 the trigger is specific and checkable: a suggestion is offered only after
real dictated text (at least :data:`MIN_CONTEXT_WORDS` words of it), only when the
model proposes at least :data:`MIN_SUGGESTION_WORDS` new words, and an accept or
decline is recognised only as a whole utterance (``parse_accept``) while an offer is
open. The thresholds are module constants, not config keys: exposing them is an owner
decision this wiring did not take.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from yazses.predict.complete import merge_completion, parse_accept

#: How long an offered suggestion can be accepted, in seconds.
SUGGESTION_TTL_S = 10.0
#: After expiry, how long an accept/decline phrase is still *consumed* (typing nothing)
#: rather than dictated as the literal word. Beyond this, nothing is pending at all.
LATE_GRACE_S = 20.0
#: The most dictated text the model is shown, in characters.
MAX_CONTEXT_CHARS = 400
#: Fewer words than this on screen is not enough to predict from.
MIN_CONTEXT_WORDS = 3
#: A suggestion adding fewer new words than this is not worth an interruption.
MIN_SUGGESTION_WORDS = 2
#: The longest suggestion offered, in characters (cut back to a word boundary).
MAX_SUGGESTION_CHARS = 120

# Resolution actions.
NONE = "none"          # nothing was pending; the utterance is ordinary dictation
ACCEPT = "accept"      # type ``Resolution.typed``; the utterance itself is consumed
DECLINE = "decline"    # consumed; nothing typed
LATE = "late"          # an accept/decline after expiry: consumed, nothing typed
EXPIRED = "expired"    # the offer had expired; the utterance is ordinary dictation
DROPPED = "dropped"    # any other utterance: the offer is dropped, dictation continues

# A suggestion starting with one of these attaches to the previous word with no space.
_GLUE_PUNCT = ",.;:!?)]}…"
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")
_QUOTES = "\"'`“”‘’"


@dataclass(frozen=True)
class Suggestion:
    """One offered completion.

    ``completion`` is exactly what an accept types — the new words only, with the
    separating space it needs. ``epoch`` is the request it answers, ``offered_at``
    the session clock when it was offered.
    """

    completion: str
    epoch: int
    offered_at: float

    @property
    def display(self) -> str:
        """The completion as shown to the user (no leading separator)."""
        return self.completion.strip()

    @property
    def words(self) -> int:
        return len(self.completion.split())


@dataclass(frozen=True)
class Resolution:
    """What the next utterance did to a pending suggestion."""

    action: str
    typed: str = ""
    consumed: bool = False


def clean_suggestion(raw: str | None, *, max_chars: int = MAX_SUGGESTION_CHARS) -> str:
    """Reduce raw model output to one short, typeable phrase, or ``""``. Pure.

    First line only; control and format characters removed (a bidi override or a
    zero-width joiner has no business being typed into someone's document or
    terminal); whitespace collapsed; wrapping quotes stripped; cut at the first
    sentence end; capped at *max_chars* on a word boundary.
    """
    s = (raw or "").replace("\r", "\n").replace("\t", " ")
    s = s.split("\n", 1)[0]
    s = "".join(ch for ch in s if ch == " " or unicodedata.category(ch)[0] != "C")
    s = " ".join(s.split()).strip(_QUOTES).strip()
    m = _SENTENCE_END.search(s)
    if m:
        s = s[: m.end()]
    if len(s) > max_chars:
        s = s[:max_chars]
        if " " in s:
            s = s.rsplit(" ", 1)[0]
        s = s.rstrip(",;:- ")
    return s


def continues_word(context: str, raw: str | None) -> bool:
    """Does the raw model output continue the last word rather than start a new one?

    A causal LM writes a new word with a leading space and a word-piece without one.
    So output that starts with a letter or digit right after a context that ends in
    one is the rest of that word ("meet" + "ing at noon"). Pure.
    """
    r = raw or ""
    return bool(r) and r[0].isalnum() and bool(context) and context[-1].isalnum()


def typed_tail(context: str, suggestion: str, *, glue: bool = False) -> str:
    """Exactly what to type to append *suggestion* after *context*. Pure.

    Reuses :func:`merge_completion`, so a suggestion that repeats the last words
    already on screen ("send the report to" + "to the team") types only the new part.
    ``glue`` (or a suggestion that opens with closing punctuation) appends with no
    space. ``""`` when nothing new would be typed.
    """
    s = (suggestion or "").strip()
    if not s:
        return ""
    base = (context or "").rstrip()
    if not base:
        return s
    if glue or s[0] in _GLUE_PUNCT:
        return s
    tail = merge_completion(base, s)[len(base):]
    if not tail.strip():
        return ""
    if context != base:  # the screen already ends in whitespace
        tail = tail.lstrip()
    return tail


class PredictSession:
    """The pending-suggestion state machine. Pure and single-threaded.

    The caller owns locking and the clock; every time-dependent method takes ``now``.
    """

    def __init__(
        self,
        *,
        ttl_s: float = SUGGESTION_TTL_S,
        late_grace_s: float = LATE_GRACE_S,
        max_context_chars: int = MAX_CONTEXT_CHARS,
        min_context_words: int = MIN_CONTEXT_WORDS,
        min_suggestion_words: int = MIN_SUGGESTION_WORDS,
    ) -> None:
        self._ttl = float(ttl_s)
        self._grace = float(late_grace_s)
        self._max_context = max(1, int(max_context_chars))
        self._min_context_words = max(1, int(min_context_words))
        self._min_suggestion_words = max(1, int(min_suggestion_words))
        self._epoch = 0
        self._context = ""
        self._app = ""
        self._pending: Suggestion | None = None

    # -- inspection -------------------------------------------------------

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def context(self) -> str:
        return self._context

    @property
    def pending(self) -> Suggestion | None:
        return self._pending

    def is_current(self, epoch: int) -> bool:
        """Is a request for *epoch* still wanted?"""
        return epoch == self._epoch

    # -- lifecycle --------------------------------------------------------

    def begin_burst(self) -> None:
        """A new burst started: any request still in flight is stale.

        The *offered* suggestion survives — the burst that just started may be the
        very "accept" that claims it.
        """
        self._epoch += 1

    def note_injected(self, text: str, app: str = "") -> tuple[int, str] | None:
        """Dictated *text* was typed into *app*. Returns ``(epoch, context)`` to request.

        New text on screen makes any earlier offer stale, so it is dropped and the
        epoch moves. ``None`` when there is not yet enough context to predict from.
        """
        if app != self._app:
            self._context = ""
            self._app = app
        self._pending = None
        self._epoch += 1
        text = text or ""
        if self._context and text and not self._context[-1].isspace() and not text[0].isspace():
            # Two bursts typed with no separator (continuation spacing off, or a long
            # pause) are still two phrases; the model should not read one glued word.
            text = " " + text
        self._append(text)
        if len(self._context.split()) < self._min_context_words:
            return None
        return self._epoch, self._context

    def offer(self, epoch: int, raw: str | None, now: float) -> Suggestion | None:
        """The generator answered request *epoch* with *raw*. The offer, or ``None``.

        ``None`` when the request is stale, the output cleans to nothing, or it adds
        fewer than the minimum number of new words.
        """
        if epoch != self._epoch:
            return None
        cleaned = clean_suggestion(raw)
        if not cleaned:
            return None
        tail = typed_tail(self._context, cleaned, glue=continues_word(self._context, raw))
        if len(tail.split()) < self._min_suggestion_words:
            return None
        self._pending = Suggestion(tail, epoch, now)
        return self._pending

    def resolve(self, utterance: str, now: float) -> Resolution:
        """Decide what *utterance* (the next burst) does to the pending offer.

        The offer is cleared whatever the outcome: it is answered at most once.
        """
        offered = self._pending
        if offered is None:
            return Resolution(NONE)
        self._pending = None
        control = parse_accept(utterance)
        age = now - offered.offered_at
        if age > self._ttl:
            if control is not None and age <= self._ttl + self._grace:
                return Resolution(LATE, consumed=True)
            return Resolution(EXPIRED)
        if control == "accept":
            self._append(offered.completion)
            return Resolution(ACCEPT, typed=offered.completion, consumed=True)
        if control == "decline":
            return Resolution(DECLINE, consumed=True)
        return Resolution(DROPPED)

    def drop(self) -> bool:
        """Withdraw the pending offer, if any. True when one was withdrawn."""
        had = self._pending is not None
        self._pending = None
        return had

    def interrupt(self) -> None:
        """Something other than dictation changed the screen (a command, an undo).

        The offer, any in-flight request and the context the model was shown all
        describe a screen that no longer exists, so all three go.
        """
        self._pending = None
        self._context = ""
        self._epoch += 1

    # -- internals --------------------------------------------------------

    def _append(self, text: str) -> None:
        ctx = self._context + (text or "")
        if len(ctx) > self._max_context:
            cut = ctx[-self._max_context:]
            # Never hand the model half a word at the start of its context.
            if not ctx[-self._max_context - 1].isspace() and " " in cut:
                cut = cut.split(" ", 1)[1]
            ctx = cut
        self._context = ctx
