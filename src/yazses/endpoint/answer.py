"""When a spoken answer to ``ask_human`` is over (#640, ADR-032 §3). Pure.

The listener used to record for the caller's whole timeout, up to two minutes, so a
two-word "yes, go ahead" held the microphone, and blocked dictation, until the agent's
wait ran out. This ends it the way a person ends an answer: once they have spoken and
then stopped.

The parts are the hands-free auto-stop's (:mod:`yazses.endpoint.autostop`), not a second
copy: :func:`~yazses.endpoint.autostop.should_stop` for "trailing silence reached the
limit, or the hard cap did", and :data:`~yazses.endpoint.autostop.MIN_SILENCE_TIMEOUT_MS`
as the floor under which a between-word pause would cut a sentence. What differs is only
the configuration: the cap is the caller's timeout, and the no-speech grace is
``[mcp] ask_human_no_speech_s`` rather than a hotkey tap's five seconds.

Fed one observation per poll -- speech or not, by the caller's own gate -- with the
clock passed in, so it is tested without a microphone or a sleep.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.endpoint.autostop import MIN_SILENCE_TIMEOUT_MS, should_stop

#: The answer was given: speech, then ``end_silence_s`` of quiet.
ANSWERED = "answered"
#: Nothing was said within ``no_speech_s``. The caller returns "" without decoding.
NO_SPEECH = "no_speech"
#: The caller's timeout ran out. Whatever was recorded is decoded.
TIMEOUT = "timeout"

#: The listener never records less than this, whatever the caller asks for (it always
#: did): a sub-second wait cannot hold an answer, only the start of one.
MIN_TIMEOUT_S = 1.0


@dataclass(frozen=True)
class _Limits:
    """The shape :func:`should_stop` reads, filled from the ``ask_human`` settings."""

    enabled: bool
    max_duration_ms: float
    silence_timeout_ms: float


class AnswerEndpoint:
    """Decides, poll by poll, when a spoken answer is complete. Not thread-safe: one
    listener owns one instance for one question."""

    def __init__(
        self, *, started_at: float, timeout_s: float, end_silence_s: float, no_speech_s: float
    ) -> None:
        self._started_at = started_at
        self._limits = _Limits(
            enabled=True,
            max_duration_ms=max(MIN_TIMEOUT_S, float(timeout_s)) * 1000.0,
            silence_timeout_ms=max(float(end_silence_s) * 1000.0, float(MIN_SILENCE_TIMEOUT_MS)),
        )
        self._no_speech_ms = max(0.0, float(no_speech_s)) * 1000.0
        self._heard = False
        self._silent_since: float | None = None

    @property
    def heard(self) -> bool:
        """Whether any speech has been observed yet."""
        return self._heard

    def observe(self, now: float, speech: bool) -> str | None:
        """One poll. ``None`` = keep listening; otherwise why the answer is over.

        The cap is checked first (inside :func:`should_stop`), so neither a long answer
        nor a user who keeps talking can outlast the caller's timeout. Silence only
        counts once speech has been heard, so a pause before answering is thinking, not
        an empty reply; that case is the no-speech grace's to end.
        """
        if speech:
            self._heard = True
            self._silent_since = None
        elif self._heard and self._silent_since is None:
            self._silent_since = now
        elapsed_ms = (now - self._started_at) * 1000.0
        silence_ms = (now - self._silent_since) * 1000.0 if self._silent_since is not None else 0.0
        if should_stop(silence_ms, elapsed_ms, self._limits):
            capped = elapsed_ms >= self._limits.max_duration_ms
            if capped and not self._heard:
                return NO_SPEECH
            return TIMEOUT if capped else ANSWERED
        # 0 disables the early give-up (the timeout governs) rather than ending every
        # question on its first poll, which is all a literal zero could mean.
        if not self._heard and self._no_speech_ms > 0 and elapsed_ms >= self._no_speech_ms:
            return NO_SPEECH
        return None
