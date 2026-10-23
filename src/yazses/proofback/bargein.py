"""Barge-in → word → replacement range for Interruptible Proofreading (pure) — ADR-v2-108.

The read-back of a dictated burst is playing. The user holds the dictation key: that
press is the barge-in. This module answers, without touching a keyboard or a clock of
its own:

1. *Was that a real barge-in?* Only while a read-back of a dictated burst is actually
   playing and at least one of its words has started (ADR-021: act on a specific,
   checkable signal, never on a heuristic). A press before playback starts, after it
   ends, or during a ``yazses say`` utterance is ordinary dictation and arms nothing.
2. *Which word?* :class:`~yazses.proofback.timeline.PlaybackTimeline` maps the press
   time to the word playing then. No reaction-time lag is subtracted (``lag_s`` 0.0):
   the ADR leaves the value open and nothing has measured it.
3. *What gets replaced?* **Everything from that word to the end of the burst**
   (decision 2026-10-22). The next dictated burst is typed in its place. The span
   ends where the burst ends, so the edit needs only backspaces from the end of the
   text YazSes itself typed — the "scratch that" and Punch-In mechanism — and never
   a caret move that an application might interpret differently. Replacing only the
   one word would need the text after it re-typed or the caret moved, and how many
   words a correction covers is a guess this module does not make.

When any check fails the answer is "report the word, change nothing": the replacement
burst is then typed exactly as an ordinary dictation would be.

4. *What if the correction cannot be typed after the erase landed?* The erased words
   are typed back, or failing that put on the clipboard with a notice, and the undo
   records are kept to what is on screen (:func:`settle_replacement`).

Dependency-free (stdlib only). The clock is injected so every decision is testable
without sleeping.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yazses.proofback.align import resolve_target
from yazses.proofback.timeline import PlaybackTimeline, Weight, char_weight

Clock = Callable[[], float]

#: The edit a barge-in arms: replace from the interrupted word to the end of the burst.
REPLACE_FROM = "replace_from"


def word_spans(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` character offsets of each whitespace-separated word of *text*.

    ``[text[s:e] for s, e in word_spans(text)] == text.split()`` — the same
    whitespace definition as ``str.split()``, so a timeline index (which counts
    ``split()`` words of the spoken text) addresses the same word here.
    """
    spans: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        j = i
        while j < n and not text[j].isspace():
            j += 1
        spans.append((i, j))
        i = j
    return spans


@dataclass(frozen=True)
class ProofTarget:
    """Where the next dictated burst goes: replace ``injected[char_offset:]``.

    ``erase_count`` is the number of characters to delete from the end of the burst
    (``len(injected) - char_offset``); ``kept`` is what stays on screen. ``stamp``
    identifies the burst (the daemon's last-dictation timestamp when it was read
    back), so a target is never applied to text that has changed since.
    """

    word_index: int
    word: str
    char_offset: int
    erase_count: int
    kept: str
    original: str
    stamp: float | None
    intent: str = REPLACE_FROM

    @property
    def erased(self) -> str:
        """The text the replacement erases: ``original[char_offset:]``."""
        return self.original[self.char_offset:]


def resolve_barge_in(
    injected: str, spoken: str, word_index: int, stamp: float | None = None
) -> ProofTarget | None:
    """Map a word index of the *spoken* read-back onto the *injected* burst.

    Returns ``None`` (report only) when the index is out of range or when the two
    texts do not agree word for word up to and including that word. They differ
    when read-back truncated a long burst to ``[tts] max_readback_chars`` and
    appended ``…``: the cut word ("hel…") then matches nothing, so it is never
    replaced on a guess.
    """
    if word_index < 0:
        return None
    spoken_words = spoken.split()
    spans = word_spans(injected)
    if word_index >= len(spoken_words) or word_index >= len(spans):
        return None
    injected_words = [injected[s:e] for s, e in spans[: word_index + 1]]
    if spoken_words[: word_index + 1] != injected_words:
        return None
    start = spans[word_index][0]
    target = resolve_target(word_index, REPLACE_FROM)
    return ProofTarget(
        word_index=int(target["word_index"]),
        word=injected_words[-1],
        char_offset=start,
        erase_count=len(injected) - start,
        kept=injected[:start],
        original=injected,
        stamp=stamp,
        intent=str(target["intent"]),
    )


@dataclass(frozen=True)
class BargeIn:
    """What one barge-in found. ``target`` is ``None`` when nothing was armed.

    ``reason`` is one of ``armed``, ``not_playing`` (no read-back of a dictated
    burst was playing), ``nothing_heard`` (playback had not reached its first word)
    or ``unmapped`` (a word was identified but cannot be located in the typed text).
    """

    word_index: int
    word: str
    target: ProofTarget | None
    reason: str


