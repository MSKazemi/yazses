"""An unplugged pinned microphone was told to pin a microphone.

PortAudio renders the failing device number into its message — `sd.check_input_settings`
on a device that is not there raises `PortAudioError: Error querying device 9999`. The
`mic-default-unresolved` rule matched a bare `"error querying device"`, so it caught **every**
index, and answered all of them with advice written for one:

    YazSes could not reach your default microphone
    It retries, and this normally passes on its own. If it keeps happening, pin the
    microphone you want with `yazses audio use <name>` so a change of default cannot
    interrupt dictation.

For a pinned device that has been unplugged, every sentence of that is wrong. It does not
retry into success, it will not pass on its own, and the user has already pinned the
microphone they want — that pin is the thing that broke.

The rule's own comment says what it was written for: *"PortAudio index -1 is 'the default
device', so this is the default failing to resolve."* The marker just did not say `-1`.

## Ordering does the work

The table takes the first rule whose markers all appear, and `mic-default-unresolved` sits
above `mic-missing`. So `-1` matches the default rule, and any other index falls through to
the numbered `mic-missing` entry — same advice as its text form (`"invalid device"`), because
it is the same fault phrased by number.

## What this pass did not add

`-9999` ("Unanticipated host error", verified against the installed PortAudio) has no rule.
It is a real class, but there is no evidence of it here and no remedy I could verify, and
this module's method is to harvest from real logs rather than imagine. Left alone
deliberately.
"""

from __future__ import annotations

import pytest

from tests.conftest import sounddevice_or_skip
from yazses.system.diagnosis import CAPTURE, diagnose


def _title(message: str) -> str:
    return diagnose(OSError(message), where=CAPTURE).title


def _fix(message: str) -> str:
    return diagnose(OSError(message), where=CAPTURE).fix


@pytest.mark.parametrize("index", ["0", "3", "9999", "12"])
def test_a_numbered_device_is_diagnosed_as_a_missing_pin(index: str) -> None:
    message = f"Error querying device {index}"
    assert "cannot find the microphone" in _title(message), (
        f"{message!r} is still answered as a transient default-device problem"
    )
    assert "audio use" in _fix(message)


def test_the_default_device_keeps_its_own_diagnosis() -> None:
    """The rule this narrows was right for the case it was written for.

    `-1` is PortAudio's "the default device", and that failure really is usually
    transient — a headset connecting, a monitor waking.
    """
    assert "default microphone" in _title("Error querying device -1")
    assert "normally passes on its own" in _fix("Error querying device -1")


def test_the_pinned_case_is_not_told_to_pin_something() -> None:
    """The specific absurdity: advice to do the thing that already broke."""
    fix = _fix("Error querying device 9999")
    assert "normally passes on its own" not in fix
    assert "unplugged" in diagnose(
        OSError("Error querying device 9999"), where=CAPTURE
    ).what


def test_the_text_form_is_unchanged() -> None:
    """`Invalid device` is the same fault in words; both must agree."""
    assert _title("Invalid device") == _title("Error querying device 9999")


def test_the_other_microphone_rules_still_win() -> None:
    """The new entry sits between them, so neither may be shadowed."""
    assert "could not open your microphone" in _title("Device unavailable")
    assert "could not open your microphone" in _title("Errno -9985")


def test_portaudio_codes_are_what_this_assumes() -> None:
    """Queried from the installed library rather than remembered.

    Skipped where PortAudio is absent, since the claim is about that library.
    """
    sd = sounddevice_or_skip()
    try:
        text = sd._ffi.string(sd._lib.Pa_GetErrorText(-9996)).decode()
    except Exception:  # pragma: no cover - binding shape varies
        pytest.skip("cannot query PortAudio error text on this build")
    assert text.lower() == "invalid device"
