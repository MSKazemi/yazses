"""A device that would not start was reported as a model that is not on this machine.

`stt/faster_whisper.py::_load_model` turns an exception from `WhisperModel(...)` into a
typed error. Only a "compute type" message had its own explanation; anything else, such
as `[stt] device = "cuda"` on a machine with no usable CUDA or cuDNN, ended as
`ModelUnavailableError` ("not on this machine, and it could not be downloaded") with three
ways to download a file that was never the problem. The real cause was only in an earlier
log line, and the CPU is not tried instead.

This fixes the wording only. Which device is used, what is retried and the exception
family (`ModelUnavailableError`, which `core/daemon.py` catches to hold in ERROR state)
are unchanged.

No GPU was available. The classifier needs POSITIVE evidence in the text (CUDA, cuDNN,
cuBLAS, NVIDIA, a GPU, an unsupported device); a non-CPU device alone is not evidence.
The strings it keys on were read out of the CTranslate2 4.8.1 binary, see
`stt/errors.py::_DEVICE_MARKERS`.
"""

from __future__ import annotations

import os

import pytest

from tests.decoder_stack import needs_faster_whisper
from yazses.stt.download import hub_cache_dir, whisper_model_url
from yazses.stt.errors import (
    ComputeTypeUnsupportedError,
    DeviceUnavailableError,
    ModelUnavailableError,
    looks_like_a_device_failure,
    model_unavailable_message,
    short_reason,
)

CUDA_ERR = "CUDA failed with error CUDA driver version is insufficient for CUDA runtime version"
CUBLAS_ERR = "libcublas.so.12: cannot open shared object file: No such file or directory"
COMPUTE_ERR = (
    "Requested float16 compute type, but the target device or backend do not "
    "support efficient float16 computation."
)
HOME = os.path.expanduser("~")


def _load(mocker, exc: BaseException, device: str = "cuda", compute_type: str = "int8"):
    from yazses.stt import faster_whisper as fw

    mocker.patch.object(fw, "WhisperModel", side_effect=exc)
    return fw._load_model("base.en", device, compute_type)


# ---- the new behaviour -------------------------------------------------


@needs_faster_whisper
@pytest.mark.parametrize(
    "exc, reason_fragment",
    [
        (RuntimeError(CUDA_ERR), "RuntimeError: CUDA failed with error"),
        (OSError(CUBLAS_ERR), "OSError: libcublas.so.12: cannot open shared object file"),
    ],
)
def test_a_cuda_failure_names_the_device_the_cause_and_the_action(mocker, exc, reason_fragment):
    with pytest.raises(DeviceUnavailableError) as caught:
        _load(mocker, exc)
    text = str(caught.value)

    assert "'cuda'" in text
    assert reason_fragment in text
    assert 'device = "cpu"' in text and "yazses restart" in text
    # the generic wording, and its three download remedies, are gone
    assert "could not be downloaded" not in text
    assert "yazses model download" not in text
    assert "huggingface.co" not in text
    # the original is preserved for debugging
    assert caught.value.__cause__ is exc


@needs_faster_whisper
def test_the_daemon_still_catches_it_and_the_toast_names_the_cause(mocker):
    with pytest.raises(ModelUnavailableError) as caught:
        _load(mocker, RuntimeError(CUDA_ERR))
    err = caught.value
    assert isinstance(err, DeviceUnavailableError)
    # the fields the daemon's error-hold logic reads
    assert err.model == "base.en" and err.device == "cuda" and err.cause is not None
    title, body = err.notification()
    assert title == "YazSes cannot start dictation"
    assert "'cuda'" in body and "CUDA failed" in body and 'device = "cpu"' in body
    assert "download" not in body


@needs_faster_whisper
def test_the_cache_miss_is_retried_exactly_as_before(mocker):
    from yazses.stt import faster_whisper as fw

    ctor = mocker.patch.object(fw, "WhisperModel", side_effect=RuntimeError(CUDA_ERR))
    with pytest.raises(DeviceUnavailableError):
        fw._load_model("base.en", "cuda", "int8")
    assert [c.kwargs.get("local_files_only", False) for c in ctor.call_args_list] == [True, False]
    assert all(c.kwargs["device"] == "cuda" for c in ctor.call_args_list)


@needs_faster_whisper
def test_home_directories_and_paths_never_reach_the_message(mocker):
    exc = OSError(f"cannot open {HOME}/.cache/lib/libcudnn.so.9 and /usr/lib/x86_64/libcuda.so")
    with pytest.raises(DeviceUnavailableError) as caught:
        _load(mocker, exc)
    err = caught.value
    text = str(err) + " ".join(err.notification())
    assert HOME not in text
    assert "/usr/lib" not in text and ".cache" not in text
    assert "<path>" in text


def test_a_windows_path_is_stripped_too():
    assert "bob" not in short_reason(OSError(r"C:\Users\bob\AppData\cudnn64_9.dll missing"))


