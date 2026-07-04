"""Transcript rendering to sidecar formats (pure) — ADR-v2-125.

Render a :class:`~yazses.recimport.pipeline.TranscriptResult` to txt / md / srt / vtt /
json, reusing the existing pure cores (``recimport.subtitles`` subtitle writers,
``diarize.labels`` attributed Markdown). Speaker-tagged ``txt`` always carries labels
when diarized — never silently dropped (WhisperX's documented bug, research §8). ``json``
is the lossless canonical (per-word timestamps + speaker). Duck-typed on the result, so
no import cycle with the pipeline.
"""
from __future__ import annotations

import json as _json

from yazses.diarize.labels import SpeakerLabelMap, render_attributed_markdown
from yazses.recimport.subtitles import merge_word_timestamps, write_srt, write_vtt

VALID_FORMATS = ("txt", "md", "srt", "vtt", "json")


def render_transcript(result, fmt: str = "txt") -> str:
    """Render *result* as a string in *fmt* (one of :data:`VALID_FORMATS`)."""
    fmt = (fmt or "txt").lower()
    if fmt == "txt":
        return _render_txt(result)
    if fmt == "md":
        return _render_md(result)
    if fmt in ("srt", "vtt"):
        return _render_subtitles(result, fmt)
    if fmt == "json":
        return _render_json(result)
    raise ValueError(f"Unknown transcript format {fmt!r}; expected one of {VALID_FORMATS}.")


def _display(result, speaker: str) -> str:
    return result.speaker_names.get(speaker, speaker) if speaker else ""


def _render_txt(result) -> str:
    if not result.diarized:
        return (result.text or "").strip() + "\n" if result.text else ""
    lines = [f"{_display(result, u.speaker)}: {u.text}".strip() for u in result.utterances]
    return "\n".join(lines) + "\n" if lines else ""


def _render_md(result) -> str:
    if not result.diarized:
        return (result.text or "").strip() + "\n" if result.text else ""
    label_map = SpeakerLabelMap()
    for canonical, name in result.speaker_names.items():
        label_map.rename(canonical, name)
    turns = [(u.speaker, u.text) for u in result.utterances]
    md = render_attributed_markdown(turns, label_map)
    return md + "\n" if md else ""


def _render_subtitles(result, fmt: str) -> str:
    triples = [(text, start, end) for (_spk, start, end, text) in result.assigned]
    segments = merge_word_timestamps(triples)
    return write_srt(segments) if fmt == "srt" else write_vtt(segments)


def _render_json(result) -> str:
    payload = {
        "language": result.language,
        "diarized": result.diarized,
        "speakers": result.speaker_names,
        "text": result.text,
        "utterances": [
            {
                "speaker": u.speaker,
                "name": _display(result, u.speaker),
                "start": round(u.start, 3),
                "end": round(u.end, 3),
                "text": u.text,
            }
            for u in result.utterances
        ],
        "words": [
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "speaker": speaker or None,
            }
            for (speaker, start, end, text) in result.assigned
        ],
    }
    return _json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
