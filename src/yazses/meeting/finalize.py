"""Meeting finalize pipeline (batch diarization at stop) — ADR-v2-127.

At *stop*, the whole recording is transcribed and diarized in one accurate batch pass by
delegating to ``recimport.pipeline.transcribe_file`` — the same cores as
``yazses transcribe`` (ADR-v2-125), so diarization/alignment/naming are shared, not
duplicated. The ``MeetingConfig`` fields mirror ``RecimportConfig``, so it passes straight
through. Every heavy backend (STT engine, diarizer, voiceprint embedder, notes LLM) is
injectable; with fakes the whole flow is unit-testable with no model download.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Annotation-only imports: the real modules are imported lazily inside
    # finalize_meeting so the heavy STT/diarization backends stay dormant until a
    # meeting is actually finalized. Typing these properly (they used to be bare
    # `object`) is what lets callers read `.transcript.speaker_names` type-checked.
    from yazses.meeting.notes import Minutes
    from yazses.recimport.pipeline import TranscriptResult


@dataclass(frozen=True)
class MeetingResult:
    transcript: TranscriptResult
    minutes: Minutes | None


def finalize_meeting(
    audio,
    config,
    *,
    sample_rate: int = 16000,
    names=None,
    renames=None,
    engine=None,
    diarizer=None,
    embedder=None,
    profiles=None,
    llm=None,
    progress=None,
) -> MeetingResult:
    """Transcribe + diarize the recording and (opt-in) generate minutes."""
    from yazses.recimport.pipeline import transcribe_file

    result = transcribe_file(
        None,
        config,
        audio=audio,
        sample_rate=sample_rate,
        names=names,
        renames=renames,
        engine=engine,
        diarizer=diarizer,
        embedder=embedder,
        profiles=profiles,
        progress=progress,
    )

    minutes = None
    if getattr(config, "notes", False):
        from yazses.meeting.notes import generate_minutes

        minutes = generate_minutes(
            result.utterances, config, llm=llm, speaker_names=result.speaker_names
        )
    return MeetingResult(transcript=result, minutes=minutes)
