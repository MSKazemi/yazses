"""Meeting finalize pipeline (batch diarization at stop) — ADR-v2-127.

At *stop*, the whole recording is transcribed and diarized in one accurate batch pass by
delegating to ``recimport.pipeline.transcribe_file`` — the same cores as
``yazses transcribe`` (ADR-v2-125), so diarization/alignment/naming are shared, not
duplicated. The ``MeetingConfig`` fields mirror ``RecimportConfig``, so it passes straight
through. Every heavy backend (STT engine, diarizer, voiceprint embedder, notes LLM) is
injectable; with fakes the whole flow is unit-testable with no model download.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

# Pure stdlib, no models: safe to import eagerly beside the lazy heavy backends.
from yazses.meeting.quality import TranscriptQuality, assess

if TYPE_CHECKING:
    # Annotation-only imports: the real modules are imported lazily inside
    # finalize_meeting so the heavy STT/diarization backends stay dormant until a
    # meeting is actually finalized. Typing these properly (they used to be bare
    # `object`) is what lets callers read `.transcript.speaker_names` type-checked.
    from yazses.meeting.notes import Minutes
    from yazses.recimport.pipeline import TranscriptResult



log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MeetingResult:
    transcript: TranscriptResult
    minutes: Minutes | None
    # Whether the batch decode is worth believing. Computed here rather than by the
    # caller so every finalize path -- the live one and `meeting recover` -- gets the
    # same verdict from the same numbers, and so the notes decision below can read it.
    quality: TranscriptQuality = field(default_factory=TranscriptQuality)


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
    live_words: int = 0,
) -> MeetingResult:
    """Transcribe + diarize the recording and (opt-in) generate minutes.

    ``live_words`` is the word count of the rolling ``live.jsonl`` decode of this same
    audio. It is the second opinion the collapse check leans on hardest, and it has to
    be passed in because this function is deliberately filesystem-free.
    """
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
    # Minutes are a local LLM reading the transcript back. When the recording held
    # no speech, that transcript is Whisper's answer to noise -- four seconds of room
    # hiss decodes to the word "You" -- and the notes pass would turn invented words
    # into confident bullet points, which is the one output nobody can tell apart
    # from a real write-up afterwards. The transcript is still written: it is the
    # evidence, and by default the audio is deleted once this returns.
    unusable = getattr(result, "silent_input", False) or getattr(result, "no_speech", False)
    if unusable:
        log.warning(
            "Meeting audio holds no speech (%s); skipping the notes pass.",
            "no signal" if getattr(result, "silent_input", False) else "no speech detected",
        )
    # Not part of `unusable`, and deliberately not a reason to skip the notes: the
    # speech was heard correctly and the discussion is really in there. What is wrong
    # is who each line is credited to, which makes the minutes' attribution untrustworthy
    # while leaving their content worth having. Suppressing them would destroy the
    # salvageable half to hide the broken one.
    suspect = getattr(result, "attribution_suspect", "")
    if suspect:
        log.warning("%s The transcript's words are unaffected.", suspect)

    # How long the recording actually was, from the audio rather than from a caller's
    # bookkeeping: `recover` reconstructs duration from the WAV and the live path from a
    # sample count, and a quality verdict that depended on which one asked would be two
    # different guards wearing one name.
    try:
        duration_s = len(audio) / float(sample_rate or 16000)
    except (TypeError, ZeroDivisionError):  # pragma: no cover - defensive
        duration_s = 0.0
    quality = assess(getattr(result, "text", "") or "", duration_s, live_words)
    if quality.suspect:
        log.warning(
            "Meeting transcript quality is %s: %s",
            quality.verdict, "; ".join(quality.reasons) or "no detail",
        )

    # A collapsed or near-empty decode is skipped for the same reason `unusable` is:
    # minutes are a local LLM reading the transcript back, and asked to summarise 41
    # minutes of "Hello, hello, hello" it will produce confident bullet points about a
    # meeting that did not happen -- the one artefact nobody can audit afterwards.
    # Deliberately *not* extended to `live_disagrees` alone: there the batch transcript
    # is short but real, and the notes over it are merely incomplete, not invented.
    collapsed = quality.verdict in ("degenerate", "thin")
    if collapsed:
        log.warning("Skipping the notes pass: the transcript is not a usable record.")

    if getattr(config, "notes", False) and not unusable and not collapsed:
        from yazses.meeting.notes import generate_minutes

        # The transcript is the expensive, irreplaceable half: an hour of audio decoded
        # and diarized, and by default the recording is deleted once this returns. The
        # minutes are an opt-in extra generated by a local LLM. So a notes failure must
        # never take the transcript with it -- and it would, because this returns AFTER
        # the notes step and the caller only writes the transcript once it has a result.
        #
        # `generate_minutes` is careful (each window guarded, the reduce guarded,
        # `_build_llm` returning None on anything) so today nothing escapes it. That is
        # the whole point of stating it here instead: the invariant is a property of THIS
        # boundary, not of a distant module's internals, and it should not quietly depend
        # on them staying that way.
        try:
            minutes = generate_minutes(
                result.utterances, config, llm=llm, speaker_names=result.speaker_names
            )
        except Exception:  # noqa: BLE001 - an optional extra never costs the transcript
            log.exception("Minutes generation failed; keeping the transcript.")
            minutes = None
    return MeetingResult(transcript=result, minutes=minutes, quality=quality)
