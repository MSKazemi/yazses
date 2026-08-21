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


def model_unavailable_message(model: str, cause: BaseException | str) -> str:
    """The full, actionable text for a model that is absent and unfetchable."""
    url = whisper_model_url(model)
    lines = [
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
        f"  1. Download it deliberately:   yazses model download {model}",
        "  2. Allow YazSes (or huggingface.co) through your firewall, then: "
        "yazses restart",
    ]
    if url:
        lines += [
            "  3. Fetch it by hand on any machine with network access and copy "
            "it into the cache:",
            f"       from: {url}",
            f"       into: {hub_cache_dir()}",
        ]
    lines += [
        "",
        "Dictation stays unavailable until the model is present. Everything that "
        "does not transcribe — doctor, config, the tray — keeps working.",
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
