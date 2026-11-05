"""Failures the user can fix, phrased so they can fix them.

A missing STT model is not a bug — it is a machine that has not been given the
one file YazSes cannot work without. Issue #310: a personal firewall blocked the
download and the daemon exited with a ``LocalEntryNotFoundError`` traceback,
which on the Windows bundle is a message box saying "Failed to execute script".
That tells the user nothing they can act on, and it buries the one fact that
matters — the model has to arrive on this machine once, and there are three
ways to make that happen.
"""

from __future__ import annotations

import os
import re

from yazses.stt.download import hub_cache_dir, whisper_model_url

# Markers that identify "the network refused us" rather than "the download was
# corrupt". Matched case-insensitively against the cause, which may be an httpx
# ConnectError, a WinError, a proxy failure, or huggingface_hub's own wrapper.
_NETWORK_MARKERS = (
    "connecterror",
    "connectionerror",
    "connecttimeout",
    "localentrynotfound",
    "check your internet connection",
    "forbidden by its access permissions",  # WinError 10013 — firewall
    "winerror 10013",
    "winerror 10060",  # connection timed out
    "max retries exceeded",
    "name or service not known",
    "temporary failure in name resolution",
    "ssl",
    "proxy",
)


def looks_like_a_blocked_network(cause: BaseException | str) -> bool:
    """True when *cause* reads as a connectivity/firewall problem.

    Used only to add a hint, never to decide whether to fail: a wrong guess here
    must not change what the user is told to do.
    """
    text = str(cause).lower()
    text += " " + type(cause).__name__.lower() if isinstance(cause, BaseException) else ""
    return any(marker in text for marker in _NETWORK_MARKERS)


#: ctranslate2 refuses an unsupported compute type from inside `WhisperModel(...)`
#: with: "Requested float16 compute type, but the target device or backend do not
#: support efficient float16 computation." The wording is stable across the types
#: and does not occur in any download failure.
_COMPUTE_TYPE_MARKER = "compute type"


def looks_like_an_unsupported_compute_type(cause: BaseException | str) -> bool:
    """True when *cause* is the CPU refusing `[stt] compute_type`.

    The supported set is a property of the machine, so this is a configuration
    failure and not an availability one — the model file is present and correct.
    """
    return _COMPUTE_TYPE_MARKER in str(cause).lower()


def compute_type_unsupported_message(
    model: str, compute_type: str, device: str, cause: BaseException | str
) -> str:
    """The full, actionable text for a compute type this machine cannot do."""
    lines = [
        f"YazSes cannot use the compute type {compute_type!r} on this {device}.",
        "",
        f"  Cause: {cause}",
        "",
        f"The speech model {model!r} is fine and already here — this is the "
        "`[stt] compute_type` setting, and which values work is a property of "
        "your processor.",
        "",
    ]
    supported = supported_compute_types(device)
    if supported:
        lines.append("  This machine supports: " + ", ".join(supported))
    lines += [
        "  Fix it by removing the `compute_type` line from `[stt]` in your "
        "config.toml,",
        "  which restores the default `int8` that every CPU supports. Then: "
        "yazses restart",
        "  (`yazses doctor` prints the path to that file, and the Settings "
        "window refuses",
        "   to set a type this machine cannot run.)",
        "",
        "Dictation stays unavailable until the setting is one this machine can "
        "run. Everything that does not transcribe keeps working.",
    ]
    return "\n".join(lines)


def supported_compute_types(device: str) -> list[str]:
    """What *device* actually supports, asked of ctranslate2 rather than assumed.

    Returns `[]` when the question cannot be answered — a message that lists
    nothing is worse than one that lists something wrong only if it also stops
    naming the fix, and it does not.
    """
    try:
        import ctranslate2  # type: ignore[import-untyped]

        return sorted(ctranslate2.get_supported_compute_types(device))
    except Exception:  # noqa: BLE001 - a hint must never become a second failure
        return []


