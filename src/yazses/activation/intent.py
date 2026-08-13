"""Activation intents — a source may say *what* it meant, not just *when* (#137).

``HotkeyBackend`` can express exactly two things: a hold started, and a hold
ended. That is the whole vocabulary of a key, and it is enough for a key. It is
not enough for anything that decodes meaning.

Every silent-speech and BCI system in the literature produces something richer —
a command label with a confidence — and none of it fits through an onset/offset
seam. A decoder that recognises "undo" at 96% confidence (Tang, arXiv:2504.13921;
Kurotaki, doi:10.1002/aisy.70440) has to discard the label, emit a bare onset,
and wait for the user to say the word out loud. That is the opposite of what a
silent interface is for.

Two design rules make this safe to add:

* **An intent is a label, never free text.** Non-invasive decoding sits around
  68% WER (Gaddy & Klein), so injecting decoded prose would be typing noise. A
  label drawn from a small declared vocabulary is the part that is reliable.
* **An intent goes through the existing command grammar.** ``handle_intent``
  hands the label to ``commands.grammar.classify`` and the result to the same
  ``dispatch`` a spoken command uses, so a silent "undo" and a spoken "undo"
  cannot drift apart — there is only one implementation of what "undo" means.

A source declares its vocabulary up front, so the daemon can reject a label the
source never claimed it could produce. ``EMGBackend`` keeps working untouched:
it declares no vocabulary and emits no intents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ActivationIntent:
    """One decoded intent from an activation source.

    ``confidence`` is the source's own probability for ``label``, in [0, 1].
    ``source`` names the emitting backend for logs and for the confirmation
    prompt — a user being asked to confirm should be told what asked.
    """

    label: str
    confidence: float
    source: str = ""


class Rejection(Enum):
    """Why an intent was refused before it reached the command grammar."""

    EMPTY_LABEL = "empty label"
    OUT_OF_VOCABULARY = "label is not in the source's declared vocabulary"
    BAD_CONFIDENCE = "confidence is not a real number in [0, 1]"
    NO_VOCABULARY = "source declared no vocabulary, so it may not emit intents"


@runtime_checkable
class IntentSource(Protocol):
    """An activation source that can emit intents as well as onset/offset.

    Structural, not inherited: a decoder implements ``vocabulary`` and calls the
    callback it was given. Sources that only trigger (the EMG squeeze, a key)
    simply do not satisfy this protocol, and nothing asks them to.
    """

    @property
    def vocabulary(self) -> tuple[str, ...]:
        """Every label this source may ever emit. Empty means trigger-only."""


def validate(intent: ActivationIntent, vocabulary: tuple[str, ...]) -> Rejection | None:
    """Check an intent against its source's declared vocabulary. Pure.

    Returns ``None`` when the intent is acceptable, otherwise the reason. The
    vocabulary check is the load-bearing one: it is what stops a
    mis-decoded or malicious label reaching ``dispatch`` and executing something
    the source never advertised it could ask for.
    """
    if not intent.label or not intent.label.strip():
        return Rejection.EMPTY_LABEL
    if not vocabulary:
        return Rejection.NO_VOCABULARY
    # NaN fails every comparison, so test it explicitly rather than relying on
    # the range check below to catch it.
    if not isinstance(intent.confidence, (int, float)) or isinstance(intent.confidence, bool):
        return Rejection.BAD_CONFIDENCE
    if math.isnan(intent.confidence) or not 0.0 <= float(intent.confidence) <= 1.0:
        return Rejection.BAD_CONFIDENCE
    if intent.label not in vocabulary:
        return Rejection.OUT_OF_VOCABULARY
    return None
