"""A setting this CPU cannot run was reported as a model that had not been downloaded.

`[stt] compute_type` is a documented, editable key whose valid values are a property of
the processor, and ctranslate2 refuses an unsupported one from inside `WhisperModel(...)`.
`stt/faster_whisper.py::_load_model` wrapped **every** exception from that constructor as
`ModelUnavailableError`, whose text is:

    The speech-to-text model 'tiny.en' is not on this machine, and it could not be
    downloaded.
    ...
      1. Download it deliberately:   yazses model download tiny.en
      2. Allow YazSes (or huggingface.co) through your firewall, then: yazses restart
      3. Fetch it by hand on any machine with network access ...

Every sentence of that is wrong here. The model is on this machine — it is the thing that
just loaded far enough to reject the compute type — and all three remedies fetch a file
already in the cache. The daemon's desktop notification composed its own copy of the same
claim, so the toast said it too.

The project already knows this shape. `settingsui/controller.py` validates compute_type
against `ctranslate2.get_supported_compute_types(device)` and says why: an unsupported value
"is reported as a missing *model*". That guard covers the Settings window. A hand-edited
config had none, and hand-editing is how the key is normally set.

## Why a subclass rather than a new exception

`core/daemon.py` catches `ModelUnavailableError` to hold the process in ERROR state with IPC
alive instead of exiting with a traceback (#310). Dictation really is unavailable here too,
so that handling is right — only the explanation was wrong. A sibling exception type would
have walked straight back into the traceback that issue was filed about, which is what
`test_the_daemon_still_handles_it_gracefully` pins.

## Two surfaces, one text

The toast now comes from `exc.notification()` rather than being composed in the daemon, so
a subclass cannot disagree with the log line printed immediately above it.
"""

from __future__ import annotations

import inspect

import pytest

from tests.decoder_stack import needs_ctranslate2
from yazses.stt.errors import (
    ComputeTypeUnsupportedError,
    ModelUnavailableError,
    compute_type_unsupported_message,
    looks_like_an_unsupported_compute_type,
    supported_compute_types,
)
from yazses.system.diagnosis import TRANSCRIBE, diagnose

#: ctranslate2's own wording, which the marker is taken from.
REAL_CAUSE = (
    "Requested float16 compute type, but the target device or backend do not "
    "support efficient float16 computation."
)

DOWNLOAD_CLAIMS = ("could not be downloaded", "model download", "huggingface.co")


def _require_cached_model() -> None:
    """Skip unless `tiny.en` is already on this machine.

    These three exercise the real loader, and without this a runner that has never
    downloaded the model would fetch it from the network — inside a suite whose
    project promises it does not need one. `_load_model`'s own docstring records that
    such a fetch can hang indefinitely behind a captive portal rather than failing.
    """
    pytest.importorskip("faster_whisper")
    from yazses.stt.download import is_cached

    if not is_cached("tiny.en"):
        pytest.skip("tiny.en is not cached; refusing to download inside the test suite")


def _unsupported_type() -> str:
    """A compute type this machine genuinely refuses, asked of ctranslate2.

    Hardcoding one would make the test a claim about the CI runner's CPU rather than
    about YazSes.
    """
    ct = pytest.importorskip("ctranslate2")
    supported = set(ct.get_supported_compute_types("cpu"))
    for candidate in ("float16", "int8_float16", "bfloat16", "int8_bfloat16"):
        if candidate not in supported:
            return candidate
    pytest.skip("this CPU supports every compute type we could test with")


# --------------------------------------------------------------------------- message


def test_it_does_not_claim_the_model_is_missing() -> None:
    message = compute_type_unsupported_message("tiny.en", "float16", "cpu", REAL_CAUSE)
    lowered = message.lower()
    for claim in DOWNLOAD_CLAIMS:
        assert claim not in lowered, f"still offers {claim!r} for a model that is present"
    assert "is fine and already here" in message


def test_it_names_the_setting_and_the_value_to_return_to() -> None:
    """A diagnosis without a remedy is the defect this module exists to avoid."""
    message = compute_type_unsupported_message("tiny.en", "float16", "cpu", REAL_CAUSE)
    assert "[stt] compute_type" in message
    assert "int8" in message
    assert "config.toml" in message
    assert "yazses restart" in message


@needs_ctranslate2
def test_it_lists_what_this_machine_can_do() -> None:
    """Read from the installed library, so the list cannot be wrong about this CPU."""
    supported = supported_compute_types("cpu")
    assert supported, "ctranslate2 reported no compute types at all"
    assert "int8" in supported, "the default must be in the supported set"
    message = compute_type_unsupported_message("tiny.en", "float16", "cpu", REAL_CAUSE)
    for name in supported:
        assert name in message


def test_the_cause_is_still_shown() -> None:
    """The original text is what a maintainer needs on an issue."""
    assert REAL_CAUSE in compute_type_unsupported_message("m", "float16", "cpu", REAL_CAUSE)


def test_an_unanswerable_device_does_not_become_a_second_failure() -> None:
    """A hint must never raise; the message still names the fix without the list."""
    assert supported_compute_types("no-such-device") == []
    message = compute_type_unsupported_message("m", "float16", "no-such-device", REAL_CAUSE)
    assert "[stt] compute_type" in message


# --------------------------------------------------------------------------- detection


