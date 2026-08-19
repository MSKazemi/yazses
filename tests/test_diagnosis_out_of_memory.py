"""Running out of memory was answered with "try once more", which cannot work.

`system/diagnosis.py` turns a caught failure into something the user can act on, and states
its own rule: *"Say the next command, not the category."* A decode failure it does not
recognise falls through to the stage wording:

    YazSes could not transcribe that
    The speech model failed while decoding what you said.
    Try once more. If it keeps happening, `yazses report` collects the details…

For a `MemoryError` that advice is not merely vague, it is wrong. The next attempt allocates
the same model and fails the same way, so "try once more" spends the user's time proving it.

The fix is a setting the project already exposes and documents: a smaller `[stt] model`. On
CPU, `medium` and `large-v3` are exactly the choices a user makes optimistically and a
low-memory machine refuses.

## Matched on the class name as well as the text

A bare `MemoryError()` carries **no message at all**, so a text-only rule would never fire on
the commonest form. The table matches markers against the exception text *and* its class
name for this reason, which is already noted where `PortAudioError` carries only a numeric
message. `ctranslate2` reports allocation failures in its own words, so "cannot allocate
memory" is matched too.

## Still advice, never a decision

Nothing changes what the daemon does — the module's second rule. A wrong guess here costs a
misleading sentence, not a working feature.
"""

from __future__ import annotations

import pytest

from yazses.system.diagnosis import CAPTURE, INJECT, TRANSCRIBE, diagnose


@pytest.mark.parametrize(
    "error",
    [
        MemoryError(),
        MemoryError("cannot allocate memory"),
        RuntimeError("CT2: cannot allocate memory of size 1073741824"),
        OSError("Cannot allocate memory"),
    ],
)
def test_an_out_of_memory_failure_names_the_real_fix(error) -> None:
    result = diagnose(error, where=TRANSCRIBE)
    assert "memory" in result.title.lower()
    assert "[stt] model" in result.fix, "the fix must name the setting to change"


@pytest.mark.parametrize("error", [MemoryError(), MemoryError("cannot allocate memory")])
def test_it_no_longer_tells_the_user_to_try_again(error) -> None:
    """The specific defect: retrying allocates the same model and fails the same way."""
    result = diagnose(error, where=TRANSCRIBE)
    text = f"{result.what} {result.fix}".lower()
    assert "try once more" not in text
    assert "will fail the same way" in text, (
        "the message should say retrying is pointless, not merely omit the suggestion"
    )


def test_a_bare_memory_error_is_still_matched() -> None:
    """`MemoryError()` carries no message, so a text-only rule would never fire on the
    commonest form of this failure."""
    assert str(MemoryError()) == ""
    assert "memory" in diagnose(MemoryError(), where=TRANSCRIBE).title.lower()


def test_ordinary_decode_failures_keep_the_generic_advice() -> None:
    """The expensive direction: a rule that swallowed every decode error would tell
    everyone to shrink their model, which is wrong for almost all of them."""
    result = diagnose(RuntimeError("tensor shape mismatch"), where=TRANSCRIBE)
    assert "memory" not in result.title.lower()
    assert "try once more" in f"{result.what} {result.fix}".lower()


@pytest.mark.parametrize("where", [CAPTURE, INJECT])
def test_the_microphone_and_injector_rules_are_unaffected(where: str) -> None:
    """The new rules sit first in the table, so the ones after them must still win
    on their own markers."""
    mic = diagnose(OSError("Device unavailable"), where=CAPTURE)
    assert "microphone" in mic.title.lower()
    typing = diagnose(FileNotFoundError("xdotool"), where=INJECT)
    assert "type" in typing.title.lower()


def test_every_failure_still_gets_a_diagnosis() -> None:
    """The module's first rule: an unrecognised error must not go quiet."""
    result = diagnose(ValueError("something nobody predicted"), where=TRANSCRIBE)
    assert result.title
    assert result.fix
    assert "yazses report" in result.fix
