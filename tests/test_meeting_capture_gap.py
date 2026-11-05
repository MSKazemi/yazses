"""A meeting whose input device vanishes must say so (lane 05, run r1105a).

When the device is lost the capture callback simply stops: ``duration_s`` counts samples
so it freezes, ``elapsed_s`` follows the clock so it keeps going, and the max-minutes cap
only runs inside ``feed`` so it never fires. Before the fix nothing recorded the
difference, and a 50-minute meeting that heard 10 seconds finalized like any other.

Everything is a pure fake: a list-backed clock, a no-op engine, ``SR = 1000``.
"""
from __future__ import annotations

import dataclasses
import json

import numpy as np

from yazses.config import MeetingConfig
from yazses.meeting import store
from yazses.meeting.controller import MeetingController
from yazses.meeting.session import read_wav_mono_f32
from yazses.postprocess.prosody import Word
from yazses.recimport.diarizer import DiarTurn

SR = 1000


class _Engine:
    def transcribe(self, audio, sample_rate=16000):
        return "x"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "hello there general kenobi", [
            Word("hello", 0.0, 0.4, 0.9), Word("there", 0.5, 0.9, 0.9),
            Word("general", 2.0, 2.6, 0.9), Word("kenobi", 2.7, 3.1, 0.9),
        ]


class _Diarizer:
    def diarize(self, audio, sample_rate=16000):
        return [DiarTurn(0.0, 1.2, "speaker_0"), DiarTurn(1.8, 3.4, "speaker_1")]


def _silent(chunk):
    return not np.asarray(chunk).any()


def _meeting(tmp_path, t, **kw):
    cfg = dataclasses.replace(
        MeetingConfig(output_dir=str(tmp_path), diarize=True), live_transcript=False
    )
    d = store.new_meeting(cfg, "m1")
    return MeetingController(
        cfg, d, "m1", engine=_Engine(), is_silent=_silent, diarizer=_Diarizer(),
        sample_rate=SR, started_at=0.0, clock=lambda: t[0], **kw,
    )


def _record(ctl, t, *, seconds: int, then_idle: float = 0.0) -> None:
    """Feed ``seconds`` of 1 s chunks on the clock, then let ``then_idle`` s pass."""
    ctl.start()
    for _ in range(seconds):
        ctl.feed(np.ones(SR, dtype="float32"))
        t[0] += 1.0
    t[0] += then_idle


def _finish(ctl):
    wav = ctl.stop_capture()
    info = ctl.finalize(read_wav_mono_f32(wav))
    meta = json.loads((ctl.dir / "meeting.json").read_text(encoding="utf-8"))
    summary = (ctl.dir / "summary.md").read_text(encoding="utf-8")
    return info, meta, summary


# ---- the repro: a device that vanishes mid-meeting ---------------------------------


def test_dead_stream_is_reported_in_status_and_metadata(tmp_path):
    t = [0.0]
    ctl = _meeting(tmp_path, t)
    _record(ctl, t, seconds=10, then_idle=3000.0)  # 10 s heard, 50 min of silence

    s = ctl.status()
    assert s["elapsed_s"] == 3010.0
    assert s["duration_s"] == 10.0
    assert s["stalled_s"] == 3001.0  # last chunk landed at t=9; now is t=3010

    info, meta, summary = _finish(ctl)
    assert meta["capture_gap_s"] == 3000.0
    assert meta["audio_kept"] is True
    assert info["audio_kept"] is True
    # The summary says it plainly, in the same words on disk and in the returned lines.
    assert "Audio stopped arriving for 50m 0s of this 50m 10s meeting" in summary
    assert "the transcript covers only what was captured." in summary
    assert info["summary"] == summary.removeprefix("```text\n").removesuffix("\n```\n").split("\n")


def test_recording_is_kept_even_when_retain_audio_is_off(tmp_path):
    t = [0.0]
    ctl = _meeting(tmp_path, t)
    assert ctl._config.retain_audio is False
    _record(ctl, t, seconds=10, then_idle=100.0)
    info, _meta, _summary = _finish(ctl)
    assert info["audio_kept"] is True


# ---- a healthy meeting is byte-identical to what it was ----------------------------

# Captured from a run on the unmodified base (a241a77b) with the same scenario.
_GOLDEN_META = {
    "id": "m1",
    "duration_s": 60.0,
    "diarized": True,
    "num_speakers": 2,
    "speakers": ["Speaker 1", "Speaker 2"],
    "has_notes": False,
    "capture": "ok",
    "attribution_suspect": "",
    "quality": "unjudged",
    "quality_suspect": False,
    "audio_kept": False,
    "status": "done",
}
_GOLDEN_SUMMARY = """```text
Meeting m1
  Duration: 1m 0s
  Speakers: Speaker 1, Speaker 2
  Files:
       transcript.md — batch transcript
       transcript.json — word-level timings + speakers (machine-readable)
       quality.json — decode-quality metrics for this meeting
  Folder: {folder}
```
"""


def test_healthy_meeting_metadata_and_summary_are_unchanged(tmp_path):
    t = [0.0]
    ctl = _meeting(tmp_path, t)
    _record(ctl, t, seconds=60, then_idle=1.5)  # a second of startup/teardown lag
    assert ctl.status()["stalled_s"] == 0.0
    _info, meta, summary = _finish(ctl)
    assert meta == _GOLDEN_META
    assert list(meta) == list(_GOLDEN_META)  # key order too: the file is byte-identical
    assert summary == _GOLDEN_SUMMARY.format(folder=ctl.dir)
    assert "capture_gap_s" not in meta


