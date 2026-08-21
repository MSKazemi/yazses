"""`yazses verify` certified a microphone that was hearing nobody.

Run for real in a quiet room with nobody speaking:

    [OK] Capture: recorded audio from the input device
    [OK] Signal: level 0.0044 clears the gate (0.0005)
    [OK] Transcription: heard "You"
    [OK] Injection: skipped (not requested)

    ✓ Dictation works end to end on this machine.

Room noise cleared the gate, the model answered near-silence with a confident invented
word, and the one command whose entire job is to find the broken link declared success.
`verify` is the project's only check that produces evidence rather than inference, so a
false pass there is the most expensive false pass it has.

Two separate faults, fixed separately, because they have different remedies.

## 1. The known artefacts were never checked

`clean_text` strips `[BLANK_AUDIO]`, and an earlier fix made `verify` run it — but
Whisper's *other* silence artefacts are ordinary English and survive cleaning. The repo
already recognises them: `postprocess/hallucination.py` has the outro list and the
repetition-loop detector, and `verify` never asked. A clip of pure room noise decoding to
"Thanks for watching" printed as a passing step.

Only whole-transcript matches are used, which is that module's own premise — nobody
dictates "please subscribe" as an entire utterance.

## 2. The verdict claimed more than the run proved

`verify` can prove the chain *ran*. Only the user can say the words are the ones they
spoke. The code already reasoned its way to that — *"whether it is what you said can [be
decided] by you, instantly, if it is on the screen"* — and put the transcript on the
screen, but the summary line underneath still read "Dictation works end to end on this
machine", unconditionally. That tick is the line people read.

## What is deliberately NOT fixed

"You" still passes. It is the commonest thing this model returns for silence *and* an
ordinary English word somebody may have said. Adding it to the ghost list would fail real
dictation.

The asymmetry runs the opposite way here than it does on the daemon's hot path: a `verify`
that wrongly passes costs one confusing session, while a `verify` that wrongly fails sends
someone off to re-calibrate a microphone that was fine. So the automated checks stop at the
artefacts with no legitimate reading, and the judgement that needs a human gets handed to
the human with the evidence next to it.
"""

from __future__ import annotations

import pytest

from yazses.system.verify import verify


def _run(text: str):
    return verify(
        record=lambda: "AUDIO",
        level_of=lambda _a: 0.01,
        threshold=0.001,
        transcribe=lambda _a: text,
    )


def _transcription_step(result):
    return next(s for s in result.steps if s.name == "Transcription")


@pytest.mark.parametrize(
    "artefact",
    [
        "Thanks for watching!",
        "Thanks for watching",
        "please subscribe",
        "Like and subscribe.",
        "See you next time!",
        "Thank you for watching",
    ],
)
def test_a_known_silence_artefact_is_not_a_passing_verify(artefact: str) -> None:
    result = _run(artefact)
    assert not result.ok, f"verify certified the chain on {artefact!r}"
    step = _transcription_step(result)
    assert not step.ok
    assert "audio status" in step.detail, "the failure must name what to check"


def test_a_repetition_loop_is_reported_as_a_decode_failure() -> None:
    """A different fault with a different remedy — the model, not the mic."""
    result = _run("okay okay okay okay okay")
    assert not result.ok
    detail = _transcription_step(result).detail
    assert "looped" in detail
    assert "stt] model" in detail or "mic-level" in detail


@pytest.mark.parametrize(
    "real",
    [
        "the quick brown fox jumps over the lazy dog",
        "You",
        "Thank you.",
        "I think you should subscribe to that feed",
        "please subscribe me to the mailing list when you get a chance",
    ],
)
def test_real_speech_still_passes(real: str) -> None:
    """The expensive direction. A verify that wrongly fails sends someone to
    re-calibrate a microphone that was fine.

    Note "Thank you." and the two sentences containing "subscribe": the check is
    whole-transcript only, so an outro phrase appearing *inside* real speech is untouched.
    """
    result = _run(real)
    assert result.ok, f"verify failed on real speech: {real!r}"


def test_you_deliberately_still_passes() -> None:
    """Pinned as a decision, not an oversight.

    "You" is the commonest thing Whisper returns for silence and an ordinary word someone
    may have said. No automated check separates those, so it is shown to the user rather
    than judged — which is why the verdict line had to change instead.
    """
    result = _run("You")
    assert result.ok
    assert 'heard "You"' in _transcription_step(result).detail


def test_the_earlier_blank_audio_guard_still_holds() -> None:
    """`clean_text` removes it entirely, so the burst is empty and verify must fail."""
    result = _run("[BLANK_AUDIO]")
    assert not result.ok
    assert "silence" in _transcription_step(result).detail


def test_the_verdict_no_longer_claims_dictation_works() -> None:
    """The line people actually read.

    verify proves the chain ran; only the user can confirm the words. Asserted on the CLI
    source because the string is the product here.
    """
    import inspect

    from yazses.cli import verify as verify_cmd

    source = inspect.getsource(verify_cmd)
    assert "Dictation works end to end on this machine." not in source, (
        "the unconditional verdict is back — verify cannot know the transcript is what "
        "was said"
    )
    assert "The whole chain ran" in source
    assert "if that is not what you said" in source
    assert "mic-level" in source, "a user who does not recognise the words needs a next step"


def test_the_chain_still_stops_at_the_first_broken_link() -> None:
    """The property the whole module is built around; the new checks sit inside it."""
    result = verify(
        record=lambda: "AUDIO",
        level_of=lambda _a: 0.0,
        threshold=0.001,
        transcribe=lambda _a: "Thanks for watching",
    )
    assert [s.name for s in result.steps] == ["Capture", "Signal"]
    assert result.failure is not None and result.failure.name == "Signal"
