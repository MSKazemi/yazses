"""Why gaze is dormant, said accurately — the sixth factory to collapse the cases.

`build_gaze` wrapped the whole construction in one `except Exception` and answered
every failure with *"install the `gaze` extra"*. Two of the things under that `except`
are not fixed by installing it.

**`backend = "l2cs"` is never fixed by it.** `pyproject.toml` declares the `gaze` extra
as mediapipe only and says so in a comment: l2cs "pulls an older torch that conflicts
with a unified resolution, so it is intentionally NOT declared — install it manually".
Advising the extra therefore sends the user after a package that cannot supply the
backend they chose, which is the exact lie `system/backends.py` was written to stop
telling for `resemblyzer` and `pyannote`.

**A blocked model download is not fixed by it either.** `MediapipeGazeBackend` calls
`ensure_face_landmarker()`, which fetches a ~3.7 MB model from Google on first use. On
a firewalled machine that raises, and the user — extra already installed — is told to
install it again.

Both land in a `log.warning` and then silence: gaze targeting simply never runs while
`yazses features` still shows the capability as ON. That is the failure mode this
project's own enum ledger calls "the worst of the three", and the message is the only
part of it a user ever sees.
"""
from __future__ import annotations

import logging
import pathlib

import pytest

from yazses.config import GazeConfig
from yazses.gaze.factory import build_gaze


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.WARNING, logger="yazses.gaze.factory")
    return caplog


def _text(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


def test_l2cs_is_not_advised_an_extra_that_deliberately_excludes_it(logs) -> None:
    pytest.importorskip  # noqa: B018 - documents that no import is needed here
    if not _absent("l2cs"):
        pytest.skip("l2cs is installed here, so there is no unavailability to report")

    assert build_gaze(GazeConfig(enabled=True, backend="l2cs")) is None
    text = _text(logs)
    assert text, "a dormant gaze backend was not reported at all"
    assert "l2cs" in text
    assert "`gaze` extra" not in text, (
        "the gaze extra is mediapipe-only by design, and was advised for l2cs:\n" + text
    )


def test_a_blocked_model_download_is_not_reported_as_a_missing_extra(
    logs, monkeypatch, tmp_path: pathlib.Path
) -> None:
    pytest.importorskip("mediapipe", reason="the gaze extra provides the adapter's dep")

    import yazses.gaze.download as download

    def unreachable(dest=None, *, echo=None):
        raise OSError("[Errno 101] Network is unreachable")

    monkeypatch.setattr(download, "ensure_face_landmarker", unreachable)

    assert build_gaze(GazeConfig(enabled=True, backend="mediapipe")) is None
    text = _text(logs)
    assert text
    assert "extra" not in text.lower(), (
        "a blocked download was blamed on a missing extra that is already "
        f"installed:\n{text}"
    )
    assert "Network is unreachable" in text, "the real error was not passed through"


def test_an_unknown_backend_is_not_offered_a_remedy(logs) -> None:
    """`[gaze] backend` is a closed set; a value outside it has nothing to install."""
    assert build_gaze(GazeConfig(enabled=True, backend="mediapip")) is None
    text = _text(logs).lower()
    assert "not implemented" in text or "unknown" in text, text
    assert "uv sync" not in text, text


def test_the_factory_stays_dormant_when_gaze_is_off(logs) -> None:
    """No probe, no import, no camera, no log line (ADR-011)."""
    assert build_gaze(GazeConfig(enabled=False)) is None
    assert not _text(logs)


def _absent(module: str) -> bool:
    from yazses.system.deps import missing_modules

    return bool(missing_modules([module]))