# Positive evidence that the accelerator, not the model file, is what failed. Matched
# case-insensitively against the cause of a failed load on a non-CPU device. Every entry
# is a string a CUDA stack really prints; "device" and "driver" alone are NOT here, because
# a disk-full or an unrelated library error also contains them.
#
# Sources (read, not guessed):
# - CTranslate2 4.8.1 binary, `strings libctranslate2-*.so`: "CUDA failed with error ",
#   "cuBLAS failed with status ", "no CUDA-capable device is detected", "No GPU is
#   available", "CUDA driver version is insufficient for CUDA runtime version",
#   "CUDA driver is a stub library", "system has unsupported display driver / cuda driver
#   combination", "unsupported device ".
# - faster-whisper 1.2.1 README (package METADATA): needs cuBLAS 12 and cuDNN 9, loaded as
#   libcublas*.so / libcudnn*.so (cublas64_*.dll / cudnn64_*.dll on Windows), so a missing
#   library names itself and is caught by "cublas" / "cudnn".
# NOT sourced: the exact text of a cuDNN load failure ("Could not load library
# libcudnn_ops...") is quoted from memory of user reports, so only the library name is relied
# on, not the sentence.
_DEVICE_MARKERS = (
    "cuda",
    "cudnn",
    "cublas",
    "cufft",
    "curand",
    "nvrtc",
    "nvidia",
    "display driver",
    "unsupported device",
)

# "gpu" as a word: "No GPU is available", not a substring of some other token.
_GPU_WORD_RE = re.compile(r"\bgpus?\b")

_REASON_LIMIT = 120

# A real filesystem path inside an error text, matched up to the next whitespace or quote:
#   - a ``file://`` URL (it carries a local path),
#   - a UNC path ``\\host\share``,
#   - a Windows drive path ``C:\`` / ``C:/``,
#   - a home path ``~/`` / ``~\``,
#   - an absolute POSIX path ``/usr/lib/...``.
# A path only starts where a token starts: not inside a word (``cuda/cuda_utils.h:61`` is a
# relative C++ location) and not as the ``//`` of a URL (``https://docs.nvidia.com/cuda/x``),
# so URLs and relative locations survive and "libcublas.so.12" is untouched.
_PATH_RE = re.compile(
    r"""
    file://[^\s'"]*
    | (?<![\w\\])\\\\[^\s'"]*
    | (?<!\w)[A-Za-z]:[\\/][^\s'"]*
    | (?<![\w/])~[\\/][^\s'"]*
    | (?<![\w/])(?!//)/[^\s'"]*
    """,
    re.VERBOSE,
)


def _scrub_paths(text: str) -> str:
    """Replace every path-like token (and the home directory) with ``<path>``."""
    home = os.path.expanduser("~")
    if home and home not in ("~", "/"):
        text = text.replace(home, "<path>")
    return _PATH_RE.sub("<path>", text)


def short_reason(cause: BaseException | str) -> str:
    """Class name plus the first line of *cause*, path-free and at most 120 characters.

    The full text, with paths, stays in the log; this is what goes on a toast and in
    ``yazses status``-style output that users paste into bug reports.
    """
    if isinstance(cause, BaseException):
        first = (str(cause).strip().splitlines() or [""])[0]
        reason = f"{type(cause).__name__}: {first}" if first else type(cause).__name__
    else:
        reason = (str(cause).strip().splitlines() or [""])[0]
    reason = _scrub_paths(reason).strip()
    if len(reason) > _REASON_LIMIT:
        reason = reason[: _REASON_LIMIT - 3].rstrip() + "..."
    return reason


def looks_like_a_device_failure(cause: BaseException | str, device: str) -> bool:
    """True when a failed load on *device* shows positive evidence of an accelerator fault.

    Never true for ``cpu``: a CPU failure keeps the wording it always had. For any
    other device (``cuda``, ``auto``) the failure is the device's only if its text names
    the accelerator (CUDA, cuDNN, cuBLAS, NVIDIA, a GPU, an unsupported device). Anything
    else - a wrong model name, a 404, a timeout, a 429/5xx, a TLS error, a full disk, a
    corrupt file - is the model's availability, so it keeps the model guidance. Used only
    to pick the explanation, never whether to fail or retry.
    """
    if (device or "cpu").strip().lower() == "cpu":
        return False
    text = str(cause).lower()
    return any(marker in text for marker in _DEVICE_MARKERS) or bool(
        _GPU_WORD_RE.search(text)
    )


