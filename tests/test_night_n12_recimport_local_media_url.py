"""N12: a file to transcribe reaches libavformat as a ``file:`` URL, never a bare name.

libavformat (behind both PyAV and the ``ffmpeg`` CLI) reads a prefix before the first
``:`` as a protocol, so a relative name like ``concat:a.wav|b.wav`` opened *other*
files and ``Interview:1.mp3`` failed with "Protocol not found". On 8a72bbc6 both
decoders passed the raw path, so the argv/argument assertions below fail there.

Fully offline: ``subprocess.run`` and ``faster_whisper`` are replaced, nothing decodes.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types
import wave

import pytest

from tests.decoder_stack import needs_faster_whisper
from yazses.recimport import audio_io


@pytest.mark.parametrize(
    "name",
    ["concat:a.wav|b.wav", "subfile,,start,0,end,0,,:x.wav", "Interview:1.mp3", "-", "plain.wav"],
)
def test_local_media_url_is_an_absolute_file_url(name):
    url = audio_io.local_media_url(name)
    assert url == "file:" + os.path.abspath(name)
    assert os.path.isabs(url[len("file:"):])


def test_local_media_url_accepts_a_pathlike(tmp_path):
    f = tmp_path / "rec.wav"
    assert audio_io.local_media_url(f) == "file:" + os.path.abspath(f)


def test_the_ffmpeg_fallback_passes_a_file_url_after_dash_i(monkeypatch):
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(audio_io.subprocess, "run", fake_run)
    audio_io._decode_ffmpeg("concat:a.wav|b.wav", 16000)

    (cmd,) = seen
    i = cmd.index("-i")
    assert cmd[i + 1] == "file:" + os.path.abspath("concat:a.wav|b.wav")
    # The raw protocol-looking name must not appear as its own argument anywhere.
    assert "concat:a.wav|b.wav" not in cmd


def test_the_pyav_path_passes_a_file_url_to_decode_audio(monkeypatch):
    seen: list[object] = []

    def fake_decode_audio(input_file, sampling_rate=16000):
        seen.append(input_file)
        return [0.0] * 4

    fake = types.ModuleType("faster_whisper")
    fake.decode_audio = fake_decode_audio  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)

    audio_io._decode_pyav("Interview:1.mp3", 16000)
    assert seen == ["file:" + os.path.abspath("Interview:1.mp3")]


@needs_faster_whisper
@pytest.mark.skipif(sys.platform == "win32", reason="Windows forbids ':' in a filename")
def test_a_relative_name_with_a_colon_really_decodes(tmp_path, monkeypatch):
    """The tests above check the argument; this one runs the real PyAV decode.

    On 8a72bbc6 ``load_audio("Interview:1.wav")`` raised "Protocol not found" from
    libavformat, so the only thing that proves the ``file:`` URL is accepted end to
    end is decoding an actual file with that name. The ffmpeg fallback is removed so
    PyAV alone has to succeed.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(audio_io.shutil, "which", lambda _name: None)
    name = "Interview:1.wav"
    with wave.open(name, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x10" * 1600)

    audio, sr = audio_io.load_audio(name)
    assert sr == 16000
    assert len(audio) == 1600
