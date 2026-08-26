"""A meeting must survive its own post-pass failing — resilience wiring, end to end.

The defect: a real 41-minute meeting's batch decode collapsed into a repetition loop.
It raised nothing, so `status` reached `"done"`, the recording was deleted as a
successful consumption, and the only surviving record of the meeting was `live.jsonl` —
a newline-delimited JSON file the product never mentioned, rendered by nothing, and
listed as a finished meeting like any other.

These pin the four things that now stand between that and a lost meeting:
  1. the live decode is rendered to a readable second transcript, before the batch pass
  2. the batch transcript is judged, and the verdict is written down
  3. the recording is NOT deleted when the verdict is bad
  4. the user is told, in the folder, in the listing, and on the way out
"""
from __future__ import annotations

import dataclasses
import json

import numpy as np

from yazses.config import MeetingConfig
from yazses.meeting import store
from yazses.meeting.controller import MeetingController
from yazses.postprocess.prosody import Word

SR = 1000
_COLLAPSE = "hello hello hello "


class _CollapsingEngine:
    """Live decode returns real prose; the batch decode loops. The observed failure."""

    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, sample_rate=16000):
        self.calls += 1
        return f"the quick brown fox number {'x' * self.calls} jumped over it"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        words = []
        t = 0.0
        for _ in range(120):
            for w in ("hello", "hello", "hello"):
                words.append(Word(w, t, t + 0.2, 0.9))
                t += 0.25
        return _COLLAPSE * 120, words


class _HealthyEngine:
    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, sample_rate=16000):
        self.calls += 1
        return f"live line {self.calls}"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        # 4400 distinct words against the 40 minutes `_run` feeds = 110 wpm, the rate a
        # real meeting decodes at. A smaller number here would trip the `thin` check and
        # make every "healthy" assertion below pass or fail for the wrong reason.
        text = " ".join(f"word{'a' * i}" for i in range(4400))
        words = [
            Word(w, i * 0.3, i * 0.3 + 0.25, 0.9) for i, w in enumerate(text.split())
        ]
        return text, words


def _silent(chunk):
    return not np.asarray(chunk).any()


def _run(tmp_path, engine, **cfgkw):
    """Drive a whole meeting and return (controller, info)."""
    cfg = dataclasses.replace(
        MeetingConfig(output_dir=str(tmp_path), diarize=False), **cfgkw
    )
    d = store.new_meeting(cfg, "m1")
    ctl = MeetingController(cfg, d, "m1", engine=engine, is_silent=_silent, sample_rate=SR)
    ctl.start()
    for _ in range(4):
        for _ in range(3):
            ctl.feed(np.ones(100, dtype="float32"))
        for _ in range(9):
            ctl.feed(np.zeros(100, dtype="float32"))
    ctl.stop_capture()
    # 40 minutes of audio at the fake rate, so the duration-gated checks are in range.
    info = ctl.finalize(np.ones(SR * 2400, dtype="float32"))
    return d, info


# --- 1. the live decode becomes a readable transcript ----------------------------


def test_the_live_decode_is_rendered_to_its_own_markdown_file(tmp_path):
    d, _info = _run(tmp_path, _HealthyEngine())
    md = d / "live-transcript.md"
    assert md.exists()
    body = md.read_text(encoding="utf-8")
    assert "live line 1" in body
    # Timestamped, because this file is read when the timed transcript cannot be trusted.
    assert "[00:" in body


def test_the_live_transcript_is_written_even_when_the_batch_pass_raises(tmp_path):
    """It is rendered *before* the decode, so a finalize that dies still leaves it."""

    class _Exploding(_HealthyEngine):
        def transcribe_words(self, *a, **kw):
            raise RuntimeError("out of memory")

    cfg = MeetingConfig(output_dir=str(tmp_path), diarize=False)
    d = store.new_meeting(cfg, "m1")
    ctl = MeetingController(cfg, d, "m1", engine=_Exploding(), is_silent=_silent,
                            sample_rate=SR)
    ctl.start()
    for _ in range(3):
        ctl.feed(np.ones(100, dtype="float32"))
    for _ in range(9):
        ctl.feed(np.zeros(100, dtype="float32"))
    ctl.stop_capture()
    try:
        ctl.finalize(np.ones(SR * 60, dtype="float32"))
    except RuntimeError:
        pass
    assert (d / "live-transcript.md").exists()


# --- 2. the verdict is computed and written down ---------------------------------


def test_a_collapsed_batch_pass_is_recorded_as_suspect(tmp_path):
    d, info = _run(tmp_path, _CollapsingEngine())
    assert info["quality"] == "degenerate"
    assert info["quality_suspect"] is True
    meta = json.loads((d / "meeting.json").read_text(encoding="utf-8"))
    assert meta["quality_suspect"] is True
    # `status` still reaches "done" — the meeting *did* finish. What changed is that
    # "done" is no longer the only thing recorded about how it went.
    assert meta["status"] == "done"


