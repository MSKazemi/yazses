"""Prove the whole pipeline works on this machine, rather than inferring it.

``yazses doctor`` checks prerequisites: is a mic present, is xdotool installed, is the
model cached. Every one of those can pass while dictation still produces nothing — the
threshold can sit above the user's voice, the injector can be pointed at a window that
ignores synthetic keys, the model can load and return empty text. Prerequisites are
evidence *about* the parts; they are not evidence that the parts work together.

This runs the real chain end to end — capture, the silence gate, transcription, *cleaning*,
injection — against a target the user cannot lose text into, and reports which link broke.
The cleaning step is not decoration: the daemon injects what survives ``clean_text``, not
what the model returned, so a check that skipped it certified transcripts the daemon
discards. It is the
only check in the project that produces evidence rather than inference, so it is also the
only honest answer to "is it definitely going to work when I press the key?".

Backends are injected, so the whole flow is testable without a microphone or a desktop —
including the speech detector, which is why a machine with no Silero asset degrades to
today's behaviour instead of failing.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from yazses.postprocess.cleaner import clean_text


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


#: How far above the silence gate a level has to sit before it is unremarkable.
#: Measured on 172 real bursts from a live daemon log: the **quietest** burst that
#: produced any text at all was 0.0081 against a 0.0040 gate, i.e. 2.0x, while the
#: bursts that decoded to nothing had a median of 0.0071. At exactly 2x, a margin note
#: would have covered 26 of the 41 empty bursts and **none** of the 131 real ones.
_CLEAR_MARGIN = 2.0


def signal_detail(level: float, threshold: float) -> str:
    """The Signal line — and, when the level barely cleared, how barely.

    The module already refuses to judge whether a *transcript* was invented (see the
    long note further down: that call belongs to the user). This is the other half of
    the same problem and it is a **measurement**, not a judgement: nothing reported how
    close the level was to the gate, and near-silence is precisely the regime where the
    model answers with a confident, entirely ordinary English sentence.

    That is not hypothetical. Four consecutive runs in a quiet room, gate 0.0040:

        level 0.0052 -> "I thought I was going to say the same thing before."
        level 0.0054 -> "I just want you to know that it's your fault."
        level 0.0060 -> "Okay. It's going to be fine."
        level 0.0052 -> ". . . . . . ." (caught -- the only one `clean_text` could catch)

    Three of the four printed as a passing Transcription step. None of them is a ghost
    phrase, a repetition loop, or blank; nothing downstream can tell them from speech,
    and it should not try. What it *can* say is that the microphone was barely above the
    gate the whole time — which is the fact that makes the sentence interpretable, and
    the one the user needs to act on the right thing.

    A disabled gate (`vad_threshold = 0`) needs no special case: the comparison is a
    multiplication, so every non-negative level clears `0 * _CLEAR_MARGIN` and gets the
    plain line. Written the other way round -- dividing first, then comparing -- the same
    input raises. Worth saying, because the note *reports* a ratio, which makes dividing
    first look like the obvious spelling.
    """
    base = f"level {level:.4f} clears the gate ({threshold:.4f})"
    if level >= threshold * _CLEAR_MARGIN:
        return base
    return (
        f"{base} — but only just ({level / threshold:.1f}x). Speech normally sits well "
        f"clear of it; noise this close is what the model answers with a confident "
        f"invented sentence. If the transcript below is not what you said, raise the "
        f"gate with `yazses mic-level --set` before suspecting the microphone."
    )


def verify(
    *,
    record: Callable[[], object],
    level_of: Callable[[object], float],
    threshold: float,
    transcribe: Callable[[object], str],
    inject: Callable[[str], None] | None = None,
    holds_no_speech: Callable[[object], bool | None] | None = None,
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
    result.add("Signal", True, signal_detail(level, threshold))

    # Ask the audio, not the transcript. The long note further down explains why this
    # module refuses to judge whether a *word* was invented, and that stands: "You" is
    # the commonest thing the model returns for silence and also an ordinary English
    # word. But that dilemma only exists on the output side. On the input side the
    # question has an answer, and `recimport/audio_io.holds_no_speech` already gives it
    # — a bundled Silero detector, nothing downloaded, nothing sent (ADR-011).
    #
    # Without this, the two commands contradicted each other on the same room, the same
    # minute, the same microphone: `yazses verify` printed `[OK] heard "You"` under
    # "The whole chain ran", while `yazses transcribe` on a clip of that room said "no
    # speech was recognised". The one that certified the pipeline is the one people are
    # sent to when dictation has stopped working.
    #
    # Only an explicit True acts. `None` means the detector could not run, and inventing
    # a verdict there would be the failure this exists to prevent, one layer up.
    if holds_no_speech is not None and holds_no_speech(audio) is True:
        result.add(
            "Speech", False,
            "the level cleared the gate but a speech detector found no speech anywhere "
            "in the recording — so whatever the model returns next is invented, not "
            "heard. Something is being captured; it is not your voice. Check the mic is "
            "unmuted and is the one being used: `yazses audio status`.",
        )
        return result

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
    # The daemon does not inject what the model returns; it injects what survives
    # `clean_text`, and a burst cleaned to nothing is discarded (core/daemon.py, the
    # "Empty transcription" branch). Verifying the raw string instead certified a chain
    # the daemon would silently drop: `[BLANK_AUDIO]` is the commonest thing Whisper
    # emits for silence, it is non-empty, and it printed as `heard "[BLANK_AUDIO]"`
    # above "Dictation works end to end on this machine". A muted microphone therefore
    # passed the one check whose entire job is to find the broken link.
    cleaned = clean_text(text)
    if not cleaned.strip():
        result.add(
            "Transcription", False,
            f'the model heard silence and returned only "{" ".join(text.split())[:40]}", '
            "which is discarded before anything is typed. The level cleared the gate, so "
            "something is being captured — but not your voice. Check the microphone is "
            "unmuted and is the one being captured: `yazses audio status`.",
        )
        return result
    # `clean_text` strips `[BLANK_AUDIO]`, but the model's other silence artefacts are
    # ordinary English and survive it. `postprocess/hallucination.py` already recognises
    # them and verify never asked: a clip of pure room noise decoding to "Thanks for
    # watching" printed as a passing Transcription step under "Dictation works end to end".
    #
    # Only whole-transcript matches against the outro list are used, which is that
    # module's own premise -- nobody dictates "please subscribe" as an entire utterance.
    # Nothing here is a general "does this look invented?" test, and it must not become
    # one: see the note below on why that call belongs to the user.
    from yazses.postprocess.hallucination import is_ghost_phrase, is_repetition_loop

    if is_ghost_phrase(cleaned):
        result.add(
            "Transcription", False,
            f'the model returned "{" ".join(cleaned.split())[:40]}" -- a phrase Whisper '
            "invents for silence, not something anyone dictates. The level cleared the "
            "gate, so something is being captured, but not your voice. Check the mic is "
            "unmuted and is the one being used: `yazses audio status`.",
        )
        return result
    if is_repetition_loop(cleaned):
        result.add(
            "Transcription", False,
            f'the model looped on one phrase ("{" ".join(cleaned.split())[:40]}"), which '
            "is a decode failure rather than speech. Try a larger `[stt] model`, or check "
            "the recording is not near-silence: `yazses mic-level`.",
        )
        return result

    text = cleaned
    # Show the words, not a count of them. A count cannot be checked against what
    # you said, so it cannot contradict anything: run in a quiet room with nobody
    # speaking, this printed "produced 1 word(s)" and then "Dictation works end to
    # end", because ambient noise cleared the gate and the model answered
    # near-silence with a confident invented word. That is the real shape of a
    # muted or wrong microphone in a room with any noise in it.
    #
    # Whether a word is invented cannot be decided reliably. Whether it is what you
    # said can -- by you, instantly, if it is on the screen.
    #
    # And that is exactly why the checks above stop at the KNOWN artefacts. "You" is the
    # commonest thing this model returns for silence, and it is also an ordinary English
    # word somebody may well have said -- adding it to the ghost list would fail a real
    # dictation. The asymmetry runs the other way here than in the daemon: a verify that
    # wrongly passes costs one confusing session, a verify that wrongly fails sends
    # someone to re-calibrate a microphone that was fine.
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
