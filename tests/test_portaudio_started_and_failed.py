"""`doctor` told a Windows box with a flawless install to reinstall the package.

Found on real hardware, not reasoned about: an Azure `Standard_D4s_v5` running Windows
Server 2022 with **zero** sound devices. `yazses doctor` printed

    [FAIL] Microphone: PortAudio could not be loaded, so no audio device can be opened.
           The sounddevice wheel bundles it on Windows, so this means a broken or
           partial install — run: pip install --force-reinstall sounddevice

while the install was perfect. `import sounddevice` reached
`sounddevice.py:2936 _initialize()` and raised

    sounddevice.PortAudioError: Error initializing PortAudio:
    Internal PortAudio error [PaErrorCode -9986]

which can only happen once PortAudio has **loaded** — it is the thing that raised. The
machine simply has no audio system. The prescribed reinstall cannot change that, and a
user who follows it spends their time on the wrong thing and ends up back at the same row.

## Why the old code could not tell

`sounddevice` calls `Pa_Initialize()` at module scope, so `import sounddevice` fails for
two unrelated reasons, and `portaudio_missing()` caught `Exception` — collapsing them.

## The same mistake was already fixed once, in the other module

`system/diagnosis.py` carries the comment *"PortAudio puts its own name in the exception
class … if PortAudio could not be loaded it could not raise a `PortAudioError`"*, and
`tests/test_diagnosis_portaudio_scope.py` names `-9986` among the codes that must not be
diagnosed as a missing library. Two guards, two vocabularies, and only one of them had
been narrowed — which is why the fixed module and the unfixed one disagreed about the
same exception on the same machine.
"""

from __future__ import annotations

import builtins

import pytest

from yazses.platform.base import (
    LINUX_PLATFORM_NAME,
    MACOS_PLATFORM_NAME,
    WINDOWS_PLATFORM_NAME,
)
from yazses.system.doctor import microphone_detail, portaudio_init_advice
from yazses.system.setup import (
    portaudio_missing,
    portaudio_state,
    portaudio_uninitialised,
)

PLATFORMS = [LINUX_PLATFORM_NAME, MACOS_PLATFORM_NAME, WINDOWS_PLATFORM_NAME]


# Stands in for `sounddevice.PortAudioError`, which the detection matches by class
# name. A real one cannot be constructed here: importing `sounddevice` to reach the
# class is the very thing that fails on the machine this file is about.
PortAudioError = type("PortAudioError", (Exception,), {})


def _import_raising(exc: BaseException):
    real = builtins.__import__

    def fake(name, *args, **kwargs):
        if name == "sounddevice":
            raise exc
        return real(name, *args, **kwargs)

    return fake


def test_a_portaudio_error_is_not_a_missing_library(monkeypatch) -> None:
    """The regression, stated as the machine stated it: -9986 from a good install."""
    exc = PortAudioError("Error initializing PortAudio: Internal PortAudio error [-9986]")
    monkeypatch.setattr(builtins, "__import__", _import_raising(exc))
    assert portaudio_state() == "uninitialised"
    assert portaudio_missing() is False
    assert portaudio_uninitialised() is True


def test_an_oserror_still_means_the_library_is_absent(monkeypatch) -> None:
    """The opposite failure: narrowing too far would lose the commonest real cause."""
    monkeypatch.setattr(
        builtins, "__import__", _import_raising(OSError("PortAudio library not found"))
    )
    assert portaudio_state() == "missing"
    assert portaudio_missing() is True
    assert portaudio_uninitialised() is False


def test_a_subclass_of_portaudio_error_is_recognised(monkeypatch) -> None:
    sub = type("StreamError", (PortAudioError,), {})
    monkeypatch.setattr(builtins, "__import__", _import_raising(sub("boom")))
    assert portaudio_state() == "uninitialised"


def test_the_real_answer_is_self_consistent() -> None:
    """`sounddevice` is a hard dependency, so this asserts the real answer.

    It used to assert `"ok"` flatly, which is only the real answer on a machine that
    has a sound card. On a Windows Server host with no audio device the honest answer
    is `"uninitialised"` -- PortAudio loaded and `Pa_Initialize()` failed -- and the
    test reported a broken product where the product was right. What must hold on
    every host is that the state and the two predicates derived from it agree, and
    that an importable sounddevice means `"ok"`.
    """
    state = portaudio_state()
    assert state in {"ok", "missing", "uninitialised"}
    assert portaudio_missing() is (state == "missing")
    assert portaudio_uninitialised() is (state == "uninitialised")

    try:
        import sounddevice  # noqa: F401
    except Exception:  # noqa: BLE001 -- the no-audio host this test now tolerates
        assert state != "ok"
    else:
        assert state == "ok"