def test_the_metrics_are_kept_for_later_analysis(tmp_path):
    d, _info = _run(tmp_path, _CollapsingEngine())
    q = json.loads((d / "quality.json").read_text(encoding="utf-8"))
    assert q["verdict"] == "degenerate"
    assert q["top_ngram_share"] > 0.5
    assert q["live_words"] > 0
    assert q["reasons"]


def test_a_healthy_meeting_is_not_flagged(tmp_path):
    """The false-alarm direction, on the real wiring rather than on the pure function."""
    d, info = _run(tmp_path, _HealthyEngine())
    assert info["quality_suspect"] is False
    assert not info["quality_warning"]
    assert json.loads((d / "quality.json").read_text(encoding="utf-8"))["verdict"] == "ok"


# --- 3. the recording is kept when the verdict is bad ----------------------------


def test_a_bad_pass_keeps_the_recording_even_though_retain_audio_is_off(tmp_path):
    _d, info = _run(tmp_path, _CollapsingEngine(), retain_audio=False)
    assert info["audio_kept"] is True


def test_a_good_pass_still_deletes_the_recording_by_default(tmp_path):
    """The privacy default is unchanged for the case it was written for."""
    _d, info = _run(tmp_path, _HealthyEngine(), retain_audio=False)
    assert info["audio_kept"] is False


def test_retain_audio_still_wins_on_a_good_pass(tmp_path):
    _d, info = _run(tmp_path, _HealthyEngine(), retain_audio=True)
    assert info["audio_kept"] is True


# --- 4. the user is told -----------------------------------------------------------


def test_the_summary_is_written_into_the_meeting_folder(tmp_path):
    d, info = _run(tmp_path, _CollapsingEngine())
    body = (d / "summary.md").read_text(encoding="utf-8")
    assert "repetition loop" in body
    assert "live-transcript.md" in body
    # The same lines the daemon and the CLI show, from the same call.
    assert info["summary"]
    assert "\n".join(info["summary"]) in body


