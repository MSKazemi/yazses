"""TTS backend factory (spec-read-back-loop).

``build_tts`` honours the dormancy contract used across YazSes (parallel to
``learning.build_writer`` / ``build_cleaner``):

- ``[tts] enabled = false`` -> ``None`` (fully dormant; nothing imported/downloaded).
- enabled but the engine is unavailable -> :class:`NullTtsBackend` (degrade, never
  crash).

Degrading is only half the contract: read-back that produces nothing has no other
symptom, so the log line *is* the whole diagnosis. It used to be one blanket
``except`` answering every failure with "install the ``tts`` extra", which collapses
three unrelated situations. Constructing the Kokoro backend imports ``kokoro_onnx``
**and** downloads a ~340 MB voice model on first use; only the first is fixed by
installing an extra, and ``melo``/``kitten`` are documented engine values with no
module in this build, which nothing installs. Issue #310 -- the first bug a real user
of this project reported -- was a blocked model download misreported as something
else, so the shape is known rather than imagined.

``system/backends.py`` already tells "not shipped" from "dependency missing" for the
denoise, voiceprint and diarization seams; this one now asks it too, and keeps a
separate message for the case where everything is installed and the backend still
would not start.
"""
from __future__ import annotations

import logging

from yazses.system.backends import probe_backend
from yazses.tts.base import TtsBackend
from yazses.tts.null import NullTtsBackend

log = logging.getLogger(__name__)

#: Third-party import names each engine's adapter needs, and the extra providing them.
_REQUIRES: dict[str, tuple[str, ...]] = {"kokoro": ("kokoro_onnx",)}
_EXTRA = "tts"


def _build(engine: str, config) -> TtsBackend:
    """Construct the adapter for *engine*. Only reached once its probe came back OK."""
    from yazses.tts.kokoro import KokoroTtsBackend

    return KokoroTtsBackend(config)


def build_tts(config) -> TtsBackend | None:
    """Return a TTS backend for *config*, or None when ``[tts]`` is disabled."""
    if not getattr(config, "enabled", False):
        return None

    engine = str(getattr(config, "engine", "kokoro") or "kokoro")
    status = probe_backend(
        engine,
        adapter=f"yazses.tts.{engine}",
        requires=_REQUIRES.get(engine, ()),
        extra=_EXTRA,
    )
    if not status.available:
        log.warning(
            "Read-back is enabled but %s. No speech will be produced.", status.message
        )
        return NullTtsBackend()

    try:
        return _build(engine, config)
    except Exception as exc:
        # Everything the backend needs is installed, so the extra is not the answer.
        # What is left is the model download (~340 MB, fetched on first use) or the
        # audio device -- both of which the error itself names, so it is passed
        # through rather than summarised away.
        log.warning(
            "Read-back is enabled and the %r backend is installed, but it could not "
            "start: %s. The voice model is downloaded on first use, so a blocked or "
            "interrupted download is the usual cause; `docs/how-to/air-gapped.md` "
            "covers installing it by hand. Read-back will be silent.",
            engine, exc,
        )
        return NullTtsBackend()
