"""`yazses verify` must not certify a transcript the daemon would discard.

Found by running the product, not by reading it. `yazses verify` was run in a quiet room
with nobody speaking; ambient noise cleared the silence gate, the model answered with an
invented sentence, and the command printed **"✓ Dictation works end to end on this
machine."** The invented-sentence half is already handled deliberately — `verify` prints
the words rather than a count, precisely so the user can see it is not what they said.

Underneath it was a decidable defect. The daemon does not inject what the model returns;
it injects what survives `clean_text`, and a burst that cleans to nothing takes the
"Empty transcription -- discarding" branch, plays the error earcon, and types nothing.
`verify` checked `text.strip()` on the **raw** string, so:

    Whisper returns "[BLANK_AUDIO]"   — the commonest thing it emits for silence
    daemon  → clean_text() == ""      → discards, types nothing, every time
    verify  → "[BLANK_AUDIO]".strip() is truthy
            → heard "[BLANK_AUDIO]"
            → ✓ Dictation works end to end on this machine

A muted microphone passed the one check in the project whose entire job is to find the
broken link — and `verify`'s own docstring claims it "runs the real chain". It ran the
chain minus the step that decides whether anything is typed.

## Why the artefacts are not listed here

The cases are taken from `clean_text` itself rather than a list copied into this file. A
copied list drifts: the cleaner learns a new artefact, the guard keeps passing the old
one, and the two silently disagree again — which is the whole defect, one layer up.
"""

from __future__ import annotations

import pytest

from yazses.postprocess.cleaner import clean_text
from yazses.system.verify import verify

#: Real strings Whisper emits for silence. Each is asserted below to be non-empty *and*
#: cleaned away — so if the cleaner stops handling one, this file fails rather than
#: quietly testing nothing.
SILENCE_ARTEFACTS = ["[BLANK_AUDIO]", "(blank)", " . "]


def _run(transcribed: str, inject=None):
    """verify() with every backend stubbed: audible capture, gate cleared."""
    return verify(
        record=lambda: object(),
        level_of=lambda _a: 0.0122,  # the level measured in that quiet room
        threshold=0.0005,
        transcribe=lambda _a: transcribed,
        inject=inject,
    )


@pytest.mark.parametrize("artefact", SILENCE_ARTEFACTS)
def test_the_artefact_is_the_shape_that_fooled_it(artefact: str) -> None:
    """The premise, checked against the cleaner rather than assumed.

    Non-empty raw (so the old `text.strip()` check passed it) and empty once cleaned
    (so the daemon discards it). A case that stops satisfying both is no longer this
    bug, and pretending otherwise makes the test below vacuous.
    """
    assert artefact.strip(), "not a case the raw-string check would have passed"
    assert not clean_text(artefact).strip(), "the cleaner no longer removes this"


@pytest.mark.parametrize("artefact", SILENCE_ARTEFACTS)
def test_verify_fails_on_a_transcript_the_daemon_would_discard(artefact: str) -> None:
    result = _run(artefact)
    assert not result.ok, (
        f"verify certified {artefact!r} as working; the daemon cleans it to nothing and "
        "types nothing. A muted microphone would pass the check meant to catch it."
    )
    failure = result.failure
    assert failure is not None and failure.name == "Transcription"
    # The advice must point at the microphone. "Try a larger model" is the wrong fix
    # here and sends the user to download gigabytes for a muted input device.
    assert "microphone" in failure.detail.lower()
    assert "yazses audio status" in failure.detail


def test_the_earlier_steps_still_pass_so_the_report_names_the_right_link() -> None:
    """Stopping at the first broken link is the command's whole design."""
    result = _run("[BLANK_AUDIO]")
    named = {s.name: s.ok for s in result.steps}
    assert named["Capture"] is True
    assert named["Signal"] is True
    assert named["Transcription"] is False
    assert "Injection" not in named, "should stop before injecting a discarded transcript"


def test_real_speech_still_passes() -> None:
    """A guard that fails on working input is worse than the bug it fixes."""
    result = _run("hello world, this is a real sentence")
    assert result.ok, [s for s in result.steps if not s.ok]
    assert result.failure is None


def test_the_cleaned_text_is_what_gets_injected() -> None:
    """Verify must prove the string the daemon would type, not the raw one.

    `clean_text` also strips leading punctuation, so raw and cleaned differ on ordinary
    speech too — injecting the raw string would verify a slightly different chain than
    the one that runs.
    """
    injected: list[str] = []
    raw = ". hello world"
    assert clean_text(raw) != raw, "pick a case the cleaner actually changes"
    result = _run(raw, inject=injected.append)
    assert result.ok, [s for s in result.steps if not s.ok]
    assert injected == [clean_text(raw)], (
        f"verify injected {injected!r}; the daemon would type {clean_text(raw)!r}"
    )