def _file_lines(meeting_dir):
    """Just the file-list block of summary.md.

    Filtered on the "Files:" heading rather than on the substring "transcript.md",
    which also appears in the warning above the list — the first version of this
    helper matched that warning and asserted about the wrong line.
    """
    lines = (meeting_dir / "summary.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "Files:")
    out = []
    for ln in lines[start + 1:]:
        if not ln.startswith("    ") or ln.strip().startswith("Folder:"):
            break
        out.append(ln)
    return out


def test_the_summary_points_at_the_live_transcript_first_when_the_batch_is_bad(tmp_path):
    d, _info = _run(tmp_path, _CollapsingEngine())
    lines = _file_lines(d)
    assert lines and "live-transcript.md" in lines[0], lines
    assert "READ THIS ONE" in lines[0]


def test_the_summary_lists_the_batch_transcript_first_when_it_is_good(tmp_path):
    d, _info = _run(tmp_path, _HealthyEngine())
    lines = _file_lines(d)
    assert lines and "live-transcript.md" not in lines[0], lines
    assert "UNRELIABLE" not in (d / "summary.md").read_text(encoding="utf-8")


def test_the_listing_offers_a_retry_for_a_finished_but_bad_meeting(tmp_path):
    """`status: done` used to end the conversation. It is no longer the only fact."""
    cfg = MeetingConfig(output_dir=str(tmp_path), diarize=False)
    d, _info = _run(tmp_path, _CollapsingEngine())
    (d / "audio.wav").write_bytes(b"\0" * 4096)  # the pass kept it
    listed = store.list_meetings(cfg)
    assert len(listed) == 1
    assert listed[0]["recoverable"] is True
    advice = store.recovery_advice(listed[0], live_lines=3)
    assert any("NOT usable" in ln for ln in advice), advice
    assert any("meeting recover" in ln for ln in advice), advice


def test_a_healthy_finished_meeting_is_not_offered_a_retry(tmp_path):
    cfg = MeetingConfig(output_dir=str(tmp_path), diarize=False)
    d, _info = _run(tmp_path, _HealthyEngine())
    (d / "audio.wav").write_bytes(b"\0" * 4096)
    listed = store.list_meetings(cfg)
    assert not listed[0].get("recoverable")
    assert store.recovery_advice(listed[0], live_lines=3) == []


# --- nothing is ever deleted --------------------------------------------------------


def test_a_rerun_archives_the_previous_outputs_instead_of_overwriting_them(tmp_path):
    d, _info = _run(tmp_path, _CollapsingEngine())
    first = (d / "transcript.md").read_text(encoding="utf-8")
    archived = store.archive_outputs(d)
    assert archived is not None
    assert (archived / "transcript.md").read_text(encoding="utf-8") == first
    assert (archived / "transcript.json").exists()
    assert (archived / "quality.json").exists()
    assert not (d / "transcript.md").exists()   # moved, not copied


def test_repeated_reruns_each_get_their_own_archive_slot(tmp_path):
    d, _info = _run(tmp_path, _CollapsingEngine())
    a1 = store.archive_outputs(d)
    (d / "transcript.md").write_text("second attempt", encoding="utf-8")
    a2 = store.archive_outputs(d)
    assert a1 != a2
    assert a1.exists() and a2.exists()
    assert (a2 / "transcript.md").read_text(encoding="utf-8") == "second attempt"


def test_archiving_an_empty_folder_is_a_no_op_not_an_empty_slot(tmp_path):
    """A guard that iterates must be proven on an empty collection."""
    d = tmp_path / "empty"
    d.mkdir()
    assert store.archive_outputs(d) is None
    assert not (d / "attempts").exists()


def test_the_live_jsonl_is_never_removed_by_any_of_this(tmp_path):
    d, _info = _run(tmp_path, _CollapsingEngine())
    store.archive_outputs(d)
    assert (d / "live.jsonl").exists()
    assert (d / "live-transcript.md").exists()


# --- backfill: the repair has to reach meetings that already happened --------------
#
# Each of these three was found by running the finished code against the five real
# meetings on the machine where the defect happened, not by reading it.


def test_an_old_meeting_with_no_verdict_gets_one_computed_from_its_transcript(tmp_path):
    """Every meeting recorded before the check existed — including the broken one."""
    cfg = MeetingConfig(output_dir=str(tmp_path), diarize=False)
    d, _info = _run(tmp_path, _CollapsingEngine())
    (d / "quality.json").unlink()
    meta = json.loads((d / "meeting.json").read_text(encoding="utf-8"))
    meta.pop("quality", None)
    meta.pop("quality_suspect", None)
    (d / "meeting.json").write_text(json.dumps(meta), encoding="utf-8")

    assert store.list_meetings(cfg)[0].get("quality_suspect") is None  # nothing known yet
    q = store.ensure_quality(d)
    assert q["verdict"] == "degenerate"
    # Written back, so the listing sees it without re-reading a 1.7 MB transcript per row.
    assert store.list_meetings(cfg)[0]["quality_suspect"] is True


def test_backfilling_does_not_bake_runtime_fields_into_the_stored_record(tmp_path):
    """`dir` is injected by `list_meetings`; writing it back freezes this machine's paths.

    It did: the first run of `meeting summary` on a real meeting wrote an absolute
    `/home/.../meetings/<id>` into `meeting.json`, where nothing had ever stored one.
    """
    cfg = MeetingConfig(output_dir=str(tmp_path), diarize=False)
    d, _info = _run(tmp_path, _CollapsingEngine())
    (d / "quality.json").unlink()
    listed = store.list_meetings(cfg)[0]      # carries dir/recoverable/audio_path
    store.ensure_quality(d, listed)
    on_disk = json.loads((d / "meeting.json").read_text(encoding="utf-8"))
    for key in ("dir", "recoverable", "audio_path", "live_transcript_path"):
        assert key not in on_disk, key


def test_backfilling_keeps_fields_written_by_an_older_version(tmp_path):
    d, _info = _run(tmp_path, _CollapsingEngine())
    (d / "quality.json").unlink()
    meta = json.loads((d / "meeting.json").read_text(encoding="utf-8"))
    meta["some_older_field"] = "keep me"
    (d / "meeting.json").write_text(json.dumps(meta), encoding="utf-8")
    store.ensure_quality(d)
    assert json.loads((d / "meeting.json").read_text(encoding="utf-8"))["some_older_field"] == "keep me"


def test_ensure_quality_is_a_no_op_without_a_transcript(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert store.ensure_quality(empty) == {}
    assert not (empty / "quality.json").exists()


def test_ensure_quality_does_not_recompute_an_existing_verdict(tmp_path):
    d, _info = _run(tmp_path, _CollapsingEngine())
    (d / "quality.json").write_text(json.dumps({"verdict": "ok", "suspect": False}),
                                    encoding="utf-8")
    assert store.ensure_quality(d)["verdict"] == "ok"


def test_a_finished_but_bad_meeting_is_not_described_as_unfinished(tmp_path):
    """`recoverable` stopped meaning "never finished" — the listing said otherwise.

    The real broken meeting listed as `41m 39s  unfinished`, which is a false statement
    about a meeting that ran to the end and wrote every output.
    """
    from yazses.cli import _speaker_summary

    assert _speaker_summary({"recoverable": True, "status": "done", "diarized": False}) \
        == "not diarized"
    assert _speaker_summary({"recoverable": True}) == "unfinished"


def test_the_live_word_count_is_not_pluralised_wrongly(tmp_path):
    one = store.describe_files({"id": "m"}, live_lines=1, quality={"live_words": 1})
    assert any("(1 word)" in ln for ln in one), one
    two = store.describe_files({"id": "m"}, live_lines=1, quality={"live_words": 2})
    assert any("(2 words)" in ln for ln in two), two
