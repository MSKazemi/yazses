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
    segments: list[tuple[float, float, str]] = []
    cur: list[str] = []
    # Set together with the first word of a segment, so they are floats whenever
    # ``cur`` is non-empty — which is the only condition under which a segment is
    # emitted. Kept as 0.0 rather than None so that invariant is expressed in the
    # types instead of relying on the reader to reconstruct it.
    seg_start: float = 0.0
    last_end: float = 0.0
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


#: Maximum characters per *rendered line*. `merge_word_timestamps` already caps a segment
#: at 80 characters, but the writers emitted that as ONE line -- on a real 162-second
#: recording, 18 of 22 cues were a single line of up to 80 characters.
#:
#: Every player and every subtitle standard assumes roughly half that: EBU-TT-D, the BBC
#: guidelines and Netflix's timed-text spec all sit at 37-42 characters over at most two
#: lines, because that is what fits the video width at default caption size. A longer line
#: does not fail loudly -- the player wraps it itself, wherever it likes, or lets it run off
#: the frame.
#:
#: 42 and 2 lines happen to fit the existing 80-character segment budget exactly, so the
#: segmentation (and therefore every timestamp) is untouched by this.
CAPTION_LINE_CHARS = 42
CAPTION_MAX_LINES = 2


def wrap_caption(text: str, width: int = CAPTION_LINE_CHARS,
                 max_lines: int = CAPTION_MAX_LINES) -> str:
    """Break one caption into at most ``max_lines`` lines of ``width``. Pure.

    The split is balanced rather than greedy: greedy filling produces a full line above a
    two-word line, which reads worse and draws the eye to the wrong place. Balanced means
    choosing the word boundary nearest the middle that still fits.

    Text that cannot fit is wrapped onto further lines rather than truncated. A caption
    that loses words is worse than one that is too tall, and callers already cap the
    segment length -- overflow here means that cap changed, not that the text is expendable.
    """
    words = (text or "").split()
    if not words:
        return ""
    if len(" ".join(words)) <= width:
        return " ".join(words)

    # Balanced two-line split: the boundary closest to the middle where both sides fit.
    if max_lines >= 2:
        total = len(" ".join(words))
        best = None
        for i in range(1, len(words)):
            head, tail = " ".join(words[:i]), " ".join(words[i:])
            if len(head) <= width and len(tail) <= width:
                skew = abs(len(head) - total / 2)
                if best is None or skew < best[0]:
                    best = (skew, head, tail)
        if best is not None:
            return f"{best[1]}\n{best[2]}"

    # Nothing fits in two lines -- greedy fill, keeping every word.
    lines: list[str] = []
    cur = ""
    for word in words:
        candidate = f"{cur} {word}".strip()
        if cur and len(candidate) > width:
            lines.append(cur)
            cur = word
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def write_srt(segments) -> str:
    """Render ``(start, end, text)`` segments as an SRT document. Pure."""
    blocks = []
    for i, (start, end, text) in enumerate(segments or (), 1):
        blocks.append(
            f"{i}\n{format_timestamp(start, 'srt')} --> {format_timestamp(end, 'srt')}\n"
            f"{wrap_caption(text)}"
        )
    return ("\n\n".join(blocks) + "\n") if blocks else ""


def write_vtt(segments) -> str:
    """Render ``(start, end, text)`` segments as a WebVTT document. Pure."""
    blocks = ["WEBVTT"]
    for start, end, text in segments or ():
        blocks.append(
            f"{format_timestamp(start, 'vtt')} --> {format_timestamp(end, 'vtt')}\n{wrap_caption(text)}"
        )
    return "\n\n".join(blocks) + "\n"
