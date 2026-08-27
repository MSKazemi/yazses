"""A machine with no audio device must still be able to *import* YazSes.

`import sounddevice` calls `Pa_Initialize()` during the import itself, and where there is
no usable audio system that raises rather than returning an empty device list:

    sounddevice.PortAudioError: Error initializing PortAudio:
    Internal PortAudio error [PaErrorCode -9986]

`audio/recorder.py` imported it at module scope and `core/daemon.py` imports the recorder
at *its* module scope, so `import yazses.core.daemon` was itself impossible on such a
host — an unhandled traceback from a line nobody called.

Measured on a Windows Server 2022 VM with no audio device: **45 test files could not be
collected**, which is a large part of why regressions keep reaching Windows unseen. It is
not an exotic state either — a stopped Windows Audio service, an RDP session without
audio redirection, a container, and a CI runner all look identical to PortAudio. And
`yazses transcribe`, which needs no microphone at all, is exactly the command such a
machine is most likely to want.

`audio/devices.py` already imported sounddevice inside each function for this reason,
which is why `yazses doctor` and `yazses audio devices` *report* the problem rather than
dying of it. These tests hold the recorder to the same rule: opening a microphone may
fail, importing a module may not.

The failure is reproduced by shadowing `sounddevice` with a module that raises on import
— the same trick that reproduced the Windows ctranslate2 failure — because a real
PortAudio here initialises perfectly well.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"

_BROKEN_SOUNDDEVICE = '''\
class PortAudioError(Exception):
    pass


raise PortAudioError(
    "Error initializing PortAudio: Internal PortAudio error [PaErrorCode -9986]"
)
'''


@pytest.fixture()
def no_audio(tmp_path: Path) -> Path:
    """A directory that shadows `sounddevice` with one that cannot initialise."""
    (tmp_path / "sounddevice.py").write_text(_BROKEN_SOUNDDEVICE, encoding="utf-8")
    return tmp_path


def _import_in_a_fresh_interpreter(module: str, shadow: Path) -> subprocess.CompletedProcess:
    """Import `module` in a subprocess whose sounddevice raises on import.

    A subprocess rather than `importlib.reload`: sounddevice and half the package are
    already imported in this one, and a reload would not reproduce a cold start.
    """
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(shadow)!r})
        sys.path.insert(1, {str(_SRC)!r})
        import {module}
        print("IMPORT_OK")
    """)
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=180
    )


def test_the_shadow_really_does_break_sounddevice(no_audio: Path) -> None:
    """Anchors the premise — if the shadow stops raising, every test below is vacuous."""
    out = _import_in_a_fresh_interpreter("sounddevice", no_audio)
    assert out.returncode != 0
    assert "PortAudioError" in out.stderr


@pytest.mark.parametrize(
    "module",
    [
        "yazses.audio.recorder",
        "yazses.core.daemon",
        "yazses.cli",
    ],
)
def test_importing_it_without_an_audio_device_still_works(no_audio: Path, module: str) -> None:
    out = _import_in_a_fresh_interpreter(module, no_audio)
    assert out.returncode == 0, (
        f"{module} cannot be imported on a machine with no audio device:\n"
        f"{out.stderr[-1500:]}"
    )
    assert "IMPORT_OK" in out.stdout


def test_the_recorder_does_not_import_sounddevice_at_module_scope() -> None:
    """States the rule directly, so the reason survives a refactor of the tests above.

    Reading the source rather than the behaviour because the behaviour is only visible on
    a host that has no audio — which the machine running this almost certainly does have.
    """
    import ast

    from yazses.audio import recorder

    source = Path(recorder.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level = [
        n
        for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    names = {
        alias.name
        for node in top_level
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "sounddevice" not in names, (
        "sounddevice is imported at module scope again; importing this module now fails "
        "outright on any host with no usable audio system"
    )


def test_the_recorder_still_actually_uses_sounddevice() -> None:
    """Guards the guard: deleting the dependency would pass the test above."""
    from yazses.audio import recorder

    source = Path(recorder.__file__).read_text(encoding="utf-8")
    assert "import sounddevice" in source, "the recorder no longer opens a microphone at all"


def test_the_seam_returns_the_real_module() -> None:
    """`_sd()` must be the module, not a stub -- but only where it can be imported.

    Separated from the test above so the no-audio host this whole file is about can
    still assert the source-level rule, which is the half that matters there.
    """
    from tests.conftest import sounddevice_or_skip
    from yazses.audio import recorder

    sounddevice_or_skip()
    assert recorder._sd() is importlib.import_module("sounddevice")
