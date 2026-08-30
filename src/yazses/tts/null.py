"""No-op TTS backend (spec-read-back-loop).

Returned by ``build_tts`` when ``[tts] enabled`` but the engine import or model is
unavailable, so the daemon degrades gracefully instead of crashing — read-back
simply produces no audio.
"""
from __future__ import annotations

from collections.abc import Iterator


class NullTtsBackend:
    """A backend that synthesizes/plays nothing."""

    @property
    def name(self) -> str:
        return "null"

    def begin(self) -> None:
        """Accept the read-back path's utterance claim; there is nothing to clear."""
        return None

    def synthesize(self, text: str) -> Iterator[bytes]:
        return iter(())

    def speak(self, text: str) -> None:
        return None

    def cancel(self) -> None:
        return None