@dataclass(frozen=True)
class Replacement:
    """The edit to perform on the replacement burst.

    With ``apply`` true: press ``erase_count`` backspaces, then type ``text``. With
    ``apply`` false: type ``text`` unchanged, exactly as ordinary dictation would.
    """

    apply: bool
    erase_count: int
    text: str
    reason: str


def plan_replacement(
    target: ProofTarget | None,
    text: str,
    *,
    current_stamp: float | None,
    streaming: bool,
    target_ok: bool | None,
) -> Replacement:
    """Decide whether an armed target may be applied to the burst *text*.

    Refuses (and leaves *text* to be typed as usual) when:

    * ``streaming`` — streamed words were already typed live after the old tail, so
      deleting from the end would eat them instead;
    * ``target_ok is False`` — the focused window holds no text field, so the
      backspaces would land somewhere else (the guard "scratch that" uses);
    * ``current_stamp != target.stamp`` — YazSes typed something since the read-back,
      so the end of the screen text is no longer the end of that burst;
    * the burst is blank — there is nothing to put in the erased text's place.
    """
    if target is None:
        return Replacement(False, 0, text, "none")
    if streaming:
        return Replacement(False, 0, text, "streaming")
    if target_ok is False:
        return Replacement(False, 0, text, "no_text_target")
    if current_stamp != target.stamp:
        return Replacement(False, 0, text, "burst_changed")
    body = text.lstrip()
    if not body:
        return Replacement(False, 0, text, "empty")
    # The kept prefix ends at the start of a word, so it already carries the space
    # before it (or is empty): the continuation space dictation prepends is dropped.
    return Replacement(True, target.erase_count, body, "applied")


# ---- Applying a replacement, and what to do when it fails -------------------------
#
# Applying a plan is two keyboard steps: erase the tail, then type the correction. The
# erase can succeed and the typing fail (a backend raises, reports failure, or the
# window refuses input part-way), and then the words the user dictated are gone with
# nothing in their place. The daemon therefore runs up to two recovery steps, and the
# functions below decide what each combination of results means:
#
#   1. restore — re-type the erased text through the same injector. It is known
#      exactly: it is the tail of the burst the target was armed on.
#   2. rescue  — if that fails too, put the erased text on the clipboard and say so.
#
# The undo records ("scratch that", the [timeline]) must describe what is on screen.
# When the screen is uncertain they never claim a longer burst than is certainly there
# (after a lost tail, only the kept prefix): undo deletes by count, so it can then
# delete too little, which the user sees and finishes by hand, but never more than
# YazSes typed, which would delete the user's own text.

#: The correction replaced the erased tail.
REPLACED = "replaced"
#: The correction could not be typed; the erased tail was typed back.
RESTORED = "restored"
#: Neither the correction nor the restore landed; the erased tail is on the clipboard.
RESCUED = "clipboard"
#: As :data:`RESCUED`, but the clipboard copy failed too.
UNSAVED = "clipboard_failed"


@dataclass(frozen=True)
class ReplacementOutcome:
    """What applying a replacement left behind, and what the user must be told.

    ``screen`` is the burst as YazSes believes it stands on screen. ``screen_known`` is
    false when a keyboard call failed: whether it delivered part of its text before
    failing cannot be seen from here. A failed erase may have deleted fewer characters
    than asked, and a failed type may have left a fragment of the correction (before
    the restored words, when they were typed back). Either way the burst on screen is
    *at least as long* as ``record``, which is what the newest undo record for the
    burst becomes (``""`` drops it): undo deletes by count, so it can then delete too
    little, never text before the burst.
    ``typed`` is true only when the correction landed, and the caller then records it
    as a burst of its own. ``notice`` is ``(title, body)`` for the user, or ``None``.
    Neither carries the transcript: dictated words stay out of notifications.
    """

    result: str
    screen: str
    screen_known: bool
    record: str
    typed: bool
    notice: tuple[str, str] | None


_CLIPBOARD_HINT = "paste them (Ctrl+V) where they were"
_APP_UNDO_HINT = "Your application's own undo (Ctrl+Z) may bring them back."


def rescue_text(
    target: ProofTarget, *, erased: bool, typed: bool, restored: bool
) -> str | None:
    """The text to put on the clipboard after the keyboard steps, or ``None``.

    Needed when the erase failed (some of the tail may be gone and the correction was
    never typed) or when the correction and the restore both failed (the tail is gone).
    """
    if erased and (typed or restored):
        return None
    return target.erased or None


