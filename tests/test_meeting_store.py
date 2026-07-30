"""Meeting-folder persistence + post-hoc relabel — ADR-v2-127."""
from __future__ import annotations

import dataclasses
import json

import numpy as np

from yazses.config import MeetingConfig
from yazses.meeting import store
from yazses.postprocess.prosody import Word
from yazses.recimport.diarizer import DiarTurn
from yazses.recimport.pipeline import transcribe_file

WORDS = [
    Word("hello", 0.0, 0.4, 0.9),
    Word("there", 0.5, 0.9, 0.9),
    Word("general", 2.0, 2.6, 0.9),
    Word("kenobi", 2.7, 3.1, 0.9),
]


class _FakeEngine:
    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "hello there general kenobi", list(WORDS)


class _FakeDiarizer:
    def diarize(self, audio, sample_rate=16000):
        return [DiarTurn(0.0, 1.2, "speaker_0"), DiarTurn(1.8, 3.4, "speaker_1")]


def _cfg(tmp_path, **kw):
    return dataclasses.replace(MeetingConfig(output_dir=str(tmp_path), diarize=True), **kw)


def _make_result(cfg):
    return transcribe_file(
        None, cfg, engine=_FakeEngine(), diarizer=_FakeDiarizer(),
        audio=np.zeros(16000, dtype="float32"),
    )


def test_new_meeting_and_write_outputs(tmp_path):
    cfg = _cfg(tmp_path)
    d = store.new_meeting(cfg, "20260710-101500")
    assert d.exists()
    written = store.write_outputs(d, _make_result(cfg), fmt="md")
    assert (d / "transcript.json").exists()
    assert (d / "transcript.md").exists()
    assert "**Speaker 1:** hello there" in written["md"].read_text()


def test_list_meetings_newest_first(tmp_path):
    cfg = _cfg(tmp_path)
    for mid in ("20260710-090000", "20260710-120000"):
        d = store.new_meeting(cfg, mid)
        store.write_meta(d, {"id": mid, "num_speakers": 2})
    ids = [m["id"] for m in store.list_meetings(cfg)]
    assert ids == ["20260710-120000", "20260710-090000"]
    assert store.list_meetings(_cfg(tmp_path / "empty")) == []


def test_live_jsonl_append_and_read(tmp_path):
    cfg = _cfg(tmp_path)
    d = store.new_meeting(cfg, "live1")
    store.append_live_line(d, "  first line  ", t=1.2)
    store.append_live_line(d, "", t=2.0)          # blank ignored
    store.append_live_line(d, "second line")       # no timestamp
    recs = store.read_live_lines(d)
    assert [r["text"] for r in recs] == ["first line", "second line"]
    assert recs[0]["t"] == 1.2
    assert "t" not in recs[1]
    # absent file reads as empty
    assert store.read_live_lines(store.new_meeting(cfg, "live2")) == []


def test_list_meetings_flags_recoverable(tmp_path):
    cfg = _cfg(tmp_path)
    crashed = store.new_meeting(cfg, "20260730-010000")
    store.append_live_line(crashed, "captured before the crash")  # no meeting.json
    done = store.new_meeting(cfg, "20260730-020000")
    store.write_meta(done, {"id": done.name, "status": "done"})
    by_id = {m["id"]: m for m in store.list_meetings(cfg)}
    assert by_id["20260730-010000"].get("recoverable") is True
    assert "recoverable" not in by_id["20260730-020000"]


def test_relabel_merges_speakers(tmp_path):
    cfg = _cfg(tmp_path)
    d = store.new_meeting(cfg, "m")
    store.write_outputs(d, _make_result(cfg), fmt="txt")
    store.relabel(d, merges={"speaker_1": "speaker_0"}, fmt="txt")
    payload = json.loads((d / "transcript.json").read_text())
    speakers = {w["speaker"] for w in payload["words"]}
    assert speakers == {"speaker_0"}
    # every rendered line now carries the same single speaker label
    labels = {ln.split(":")[0] for ln in (d / "transcript.txt").read_text().splitlines() if ln}
    assert labels == {"Speaker 1"}


def test_relabel_renames_speaker(tmp_path):
    cfg = _cfg(tmp_path)
    d = store.new_meeting(cfg, "m")
    store.write_outputs(d, _make_result(cfg), fmt="txt")
    store.relabel(d, renames={"speaker_0": "Alice"}, fmt="txt")
    txt = (d / "transcript.txt").read_text()
    assert "Alice: hello there" in txt
    assert "Speaker" in txt  # the other cluster stays anonymous


def test_relabel_preserves_prior_custom_name(tmp_path):
    cfg = _cfg(tmp_path)
    d = store.new_meeting(cfg, "m")
    result = _make_result(cfg)
    result = dataclasses.replace(result, speaker_names={"speaker_0": "Alice", "speaker_1": "Speaker 2"})
    store.write_outputs(d, result, fmt="txt")
    # renaming only the anonymous one keeps Alice intact
    store.relabel(d, renames={"speaker_1": "Bob"}, fmt="txt")
    txt = (d / "transcript.txt").read_text()
    assert "Alice: hello there" in txt
    assert "Bob: general kenobi" in txt