@pytest.mark.parametrize(
    "text, kept",
    [
        ("see https://docs.nvidia.com/cuda/x", "https://docs.nvidia.com/cuda/x"),
        ("CUDA failed (cuda/cuda_utils.h:61)", "(cuda/cuda_utils.h:61)"),
        ("retry at http://localhost:8080/v1/models later", "http://localhost:8080/v1/models"),
        ("libcublas.so.12 missing", "libcublas.so.12"),
    ],
)
def test_urls_and_relative_locations_are_not_mistaken_for_paths(text, kept):
    reason = short_reason(RuntimeError(text))
    assert kept in reason
    assert "<path>" not in reason


@pytest.mark.parametrize(
    "text, secret",
    [
        ("open /home/bob/.cache/libcudnn.so.9 failed", "bob"),
        ("open (/home/bob/.cache/libcudnn.so.9) failed", "bob"),
        ("path=/home/bob/models/x", "bob"),
        ("see /home/bob/x and https://docs.nvidia.com/cuda/x", "bob"),
        (r"open C:\Users\bob\AppData\cudnn64_9.dll", "bob"),
        ("open C:/Users/bob/AppData/cudnn64_9.dll", "bob"),
        ("open ~/bob-private/x", "bob"),
        (r"open ~\bob-private\x", "bob"),
        ("open file:///home/bob/model.bin", "bob"),
        (r"open \\fileserver\bob\model.bin", "bob"),
        ("failed:/home/bob/x", "bob"),
    ],
)
def test_real_paths_never_survive_the_scrub(text, secret):
    assert secret not in short_reason(RuntimeError(text))
    assert "<path>" in short_reason(RuntimeError(text))


def test_a_url_and_a_path_in_one_message_keep_the_url_and_lose_the_path():
    reason = short_reason(RuntimeError("see https://a.example/c and /home/bob/x"))
    assert "https://a.example/c" in reason and "bob" not in reason


def test_the_reason_is_one_line_and_at_most_120_characters():
    reason = short_reason(RuntimeError("CUDA failed " + "x" * 400 + "\nsecond line"))
    assert len(reason) <= 120
    assert "\n" not in reason and "second line" not in reason
    assert reason.startswith("RuntimeError: CUDA failed")


def test_classifier():
    assert looks_like_a_device_failure(RuntimeError(CUDA_ERR), "cuda")
    assert looks_like_a_device_failure(OSError(CUBLAS_ERR), "cuda")
    assert looks_like_a_device_failure(ValueError("unsupported device quux"), "auto")
    # a disk-full error is not the accelerator's
    assert not looks_like_a_device_failure(OSError(28, "No space left on device"), "cuda")
    # cpu is never a device failure, whatever the text says
    assert not looks_like_a_device_failure(RuntimeError(CUDA_ERR), "cpu")
    assert not looks_like_a_device_failure(RuntimeError(CUDA_ERR), "CPU")
    # a blocked download on a GPU box keeps the network explanation
    assert not looks_like_a_device_failure(
        OSError("[WinError 10013] forbidden by its access permissions"), "cuda"
    )


# Failures that are the MODEL's availability, not the accelerator's. On `cuda` and `auto`
# they used to be called device failures (the old rule: anything not a network marker),
# so the user was told to set `device = "cpu"` instead of how to get the model.
NOT_THE_DEVICE = [
    ValueError("Invalid model size 'larg', expected one of: tiny, base, small, medium"),
    RuntimeError("404 Client Error: Repository Not Found for url: https://huggingface.co/x"),
    TimeoutError("The read operation timed out"),
    RuntimeError("429 Client Error: Too Many Requests for url: https://huggingface.co/x"),
    RuntimeError("500 Server Error: Internal Server Error for url: https://huggingface.co/x"),
    RuntimeError("503 Server Error: Service Unavailable for url: https://huggingface.co/x"),
    OSError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"),
    OSError(28, "No space left on device"),
    OSError("[Errno 28] No space left on device: '/home/u/.cache/huggingface'"),
    RuntimeError("Unable to open file 'model.bin' in model '/x/models/base.en'"),
    RuntimeError("Unexpected end of file while reading model.bin (corrupt download)"),
]

# Texts a CUDA stack prints. The first six are strings found in the CTranslate2 4.8.1
# binary; the library-load lines name the library the same way the dynamic linker does.
DEVICE_TEXTS = [
    "CUDA failed with error CUDA driver version is insufficient for CUDA runtime version",
    "CUDA failed with error no CUDA-capable device is detected",
    "CUDA failed with error out of memory",
    "cuBLAS failed with status CUBLAS_STATUS_NOT_INITIALIZED",
    "CUDA driver is a stub library",
    "No GPU is available",
    "libcublas.so.12: cannot open shared object file: No such file or directory",
    "libcudnn_ops.so.9: cannot open shared object file: No such file or directory",
    "Could not load library cudnn64_9.dll. Error code 126",
    "unsupported device quux",
    "NVIDIA driver on your system is too old",
]