def device_unavailable_message(
    model: str, device: str, cause: BaseException | str
) -> str:
    """The full, actionable text for a device that could not run the model."""
    lines = [
        f"YazSes could not start the speech model {model!r} on [stt] device = "
        f"{device!r}.",
        "",
        f"  Cause: {short_reason(cause)}",
        "",
        "This is a problem with the device, not a missing model, so downloading "
        "the model again will not help. The full error is in `yazses logs`.",
        "",
        "  Fix it by setting `device = \"cpu\"` under `[stt]` in your config.toml, "
        "then: yazses restart",
        "  (`yazses doctor` prints the path to that file.)",
        "",
        "Dictation stays unavailable until the device works or the setting is "
        "changed. Everything that does not transcribe keeps working.",
    ]
    return "\n".join(lines)


def model_unavailable_message(model: str, cause: BaseException | str) -> str:
    """The full, actionable text for a model that is absent and unfetchable."""
    url = whisper_model_url(model)
    lines = [
        # The tray tooltip shows only the opening characters of this text, so the
        # first line is the whole answer: what is wrong, and the two commands.
        f"Speech model {model!r} missing - run: yazses model download {model}, "
        "then: yazses restart",
        "",
        f"The speech-to-text model {model!r} is not on this machine, and it "
        "could not be downloaded.",
        "",
        f"  Cause: {cause}",
    ]
    if looks_like_a_blocked_network(cause):
        lines.append(
            "  That reads as a blocked connection — a firewall, proxy or "
            "offline machine."
        )
    lines += [
        "",
        "YazSes transcribes entirely offline, but the model itself has to arrive "
        "here once. Any one of these fixes it:",
        "",
        f"  1. Download it deliberately:   yazses model download {model}, "
        "then: yazses restart",
        "  2. Allow YazSes (or huggingface.co) through your firewall, then: "
        "yazses restart",
    ]
    if url:
        lines += [
            "  3. Fetch it by hand on any machine with network access and copy "
            "it into the cache:",
            f"       from: {url}",
            f"       into: {hub_cache_dir()}",
            "     then: yazses restart",
        ]
    lines += [
        "",
        "Dictation stays unavailable until the model is present and the daemon "
        "has been restarted (a running daemon does not retry on its own). "
        "Everything that does not transcribe — doctor, config, the tray — keeps "
        "working.",
    ]
    return "\n".join(lines)


class ModelUnavailableError(RuntimeError):
    """The configured STT model is absent and could not be fetched.

    Carries the ready-to-print guidance so every caller says the same thing;
    ``__str__`` is that guidance, which is what makes a bare ``log.error("%s",
    exc)`` correct.
    """

    def __init__(self, model: str, cause: BaseException | str) -> None:
        self.model = model
        self.cause = cause
        super().__init__(model_unavailable_message(model, cause))

    def notification(self) -> tuple[str, str]:
        """Title and body for the desktop toast the daemon pops on this failure.

        It lives here rather than in `core/daemon.py` because the daemon used to
        compose its own text, so the toast and the log line stated different
        causes the moment a subclass disagreed with the base.
        """
        return (
            "YazSes cannot start dictation",
            f"The speech model {self.model!r} is missing and could not be "
            f"downloaded. Run: yazses model download {self.model}, then: "
            "yazses restart",
        )


class ComputeTypeUnsupportedError(ModelUnavailableError):
    """`[stt] compute_type` names something this processor cannot do.

    A subclass on purpose. `core/daemon.py` catches `ModelUnavailableError` to hold
    the process in ERROR state with IPC alive instead of dying with a traceback
    (#310), and dictation genuinely is unavailable here too — so the handling is
    right and only the explanation was wrong. Raising an unrelated type would have
    walked straight back into the traceback that issue was filed about.

    What it replaces: ctranslate2 rejects the value from inside `WhisperModel(...)`,
    faster-whisper's loader wrapped every exception as "the model is not on this
    machine, and it could not be downloaded", and the user was then given three
    ways to download a file already sitting in the cache. `settingsui/controller.py`
    validates compute_type against `ctranslate2.get_supported_compute_types(device)`
    precisely because of this, noting it "is reported as a missing *model*" — that
    guard covers the Settings window, and a hand-edited config had none.
    """

    def __init__(
        self, model: str, compute_type: str, device: str, cause: BaseException | str
    ) -> None:
        self.model = model
        self.compute_type = compute_type
        self.device = device
        self.cause = cause
        RuntimeError.__init__(
            self, compute_type_unsupported_message(model, compute_type, device, cause)
        )

    def notification(self) -> tuple[str, str]:
        return (
            "YazSes cannot start dictation",
            f"[stt] compute_type = {self.compute_type!r} is not supported on this "
            "machine. Remove it to use the default int8, then: yazses restart",
        )


