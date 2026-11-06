"""download_model: atomic .part, size/checksum verification, timeout (offline, fake opener)."""
from __future__ import annotations

import dataclasses
import hashlib

import pytest

from yazses.commands import model_manager as mm

MODEL = "qwen2.5-0.5b"


class _Resp:
    def __init__(self, data: bytes, *, length: int | None, fail_after: int | None = None):
        self._data, self._pos, self._fail_after = data, 0, fail_after
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        if self._fail_after is not None and self._pos >= self._fail_after:
            raise ConnectionResetError("reset")
        end = self._pos + n
        if self._fail_after is not None:
            end = min(end, self._fail_after)
        chunk = self._data[self._pos : end]
        self._pos += len(chunk)
        return chunk


@pytest.fixture
def small(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "_CACHE_BASE", tmp_path)
    info = dataclasses.replace(mm.REGISTRY[MODEL], size_mb=1)
    monkeypatch.setitem(mm.REGISTRY, MODEL, info)
    return tmp_path, info


def _opener(resp, seen=None):
    def op(url, timeout=None):
        if seen is not None:
            seen["timeout"] = timeout
        return resp

    return op


def _no_leftovers(d, info):
    assert not (d / info.filename).exists()
    assert not (d / (info.filename + ".part")).exists()


def test_success_renames_and_sets_timeout(small):
    d, info = small
    data = b"x" * (1024 * 1024)
    seen: dict = {}
    p = mm.download_model(MODEL, show_progress=False,
                          _opener=_opener(_Resp(data, length=len(data)), seen))
    assert p.read_bytes() == data
    assert not (d / (info.filename + ".part")).exists()
    assert seen["timeout"] and seen["timeout"] > 0


def test_interrupted_stream_leaves_nothing(small):
    d, info = small
    data = b"x" * (2 * 1024 * 1024)
    with pytest.raises(ConnectionResetError):
        mm.download_model(MODEL, show_progress=False,
                          _opener=_opener(_Resp(data, length=len(data), fail_after=700_000)))
    _no_leftovers(d, info)


def test_short_body_vs_content_length_is_rejected(small):
    d, info = small
    data = b"x" * (1024 * 1024)
    with pytest.raises(OSError, match="incomplete"):
        mm.download_model(MODEL, show_progress=False,
                          _opener=_opener(_Resp(data, length=len(data) + 10)))
    _no_leftovers(d, info)


def test_tiny_body_without_length_is_rejected(small):
    d, info = small
    with pytest.raises(OSError, match="only"):
        mm.download_model(MODEL, show_progress=False,
                          _opener=_opener(_Resp(b"<html>error</html>", length=None)))
    _no_leftovers(d, info)


def test_checksum_mismatch_cleans_up(small, monkeypatch):
    d, info = small
    data = b"x" * (1024 * 1024)
    monkeypatch.setitem(mm.REGISTRY, MODEL, dataclasses.replace(info, sha256="0" * 64))
    with pytest.raises(OSError, match="checksum"):
        mm.download_model(MODEL, show_progress=False,
                          _opener=_opener(_Resp(data, length=len(data))))
    _no_leftovers(d, info)


def test_checksum_match_succeeds(small, monkeypatch):
    d, info = small
    data = b"y" * (1024 * 1024)
    monkeypatch.setitem(mm.REGISTRY, MODEL,
                        dataclasses.replace(info, sha256=hashlib.sha256(data).hexdigest()))
    p = mm.download_model(MODEL, show_progress=False,
                          _opener=_opener(_Resp(data, length=len(data))))
    assert p.exists()


def test_truncated_cached_file_is_not_trusted(small):
    d, info = small
    (d / info.filename).write_bytes(b"short")
    assert mm.local_path(MODEL) is None
    data = b"z" * (1024 * 1024)
    p = mm.download_model(MODEL, show_progress=False,
                          _opener=_opener(_Resp(data, length=len(data))))
    assert p.read_bytes() == data


def test_complete_cached_file_is_kept_without_network(small):
    d, info = small
    (d / info.filename).write_bytes(b"k" * (1024 * 1024))

    def boom(*a, **k):
        raise AssertionError("network used")

    assert mm.download_model(MODEL, show_progress=False, _opener=boom).exists()