@pytest.mark.parametrize("device", ["cuda", "auto", "CUDA"])
@pytest.mark.parametrize("exc", NOT_THE_DEVICE, ids=lambda e: str(e)[:40])
def test_a_model_failure_is_not_blamed_on_the_device(exc, device):
    assert not looks_like_a_device_failure(exc, device)


@pytest.mark.parametrize("device", ["cuda", "auto"])
@pytest.mark.parametrize("text", DEVICE_TEXTS, ids=lambda t: t[:40])
def test_positive_accelerator_evidence_is_a_device_failure(text, device):
    assert looks_like_a_device_failure(RuntimeError(text), device)
    assert looks_like_a_device_failure(text, device)


@needs_faster_whisper
@pytest.mark.parametrize("exc", NOT_THE_DEVICE, ids=lambda e: str(e)[:40])
def test_a_model_failure_on_cuda_gets_the_model_guidance(mocker, exc):
    with pytest.raises(ModelUnavailableError) as caught:
        _load(mocker, exc, device="cuda")
    assert type(caught.value) is ModelUnavailableError
    assert "yazses model download base.en" in str(caught.value)
    assert 'device = "cpu"' not in str(caught.value)


# ---- what must not change ----------------------------------------------


@needs_faster_whisper
def test_cpu_failures_keep_todays_wording(mocker):
    exc = RuntimeError(CUDA_ERR)  # even a CUDA-looking text, on cpu
    with pytest.raises(ModelUnavailableError) as caught:
        _load(mocker, exc, device="cpu")
    assert type(caught.value) is ModelUnavailableError
    assert str(caught.value) == model_unavailable_message("base.en", exc)


@needs_faster_whisper
def test_a_blocked_download_on_cuda_keeps_the_network_wording(mocker):
    exc = OSError("[WinError 10013] An attempt was made to access a socket in a way "
                  "forbidden by its access permissions")
    with pytest.raises(ModelUnavailableError) as caught:
        _load(mocker, exc, device="cuda")
    assert type(caught.value) is ModelUnavailableError
    assert "yazses model download base.en" in str(caught.value)


@needs_faster_whisper
def test_a_bad_compute_type_still_takes_the_compute_type_path_even_on_cuda(mocker):
    with pytest.raises(ComputeTypeUnsupportedError) as caught:
        _load(mocker, ValueError(COMPUTE_ERR), device="cuda", compute_type="float16")
    assert type(caught.value) is ComputeTypeUnsupportedError
    assert caught.value.device == "cuda" and caught.value.compute_type == "float16"
    assert "compute_type" in str(caught.value)


@needs_faster_whisper
def test_a_compute_type_error_on_the_download_attempt_still_wins_over_the_device(mocker):
    """The cached attempt misses; the second attempt raises the compute-type error."""
    from yazses.stt import faster_whisper as fw

    mocker.patch.object(
        fw, "WhisperModel", side_effect=[OSError("not in cache"), ValueError(COMPUTE_ERR)]
    )
    with pytest.raises(ComputeTypeUnsupportedError):
        fw._load_model("base.en", "cuda", "float16")


@needs_faster_whisper
def test_a_home_directory_containing_a_space_is_stripped_whole(mocker, monkeypatch):
    monkeypatch.setenv("HOME", "/home/Jane Doe")
    monkeypatch.setenv("USERPROFILE", "/home/Jane Doe")
    with pytest.raises(DeviceUnavailableError) as caught:
        _load(mocker, OSError("cannot open /home/Jane Doe/venv/libcudnn.so.9"))
    assert "Jane" not in str(caught.value) and "Doe" not in str(caught.value)


def test_golden_model_unavailable_message_is_byte_identical_to_the_base():
    """Recorded from the base commit (a241a77b) for `OSError('boom')` / `base.en`."""
    expected = (
        "The speech-to-text model 'base.en' is not on this machine, and it could not be "
        "downloaded.\n\n  Cause: boom\n\nYazSes transcribes entirely offline, but the model "
        "itself has to arrive here once. Any one of these fixes it:\n\n"
        "  1. Download it deliberately:   yazses model download base.en\n"
        "  2. Allow YazSes (or huggingface.co) through your firewall, then: yazses restart\n"
        "  3. Fetch it by hand on any machine with network access and copy it into the "
        "cache:\n"
        f"       from: {whisper_model_url('base.en')}\n"
        f"       into: {hub_cache_dir()}\n\n"
        "Dictation stays unavailable until the model is present. Everything that does not "
        "transcribe — doctor, config, the tray — keeps working."
    )
    assert model_unavailable_message("base.en", OSError("boom")) == expected
    assert ModelUnavailableError("base.en", OSError("boom")).notification() == (
        "YazSes cannot start dictation",
        "The speech model 'base.en' is missing and could not be downloaded. "
        "Run: yazses model download base.en",
    )
