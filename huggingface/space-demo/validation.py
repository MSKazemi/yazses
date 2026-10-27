"""Pure checks for the hosted YazSes demo: upload validation, duration bounds,
transcript formatting and temp-file cleanup.

Standard library only, so the Space's logic can be unit-tested on any machine
without gradio, faster-whisper or a GPU. `app.py` owns the model and the UI.
"""

from __future__ import annotations

import math
import os
import wave
from pathlib import Path

#: Largest upload accepted, in bytes. 25 MB is about 13 minutes of 16 kHz mono 16-bit
#: WAV, or several times that as compressed audio, which is more than the duration cap
#: below will ever admit. It also bounds how much a single request can make the server
#: decode into memory.
MAX_FILE_BYTES = 25 * 1024 * 1024

#: Longest recording decoded, in seconds. The Space runs its decode inside a
#: `@spaces.GPU(duration=60)` slot, which includes the model load and the decode. The
#: project's own measurement of `base.en` on CPU int8 (docs/benchmarks.md, speed table)
#: is a real-time factor of about 0.28 at the median, so 60 s of audio decodes in about
#: 17 s there, leaving roughly 3.5x headroom for slower hardware inside the slot. Going
#: to 120 s would need the decode to be 2x faster than that measurement to stay safe,
#: and the Space's own hardware has not been measured, so the cap stays at 60 s.
MAX_DURATION_SECONDS = 60.0

#: Container/codec extensions the decoder (PyAV via faster-whisper) is expected to read.
ALLOWED_EXTENSIONS = frozenset({".wav", ".flac", ".mp3", ".ogg", ".m4a", ".webm"})

#: Returned verbatim for an empty, silent or punctuation-only decode. Never replaced by
#: text the model did not produce.
NO_SPEECH_MESSAGE = "(no speech detected)"


def check_upload(path: str | os.PathLike[str] | None) -> tuple[bool, str]:
    """Decide whether *path* is a file this demo should try to decode.

    Returns ``(ok, message)``. ``message`` is empty when ``ok`` is true and a short,
    user-facing sentence otherwise. Only metadata is read; the audio is not opened.
    """
    if not path:
        return False, "Record or upload some audio first."
    file_path = Path(path)
    if not file_path.is_file():
        return False, "The upload could not be found. Please try again."
    suffix = file_path.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ext.lstrip(".").upper() for ext in ALLOWED_EXTENSIONS))
        return False, f"That file type is not supported. Use one of: {allowed}."
    size = file_path.stat().st_size
    if size == 0:
        return False, "The uploaded file is empty."
    if size > MAX_FILE_BYTES:
        limit_mb = MAX_FILE_BYTES // (1024 * 1024)
        return False, f"That file is too large. The limit is {limit_mb} MB."
    return True, ""


def check_duration(seconds: float | None) -> tuple[bool, str]:
    """Decide whether a decoded recording is inside the duration bounds.

    Rejects missing, non-finite, non-positive and over-length values. A zero-length
    recording is treated the same as an empty upload.
    """
    if seconds is None or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        return False, "Could not determine how long that recording is."
    if seconds <= 0:
        return False, "That recording is empty."
    if seconds > MAX_DURATION_SECONDS:
        return False, (
            f"That recording is {seconds:.0f} seconds long. This demo accepts up to "
            f"{MAX_DURATION_SECONDS:.0f} seconds; trim it and try again."
        )
    return True, ""


def wav_duration_seconds(path: str | os.PathLike[str]) -> float | None:
    """Duration of a PCM WAV file from its header, or ``None`` for any other format.

    Lets `app.py` reject an over-long WAV before the decoder touches it. Other
    containers return ``None`` and are checked after decoding instead.
    """
    file_path = Path(path)
    if file_path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(file_path), "rb") as handle:
            rate = handle.getframerate()
            if rate <= 0:
                return None
            return handle.getnframes() / rate
    except (wave.Error, EOFError, OSError):
        return None


def format_transcript(segment_texts: list[str]) -> str:
    """Join decoded segment texts into the transcript shown to the user.

    Empty, whitespace-only and punctuation-only pieces (what a silent clip tends to
    yield) are dropped. If nothing remains, `NO_SPEECH_MESSAGE` is returned instead of
    an empty box, so the user can tell "nothing was heard" from "the page broke".
    """
    kept: list[str] = []
    for piece in segment_texts:
        text = (piece or "").strip()
        if any(ch.isalnum() for ch in text):
            kept.append(text)
    if not kept:
        return NO_SPEECH_MESSAGE
    return " ".join(kept)


def safe_cleanup(path: str | os.PathLike[str], temp_dir: str | os.PathLike[str]) -> bool:
    """Delete *path* only if it is a regular file strictly inside *temp_dir*.

    Both paths are resolved first, so `..` segments and symlinks that point outside the
    directory are refused. Returns ``True`` when a file was removed. The directory
    itself, anything outside it, directories and missing paths are never touched.
    """
    try:
        target = Path(path).resolve()
        root = Path(temp_dir).resolve()
    except (OSError, RuntimeError):
        return False
    if target == root or not target.is_relative_to(root):
        return False
    if not target.is_file():
        return False
    try:
        target.unlink()
    except OSError:
        return False
    return True
