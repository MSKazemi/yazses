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


def _build_engine(config):
    from yazses.stt.faster_whisper import FasterWhisperEngine

    return FasterWhisperEngine(model_name=(getattr(config, "model", "") or "small.en"))


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

    if progress:
        progress(1.0)
    return TranscriptResult(
        text=text,
        utterances=utterances,
        assigned=assigned,
        language=getattr(config, "language", "en"),
        diarized=diarized,
        speaker_names=speaker_names,
    )
