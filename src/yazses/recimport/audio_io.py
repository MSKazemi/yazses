"""Audio-file decoding to 16 kHz mono float32 (ADR-v2-125).

Primary path reuses ``faster_whisper.decode_audio`` (PyAV), which is already a
transitive dependency of the STT stack YazSes ships — so mp3/m4a/aac/opus/mp4/ogg/
flac/wav all decode and resample with **no new dependency** (research §3). A system
``ffmpeg`` subprocess is a fallback for the rare files where PyAV's decode loop stalls.
"""
from __future__ import annotations

import logging
import os
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
    # The docstring promised this and nothing checked, so a path that does not exist
    # fell through to the decode-failure branch and was reported as "probably not an
    # audio or video file, or it is truncated" -- every cause wrong, and each one
    # sends the reader to inspect the file's contents rather than its name. Only
    # reachable programmatically (the CLI rejects a missing path at argument
    # parsing); found through the MCP server, where an agent hits it directly.
    #
    # `is_file` rather than `exists`: a directory is present, and calling it missing
    # would just be a different wrong cause. It falls through to the decoder, which
    # reports that it cannot be read.
    if not os.path.exists(path):
        raise FileNotFoundError(f"No such file: {path}")
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


# Peak amplitude below which a recording carries nothing a microphone produced.
# A muted input, a device that was never opened, or capture stolen by another
# application all write exact digital zero; a working microphone's noise floor is
# orders of magnitude above this even in a quiet room. Set low deliberately: this
# exists to catch "there is no audio here at all", not to judge quiet speech.
SIGNAL_FLOOR = 1e-4


def carries_no_signal(audio, floor: float = SIGNAL_FLOOR) -> bool:
    """True when *audio* holds no signal at all -- a failed capture, not quiet speech.

    Measured on the **peak**, not the mean. The daemon's silence gate averages,
    which is right for a hold-to-talk burst that is nearly all speech, and wrong
    for a file: an hour of interview with sparse talking averages to almost
    nothing, so a mean-based gate would call a real recording silent.

    This is a statement about the input, which is why it is worth making. Whisper
    answers silence with a confident hallucination -- two seconds of digital
    silence decodes to "You", with a start and an end time -- so the empty
    transcript check cannot see it, and no threshold on the *output* separates a
    hallucinated word from a real one.
    """
    import numpy as np

    if audio is None or getattr(audio, "size", 0) == 0:
        return True
    return float(np.abs(audio).max()) < floor
