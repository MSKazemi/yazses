"""Prove the whole pipeline works on this machine, rather than inferring it.

``yazses doctor`` checks prerequisites: is a mic present, is xdotool installed, is the
model cached. Every one of those can pass while dictation still produces nothing — the
threshold can sit above the user's voice, the injector can be pointed at a window that
ignores synthetic keys, the model can load and return empty text. Prerequisites are
evidence *about* the parts; they are not evidence that the parts work together.

This runs the real chain end to end — capture, the silence gate, transcription, injection —
against a target the user cannot lose text into, and reports which link broke. It is the
only check in the project that produces evidence rather than inference, so it is also the
only honest answer to "is it definitely going to work when I press the key?".

Backends are injected, so the whole flow is testable without a microphone or a desktop.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Step:
    """One link in the chain, and what it proved."""

    name: str
    ok: bool
    detail: str


@dataclass
class VerifyResult:
    steps: list[Step] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(step.ok for step in self.steps)

    @property
    def failure(self) -> Step | None:
        """The first broken link — the one worth acting on."""
        return next((s for s in self.steps if not s.ok), None)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.steps.append(Step(name, ok, detail))


def verify(
    *,
    record: Callable[[], object],
    level_of: Callable[[object], float],
    threshold: float,
    transcribe: Callable[[object], str],
    inject: Callable[[str], None] | None = None,
) -> VerifyResult:
    """Run capture → gate → transcribe → inject, stopping at the first broken link.

    Stopping early is the point: once capture returns silence, every later step would fail
    for a reason that is not its own fault, and a report listing four failures hides which
    one to fix.
    """
    result = VerifyResult()

    try:
        audio = record()
    except Exception as exc:  # noqa: BLE001 — the failure IS the result here
        result.add("Capture", False, f"could not record: {exc}")
        return result
    result.add("Capture", True, "recorded audio from the input device")

    try:
        level = level_of(audio)
    except Exception as exc:  # noqa: BLE001
        result.add("Signal", False, f"could not measure the recording: {exc}")
        return result

    if level <= 0:
        result.add(
            "Signal", False,
            "the recording is pure silence — the microphone is muted, dead, or not the "
            "one YazSes is using. Check `yazses audio devices`.",
        )
        return result
    if level < threshold:
        result.add(
            "Signal", False,
            f"level {level:.4f} is below the silence gate {threshold:.4f}, so real speech "
            f"would be discarded. Fix with `yazses mic-level --set`.",
        )
        return result
    result.add("Signal", True, f"level {level:.4f} clears the gate ({threshold:.4f})")

    try:
        text = transcribe(audio)
    except Exception as exc:  # noqa: BLE001
        result.add("Transcription", False, f"the model failed: {exc}")
        return result
    if not text.strip():
        result.add(
            "Transcription", False,
            "the model returned nothing. Audio reached it, so this is the model or the "
            "language — try a larger one with `[stt] model`.",
        )
        return result
    # Show the words, not a count of them. A count cannot be checked against what
    # you said, so it cannot contradict anything: run in a quiet room with nobody
    # speaking, this printed "produced 1 word(s)" and then "Dictation works end to
    # end", because ambient noise cleared the gate and the model answered
    # near-silence with a confident invented word. That is the real shape of a
    # muted or wrong microphone in a room with any noise in it.
    #
    # Whether a word is invented cannot be decided reliably. Whether it is what you
    # said can -- by you, instantly, if it is on the screen.
    spoken = " ".join(text.split())
    n = len(text.split())
    shown = spoken if len(spoken) <= 60 else spoken[:59].rstrip() + "\u2026"
    detail = f'heard "{shown}"' + (f" ({n} words)" if n > 8 else "")
    result.add("Transcription", True, detail)

    if inject is None:
        result.add("Injection", True, "skipped (not requested)")
        return result
    try:
        inject(text)
    except Exception as exc:  # noqa: BLE001
        result.add("Injection", False, f"could not type the text: {exc}")
        return result
    result.add("Injection", True, "typed the transcript into the focused window")
    return result
