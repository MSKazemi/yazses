"""`yazses doctor` must name the commonest reason a fresh install has no microphone.

`sounddevice` cannot import without the PortAudio runtime, and nothing about a
`pipx`/`uv tool` install pulls `libportaudio2` in. `LinuxPermissions.check_microphone`
catches that import failure and returns `UNKNOWN` — the same answer it gives for a
machine with no input hardware. Doctor rendered that as:

    [FAIL] Microphone: unknown

which is the symptom with the cause removed. The two states need opposite actions:
one is an apt command, the other is "plug something in".

The package name was already known in two other places — `setup.py` lists
`libportaudio2` first in `APT_PACKAGES` with the comment *"always required"*, and the
error classifier names it in its advice — so the check people actually run when
something is wrong was the one surface that did not say it.

Found while auditing the (still uncommitted) `docs/compare/yazses-vs-nerd-dictation.md`,
which tells a migrating user that `yazses doctor` *"will catch"* exactly this. It caught
the symptom. Fixing the tool was better than weakening the page.
"""

from __future__ import annotations

import pathlib

from yazses.system import doctor as doctor_mod
from yazses.system.setup import portaudio_missing


def test_portaudio_missing_is_false_when_sounddevice_imports() -> None:
    """On this machine PortAudio is present; the helper must not cry wolf."""
    assert portaudio_missing() is False


def test_portaudio_missing_is_true_when_the_import_fails(monkeypatch) -> None:
    """Simulates the real failure: `OSError: PortAudio library not found` on import.

    Patched rather than read from the host — a test that only passes on a machine
    without PortAudio would never run anywhere that matters.
    """
    import builtins

    real_import = builtins.__import__

    def _no_portaudio(name, *args, **kwargs):
        if name == "sounddevice":
            raise OSError("PortAudio library not found")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_portaudio)
    assert portaudio_missing() is True


def test_a_failing_mic_with_no_portaudio_names_the_package() -> None:
    """The defect: this used to render as the bare word 'unknown'."""
    detail = doctor_mod.microphone_detail(
        "unknown", snap_pending=False, no_portaudio=True, platform_name="linux"
    )
    assert "libportaudio2" in detail
    assert "apt install" in detail


def test_a_failing_mic_with_portaudio_present_does_not_blame_it() -> None:
    """The half that makes the message worth having.

    A machine that has PortAudio and no input device must not be sent to apt —
    naming the package unconditionally would be as wrong as never naming it, just
    louder.
    """
    detail = doctor_mod.microphone_detail(
        "unknown", snap_pending=False, no_portaudio=False, platform_name="linux"
    )
    assert "libportaudio2" not in detail
    assert detail == "unknown"


def test_the_snap_message_still_wins() -> None:
    """Inside the snap, PortAudio ships with the package, so the cause is the
    un-connected interface and that answer must not be displaced."""
    detail = doctor_mod.microphone_detail(
        "unknown", snap_pending=True, no_portaudio=True, platform_name="linux"
    )
    assert "snap connect" in detail
    assert "libportaudio2" not in detail


def test_the_helper_is_the_one_doctor_actually_calls() -> None:
    """A pure helper nothing calls would pass these tests and change no output."""
    source = (
        pathlib.Path(doctor_mod.__file__).read_text(encoding="utf-8")
    )
    assert "mic_detail = microphone_detail(" in source