def test_clockless_controller_never_reports_a_gap(tmp_path):
    cfg = dataclasses.replace(
        MeetingConfig(output_dir=str(tmp_path), diarize=True), live_transcript=False
    )
    d = store.new_meeting(cfg, "m1")
    ctl = MeetingController(
        cfg, d, "m1", engine=_Engine(), is_silent=_silent, diarizer=_Diarizer(),
        sample_rate=SR,
    )
    ctl.start()
    ctl.feed(np.ones(SR, dtype="float32"))
    assert ctl.status()["stalled_s"] == 0.0
    _info, meta, _summary = _finish(ctl)
    assert "capture_gap_s" not in meta


# ---- the threshold: max(10 s, 2 % of the meeting) ----------------------------------


def test_threshold_formula():
    assert store.capture_gap_threshold(0) == 10.0
    assert store.capture_gap_threshold(100) == 10.0
    assert store.capture_gap_threshold(500) == 10.0  # 2 % == 10 s exactly
    assert store.capture_gap_threshold(1000) == 20.0
    assert store.capture_gap_threshold(3600) == 72.0


def test_gap_exactly_at_the_10s_floor_is_not_recorded(tmp_path):
    t = [0.0]
    ctl = _meeting(tmp_path, t)
    _record(ctl, t, seconds=90, then_idle=10.0)  # elapsed 100, gap 10 == threshold
    _info, meta, _summary = _finish(ctl)
    assert "capture_gap_s" not in meta


def test_gap_just_over_the_10s_floor_is_recorded(tmp_path):
    t = [0.0]
    ctl = _meeting(tmp_path, t)
    _record(ctl, t, seconds=90, then_idle=10.5)  # elapsed 100.5, gap 10.5 > 10
    _info, meta, summary = _finish(ctl)
    assert meta["capture_gap_s"] == 10.5
    assert "Audio stopped arriving for 10s of this 1m 40s meeting" in summary


def test_long_meeting_uses_the_two_percent_bar(tmp_path):
    # 2000 s elapsed -> bar is 40 s. A 39 s hole is noise, a 41 s hole is not.
    for hole, expect in ((39.0, False), (41.0, True)):
        t = [0.0]
        sub = tmp_path / str(int(hole))
        sub.mkdir()
        ctl = _meeting(sub, t)
        _record(ctl, t, seconds=int(2000 - hole), then_idle=hole)
        _info, meta, _summary = _finish(ctl)
        assert ("capture_gap_s" in meta) is expect, hole


# ---- stalled_s ---------------------------------------------------------------------


def test_stalled_s_is_zero_before_the_first_chunk_and_after_stop(tmp_path):
    t = [0.0]
    ctl = _meeting(tmp_path, t)
    ctl.start()
    t[0] = 500.0
    assert ctl.status()["stalled_s"] == 0.0  # none yet: not a stall, a meeting not begun
    ctl.feed(np.ones(SR, dtype="float32"))
    t[0] += 60.0
    assert ctl.status()["stalled_s"] == 60.0
    ctl.feed(np.ones(SR, dtype="float32"))
    assert ctl.status()["stalled_s"] == 0.0
    t[0] += 4.9
    assert ctl.status()["stalled_s"] == 0.0  # jitter below the report floor
    t[0] += 0.2
    assert ctl.status()["stalled_s"] == 5.1
    ctl.stop_capture()
    assert ctl.status()["stalled_s"] == 0.0


def test_stop_before_any_chunk_records_no_gap(tmp_path):
    t = [0.0]
    ctl = _meeting(tmp_path, t)
    ctl.start()
    t[0] = 3000.0
    wav = ctl.stop_capture()
    assert ctl.status()["stalled_s"] == 0.0
    info = ctl.finalize(read_wav_mono_f32(wav))
    meta = json.loads((ctl.dir / "meeting.json").read_text(encoding="utf-8"))
    # No chunk ever arrived: the whole 3000 s is a gap, which is the truthful reading,
    # and finalize copes with an empty recording instead of raising.
    assert meta["duration_s"] == 0.0
    assert meta["capture_gap_s"] == 3000.0
    assert info["audio_kept"] is True


# ---- store: old metadata still loads, malformed input never raises ------------------


def test_old_metadata_without_capture_gap_still_loads_and_renders(tmp_path):
    d = tmp_path / "old"
    d.mkdir()
    store.write_meta(d, dict(_GOLDEN_META))
    meta = store.read_meta(d)
    assert "capture_gap_s" not in meta
    assert store.capture_gap_warning(meta) is None
    lines = store.summary_lines({**meta, "dir": str(d)})
    assert not any("Audio stopped arriving" in ln for ln in lines)


def test_capture_gap_warning_tolerates_bad_values():
    for bad in (None, "", "abc", 0, -5, [], {}, float("nan")):
        assert store.capture_gap_warning({"capture_gap_s": bad, "duration_s": 5}) is None
    # A bad duration degrades to "captured 0", never an exception.
    assert "Audio stopped arriving for 30s of this 30s meeting" in store.capture_gap_warning(
        {"capture_gap_s": 30, "duration_s": "oops"}
    )


def test_summary_puts_the_gap_line_with_the_other_warnings(tmp_path):
    lines = store.summary_lines(
        {"id": "m9", "duration_s": 10.0, "capture_gap_s": 3000.0, "diarized": False}
    )
    gap_i = next(i for i, ln in enumerate(lines) if "Audio stopped arriving" in ln)
    assert lines.index("  Files:") > gap_i
    assert gap_i == 2  # right after the Duration line, before Speakers/Files
