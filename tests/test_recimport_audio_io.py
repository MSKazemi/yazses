"""Audio decode to 16 kHz mono float32 — ADR-v2-125 (recimport/audio_io.py)."""
from __future__ import annotations

import wave

import numpy as np
import pytest

pytest.importorskip("faster_whisper")  # PyAV decode path rides in with faster-whisper

from yazses.recimport.audio_io import load_audio  # noqa: E402


def _write_wav(path, seconds=0.5, sr=16000):
    n = int(seconds * sr)
    samples = (np.sin(np.linspace(0, 40 * np.pi, n)) * 8000).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.tobytes())


def test_load_wav_returns_16k_mono_float32(tmp_path):
    f = tmp_path / "tone.wav"
    _write_wav(f)
    audio, sr = load_audio(f)
    assert sr == 16000
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert abs(len(audio) - 8000) < 400  # ~0.5s at 16 kHz


# ---- the documented contract when nothing can decode the file ---------------


def test_an_undecodable_file_raises_the_documented_runtimeerror(tmp_path, monkeypatch):
    """`load_audio` promises RuntimeError "if no decoder can read it (neither PyAV
    nor a system ffmpeg)" — and the ffmpeg fallback was unguarded, so that promise
    held only when ffmpeg was *absent*.

    With ffmpeg present and the file not audio — the ordinary case — a raw
    `CalledProcessError` escaped and `yazses transcribe` printed the whole argv:

        Transcription failed: Command '['ffmpeg', '-nostdin', '-threads', '0',
        '-i', '/…/notes.docx', '-f', 'f32le', …]' returned non-zero exit status 183.

    which names neither the problem nor anything the reader can do.
    """
    import subprocess

    from yazses.recimport import audio_io

    bad = tmp_path / "notes.docx"
    bad.write_bytes(b"PK\x03\x04 not audio")

    monkeypatch.setattr(audio_io.shutil, "which", lambda _n: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        audio_io, "_decode_pyav",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("Invalid data found")))
    monkeypatch.setattr(
        audio_io, "_decode_ffmpeg",
        lambda *_a, **_k: (_ for _ in ()).throw(
            subprocess.CalledProcessError(183, ["ffmpeg", "-nostdin", "-i", str(bad)])))

    with pytest.raises(RuntimeError) as caught:
        audio_io.load_audio(bad)

    message = str(caught.value)
    assert "ffmpeg" in message and "-nostdin" not in message, (
        f"the raw command line reached the user: {message}"
    )
    assert "not an audio or video file" in message or "truncated" in message
    assert "mp3" in message, "the message never says which formats do work"


def test_a_missing_ffmpeg_still_says_to_install_it(tmp_path, monkeypatch):
    """The other branch keeps its own advice: with no ffmpeg at all, the useful
    thing to say is 'install it', not 'this file is not audio'."""
    from yazses.recimport import audio_io

    bad = tmp_path / "clip.opus"
    bad.write_bytes(b"nope")
    monkeypatch.setattr(audio_io.shutil, "which", lambda _n: None)
    monkeypatch.setattr(
        audio_io, "_decode_pyav",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("no decoder")))

    with pytest.raises(RuntimeError, match="Install ffmpeg"):
        audio_io.load_audio(bad)
