"""`yazses doctor` must notice that nothing can be transcribed.

On a real Windows host on 2026-08-23 doctor reported exactly two problems, and neither
of them was that dictation could never work there. It printed

    [WARN] STT model: base.en not downloaded — fetched automatically on first dictation

while, on the same machine and in the same virtualenv, `import ctranslate2` was dying:

    FileNotFoundError: Could not find module
    'C:\\yazses-main\\.venv\\Lib\\site-packages\\ctranslate2\\ctranslate2.dll'
    (or one of its dependencies). Try using the full path with constructor syntax.

A model that has not been downloaded yet is a warning — it arrives on first use. A
decoder that will not load is the reason nothing will ever be typed, and the place the
user was going to discover it is the first time they hold the key, with no terminal open
and a traceback naming a DLL path.

The failure is a *load*, not a missing package: pip had installed ctranslate2 4.8.1 and
the directory was there. Windows says "or one of its dependencies" because the dependency
is the Microsoft Visual C++ runtime, which CTranslate2's installation docs list as a
Windows requirement and which a fresh Windows image does not always carry. Advising a
reinstall of a package that is already installed correctly sends the user in a circle,
so the two causes are reported apart.

CTranslate2 is probed whatever `[stt] engine` says, because `stt/factory.py` falls back to
faster-whisper whenever the configured engine cannot be built — so it is the decoder every
path can land on.
"""

from __future__ import annotations

import builtins

import pytest

from tests.decoder_stack import needs_ctranslate2
from yazses.system import doctor as doctor_mod

_WINDOWS_DLL_ERROR = FileNotFoundError(
    r"Could not find module 'C:\yazses-main\.venv\Lib\site-packages\ctranslate2"
    r"\ctranslate2.dll' (or one of its dependencies). "
    "Try using the full path with constructor syntax."
)


def _break_the_import(mocker, exc: BaseException) -> None:
    real_import = builtins.__import__

    def _fake(name, *args, **kwargs):
        if name == "ctranslate2":
            raise exc
        return real_import(name, *args, **kwargs)

    mocker.patch.object(builtins, "__import__", _fake)


@needs_ctranslate2
def test_a_healthy_install_reports_ok_and_names_the_version() -> None:
    """The other direction: a check that always fails would be no check at all."""
    name, status, detail = doctor_mod._stt_engine_check("")
    assert (name, status) == ("STT engine", "OK")
    assert "faster-whisper" in detail


def test_a_dll_that_will_not_load_is_a_failure_not_a_warning(mocker) -> None:
    """The exact observed defect, in the exact shape it was observed in."""
    _break_the_import(mocker, _WINDOWS_DLL_ERROR)
    name, status, detail = doctor_mod._stt_engine_check("")
    assert (name, status) == ("STT engine", "FAIL")
    assert "will not load" in detail
    assert "transcribe" in detail, f"must say what stops working: {detail}"


def test_the_windows_remedy_is_the_cpp_runtime_not_another_pip_install(mocker) -> None:
    """pip had already installed it correctly. Re-running pip changes nothing."""
    mocker.patch.object(doctor_mod.sys, "platform", "win32")
    _break_the_import(mocker, _WINDOWS_DLL_ERROR)
    detail = doctor_mod._stt_engine_check("")[2]
    assert "Visual C++" in detail
    assert "aka.ms" in detail, f"must link the installer, not just name it: {detail}"


def test_a_genuinely_missing_package_is_told_to_install_it(mocker) -> None:
    """Separated from the load failure because the fixes are different.

    Sending someone after the Visual C++ runtime when the package simply is not there
    is the same wasted round-trip in the other direction.
    """
    _break_the_import(mocker, ModuleNotFoundError("No module named 'ctranslate2'"))
    name, status, detail = doctor_mod._stt_engine_check("")
    assert (name, status) == ("STT engine", "FAIL")
    assert "not installed" in detail
    assert "Visual C++" not in detail


@pytest.mark.parametrize("engine", ["parakeet", "moonshine", "nonsense"])
def test_the_decoder_is_checked_whatever_engine_is_configured(mocker, engine) -> None:
    """`stt/factory.py` falls back to faster-whisper, so this is never irrelevant."""
    _break_the_import(mocker, _WINDOWS_DLL_ERROR)
    assert doctor_mod._stt_engine_check(engine)[1] == "FAIL"


@needs_ctranslate2
def test_a_healthy_install_says_which_engine_it_is_standing_in_for() -> None:
    detail = doctor_mod._stt_engine_check("parakeet")[2]
    assert "parakeet" in detail, f"a fallback the user did not ask for must be named: {detail}"


def test_run_doctor_actually_runs_the_check() -> None:
    """Guards the guard. Every test above calls the function directly, so all of them
    would still pass on a doctor that never calls it -- which is the shape the defect
    took in the first place: the information existed, nothing asked for it."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(doctor_mod.run_doctor))
    called = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_stt_engine_check" in called, "run_doctor never asks whether the decoder loads"


def test_the_decoder_row_is_reported_before_the_model_row() -> None:
    """Read order is fix order, and these two rows are easy to confuse.

    Both talk about STT and the model row is reassuring -- "fetched automatically on
    first dictation". Printing it above a dead decoder is how that Windows output
    managed to look nearly healthy while nothing could be transcribed.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(doctor_mod.run_doctor))
    where = {
        n.func.id: n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id in ("_stt_engine_check", "_model_check")
    }
    assert set(where) == {"_stt_engine_check", "_model_check"}, where
    assert where["_stt_engine_check"] < where["_model_check"], (
        f"the model row is printed above the decoder row: {where}"
    )
