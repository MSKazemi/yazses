"""What can leave this computer, and what is kept on it, read from the config. Pure.

Facts, never switches. The egress paths are inventoried in ADR-019; the two that can
carry what the user said are AI cleanup and remote dictation.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.config import Config


@dataclass(frozen=True)
class Fact:
    label: str
    value: str
    detail: str
    leaves: bool = False    # True when this setup can send dictated text elsewhere


def _cleanup(cfg: Config) -> Fact:
    from yazses.postprocess.llm_cleanup import is_loopback_endpoint

    settings = cfg.filters.disfluency
    if not settings.llm_enabled:
        return Fact("AI cleanup", "Off", "When on, it rewrites punctuation and paragraphs.")
    if settings.llm_model:
        return Fact("AI cleanup", "On", "Uses a model file on this computer.")
    local = is_loopback_endpoint(settings.llm_endpoint)
    if not local and settings.llm_allow_remote_endpoint:
        return Fact(
            "AI cleanup", "On",
            f"Sends dictated text to {settings.llm_endpoint}, which is not this computer.",
            leaves=True,
        )
    if not local:
        return Fact(
            "AI cleanup", "On",
            f"{settings.llm_endpoint} is not this computer and is not allowed, so no "
            "text is sent.",
        )
    return Fact("AI cleanup", "On", "Sends text to a model server on this computer.")


def privacy_facts(cfg: Config) -> tuple[Fact, ...]:
    """The facts the General page lists, in reading order."""
    return (
        _cleanup(cfg),
        Fact(
            "Remote dictation", "Only while you run it",
            "`yazses remote <host>` sends dictated text to that computer over SSH.",
        ),
        Fact(
            "Learning corpus", "On" if cfg.learning.enabled else "Off",
            "An encrypted record of dictations, "
            f"{'including the audio' if cfg.learning.capture_audio else 'text only'}, "
            "kept on this computer.",
        ),
        Fact(
            "Meeting audio",
            "Kept" if cfg.meeting.retain_audio else "Deleted after a good transcript",
            "It is kept if processing fails, so it can be retried. Transcripts stay on "
            "this computer.",
        ),
    )
