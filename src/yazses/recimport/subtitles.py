"""Word-timestamp segmentation + subtitle writers (pure) — ADR-v2-083.

Group word-level timestamps into caption segments and emit SRT/VTT. Pure and deterministic; the
STT backend that produces the words lives elsewhere.
"""
from __future__ import annotations


def format_timestamp(seconds: float, style: str = "srt") -> str:
    """Format seconds as ``HH:MM:SS,mmm`` (srt) or ``HH:MM:SS.mmm`` (vtt). Pure."""
    if seconds < 0:
        seconds = 0.0
    whole = int(seconds)
    ms = round((seconds - whole) * 1000)
    if ms == 1000:  # rounding carried into the next second
        whole += 1
        ms = 0
    h, m, s = whole // 3600, (whole % 3600) // 60, whole % 60
    sep = "," if style == "srt" else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def merge_word_timestamps(words, max_gap: float = 0.8, max_chars: int = 80):
    """Group ``(word, start, end)`` triples into ``(start, end, text)`` caption segments. Pure.

    Starts a new segment on a silence gap larger than ``max_gap`` or when the line would exceed
    ``max_chars``.
    """
    segments = []
    cur, seg_start, last_end = [], None, None
    for word, start, end in words or ():
        if not cur:
            cur, seg_start, last_end = [word], start, end
            continue
        line_len = len(" ".join(cur))
        if (start - last_end) > max_gap or line_len + 1 + len(word) > max_chars:
            segments.append((seg_start, last_end, " ".join(cur)))
            cur, seg_start = [word], start
        else:
            cur.append(word)
        last_end = end
    if cur:
        segments.append((seg_start, last_end, " ".join(cur)))
    return segments


def write_srt(segments) -> str:
    """Render ``(start, end, text)`` segments as an SRT document. Pure."""
    blocks = []
    for i, (start, end, text) in enumerate(segments or (), 1):
        blocks.append(
            f"{i}\n{format_timestamp(start, 'srt')} --> {format_timestamp(end, 'srt')}\n"
            f"{text.strip()}"
        )
    return ("\n\n".join(blocks) + "\n") if blocks else ""


def write_vtt(segments) -> str:
    """Render ``(start, end, text)`` segments as a WebVTT document. Pure."""
    blocks = ["WEBVTT"]
    for start, end, text in segments or ():
        blocks.append(
            f"{format_timestamp(start, 'vtt')} --> {format_timestamp(end, 'vtt')}\n{text.strip()}"
        )
    return "\n\n".join(blocks) + "\n"
