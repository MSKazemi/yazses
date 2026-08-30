"""Why read-back is silent, said accurately — not "install the extra" every time.

`build_tts` wrapped the whole construction in one `except Exception` and answered every
failure with *"install the `tts` extra (uv sync --extra tts)"*. Constructing the Kokoro
backend does two very different things under that one `except`: it imports
`kokoro_onnx`, and it **downloads a ~340 MB voice model on first use**. Only the first
is fixed by installing an extra.

So a user behind a firewall — with the extra already installed — was told to install it
again, in a `log.warning` they would have to go looking for, while read-back silently
produced nothing. That is not a hypothetical shape: issue #310, the first bug reported
by a real user of this project, was a blocked model download misreported as something
else.

`system/backends.py` exists for exactly this and was already wired into the denoise,
voiceprint and diarization factories; the read-back factory was the one that still
collapsed the cases. The three answers are now distinct: the adapter was never shipped
(nothing installs it), a dependency is missing (the named extra fixes it), or everything
is installed and the backend still would not start (which is a model or a device, and
the message says where to look).
"""
from __future__ import annotations

import logging
import pathlib

import pytest

from yazses.config import TtsConfig
from yazses.tts.factory import build_tts


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.WARNING, logger="yazses.tts.factory")
    return caplog


def _text(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


def test_a_blocked_model_download_is_not_reported_as_a_missing_extra(
    logs, monkeypatch, tmp_path: pathlib.Path
) -> None:
    """The #310 shape: the dependency is present and the network is not."""
    pytest.importorskip("kokoro_onnx", reason="the tts extra provides the adapter's dep")

    import yazses.tts.download as download

    def unreachable(echo=None):
        raise OSError("[Errno 101] Network is unreachable")

    monkeypatch.setattr(download, "download_models", unreachable)

    backend = build_tts(
        TtsConfig(
            enabled=True,
            engine="kokoro",
            model_path=str(tmp_path / "absent.onnx"),
            voices_path=str(tmp_path / "absent.bin"),
        )
    )
    assert backend.name == "null", "read-back must degrade, never crash"

    text = _text(logs)
    assert text, "a silent read-back was not reported at all"
    assert "extra" not in text.lower(), (
        "a blocked download was blamed on a missing extra that is already "
        f"installed:\n{text}"
    )
    assert "Network is unreachable" in text, "the real error was not passed through"


def test_an_engine_with_no_adapter_is_not_offered_an_extra_that_cannot_supply_it(
    logs,
) -> None:
    """`melo` and `kitten` are documented values with no module in this build.

    Installing the `tts` extra cannot produce them, so advising it is the same lie
    `system/backends.py` was written to stop telling for `deepfilternet`.
    """
    backend = build_tts(TtsConfig(enabled=True, engine="melo"))
    assert backend.name == "null"
    text = _text(logs)
    assert "not implemented" in text.lower(), text
    assert "uv sync" not in text, f"an unimplemented backend was offered an extra:\n{text}"


def test_a_missing_dependency_still_names_the_extra(logs, monkeypatch) -> None:
    """The one case where the old message was right must keep working."""
    import yazses.system.backends as backends

    real = backends.probe_backend

    def as_if_absent(backend, **kw):
        return real(backend, **{**kw, "missing": lambda mods: [
            m for m in mods if m == "kokoro_onnx"
        ]})

    monkeypatch.setattr("yazses.tts.factory.probe_backend", as_if_absent)
    backend = build_tts(TtsConfig(enabled=True, engine="kokoro"))
    assert backend.name == "null"
    text = _text(logs)
    assert "kokoro_onnx" in text and "tts" in text, text


def test_the_factory_stays_dormant_when_read_back_is_off(logs) -> None:
    """No probe, no import, no log line — the ADR-011 dormancy contract."""
    assert build_tts(TtsConfig(enabled=False)) is None
    assert not _text(logs)
