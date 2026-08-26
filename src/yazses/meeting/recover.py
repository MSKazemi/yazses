"""Re-run the post-pass on a meeting whose finalize never completed — ADR-v2-127.

The daemon deletes ``audio.wav`` only *after* the batch post-pass succeeds, and its
failure path logs that the file "has been KEPT … so it can be retried". Nothing
performed that retry. The recording survived a crash, a kill, or an out-of-memory
notes model, and the only way back to a transcript was to find the WAV by hand.

This is that retry, and it is deliberately **not** the daemon's path:

* It never builds a :class:`~yazses.meeting.session.MeetingSession`. That constructor
  opens ``audio.wav`` with ``wave.open(..., "wb")`` — recovering a meeting through a
  controller would truncate the recording it is recovering, on the first line.
* It never deletes the recording. Deleting is what the *successful* live path does with
  audio it has just consumed; on a retry the file is the only copy, and a second failure
  must leave the user no worse off than the first.
"""
from __future__ import annotations

import logging
from pathlib import Path

from yazses.meeting.quality import warning as quality_warning

log = logging.getLogger(__name__)

AUDIO = "audio.wav"


def recovery_refusal(meeting_dir: str | Path, meta: dict, *, force: bool = False) -> str | None:
    """Why this meeting cannot (or must not) be recovered, else ``None``. Pure-ish.

    Split out so the CLI's refusals are testable without an STT engine, and so the
    "already finished" case is a refusal rather than a silent overwrite: a completed
    meeting's transcript is the expensive artefact, and re-running the post-pass over
    it would replace a good one with whatever this run produces.

    A meeting whose own quality check calls its transcript unusable is the exception,
    and it is the case this command was missing. ``status: "done"`` used to mean "there
    is a good transcript here"; a decode that collapses into a repetition loop reaches
    ``done`` too, and refusing on that flag alone left the one meeting that most needed
    a retry as the one meeting that could not have one. The transcript is no longer at
    risk either way — ``recover_meeting`` archives it rather than overwriting it.
    """
    d = Path(meeting_dir)
    if not d.is_dir():
        return f"No meeting directory at {d}."
    if meta.get("status") == "done" and not (force or meta.get("quality_suspect")):
        return (
            f"Meeting {meta.get('id', d.name)} already finished — its transcript is in "
            f"{d}. Nothing to recover. (Re-run it anyway with --force; the current "
            f"transcript is archived, never overwritten.)"
        )
    wav = d / AUDIO
    # `store.has_recording`, not a second size check here: the listing decides which
    # meetings to offer this command for, and a divergence between the two would offer
    # a recovery that is then refused.
    from yazses.meeting import store

    if not store.has_recording(wav):
        return (
            f"No recording kept for {meta.get('id', d.name)} — {wav} is missing or empty. "
            "If a live transcript was written it is in live.jsonl; there is nothing to "
            "re-transcribe."
        )
    return None


def recover_meeting(
    meeting_dir: str | Path,
    config,
    *,
    sample_rate: int = 16000,
    engine=None,
    diarizer=None,
    embedder=None,
    profiles=None,
    llm=None,
    progress=None,
) -> dict:
    """Transcribe the kept recording and write the meeting outputs. Heavy.

    Mirrors what ``MeetingController.finalize`` writes, so a recovered meeting is
    indistinguishable from one that finished normally — except for ``recovered: true``,
    which is recorded because the duration comes from the WAV rather than from a live
    sample count, and a reader deserves to know which.
    """
    from yazses.meeting import store
    from yazses.meeting.finalize import finalize_meeting
    from yazses.meeting.notes import render_minutes_md
    from yazses.meeting.session import read_wav_mono_f32

    d = Path(meeting_dir)
    meeting_id_early = store.read_meta(d).get("id") or d.name
    # Two things before any decoding, both cheap and both about not being able to end up
    # worse off than we started. The live transcript is rendered whether or not this run
    # succeeds; the previous attempt's outputs are moved aside, because a retry is run
    # precisely when the last result was not trusted -- and this one may be worse.
    store.write_live_transcript(d, meeting_id_early)
    live_words = store.live_word_count(d)
    archived = store.archive_outputs(d)

    audio = read_wav_mono_f32(d / AUDIO)
    res = finalize_meeting(
        audio, config, sample_rate=sample_rate, engine=engine, diarizer=diarizer,
        embedder=embedder, profiles=profiles, llm=llm, progress=progress,
        live_words=live_words,
    )
    notes_md = render_minutes_md(res.minutes) if res.minutes else None
    written = store.write_outputs(
        d, res.transcript,
        fmt=getattr(config, "output_format", "md"), notes_md=notes_md,
    )
    store.write_quality(d, res.quality)
    speakers = sorted(set(res.transcript.speaker_names.values()))
    capture = store.capture_state(
        getattr(res.transcript, "silent_input", False),
        getattr(res.transcript, "no_speech", False),
    )
    suspect = getattr(res.transcript, "attribution_suspect", "")
    meeting_id = meeting_id_early
    meta = {
        "id": meeting_id,
        "duration_s": round(len(audio) / float(sample_rate or 16000), 1),
        "diarized": res.transcript.diarized,
        "num_speakers": len(res.transcript.speaker_names),
        "speakers": speakers,
        "has_notes": notes_md is not None,
        "capture": capture,
        "attribution_suspect": suspect,
        "quality": res.quality.verdict,
        "quality_suspect": res.quality.suspect,
        # Never deleted on this path — `recover_meeting` is the retry, and a retry that
        # consumes its own only input can only be run once.
        "audio_kept": True,
        "recovered": True,
        "status": "done",
    }
    store.write_meta(d, meta)
    lines = store.summary_lines(
        {**meta, "dir": str(d)},
        live_lines=len(store.read_live_lines(d)),
        quality=res.quality.as_dict(),
    )
    store.write_summary(d, lines)
    log.info("Recovered meeting %s from %s (%d speakers)", meeting_id, d / AUDIO, len(speakers))
    return {
        **meta,
        "dir": str(d),
        "quality_warning": quality_warning(res.quality) or "",
        "archived_previous": str(archived) if archived else "",
        "summary": lines,
        "files": {k: str(v) for k, v in written.items()},
    }
