"""Replacing text YazSes typed: erase it, type the new text, and recover if that fails.

Three features change words already on screen with the same two keyboard steps —
backspaces from the end of the burst YazSes typed, then the new text:

* Interruptible Proofreading replaces the tail of a burst (``proofback/bargein.py``);
* Spoken Edit ("change X to Y") and Punch-In retype the whole last burst.

The erase can land and the typing fail — a backend raises, reports failure, or the
window stops taking input part-way — and then the words the user dictated are gone
with nothing in their place. The rule, the same for all three:

1. **restore** — type the erased text back through the same injector. It is known
   exactly: it is the end of a burst YazSes itself typed. A failed call may already
   have typed part of the new text, so the restored words can follow a fragment of it.
   That fragment is visible and editable; erased words are not, which is why a restore
   is tried even though the screen is uncertain.
2. **rescue** — if the restore fails too, put the erased text on the clipboard and say
   so; if the clipboard fails as well, say that, and point at the application's own undo.
3. **an erase that stopped part-way is never typed over** — where it stopped is
   unknown, so no new text and no restore is typed; the erased text goes straight to
   the clipboard.

And whatever happened, the undo records ("scratch that", the ``[timeline]``) must not
claim a longer burst than is certainly on screen. Undo deletes by count: a record that
under-counts deletes too little, which the user sees and finishes by hand; one that
over-counts deletes the user's own text before the burst. So when the screen is
uncertain the record shrinks to the part that is certain (:attr:`Span.kept`).

No notice ever quotes the dictated words: notifications are shown on screen and logged.

Dependency-free (stdlib only). The injector and the clipboard are passed in, so every
outcome is testable with a scripted fake.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

#: The new text replaced the erased text.
REPLACED = "replaced"
#: The new text could not be typed; the erased text was typed back.
RESTORED = "restored"
#: Neither the new text nor the restore landed (or the erase stopped part-way); the
#: erased text is on the clipboard.
RESCUED = "clipboard"
#: As :data:`RESCUED`, but the clipboard copy failed too.
UNSAVED = "clipboard_failed"


class SpanLike(Protocol):
    """What a replacement needs to know about the text it erases.

    ``original`` is the burst as YazSes typed it, ``kept`` the prefix that stays, and
    ``erased`` the rest: ``kept + erased == original``.
    """

    @property
    def original(self) -> str: ...

    @property
    def kept(self) -> str: ...

    @property
    def erased(self) -> str: ...


@dataclass(frozen=True)
class Span:
    """A burst YazSes typed and the prefix of it that a replacement keeps.

    ``Span(text)`` is the whole burst (Spoken Edit, Punch-In); a non-empty ``kept`` is a
    tail replacement. ``kept`` must be a prefix of ``original``.
    """

    original: str
    kept: str = ""

    def __post_init__(self) -> None:
        if not self.original.startswith(self.kept):
            raise ValueError("kept must be a prefix of original")

    @property
    def erased(self) -> str:
        return self.original[len(self.kept):]


@dataclass(frozen=True)
class Wording:
    """How one feature names itself in the notices. Never carries dictated words.

    ``noun`` is what the user asked for ("correction", "edit"), ``span`` the text that
    was erased as the user would describe it, and ``retry`` one sentence on what to do.
    """

    noun: str
    span: str
    retry: str


@dataclass(frozen=True)
class ReplacementOutcome:
    """What applying a replacement left behind, and what the user must be told.

    ``screen`` is the burst as YazSes believes it stands on screen. ``screen_known`` is
    false when a keyboard call failed: whether it delivered part of its text before
    failing cannot be seen from here. A failed erase may have deleted fewer characters
    than asked, and a failed type may have left a fragment of the new text (before the
    restored words, when they were typed back). Either way the burst on screen is *at
    least as long* as ``record``, which is what the newest undo record for the burst
    becomes (``""`` drops it): undo deletes by count, so it can then delete too little,
    never text before the burst.
    ``typed`` is true only when the new text landed; ``record`` then excludes it, and
    the caller records it (as a burst of its own, or appended to ``record``).
    ``notice`` is ``(title, body)`` for the user, or ``None``. Neither carries the
    transcript: dictated words stay out of notifications.
    """

    result: str
    screen: str
    screen_known: bool
    record: str
    typed: bool
    notice: tuple[str, str] | None


_CLIPBOARD_HINT = "paste them (Ctrl+V) where they were"
_APP_UNDO_HINT = "Your application's own undo (Ctrl+Z) may bring them back."


def rescue_text(span: SpanLike, *, erased: bool, typed: bool, restored: bool) -> str | None:
    """The text to put on the clipboard after the keyboard steps, or ``None``.

    Needed when the erase failed (some of the erased text may be gone and the new text
    was never typed) or when the new text and the restore both failed (it is gone).
    """
    if erased and (typed or restored):
        return None
    return span.erased or None


def settle_replacement(
    span: SpanLike,
    replacement: str,
    *,
    erased: bool,
    typed: bool = False,
    restored: bool = False,
    copied: bool = False,
    wording: Wording,
) -> ReplacementOutcome:
    """Map the results of erase → type → restore → clipboard onto records and a notice.

    A step that was not attempted is passed as ``False``: *typed* is ignored when the
    erase failed (the new text is never typed over an erase that stopped at an unknown
    point), *restored* when the new text landed, and *copied* when no rescue was needed.
    """
    kept = span.kept
    if erased and typed:
        return ReplacementOutcome(REPLACED, kept + replacement, True, kept, True, None)
    noun = wording.noun
    if erased and restored:
        # The restore put back exactly the erased words, so the records stand as they
        # were. Unknown: whether the failed call typed a fragment of the new text first
        # (that would sit before the restored words, and only lengthen the burst).
        return ReplacementOutcome(
            RESTORED,
            span.original,
            False,
            span.original,
            False,
            (
                f"⌨ {noun.capitalize()} not typed",
                f"YazSes could not type your {noun}, so it typed back the words it "
                f"had erased. {wording.retry}",
            ),
        )
    if not erased:
        what = (
            f"YazSes could not finish erasing {wording.span}, so it did not type your "
            f"{noun}. Some of those words may be gone."
        )
    else:
        what = (
            f"YazSes erased {wording.span}, then could not type your {noun} or type "
            "the erased words back."
        )
    if copied:
        result = RESCUED
        body = f"{what} The erased words are on the clipboard — {_CLIPBOARD_HINT}."
        title = "⌨ Erased words copied to the clipboard"
    else:
        result = UNSAVED
        body = f"{what} The clipboard copy failed too. {_APP_UNDO_HINT}"
        title = "⌨ Erased words could not be saved"
    # The screen past `kept` is unknown: a failed erase may have stopped early, and a
    # failed type or restore may have typed part of its text. `kept` is certain: the
    # erase sent at most `len(erased)` backspaces, and the restore deleted only
    # characters of the new text that had certainly landed.
    return ReplacementOutcome(result, kept, False, kept, False, (title, body))


class InjectionTally:
    """An injector wrapper that counts what it delivered and makes failure an exception.

    ``typed`` counts the characters of :meth:`inject` calls that returned, so after a
    failure part-way through a paced (multi-call) replacement the caller knows how much
    of it certainly reached the window. A backend that reports failure by returning
    ``False`` instead of raising is turned into an exception here, so every step has
    one failure signal. The call that failed is not counted: whether it typed part of
    its text is unknowable from here.
    """

    def __init__(self, injector: Any) -> None:
        self._injector = injector
        self.typed = 0

    def inject(self, text: str) -> None:
        if self._injector.inject(text) is False:
            raise RuntimeError("the injector reported that typing failed")
        self.typed += len(text)

    def inject_backspaces(self, count: int) -> None:
        if self._injector.inject_backspaces(count) is False:
            raise RuntimeError("the injector reported that the backspaces failed")

    def inject_key_sequence(self, keys: list[str]) -> None:
        if self._injector.inject_key_sequence(keys) is False:
            raise RuntimeError("the injector reported that the key sequence failed")


@dataclass(frozen=True)
class ReplacementSteps:
    """Which keyboard steps of a replacement succeeded, and how each failure looked.

    ``delivered`` is how many characters of the replacement certainly reached the
    window before typing failed (calls that returned; see :class:`InjectionTally`).
    The ``*_error`` fields hold the exception each failed step raised, for the caller
    to log by type and diagnose — never to show: a backend's message can quote text.
    """

    erased: bool
    typed: bool
    restored: bool
    copied: bool
    delivered: int = 0
    erase_error: BaseException | None = None
    type_error: BaseException | None = None
    restore_error: BaseException | None = None

    @property
    def error(self) -> BaseException | None:
        """The first failure: the one that started the recovery."""
        return self.erase_error or self.type_error


def run_replacement(
    span: SpanLike,
    replacement: str,
    injector: Any,
    *,
    type_text: Callable[[str, InjectionTally], None] | None = None,
    copy: Callable[[str], bool] | None = None,
) -> ReplacementSteps:
    """Erase ``span.erased``, type *replacement*, and recover if typing fails.

    Only backspaces from the end of the burst — no caret is moved. The steps, each run
    only if needed:

    1. erase ``len(span.erased)`` characters;
    2. type *replacement* (through *type_text* when given — e.g. paced — else in one
       call);
    3. if that failed: delete what of it certainly landed, and type the erased text back;
    4. if the erase or the restore failed: hand the erased text to *copy* (the
       clipboard), when one is given.

    Never raises. Pass the result to :func:`settle_replacement` for the records and the
    notice.
    """
    erased = typed = restored = copied = False
    erase_error: BaseException | None = None
    type_error: BaseException | None = None
    restore_error: BaseException | None = None
    tally = InjectionTally(injector)
    try:
        InjectionTally(injector).inject_backspaces(len(span.erased))
        erased = True
    except Exception as exc:  # noqa: BLE001 - recovery must never raise
        erase_error = exc
    if erased:
        try:
            if type_text is not None:
                type_text(replacement, tally)
            else:
                tally.inject(replacement)
            typed = True
        except Exception as exc:  # noqa: BLE001
            type_error = exc
        if not typed:
            try:
                restore = InjectionTally(injector)
                if tally.typed:
                    restore.inject_backspaces(tally.typed)
                restore.inject(span.erased)
                restored = True
            except Exception as exc:  # noqa: BLE001
                restore_error = exc
    rescue = rescue_text(span, erased=erased, typed=typed, restored=restored)
    if rescue and copy is not None:
        try:
            copied = bool(copy(rescue))
        except Exception:  # noqa: BLE001 - a clipboard failure is reported as UNSAVED
            copied = False
    return ReplacementSteps(
        erased=erased,
        typed=typed,
        restored=restored,
        copied=copied,
        delivered=tally.typed,
        erase_error=erase_error,
        type_error=type_error,
        restore_error=restore_error,
    )
