"""Learn the silence threshold from what actually happens, instead of trusting a number.

``[accessibility] vad_threshold`` is a single float that decides whether a burst was speech
or silence, and it is wrong by construction: the right value depends on the microphone, the
room, and the speaker, so a number that fits one machine fits no other and stops fitting the
same machine when any of those change. When it drifts too high the failure is the worst kind
— you hold the key, you speak, nothing is typed, and the only evidence is a log line you
have no reason to read.

That is not hypothetical. On the machine this was written on, a laptop's digital microphone
array produced ``mean|audio|`` around 0.003–0.005 **at full gain**, sitting right against a
threshold of 0.0024. Turning the microphone up was not available: it was already at 100%.

So watch the outcomes instead. Bursts that transcribe are speech; bursts discarded as
silence are candidates for being speech that was wrongly rejected. A *run* of discards with
no successes between them is the signature of a threshold set above the user's actual voice,
and the level of those discarded bursts says exactly where it should have been.

Deliberately one-directional. Lowering the gate when speech is being lost restores a broken
setup; raising it when noise leaks through merely trims transcripts the user can see and
delete. Only the first failure is silent, so only the first is automated.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Enough consecutive discards to rule out ordinary causes — a brushed hotkey, a hold
# released before speaking. Matches the default silent-streak notification threshold.
DEFAULT_MIN_DISCARDS = 3
# Leave the new gate below the quietest rejected burst, so the speech that was being lost
# now passes with room to spare rather than landing exactly on the boundary.
SAFETY_FACTOR = 0.6
# Never propose a gate so low that room tone reads as speech.
MIN_THRESHOLD = 0.0005


@dataclass
class AdaptiveThreshold:
    """Watches discard/success outcomes and proposes a threshold when one is losing speech.

    Pure and side-effect free: it observes and suggests, and the caller decides whether to
    apply, persist, or merely mention it. That split keeps the policy testable without a
    microphone and lets the daemon stay in charge of anything user-visible.
    """

    min_discards: int = DEFAULT_MIN_DISCARDS
    safety_factor: float = SAFETY_FACTOR
    min_threshold: float = MIN_THRESHOLD
    _discarded: list[float] = field(default_factory=list)

    def observe_speech(self, level: float) -> None:
        """A burst transcribed successfully — the gate is working, forget the streak."""
        self._discarded.clear()

    def observe_discard(self, level: float) -> None:
        """A burst was rejected as silence at this level."""
        if level > 0:
            self._discarded.append(float(level))

    @property
    def streak(self) -> int:
        return len(self._discarded)

    def suggest(self, current: float) -> float | None:
        """A threshold that would have let the rejected bursts through, or ``None``.

        ``None`` means "not enough evidence, or the gate is not what is wrong" — a caller
        must never treat a suggestion as mandatory, because the same symptom is produced by
        a muted or dead microphone, where lowering the gate fixes nothing and only makes
        the next failure noisier.
        """
        if len(self._discarded) < self.min_discards:
            return None
        loudest = max(self._discarded)
        if loudest >= current:
            # These bursts were above the gate, so the gate is not why they were dropped.
            return None
        proposed = max(loudest * self.safety_factor, self.min_threshold)
        if proposed >= current:
            return None  # no actual improvement to offer
        return proposed

    def reset(self) -> None:
        self._discarded.clear()
