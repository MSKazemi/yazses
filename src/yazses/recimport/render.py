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
    """Captions, segmented **within** each speaker's run and labelled when diarized.

    The words were segmented on silence and line length alone, with the speaker thrown
    away, which did the very thing this module's docstring names as the bug to avoid:

        00:00:00,000 --> 00:00:04,000
        hello there hi              <- Alice's words and Bob's, in one caption, unlabelled

    Two separate faults there. The missing label is a loss; the *merge* is worse, because
    the caption then asserts something untrue — one person said all of it — and a caption
    file is read by people who were not in the room.

    Segments are built per contiguous speaker run, so a caption can never straddle a
    speaker change, and each is prefixed with the display name when the recording is
    diarized. An undiarized transcript is unchanged.
    """
    runs: list[tuple[str, list]] = []
    for spk, start, end, text in result.assigned or ():
        if runs and runs[-1][0] == spk:
            runs[-1][1].append((text, start, end))
        else:
            runs.append((spk, [(text, start, end)]))

    segments: list[tuple[float, float, str]] = []
    for spk, triples in runs:
        name = _display(result, spk) if result.diarized else ""
        for seg_start, seg_end, text in merge_word_timestamps(triples):
            segments.append((seg_start, seg_end, f"{name}: {text}" if name else text))
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