@pytest.mark.parametrize(
    "text",
    [
        REAL_CAUSE,
        "Requested int8_float16 compute type, but the target device or backend do not "
        "support efficient int8_float16 computation.",
    ],
)
def test_the_marker_matches_the_real_messages(text: str) -> None:
    assert looks_like_an_unsupported_compute_type(ValueError(text))


@pytest.mark.parametrize(
    "text",
    [
        "LocalEntryNotFoundError: Cannot find an appropriate cached snapshot",
        "WinError 10013: forbidden by its access permissions",
        "Max retries exceeded with url",
        "No such file or directory: 'model.bin'",
    ],
)
def test_a_download_failure_is_not_mistaken_for_one(text: str) -> None:
    """The expensive direction: stealing a genuine missing model would lose the
    three ways to get it, which is what #310 was about."""
    assert not looks_like_an_unsupported_compute_type(OSError(text))


# --------------------------------------------------------------------------- exception


def test_the_daemon_still_handles_it_gracefully() -> None:
    """`core/daemon.py` catches `ModelUnavailableError` to stay up in ERROR state
    rather than exiting with a traceback (#310). A sibling type would bypass that."""
    error = ComputeTypeUnsupportedError("tiny.en", "float16", "cpu", REAL_CAUSE)
    assert isinstance(error, ModelUnavailableError)
    assert error.model == "tiny.en", "the handler reads .model"


def test_its_str_is_the_guidance() -> None:
    """What makes a bare `log.error("%s", exc)` correct, as the base class documents."""
    error = ComputeTypeUnsupportedError("tiny.en", "float16", "cpu", REAL_CAUSE)
    text = str(error)
    assert "[stt] compute_type" in text
    assert "could not be downloaded" not in text


def test_the_toast_says_the_same_thing_as_the_message() -> None:
    """They are printed one after the other; they may not name different causes."""
    error = ComputeTypeUnsupportedError("tiny.en", "float16", "cpu", REAL_CAUSE)
    _title, body = error.notification()
    assert "compute_type" in body
    assert "int8" in body
    for claim in DOWNLOAD_CLAIMS:
        assert claim not in body.lower()


def test_a_genuinely_missing_model_is_untouched() -> None:
    """The whole point of the base class must survive the split."""
    error = ModelUnavailableError("tiny.en", OSError("LocalEntryNotFoundError"))
    assert "could not be downloaded" in str(error)
    _title, body = error.notification()
    assert "yazses model download tiny.en" in body


def test_the_daemon_asks_the_exception_for_the_toast() -> None:
    """It used to compose its own, so the toast contradicted the log line above it
    for any cause that was not a missing model."""
    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon._await_shutdown_in_error)
    # Comments stripped first: the comment explaining this change contains the very
    # phrase being searched for, so a raw scan passes on prose rather than on code.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "exc.notification()" in code
    assert "missing and could not be" not in code, (
        "the daemon is composing the text again; it must come from the exception"
    )


# --------------------------------------------------------------------------- the loader


def test_loading_with_an_unsupported_type_raises_the_right_error() -> None:
    """The real chain: config -> factory -> ctranslate2 -> the error the user reads."""
    _require_cached_model()
    from yazses.config import Config
    from yazses.stt.factory import build_engine

    stt = Config().stt
    stt.model = "tiny.en"
    stt.compute_type = _unsupported_type()
    with pytest.raises(ComputeTypeUnsupportedError) as caught:
        build_engine(stt)
    assert "compute_type" in str(caught.value)
    assert caught.value.compute_type == stt.compute_type


def test_it_does_not_try_to_download_first(caplog) -> None:
    """`_load_model` falls back to a network fetch when the cached load fails. For this
    failure the fetch reaches the identical error by a longer route — and on a firewalled
    machine it fails first, burying the real cause under a network one."""
    _require_cached_model()
    from yazses.config import Config
    from yazses.stt.factory import build_engine

    stt = Config().stt
    stt.model = "tiny.en"
    stt.compute_type = _unsupported_type()
    with caplog.at_level("INFO"):
        with pytest.raises(ComputeTypeUnsupportedError):
            build_engine(stt)
    assert "downloading it once" not in caplog.text


def test_a_supported_type_still_loads() -> None:
    """The expensive direction: a check placed too eagerly would refuse working setups."""
    _require_cached_model()
    from yazses.config import Config
    from yazses.stt.factory import build_engine

    stt = Config().stt
    stt.model = "tiny.en"
    stt.compute_type = "int8"
    assert build_engine(stt) is not None


# --------------------------------------------------------------------------- diagnose


def test_diagnose_routes_it_away_from_model_missing() -> None:
    """`diagnose()` is fed whatever was caught, including the raw ctranslate2 error
    from any path that does not go through the loader above."""
    result = diagnose(ValueError(REAL_CAUSE), where=TRANSCRIBE)
    assert "compute type" in result.title.lower()
    assert "[stt] compute_type" in result.what
    assert "downloadable" not in result.fix


def test_diagnose_still_answers_a_real_model_failure() -> None:
    """The rule sits above `model-missing`; it must not shadow it."""
    result = diagnose(ModelUnavailableError("tiny.en", OSError("connection refused")))
    assert "speech model" in result.title.lower()
    assert "doctor" in result.fix


def test_every_failure_still_gets_a_diagnosis() -> None:
    """This module's first rule: an unrecognised error must not go quiet."""
    result = diagnose(RuntimeError("something nobody predicted"), where=TRANSCRIBE)
    assert result.title and result.fix
