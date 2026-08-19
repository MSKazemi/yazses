"""Diarized Recording Import orchestration (pure given its backends) — ADR-v2-125.

``transcribe_file`` wires the pipeline: decode → ASR words → (optional) diarize turns →
align words↔turns → merge utterances → resolve speaker names → build a result the
renderer turns into a sidecar file. Every heavy backend (STT engine, diarizer, voiceprint
embedder) is *injectable*; when omitted it is lazily built from config, and when a
backend is dormant/unavailable the pipeline degrades to a plain transcript. Injecting
fakes makes the whole flow unit-testable with no model download (research §; spec).
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.postprocess.cleaner import clean_text
from yazses.recimport.align import Utterance, assign_words_to_turns, merge_utterances
from yazses.recimport.factory import build_diarizer
from yazses.recimport.naming import resolve_names


@dataclass(frozen=True)
class TranscriptResult:
    text: str                 # full plain transcript
    utterances: list          # list[Utterance] (one unattributed entry when not diarized)
    assigned: list            # per-word (speaker|"", start, end, text)
    language: str
    diarized: bool
    speaker_names: dict       # canonical speaker id -> display name
    silent_input: bool = False  # the audio carried no signal; any text is hallucinated


def _build_engine(config):
    from yazses.stt.faster_whisper import FasterWhisperEngine

    return FasterWhisperEngine(model_name=(getattr(config, "model", "") or "small.en"))


def _cleaned(u):
    """*u* with its text cleaned, or None when nothing survives. Pure."""
    cleaned = clean_text(getattr(u, "text", "") or "")
    if not cleaned.strip():
        return None
    return Utterance(u.speaker, u.start, u.end, cleaned)


def transcribe_file(
    path,
    config,
    *,
    names=None,
    renames=None,
    engine=None,
    diarizer=None,
    embedder=None,
    profiles=None,
    audio=None,
    sample_rate: int = 16000,
    progress=None,
) -> TranscriptResult:
    """Transcribe (and optionally diarize) an audio file into a ``TranscriptResult``."""
    if audio is None:
        from yazses.recimport.audio_io import load_audio

        audio, sample_rate = load_audio(path)

    if engine is None:
        engine = _build_engine(config)
    task = "translate" if getattr(config, "language", "en") == "translate" else None
    # Measured before decoding, on the audio itself. Whisper answers silence with a
    # confident hallucination rather than nothing, so this cannot be inferred from the
    # transcript afterwards.
    from yazses.recimport.audio_io import carries_no_signal

    silent_input = carries_no_signal(audio)
    text, words = engine.transcribe_words(audio, sample_rate, task=task)
    words = [w for w in words if (getattr(w, "text", "") or "").strip()]
    if progress:
        progress(0.7)

    if diarizer is None:
        diarizer = build_diarizer(config)
    turns = diarizer.diarize(audio, sample_rate) if diarizer is not None else []
    diarized = bool(turns)

    if diarized:
        turn_tuples = [(t.start, t.end, t.speaker) for t in turns]
        assigned = assign_words_to_turns(words, turn_tuples)
        utterances = merge_utterances(assigned)
        speaker_names = resolve_names(
            utterances,
            names=names,
            renames=renames,
            embedder=embedder,
            audio=audio,
            sample_rate=sample_rate,
            profiles=profiles,
            min_speaker_seconds=float(getattr(config, "min_speaker_seconds", 3.0)),
            name_threshold=float(getattr(config, "name_threshold", 0.5)),
        )
    else:
        assigned = [("", w.start, w.end, (w.text or "").strip()) for w in words]
        start = words[0].start if words else 0.0
        end = words[-1].end if words else 0.0
        utterances = [Utterance("", start, end, text)] if text else []
        speaker_names = {}

    # The dictation path injects what survives `clean_text`, never what the model
    # returned. Neither file path ran it, so Whisper's artefacts were stored as
    # transcript content: an 11.6 s meeting of room noise finalized with
    # `"text": ". . ."`, three word entries each `"."`, and `status: "done"`.
    #
    # `silent_input` above does not catch that case and cannot -- it measures the
    # *peak* of the input, and a quiet room is not digital silence. It answers "was
    # anything recorded at all"; this answers "did any of it survive cleaning".
    #
    # Utterances that clean to nothing are dropped rather than emptied, so a caller
    # counting them sees the truth. `words` are deliberately left alone: they are
    # timing data feeding alignment and subtitle spans, and an index into them is not
    # this function's to invalidate.
    utterances = [u for u in (_cleaned(u) for u in utterances) if u is not None]
    text = clean_text(text)

    if progress:
        progress(1.0)
    return TranscriptResult(
        text=text,
        utterances=utterances,
        assigned=assigned,
        language=getattr(config, "language", "en"),
        diarized=diarized,
        speaker_names=speaker_names,
        silent_input=silent_input,
    )
