"""`yazses doctor` must notice when the *configured* STT engine is not the one
actually decoding.

Found on a real machine: `[stt] engine = "parakeet"` with its dependency
(`onnx_asr`) missing from the installed environment. `stt/factory.py` falls
back to faster-whisper exactly as designed — dictation keeps working — but the
only trace of it was one WARNING line in a rotating log file:

    [stt] engine = "parakeet" but its optional dependency (onnx_asr) is not
    installed — falling back to faster-whisper for now.

`_stt_engine_check` (see test_doctor_sees_a_dead_decoder.py) answers a
different question — "can faster-whisper load at all" — and is `OK` in both
the healthy and the silently-downgraded case, because faster-whisper itself is
fine either way. `doctor` had no row that could ever go red for this.

The fallback is quiet for a real reason (dictation must never brick over a
config value), but quiet is not the same as invisible. This is the visible
half.
"""

from __future__ import annotations

from yazses.system import doctor as doctor_mod


def test_the_default_engine_needs_no_extra_check():
    assert doctor_mod._configured_engine_check("") is None
    assert doctor_mod._configured_engine_check("faster-whisper") is None


def test_an_installed_configured_engine_reports_ok(mocker):
    mocker.patch.object(doctor_mod.importlib.util, "find_spec", lambda name: object())
    label, status, detail = doctor_mod._configured_engine_check("parakeet")
    assert status == "OK"
    assert "onnx_asr" in detail


def test_a_missing_configured_engine_dependency_is_a_warning_not_silence(mocker):
    """The exact observed defect: this used to not exist at all."""
    mocker.patch.object(doctor_mod.importlib.util, "find_spec", lambda name: None)
    label, status, detail = doctor_mod._configured_engine_check("parakeet")
    assert label == "Parakeet engine"
    assert status == "WARN"
    assert "onnx_asr" in detail
    assert "faster-whisper instead" in detail, "must say what is actually running"
    assert "yazses features enable stt-parakeet" in detail, "must give the exact fix"


def test_moonshine_names_its_own_module_and_feature(mocker):
    mocker.patch.object(doctor_mod.importlib.util, "find_spec", lambda name: None)
    label, status, detail = doctor_mod._configured_engine_check("moonshine")
    assert label == "Moonshine engine"
    assert "moonshine_onnx" in detail
    assert "stt-moonshine" in detail


def test_an_unrecognised_engine_name_is_left_to_the_decoder_check():
    """`_stt_engine_check` already warns about an unknown `[stt] engine`;
    re-deriving the valid set here would be a second place to keep in sync."""
    assert doctor_mod._configured_engine_check("not-a-real-engine") is None


def test_run_doctor_actually_runs_the_check() -> None:
    """Guards the guard, the same way test_doctor_sees_a_dead_decoder.py does for
    _stt_engine_check: every test above calls the function directly, so all of
    them would still pass on a doctor that never calls it."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(doctor_mod.run_doctor))
    called = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_configured_engine_check" in called
