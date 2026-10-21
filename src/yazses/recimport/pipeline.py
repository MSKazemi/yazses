"""Diarized Recording Import orchestration (pure given its backends) — ADR-v2-125.

``transcribe_file`` wires the pipeline: decode → ASR words → (optional) diarize turns →
align words↔turns → merge utterances → resolve speaker names → build a result the
renderer turns into a sidecar file. Every heavy backend (STT engine, diarizer, voiceprint
embedder) is *injectable*; when omitted it is lazily built from config, and when a
backend is dormant/unavailable the pipeline degrades to a plain transcript. Injecting
fakes makes the whole flow unit-testable with no model download (research §; spec).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from yazses.postprocess.cleaner import clean_text
from yazses.recimport.align import Utterance, assign_words_to_turns, merge_utterances
from yazses.recimport.factory import build_diarizer
from yazses.recimport.naming import resolve_names
from yazses.recimport.plausibility import attribution_problem

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptResult:
    text: str                 # full plain transcript
    utterances: list          # list[Utterance] (one unattributed entry when not diarized)
    assigned: list            # per-word (speaker|"", start, end, text)
    language: str
    diarized: bool
    speaker_names: dict       # canonical speaker id -> display name
    silent_input: bool = False  # the audio carried no signal; any text is hallucinated
    no_speech: bool = False     # signal, but a speech detector found none; same for the text
    # Set when the speaker labels do not look like people (ADR-v2-133). Orthogonal to
    # the two above: the speech is real and was heard correctly, only the attribution
    # is wrong, so it is a separate field rather than another value of one flag.
    attribution_suspect: str = ""


def _build_engine(config, stt=None):
    """The Whisper engine for a file transcription, built from the user's settings.

    Not `stt.factory.build_engine`: this path needs `transcribe_words`, which is a
    faster-whisper method rather than part of the `SttEngine` protocol. What it must
    still share with that factory is *what the user configured*, and every setting it
    has dropped was dropped silently -- `language` reaches the decoder only through
    this constructor and defaults to `"en"`, so `--language fa` once had Persian audio
    transcribed as English; the model fell back to a hard-coded `small.en` rather than
    `[stt] model`; and `[stt] device`/`compute_type` never arrived at all.

    So the decision lives in one pure function,
    :func:`yazses.stt.decoder_settings.file_decoder_settings`, and this only executes
    it. ``config`` is the ``[recimport]`` or ``[meeting]`` section; ``stt`` is the
    ``[stt]`` section (``None`` = its defaults). ``[stt] chinese_script`` (#501,
    COMP-03) and ``[stt] persian_normalisation`` are applied the way the daemon's
    factory applies them, but judged against the *file's* model and language.
    """
    from yazses.stt.decoder_settings import file_decoder_settings
    from yazses.stt.faster_whisper import FasterWhisperEngine

    settings = file_decoder_settings(stt, config)
    for problem in settings.problems:
        log.warning("[transcribe] %s", problem)
    engine = FasterWhisperEngine(
        model_name=settings.model,
        device=settings.device,
        compute_type=settings.compute_type,
        language=settings.language,
        cpu_threads=settings.cpu_threads,
        beam_size=settings.beam_size,
        condition_on_previous_text=settings.condition_on_previous_text,
    )
    if stt is None:
        return engine
    from yazses.postprocess.persian_text import is_persian_language
    from yazses.stt.factory import _with_han_script, _with_persian_normaliser

    # `settings` carries `model`, `language`, `chinese_script` and
    # `persian_normalisation` -- every attribute the two wrappers read -- so their
    # checks ("an .en model cannot emit Han characters") look at this decode, not at
    # the dictation model. The Persian wrapper is applied only to a Persian file: on
    # any other it would log that the opt-in "has no effect", which is true of this
    # file and misleading about the user's dictation.
    engine = _with_han_script(engine, settings)
    if is_persian_language(settings.language):
        engine = _with_persian_normaliser(engine, settings)
    return engine


def cleaned_utterance(u):
    """*u* with its text cleaned, or None when nothing survives. Pure.

    Public because `meeting/store.py::relabel` must apply the *same* rule: it rebuilds a
    transcript from stored data and would otherwise resurrect exactly the artefacts this
    drops.
    """
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
    stt=None,
) -> TranscriptResult:
    """Transcribe (and optionally diarize) an audio file into a ``TranscriptResult``.

    ``config`` is the ``[recimport]`` or ``[meeting]`` section -- never the whole
    ``Config``, which raises ``TypeError``. ``stt`` is the ``[stt]`` section, used only
    when no ``engine`` is passed: the engine built here then inherits ``[stt] model``
    (when the section's is empty), device, precision and ``chinese_script`` (#501).
    """
    from yazses.stt.decoder_settings import file_decoder_settings, require_section

    require_section(config, "transcribe_file")
    if audio is None:
        from yazses.recimport.audio_io import load_audio

        audio, sample_rate = load_audio(path)

    if engine is None:
        engine = _build_engine(config, stt=stt)
    # From the same pure rule the engine was built with, so the two cannot disagree
    # about whether this decode is a translation.
    task = file_decoder_settings(stt, config).task
    # Measured before decoding, on the audio itself. Whisper answers silence with a
    # confident hallucination rather than nothing, so this cannot be inferred from the
    # transcript afterwards.
    from yazses.recimport.audio_io import carries_no_signal, holds_no_speech

    silent_input = carries_no_signal(audio)
    # A separate question with a separate remedy. `silent_input` means nothing was
    # captured -- a muted mic, the wrong device. `no_speech` means something was
    # captured and none of it is speech: music, room noise, a recording of the wrong
    # thing. Both produce invented words, and telling a user to check their input
    # device when the file is a song sends them to the wrong place. Only asked when
    # the peak test already passed, so the cheap answer wins where it applies.
    no_speech = False if silent_input else holds_no_speech(audio, sample_rate) is True
    text, words = engine.transcribe_words(audio, sample_rate, task=task)
    words = [w for w in words if (getattr(w, "text", "") or "").strip()]
    if progress:
        progress(0.7)

    if diarizer is None:
        diarizer = build_diarizer(config)
    turns = diarizer.diarize(audio, sample_rate) if diarizer is not None else []
    diarized = bool(turns)
    # Asked of the turns, before alignment collapses them into utterances. Measured
    # on AMI, the shipped clustering can return 86 labels for four people and nothing
    # downstream can tell -- the transcript is fluent, the timings are right, and the
    # minutes in ADR-v2-128 will name the crowd as participants.
    attribution_suspect = (attribution_problem(turns) or "") if diarized else ""

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
    utterances = [u for u in (cleaned_utterance(u) for u in utterances) if u is not None]
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
        no_speech=no_speech,
        attribution_suspect=attribution_suspect,
    )