def settle_replacement(
    target: ProofTarget,
    correction: str,
    *,
    erased: bool,
    typed: bool = False,
    restored: bool = False,
    copied: bool = False,
) -> ReplacementOutcome:
    """Map the results of erase → type → restore → clipboard onto records and a notice.

    A step that was not attempted is passed as ``False``: *typed* is ignored when the
    erase failed (the correction is never typed over an erase that stopped at an
    unknown point), *restored* when the correction landed, and *copied* when no
    rescue was needed.
    """
    kept = target.kept
    if erased and typed:
        return ReplacementOutcome(REPLACED, kept + correction, True, kept, True, None)
    if erased and restored:
        # The restore put back exactly the erased words, so the records stand as they
        # were. Unknown: whether the failed call typed a fragment of the correction
        # first (that would sit before the restored words, and only lengthen the burst).
        return ReplacementOutcome(
            RESTORED,
            target.original,
            False,
            target.original,
            False,
            (
                "⌨ Correction not typed",
                "YazSes could not type your correction, so it typed back the words it "
                "had erased. Dictate the correction again.",
            ),
        )
    if not erased:
        what = (
            "YazSes could not finish erasing the text from the word you interrupted, "
            "so it did not type your correction. Some of those words may be gone."
        )
    else:
        what = (
            "YazSes erased the text from the word you interrupted, then could not type "
            "your correction or type the erased words back."
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
    # erase sent at most `erase_count` backspaces, and the restore deleted only
    # characters of the correction that had certainly landed.
    return ReplacementOutcome(result, kept, False, kept, False, (title, body))


class InjectionTally:
    """An injector wrapper that counts what it delivered and makes failure an exception.

    ``typed`` counts the characters of :meth:`inject` calls that returned, so after a
    failure part-way through a paced (multi-call) correction the caller knows how much
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


@dataclass(eq=False)
class ReadbackSession:
    """One read-back of one injected burst, and the timeline its playback fills."""

    injected: str
    spoken: str
    stamp: float | None
    timeline: PlaybackTimeline
    playing: bool = False

    def on_chunk(self, text: str, n_samples: int, sample_rate: int, started_at: float) -> None:
        """Playback listener: record a sentence chunk as it starts playing."""
        self.timeline.add_chunk(text, n_samples, sample_rate, started_at)


class ProofbackController:
    """Tracks the read-back in progress and the target a barge-in armed.

    Thread-safe: playback reports on the read-back thread while a barge-in arrives
    on the hotkey thread. ``clock`` must be the clock the TTS backend stamps chunks
    with (``time.monotonic`` for Kokoro).
    """

    def __init__(self, clock: Clock, *, lag_s: float = 0.0, weight: Weight = char_weight) -> None:
        self._clock = clock
        self._lag_s = lag_s
        self._weight = weight
        self._lock = threading.Lock()
        self._current: ReadbackSession | None = None
        self._armed: ProofTarget | None = None

    def start_readback(self, injected: str, spoken: str, stamp: float | None) -> ReadbackSession:
        """A new session for the read-back of *injected* (spoken as *spoken*)."""
        return ReadbackSession(injected, spoken, stamp, PlaybackTimeline(self._weight))

    def playback_started(self, session: ReadbackSession | None) -> None:
        """An utterance began playing. ``None``: it is not a dictated burst."""
        with self._lock:
            self._current = session
            if session is not None:
                session.playing = True

    def playback_finished(self, session: ReadbackSession | None) -> None:
        """An utterance stopped playing (finished, cancelled, or failed)."""
        if session is None:
            return
        with self._lock:
            session.playing = False

    def barge_in(self) -> BargeIn:
        """A hold arrived during read-back: identify the word and arm the target.

        Disarms any earlier target first, so one press can never apply an older one.
        """
        now = self._clock()
        with self._lock:
            self._armed = None
            session = self._current
            self._current = None
            if session is None or not session.playing:
                return BargeIn(-1, "", None, "not_playing")
        index = session.timeline.word_at(now, lag_s=self._lag_s)
        if index < 0:
            return BargeIn(-1, "", None, "nothing_heard")
        words = session.spoken.split()
        word = words[index] if index < len(words) else ""
        target = resolve_barge_in(session.injected, session.spoken, index, session.stamp)
        if target is None:
            return BargeIn(index, word, None, "unmapped")
        with self._lock:
            self._armed = target
        return BargeIn(index, word, target, "armed")

    def disarm(self) -> None:
        """Forget any armed target (a hold that was not a barge-in)."""
        with self._lock:
            self._armed = None

    def take_armed(self) -> ProofTarget | None:
        """Pop the armed target: it applies to one burst at most."""
        with self._lock:
            target, self._armed = self._armed, None
            return target

    @property
    def armed(self) -> ProofTarget | None:
        with self._lock:
            return self._armed
