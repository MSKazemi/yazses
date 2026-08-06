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


def inactive_reason(config) -> str | None:
    """Why ``[translate]`` is enabled but will not actually translate, else ``None``.

    Returning ``None`` from :func:`translation_task` is the right *behaviour* — silently
    transcribing instead is not the right *experience*. Someone who enabled translation
    to French and got untranslated French back has no way to tell that the combination
    they chose is unsupported. Callers log this once so the degrade is explained.

    Pure and deterministic; no logging or state here.
    """
    if not getattr(config, "enabled", False):
        return None
    backend = str(getattr(config, "backend", "whisper") or "whisper").lower()
    target = str(getattr(config, "target", "en") or "en").lower()
    if backend != "whisper":
        return (
            f"the {backend!r} translation backend is not implemented in this build; "
            f"only 'whisper' (X→English) is available"
        )
    if target not in ("en", "english"):
        return (
            f"Whisper can only translate into English, not {target!r}; "
            f"set [translate] target = \"en\" or use a different backend"
        )
    return None