@pytest.mark.parametrize("platform_name", PLATFORMS)
def test_the_started_and_failed_advice_never_prescribes_an_install(platform_name) -> None:
    """The whole point: none of these may send the user to a package manager."""
    advice = portaudio_init_advice(platform_name)
    lowered = advice.lower()
    for wrong in ("reinstall sounddevice", "apt install", "brew install", "pkg install"):
        assert wrong not in lowered, f"{platform_name}: {advice}"


@pytest.mark.parametrize("platform_name", PLATFORMS)
def test_the_started_and_failed_advice_says_reinstalling_will_not_help(platform_name) -> None:
    """Saying nothing about the reinstall leaves the obvious wrong move available."""
    assert "reinstalling will not help" in portaudio_init_advice(platform_name)


def test_the_advice_is_per_os_and_not_one_string() -> None:
    """The bug it replaces was one Linux sentence printed on three operating systems."""
    assert len({portaudio_init_advice(p) for p in PLATFORMS}) == len(PLATFORMS)
    assert "services.msc" in portaudio_init_advice(WINDOWS_PLATFORM_NAME)
    assert "pipewire" in portaudio_init_advice(LINUX_PLATFORM_NAME)
    assert "System Settings" in portaudio_init_advice(MACOS_PLATFORM_NAME)


@pytest.mark.parametrize("platform_name", PLATFORMS)
def test_the_doctor_row_uses_it(platform_name) -> None:
    detail = microphone_detail(
        "unknown",
        snap_pending=False,
        no_portaudio=False,
        portaudio_uninitialised=True,
        platform_name=platform_name,
        advice="GRANT-ADVICE",
    )
    assert detail == portaudio_init_advice(platform_name)
    assert "GRANT-ADVICE" not in detail


@pytest.mark.parametrize("platform_name", PLATFORMS)
def test_a_genuinely_missing_library_still_wins(platform_name) -> None:
    """Ordering guard: the two states are exclusive, but the branch order must be too."""
    detail = microphone_detail(
        "unknown",
        snap_pending=False,
        no_portaudio=True,
        portaudio_uninitialised=True,
        platform_name=platform_name,
        advice="",
    )
    assert "reinstalling will not help" not in detail


def test_the_snap_answer_still_wins_over_both() -> None:
    detail = microphone_detail(
        "unknown",
        snap_pending=True,
        no_portaudio=True,
        portaudio_uninitialised=True,
        platform_name=LINUX_PLATFORM_NAME,
        advice="",
    )
    assert "snap connect yazses:audio-record" in detail


def test_the_call_site_passes_the_new_state() -> None:
    """A pure helper improved in isolation changes no output — the shape this file's
    sibling `test_microphone_remedy.py` already guards for the other argument."""
    import ast
    from pathlib import Path

    source = Path(
        __import__("yazses.system.doctor", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")
    calls = [
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "microphone_detail"
    ]
    assert len(calls) == 1, calls
    assert "portaudio_uninitialised" in {kw.arg for kw in calls[0].keywords}


def test_the_input_device_row_is_not_ok_when_the_audio_system_did_not_answer(monkeypatch) -> None:
    """The same defect one line down: a status tag asserting what was never checked.

    On the Windows box the report read

        [FAIL] Microphone: ... this machine has no usable audio system
        [OK]   Input device: OS default: unknown (pin with `yazses audio use <name>`)

    Two adjacent rows contradicting each other, and the OK one offering a command that
    can only print the same error.
    """
    from pathlib import Path as _Path

    from yazses.config import load_config
    from yazses.system import doctor as doctor_mod

    monkeypatch.setattr("yazses.audio.devices.current_default_input_name", lambda: None)
    rows = doctor_mod._config_summary(load_config(None), _Path("/nonexistent.toml"))
    name, status, detail = next(r for r in rows if r[0] == "Input device")
    assert status == "WARN", (status, detail)
    assert "yazses audio use" not in detail, detail


def test_the_input_device_row_stays_ok_when_a_device_is_named(monkeypatch) -> None:
    """The opposite failure: warning on every healthy machine would train the eye past it."""
    from pathlib import Path as _Path

    from yazses.config import load_config
    from yazses.system import doctor as doctor_mod

    monkeypatch.setattr(
        "yazses.audio.devices.current_default_input_name", lambda: "USB PnP Audio Device"
    )
    rows = doctor_mod._config_summary(load_config(None), _Path("/nonexistent.toml"))
    _name, status, detail = next(r for r in rows if r[0] == "Input device")
    assert status == "OK", (status, detail)
    assert "USB PnP Audio Device" in detail
