"""The meeting recording ``audio.wav`` is owner-only, like every other meeting file.

Every text file a meeting writes (``meeting.json``, ``live.jsonl``, the transcript, the
notes) goes through ``system/private_files`` and lands ``0600``. The recording itself was
the exception: ``WavFileSink`` opened it with ``wave.open(path, "wb")``, which takes the
process umask (``022`` on almost every login) and so created raw, unencrypted meeting
audio ``0644`` — readable by every local account wherever the directory mode does not
also protect it (a symlinked meetings dir is deliberately left alone, a user copying the
folder elsewhere). It also wrote straight through a symlink planted at ``audio.wav``.

POSIX-only: on Windows permissions are ACLs and ``private_files`` makes no claim there.
"""
from __future__ import annotations

import os
import stat
import wave

import numpy as np
import pytest

from yazses.meeting.session import WavFileSink

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX file modes only")


@pytest.fixture(params=[0o022, 0o000], ids=["umask022", "umask000"])
def umask(request):
    old = os.umask(request.param)
    try:
        yield request.param
    finally:
        os.umask(old)


@posix_only
def test_the_recording_is_created_owner_only(tmp_path, umask):
    path = tmp_path / "audio.wav"
    sink = WavFileSink(path, 16000)
    sink.write(np.zeros(160, dtype="float32"))
    sink.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with wave.open(str(path), "rb") as w:  # still a valid recording
        assert w.getnframes() == 160
        assert w.getframerate() == 16000


@posix_only
def test_a_looser_existing_recording_is_tightened(tmp_path, umask):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"stale")
    os.chmod(path, 0o644)
    WavFileSink(path, 16000).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@posix_only
def test_a_symlinked_recording_is_not_written_through(tmp_path, umask):
    target = tmp_path / "elsewhere.bin"
    target.write_bytes(b"untouched")
    os.chmod(target, 0o644)
    link = tmp_path / "audio.wav"
    link.symlink_to(target)
    with pytest.raises(OSError):
        WavFileSink(link, 16000)
    assert target.read_bytes() == b"untouched"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
