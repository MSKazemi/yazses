"""The live transcript is readable *during* the meeting, not only after it — P0.

`live.jsonl` already made a mid-meeting crash survivable, but it is newline-delimited
JSON: nothing a person opens while a meeting is running, and nothing a markdown
previewer renders. `live-transcript.md` is now appended to as each utterance is
decoded, so the meeting can be followed as it happens.

The load-bearing property is that the two writers agree. The incremental appender and
the whole-file re-render at finalize must produce **byte-identical** files for the same
records — otherwise every finalize silently rewrites the file the user has been reading,
and a diff between "what I watched" and "what was saved" is exactly the kind of doubt
this feature exists to remove.
"""
from __future__ import annotations

import dataclasses
import time

import numpy as np

from yazses.config import MeetingConfig
from yazses.meeting import store
from yazses.meeting.controller import MeetingController
from yazses.meeting.session import MeetingSession

SR = 1000


class _Engine:
    """Returns a distinct sentence per utterance so ordering is checkable."""

    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, sample_rate=16000):
        self.calls += 1
        return f"sentence number {self.calls}"


def _silent(chunk):
    return not np.asarray(chunk).any()


def _cfg(tmp_path, **kw):
    return dataclasses.replace(MeetingConfig(output_dir=str(tmp_path)), **kw)


def _controller(tmp_path, engine, **cfgkw):
    cfg = _cfg(tmp_path, **cfgkw)
    d = store.new_meeting(cfg, "m1")
    return MeetingController(
        cfg, d, "m1", engine=engine, is_silent=_silent, sample_rate=SR,
    )


def _utterance(ctl, voiced=3, silence=8):
    """Feed one voiced burst followed by enough silence to close the utterance."""
    for _ in range(voiced):
        ctl.feed(np.ones(100, dtype="float32"))
    for _ in range(silence):
        ctl.feed(np.zeros(100, dtype="float32"))


def _read(p):
    return p.read_text(encoding="utf-8")


