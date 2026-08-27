"""A rule fired precisely when its own diagnosis was impossible.

`audio-backend-missing` matched the marker `"portaudio"` and answered:

    YazSes cannot reach your sound system
    The audio backend PortAudio could not be loaded or found no devices.
    On Linux install it with `sudo apt install libportaudio2`…

PortAudio puts its own name in the exception class, so that marker caught **every**
`PortAudioError` — and a `PortAudioError` can only be raised by a PortAudio that loaded.
The advice was to install a library that is demonstrably present, because it is the thing
that raised.

Four error codes were landing there, verified against the installed library:

    -9997  Invalid sample rate
    -9999  Unanticipated host error
    -9986  Internal PortAudio error
    -9973  Incompatible stream host API

## The one worth its own rule

`[audio] sample_rate` is a documented, editable key, so `-9997` is a realistic edit rather
than an exotic failure — someone setting 44100 or 48000 on a device that will not do it. It
now names the setting and the value to go back to.

The other three fall through to the stage wording. That says less, and says nothing false,
which is the right trade: this module's second rule is that a diagnosis is advice, and its
first is that an unrecognised error still gets a message.

## What a genuine load failure looks like

`sounddevice` raises `OSError("PortAudio library not found")` — read out of the installed
package, not remembered. That is what the narrowed rule matches, and it is the only case
where "install libportaudio2" is the right answer.
"""

from __future__ import annotations

import pytest

from tests.conftest import sounddevice_or_skip
from yazses.system.diagnosis import CAPTURE, diagnose

sounddevice_or_skip(allow_module_level=True)


def _pa(code: int):
    """A real `PortAudioError` with the library's own text for *code*."""
    import sounddevice as sd

    text = sd._ffi.string(sd._lib.Pa_GetErrorText(code)).decode()
    return sd.PortAudioError(f"{text} [PaErrorCode {code}]"), text


def test_an_unsupported_sample_rate_names_the_setting() -> None:
    error, _text = _pa(-9997)
    result = diagnose(error, where=CAPTURE)
    assert "sample rate" in result.title.lower()
    assert "sample_rate" in result.what
    assert "16000" in result.fix, "the fix must name the value that always works"


@pytest.mark.parametrize("code", [-9999, -9986, -9973])
def test_other_portaudio_errors_are_not_blamed_on_a_missing_library(code: int) -> None:
    """Saying less is better than saying something that cannot be true."""
    error, _text = _pa(code)
    result = diagnose(error, where=CAPTURE)
    assert "libportaudio2" not in result.fix
    assert "could not be loaded" not in result.what


@pytest.mark.parametrize("code", [-9997, -9999, -9986, -9973])
def test_every_one_still_gets_a_diagnosis(code: int) -> None:
    """The module's first rule: an unrecognised error must not go quiet."""
    error, _text = _pa(code)
    result = diagnose(error, where=CAPTURE)
    assert result.title and result.fix


def test_a_genuine_load_failure_still_says_install_it() -> None:
    """The expensive direction: narrowing must not lose the case the rule exists for.

    `sounddevice` raises exactly this when the shared library is absent.
    """
    result = diagnose(OSError("PortAudio library not found"), where=CAPTURE)
    assert "sound system" in result.title.lower()
    assert "libportaudio2" in result.fix


def test_sounddevice_still_raises_that_message() -> None:
    """The narrowed marker is copied from the installed package; if its wording changes,
    the rule stops matching and this fails rather than the user getting nothing."""
    import inspect

    import sounddevice

    assert "PortAudio library not found" in inspect.getsource(sounddevice)


def test_the_earlier_microphone_rules_still_win() -> None:
    """The new sample-rate rule sits above them; none may be shadowed."""
    assert "could not open your microphone" in diagnose(
        OSError("Device unavailable"), where=CAPTURE
    ).title
    assert "cannot find the microphone" in diagnose(
        OSError("Error querying device 3"), where=CAPTURE
    ).title
    assert "default microphone" in diagnose(
        OSError("Error querying device -1"), where=CAPTURE
    ).title


def test_the_codes_are_read_from_the_library() -> None:
    """These assertions are about PortAudio's own wording, so they ask PortAudio."""
    _error, text = _pa(-9997)
    assert text.lower() == "invalid sample rate"