class DeviceUnavailableError(ModelUnavailableError):
    """`[stt] device` names an accelerator that could not run the model.

    A subclass for the reason `ComputeTypeUnsupportedError` is one: `core/daemon.py`
    catches `ModelUnavailableError` to hold the process in ERROR state, and that
    handling is right. Only the explanation was wrong: a missing cuDNN or an
    insufficient driver was reported as "the model is not on this machine".
    """

    def __init__(self, model: str, device: str, cause: BaseException | str) -> None:
        self.model = model
        self.device = device
        self.cause = cause
        RuntimeError.__init__(self, device_unavailable_message(model, device, cause))

    def notification(self) -> tuple[str, str]:
        return (
            "YazSes cannot start dictation",
            f"[stt] device = {self.device!r} failed: {short_reason(self.cause)}. "
            'Set device = "cpu" under [stt] in config.toml, then: yazses restart',
        )


class LanguageUnsupportedError(ModelUnavailableError):
    """`[stt] language` names a language the configured engine/model cannot transcribe.

    Raised by `stt/factory.py` *before* any model is loaded (#515). A subclass of
    `ModelUnavailableError` for the same reason `ComputeTypeUnsupportedError` is one:
    `core/daemon.py` catches that type to hold the daemon in ERROR state with IPC
    alive, a red tray icon and a desktop toast, instead of either dying with a
    traceback or — the failure this exists to stop — loading the English-only model
    anyway and typing English for Persian speech. Every other caller of the factory
    already handles the base type, because a missing model raises it too.
    """

    def __init__(
        self,
        engine: str,
        model: str,
        language: str,
        reason: str,
        *,
        requested_engine: str = "",
        requested_model: str = "",
        requested_failure: str = "",
    ) -> None:
        """The ``requested_*`` fields are set only when a fallback engine was refused
        after the configured engine failed to start: the message then leads with that
        failure (and its fix) instead of blaming a fallback model the user never chose.
        """
        self.model = model
        self.engine = engine
        self.language = language
        self.cause = reason
        self.requested_engine = requested_engine
        self.requested_model = requested_model
        self.requested_failure = requested_failure
        if requested_engine:
            lines = [
                f"The {requested_engine} engine is not running because "
                f"{requested_failure}.",
                "",
                f"  The faster-whisper fallback cannot take over for {language!r}: "
                f"{reason}",
                "",
                f"{language!r} needs the {requested_engine} engine "
                f"({requested_model or 'your configured model'}) or a multilingual "
                "Whisper model. Fix the engine above, or set [stt] engine = "
                '"faster-whisper" with a multilingual model. '
                "`yazses language status` shows the pairing; then: yazses restart",
            ]
        else:
            lines = [
                f"YazSes will not transcribe {language!r} with {engine} / {model!r}.",
                "",
                f"  {reason}",
                "",
                "Dictation stays unavailable until [stt] language, engine and model "
                "agree, rather than silently typing English. "
                "`yazses language status` shows the pairing; then: yazses restart",
            ]
        RuntimeError.__init__(self, "\n".join(lines))

    def notification(self) -> tuple[str, str]:
        if self.requested_engine:
            return (
                "YazSes cannot start dictation",
                f"The {self.requested_engine} engine is not running because "
                f"{self.requested_failure}; {self.language!r} needs it or a "
                "multilingual Whisper model. Run: yazses language status",
            )
        return (
            "YazSes cannot start dictation",
            f"[stt] language = {self.language!r} cannot be transcribed by "
            f"{self.engine} / {self.model!r}. Run: yazses language status",
        )