def _wait_for(predicate, timeout=30.0, interval=0.01):
    """Wait for the live worker's side effect without ending the meeting.

    The worker is a thread with no completion signal a caller can wait on. Every other
    test in this file reaches the decoded state by calling `stop_capture`, which drains
    it; this one cannot, because the property under test is that the file is readable
    *while capture is still running*, and draining would destroy what is being measured.

    So it polls -- but on the postcondition itself rather than on the file existing.
    The header is written before the first utterance line is appended, so "the file is
    there" becomes true a moment before the content the assertions need, and waiting on
    existence alone is a race that reads an empty or header-only file.

    The timeout is a ceiling on failure, never a cost on success: a healthy run returns
    on the first interval and only a genuinely stuck worker waits the whole budget. It
    is generous because the slowest leg in CI is a FreeBSD VM driven over ssh, where the
    previous 10s was not enough -- the test failed there on a pull request that changed
    nothing but a markdown file, and passed on re-run from the same commit.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# --- the invariant that ties the two writers together ----------------------------


def test_appending_matches_a_full_re_render(tmp_path):
    """N appends == one render of the same N records, byte for byte."""
    records = [
        {"text": "first thing said", "t": 0.0},
        {"text": "second thing said", "t": 61.4},
        {"text": "third thing said", "t": 3599.9},
    ]
    appended = tmp_path / "a"
    appended.mkdir()
    for r in records:
        store.append_live_markdown(appended, r["text"], r["t"], "m1")

    assert _read(store.live_markdown_path(appended)) == store.render_live_transcript(
        records, "m1"
    )


def test_a_finalize_re_render_does_not_change_the_file_it_was_appending_to(tmp_path):
    """The user reads the file mid-meeting; finalize must not rewrite it under them."""
    ctl = _controller(tmp_path, _Engine())
    ctl.start()
    _utterance(ctl)
    _utterance(ctl)
    ctl.stop_capture()

    live_md = store.live_markdown_path(ctl.dir)
    during = _read(live_md)
    assert store.write_live_transcript(ctl.dir, "m1") is not None
    assert _read(live_md) == during


def test_the_re_render_repairs_a_torn_append(tmp_path):
    """`live.jsonl` is the source of truth, so a damaged .md is not a lost transcript."""
    ctl = _controller(tmp_path, _Engine())
    ctl.start()
    _utterance(ctl)
    _utterance(ctl)
    ctl.stop_capture()

    live_md = store.live_markdown_path(ctl.dir)
    intact = _read(live_md)
    live_md.write_text(intact[: len(intact) // 3], encoding="utf-8")  # a killed write

    store.write_live_transcript(ctl.dir, "m1")
    assert _read(live_md) == intact


# --- readable while the meeting is still running ----------------------------------


def test_the_transcript_is_on_disk_before_the_meeting_is_stopped(tmp_path):
    ctl = _controller(tmp_path, _Engine())
    ctl.start()
    _utterance(ctl)
    # Wait for the background decode without ending the meeting: the point is that the
    # file is readable while capture is still running, so `stop_capture` (which drains
    # the worker) must not be what makes it appear.
    live_md = store.live_markdown_path(ctl.dir)
    decoded = _wait_for(
        lambda: live_md.exists() and "sentence number 1" in _read(live_md)
    )
    body = _read(live_md) if live_md.exists() else ""
    ctl.stop_capture()

    assert decoded, (
        "the live worker did not write the utterance within the budget -- "
        f"exists={live_md.exists()} body={body!r}"
    )
    assert "# Live transcript — m1" in body
    assert "sentence number 1" in body


def test_each_utterance_is_appended_in_order(tmp_path):
    ctl = _controller(tmp_path, _Engine())
    ctl.start()
    for _ in range(3):
        _utterance(ctl)
    ctl.stop_capture()

    body = _read(store.live_markdown_path(ctl.dir))
    assert body.index("sentence number 1") < body.index("sentence number 2")
    assert body.index("sentence number 2") < body.index("sentence number 3")


def test_the_header_is_written_exactly_once(tmp_path):
    ctl = _controller(tmp_path, _Engine())
    ctl.start()
    for _ in range(4):
        _utterance(ctl)
    ctl.stop_capture()

    assert _read(store.live_markdown_path(ctl.dir)).count("# Live transcript") == 1


def test_the_status_view_names_the_file_once_it_exists(tmp_path):
    ctl = _controller(tmp_path, _Engine())
    ctl.start()
    # Nothing decoded yet: naming a path that does not exist would tell a user with a
    # dead microphone that their meeting is being written down.
    assert ctl.status()["live_transcript_path"] == ""
    _utterance(ctl)
    ctl.stop_capture()
    assert ctl.status()["live_transcript_path"] == str(store.live_markdown_path(ctl.dir))


# --- the opt-out, and the things that must not write a line -----------------------


def test_live_markdown_false_writes_nothing_during_the_meeting(tmp_path):
    ctl = _controller(tmp_path, _Engine(), live_markdown=False)
    ctl.start()
    _utterance(ctl)
    ctl.stop_capture()
    assert not store.live_markdown_path(ctl.dir).exists()


def test_live_markdown_false_still_gets_the_file_at_finalize(tmp_path):
    """Opting out of the incremental write is not opting out of the transcript."""
    ctl = _controller(tmp_path, _Engine(), live_markdown=False)
    ctl.start()
    _utterance(ctl)
    ctl.stop_capture()

    assert store.write_live_transcript(ctl.dir, "m1") is not None
    assert "sentence number 1" in _read(store.live_markdown_path(ctl.dir))


def test_an_empty_utterance_appends_nothing(tmp_path):
    store.append_live_markdown(tmp_path, "   ", 1.0, "m1")
    store.append_live_markdown(tmp_path, "", 1.0, "m1")
    assert not store.live_markdown_path(tmp_path).exists()


def test_a_zero_byte_file_still_gets_its_header(tmp_path):
    """A crash between `open` and the first write must not cost the header forever."""
    store.live_markdown_path(tmp_path).write_text("", encoding="utf-8")
    store.append_live_markdown(tmp_path, "hello", 0.0, "m1")
    assert _read(store.live_markdown_path(tmp_path)).startswith("# Live transcript — m1")


def test_an_unwritable_folder_never_raises_into_the_live_worker(tmp_path):
    """This runs on the decode thread; a full disk costs the copy, never the capture."""
    missing = tmp_path / "does" / "not" / "exist"
    store.append_live_markdown(missing, "hello", 0.0, "m1")  # must not raise
    assert not (missing / "live-transcript.md").exists()


def test_a_bad_timestamp_still_yields_a_line(tmp_path):
    """The text is the record; a junk clock value must not swallow the sentence."""
    assert store.live_markdown_line({"text": "hello", "t": "not-a-number"}) == "hello"
    assert store.live_markdown_line({"text": "hello", "t": -5}) == "hello"
    assert store.live_markdown_line({"text": "hello", "t": 65}) == "[01:05] hello"


def test_the_session_writes_both_files_from_one_line(tmp_path):
    """`live.jsonl` and `live-transcript.md` are two views of the same event."""
    s = MeetingSession("m1", tmp_path, sample_rate=SR)
    s.add_live_line("something was said")
    s.stop()

    assert [r["text"] for r in store.read_live_lines(tmp_path)] == ["something was said"]
    assert "something was said" in _read(store.live_markdown_path(tmp_path))
