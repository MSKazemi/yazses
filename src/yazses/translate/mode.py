"""Speech-translation mode decision (pure) — ADR-v2-014.

Decide whether/how to translate on the dictation path. X→English uses Whisper's
built-in ``task=translate`` (no new dep); other targets need the Seamless backend
(opt-in, out of scope for this pure layer). Pure and testable.
"""
from __future__ import annotations


def translation_task(config) -> str | None:
    """Return the faster-whisper ``task`` for the current translate config, or ``None``.

    Returns ``"translate"`` only when translation is enabled, the ``whisper`` backend
    is selected, and the target is English (Whisper translate is X→English only). Any
    other combination returns ``None`` (transcribe as normal), so a disabled or
    heavy-backend setup never silently changes behavior. Pure and deterministic.
    """
    if not getattr(config, "enabled", False):
        return None
    backend = str(getattr(config, "backend", "whisper") or "whisper").lower()
    target = str(getattr(config, "target", "en") or "en").lower()
    if backend == "whisper" and target in ("en", "english"):
        return "translate"
    return None
