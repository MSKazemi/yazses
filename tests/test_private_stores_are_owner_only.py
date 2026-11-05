"""Plaintext private stores are owner-only on POSIX: dirs 0700, files 0600.

The meeting store (transcripts of a whole meeting), the clipboard history and the scratch
notes are unencrypted files. Created with ``Path.write_text`` they took the process umask
and were 0644 inside a 0755 directory, readable by every other local account. The learning
corpus and voiceprints sit behind a 0600 key; these have only their mode.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import types
from pathlib import Path

import pytest

from yazses.cliphistory import store as clip
from yazses.meeting import store as ms
from yazses.recall.scratch import ScratchPad

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or os.name != "posix",
    reason="POSIX permission bits; Windows uses ACLs, which these stores do not set",
)


def _mode(p: Path) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


@pytest.fixture(params=[0o022, 0o000], ids=["umask022", "umask000"])
def umask(request):
    old = os.umask(request.param)
    try:
        yield request.param
    finally:
        os.umask(old)


def _meeting(tmp_path: Path) -> Path:
    cfg = types.SimpleNamespace(output_dir=str(tmp_path / "meetings"))
    return ms.new_meeting(cfg, "m1")


def test_meeting_store_is_owner_only(tmp_path, umask):
    d = _meeting(tmp_path)
    ms.write_meta(d, {"id": "m1", "title": "board"})
    ms.append_live_line(d, "the password is hunter2", 1.0)
    ms.append_live_markdown(d, "the password is hunter2", 1.0, "m1")
    ms.write_live_transcript(d, "m1")
    ms.write_quality(d, {"words": 4})
    ms.write_summary(d, ["a", "b"])
    assert _mode(d) == 0o700
    names = {f.name for f in d.iterdir()}
    assert {"meeting.json", "live.jsonl", "quality.json", "summary.md"} <= names
    for f in d.iterdir():
        assert _mode(f) == 0o600, f.name


def test_meeting_outputs_and_archive_are_owner_only(tmp_path, umask):
    d = _meeting(tmp_path)
    result = types.SimpleNamespace(
        text="hello", utterances=[], assigned=[], language="en", diarized=False,
        speaker_names={},
    )
    written = ms.write_outputs(d, result, fmt="md", notes_md="# notes")
    assert written
    assert all(_mode(p) == 0o600 for p in written.values())
    archived = ms.archive_outputs(d)
    assert archived is not None
    assert _mode(archived) == 0o700
    assert _mode(archived.parent) == 0o700


def test_live_jsonl_append_keeps_0600(tmp_path, umask):
    d = _meeting(tmp_path)
    ms.append_live_line(d, "one", 1.0)
    ms.append_live_line(d, "two", 2.0)
    assert _mode(d / "live.jsonl") == 0o600
    assert [r["text"] for r in ms.read_live_lines(d)] == ["one", "two"]


def test_cliphistory_is_owner_only(tmp_path, umask):
    p = tmp_path / "config" / "cliphistory.json"
    clip.add_item(p, "sk-live-SECRET")
    clip.add_item(p, "second")
    assert _mode(p.parent) == 0o700
    assert _mode(p) == 0o600
    assert clip.load_items(p) == ["second", "sk-live-SECRET"]


def test_scratch_is_owner_only(tmp_path, umask):
    p = tmp_path / "data" / "scratch.jsonl"
    pad = ScratchPad(p)
    assert pad.add("buy milk", 1.0)
    assert pad.add("call mum", 2.0)
    assert _mode(p.parent) == 0o700
    assert _mode(p) == 0o600
    assert [n.text for n in pad.list()] == ["buy milk", "call mum"]


def test_preexisting_loose_meeting_store_is_tightened(tmp_path, umask):
    d = tmp_path / "meetings" / "old"
    d.mkdir(parents=True)
    (d / "live.jsonl").write_text('{"text": "old"}\n', encoding="utf-8")
    (d / "meeting.json").write_text("{}\n", encoding="utf-8")
    os.chmod(d, 0o755)
    os.chmod(d / "live.jsonl", 0o644)
    os.chmod(d / "meeting.json", 0o644)
    ms.append_live_line(d, "new", 3.0)
    ms.write_meta(d, {"id": "old"})
    assert _mode(d) == 0o700
    assert _mode(d / "live.jsonl") == 0o600
    assert _mode(d / "meeting.json") == 0o600
    assert [r["text"] for r in ms.read_live_lines(d)] == ["old", "new"]


def test_preexisting_loose_cliphistory_is_tightened(tmp_path, umask):
    cfg = tmp_path / "config"
    cfg.mkdir()
    p = cfg / "cliphistory.json"
    p.write_text('["old"]\n', encoding="utf-8")
    os.chmod(cfg, 0o755)
    os.chmod(p, 0o644)
    clip.add_item(p, "new")
    assert _mode(cfg) == 0o700
    assert _mode(p) == 0o600
    assert clip.load_items(p) == ["new", "old"]


def test_preexisting_loose_scratch_is_tightened(tmp_path, umask):
    p = tmp_path / "scratch.jsonl"
    p.write_text('{"ts": 1.0, "text": "old"}\n', encoding="utf-8")
    os.chmod(p, 0o644)
    ScratchPad(p).add("new", 2.0)
    assert _mode(p) == 0o600
    assert [n.text for n in ScratchPad(p).list()] == ["old", "new"]


def test_chmod_failure_does_not_lose_the_write(tmp_path, monkeypatch):
    """A filesystem without POSIX modes refuses chmod; the data must still land."""

    def refuse(*_a, **_k):
        raise OSError("operation not supported")

    monkeypatch.setattr(os, "chmod", refuse)
    d = _meeting(tmp_path)
    ms.append_live_line(d, "kept", 1.0)
    ms.write_meta(d, {"id": "m1"})
    p = tmp_path / "config" / "cliphistory.json"
    clip.add_item(p, "kept")
    pad = ScratchPad(tmp_path / "scratch.jsonl")
    assert pad.add("kept", 1.0)
    assert [r["text"] for r in ms.read_live_lines(d)] == ["kept"]
    assert ms.read_meta(d) == {"id": "m1"}
    assert clip.load_items(p) == ["kept"]
    assert [n.text for n in pad.list()] == ["kept"]


def test_new_file_is_never_world_readable_even_if_chmod_fails(tmp_path, monkeypatch):
    """Creation mode alone must be 0600: no create-then-chmod window."""
    old = os.umask(0o000)
    try:

        def refuse(*_a, **_k):
            raise OSError("no")

        monkeypatch.setattr(os, "chmod", refuse)
        p = tmp_path / "scratch.jsonl"
        ScratchPad(p).add("x", 1.0)
        assert _mode(p) == 0o600
    finally:
        os.umask(old)


def test_content_bytes_are_unchanged(tmp_path):
    """Golden compare: on-disk bytes equal what the previous write_text code wrote."""
    d = _meeting(tmp_path)
    ms.write_meta(d, {"id": "m1", "title": "réunion"})
    ms.append_live_line(d, "héllo", 1.234)
    ms.append_live_line(d, "wörld", 2.0)
    expected_meta = json.dumps({"id": "m1", "title": "réunion"}, ensure_ascii=False, indent=2)
    assert (d / "meeting.json").read_bytes() == (expected_meta + "\n").encode("utf-8")
    assert (d / "live.jsonl").read_bytes() == (
        '{"text": "héllo", "t": 1.23}\n{"text": "wörld", "t": 2.0}\n'.encode()
    )
    p = tmp_path / "config" / "cliphistory.json"
    clip.add_item(p, "a")
    clip.add_item(p, "b")
    expected_clip = json.dumps(["b", "a"], ensure_ascii=False, indent=2)
    assert p.read_bytes() == (expected_clip + "\n").encode("utf-8")
    sp = tmp_path / "s.jsonl"
    ScratchPad(sp).add("n", 5.0)
    assert sp.read_bytes() == b'{"ts": 5.0, "text": "n"}\n'
