"""The one dependency whose absence means YazSes cannot do anything at all.

`faster-whisper` is a core dependency, not an extra, and it decodes through CTranslate2 —
a compiled extension. `stt/factory.py` falls back to faster-whisper whenever a configured
engine cannot be built, so this is the decoder every path can land on.

It broke on a real Windows host and the suite said something else entirely. `import
ctranslate2` was failing with

    FileNotFoundError: Could not find module '...\\ctranslate2\\ctranslate2.dll'
    (or one of its dependencies)

— the Microsoft Visual C++ runtime, which CTranslate2's installation docs list as a
Windows requirement and which a fresh Windows image does not always carry. What the
suite reported was three failures in `tests/test_settings_decode_controls.py`, a file
about dropdown contents, because those three are the only tests that import ctranslate2
directly. Three settings failures is not what "nothing can be transcribed on this
machine" should look like, and working out that they were the same thing took a rescued
log from a deleted VM.

So the condition gets a test named after itself. One assertion, no subject beyond the
import: when this is the thing that is wrong, this is the thing that fails.

Note it deliberately does not use `pytest.importorskip`, which catches ImportError only —
and a compiled extension that will not load raises FileNotFoundError or OSError, not
ImportError. Skipping is also the wrong answer here even if it worked: on a machine where
the decoder cannot load, dictation cannot work, and a green suite would be a false report.

`yazses doctor` reports the same condition to the user, with the platform's remedy
(`tests/test_doctor_sees_a_dead_decoder.py`).
"""

from __future__ import annotations


def test_ctranslate2_loads() -> None:
    try:
        import ctranslate2
    except Exception as exc:  # not just ImportError — see the module docstring
        raise AssertionError(
            f"the STT decoder cannot load here ({type(exc).__name__}: {exc}).\n"
            "Dictation, `yazses transcribe` and Meeting Mode can all do nothing until "
            "it does. On Windows this is normally the Microsoft Visual C++ "
            "Redistributable (x64): https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
            "Elsewhere: pip install --force-reinstall ctranslate2"
        ) from exc

    assert ctranslate2.__version__
