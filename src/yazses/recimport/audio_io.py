"""Audio-file decoding to 16 kHz mono float32 (ADR-v2-125).

Primary path reuses ``faster_whisper.decode_audio`` (PyAV), which is already a
transitive dependency of the STT stack YazSes ships — so mp3/m4a/aac/opus/mp4/ogg/
flac/wav all decode and resample with **no new dependency** (research §3). A system
``ffmpeg`` subprocess is a fallback for the rare files where PyAV's decode loop stalls.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

import numpy as np

log = logging.getLogger(__name__)


def load_audio(path, sample_rate: int = 16000):
    """Decode any common audio file to ``(mono float32 ndarray, sample_rate)``.

    Raises ``FileNotFoundError`` if the path is missing and ``RuntimeError`` if no
    decoder can read it (neither PyAV nor a system ffmpeg).
    """
    path = str(path)
    try:
        audio = _decode_pyav(path, sample_rate)
        return np.asarray(audio, dtype="float32"), sample_rate
    except Exception as exc:
        if shutil.which("ffmpeg"):
            log.warning("PyAV decode failed for %s (%s); falling back to ffmpeg.", path, exc)
            try:
                return _decode_ffmpeg(path, sample_rate), sample_rate
            except Exception as ffmpeg_exc:
                # The fallback was unguarded, so the docstring's promise held only when
                # ffmpeg was *missing*. When both decoders failed -- the ordinary case
                # for a file that is not audio -- a raw CalledProcessError escaped and
                # the user was shown the whole ffmpeg argv:
                #
                #   Transcription failed: Command '['ffmpeg', '-nostdin', '-threads',
                #   '0', '-i', '/…/notes.docx', '-f', 'f32le', …]' returned non-zero
                #   exit status 183.
                #
                # which says nothing about what is wrong or what to do about it.
                raise RuntimeError(
                    f"Could not decode {path!r} as audio. Neither PyAV nor ffmpeg could "
                    "read it, so it is probably not an audio or video file, or it is "
                    "truncated. Any format ffmpeg reads works: wav, mp3, m4a, flac, ogg, "
                    "opus, mp4, mkv."
                ) from ffmpeg_exc
        raise RuntimeError(
            f"Could not decode {path!r}: {exc}. Install ffmpeg for broader format support."
        ) from exc


def _decode_pyav(path, sample_rate):
    """Decode via faster-whisper's bundled PyAV helper (import-location tolerant)."""
    try:
        from faster_whisper import decode_audio
    except ImportError:
        from faster_whisper.audio import decode_audio
    return decode_audio(path, sampling_rate=sample_rate)


def _decode_ffmpeg(path, sample_rate):
    """Decode via a system ffmpeg subprocess to raw f32le mono."""
    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0", "-i", path,
        "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=True)
    return np.frombuffer(proc.stdout, dtype="float32").copy()
