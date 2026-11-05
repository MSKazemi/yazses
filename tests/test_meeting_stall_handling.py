"""A meeting that stops hearing audio must end at its cap and say so (run r1105c).

Stacked on ``test_meeting_capture_gap.py``, which made the stall *visible* (``stalled_s``,
``capture_gap_s``). This makes it *handled*:

* the max-minutes cap also counts wall-clock time once it disagrees with the sample
  count, and the daemon's watchdog re-checks it without a chunk (a lost device never
  calls ``feed`` again, so nothing else would);
* one fixed notification per stall, re-armed only after audio resumes;
* ``recover_meeting`` carries ``capture_gap_s`` through its metadata rewrite.

Pure fakes: a list-backed clock, a no-op engine, ``SR = 1000``.
"""
from __future__ import annotations

import dataclasses
import json
import threading

import numpy as np

from yazses.config import Config, MeetingConfig
from yazses.core.daemon import Daemon
from yazses.meeting import recover, store
from yazses.meeting.controller import MeetingController
from yazses.meeting.session import read_wav_mono_f32
from yazses.meeting.stall import (
    STALL_BODY,
    STALL_BODY_NO_LIMIT,
    STALL_NOTIFY_S,
    STALL_TITLE,
    StallNotice,
    stall_body,
)
from yazses.platform import get_platform

SR = 1000


class _Engine:
    def transcribe(self, audio, sample_rate=16000):
        return "x"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "hello", []


def _cfg(tmp_path):
    return dataclasses.replace(
        MeetingConfig(output_dir=str(tmp_path), diarize=False), live_transcript=False
    )


def _meeting(tmp_path, t, fired, *, max_seconds=3600.0):
    cfg = _cfg(tmp_path)
    d = store.new_meeting(cfg, "m1")
    return MeetingController(
        cfg, d, "m1", engine=_Engine(), is_silent=lambda ch: False, sample_rate=SR,
        started_at=0.0, clock=lambda: t[0], max_seconds=max_seconds,
        on_auto_stop=lambda: fired.append(t[0]),
    )


def _chunks(ctl, t, seconds):
    for _ in range(seconds):
        ctl.feed(np.ones(SR, dtype="float32"))
        t[0] += 1.0


# ---- (a) the cap counts wall-clock once audio has stopped --------------------------


def test_cap_fires_on_wall_clock_with_zero_chunks(tmp_path):
    t, fired = [0.0], []
    ctl = _meeting(tmp_path, t, fired)
    ctl.start()
    _chunks(ctl, t, 10)
    t[0] = 3599.0
    ctl.tick()
    assert fired == []  # not yet: the cap is 3600 s
    t[0] = 3600.0
    ctl.tick()
    assert fired == [3600.0]
    t[0] = 4000.0
    ctl.tick()
    assert fired == [3600.0]  # once, however often the watchdog looks


def test_cap_fires_when_no_chunk_ever_arrived(tmp_path):
    t, fired = [0.0], []
    ctl = _meeting(tmp_path, t, fired)
    ctl.start()
    t[0] = 3600.0
    ctl.tick()
    assert fired == [3600.0]


def test_healthy_meeting_still_ends_on_captured_audio(tmp_path):
    """The clock leads the samples by buffering; that must not pull the end earlier."""
    t, fired = [0.0], []
    ctl = _meeting(tmp_path, t, fired, max_seconds=100.0)
    ctl.start()
    t[0] = 4.0  # first callback arrived 4 s late: wall clock ahead of the samples
    chunks_when_fired = []
    ctl._on_auto_stop = lambda: chunks_when_fired.append(ctl.status()["duration_s"])
    for _ in range(100):
        ctl.feed(np.ones(SR, dtype="float32"))
        t[0] += 1.0
    # Wall clock passed 100 s at the 97th chunk, but the 4 s lead is under the gap
    # threshold, so only the 100th chunk's audio ends the meeting -- as before.
    assert chunks_when_fired == [100.0]


def test_wall_clock_counts_only_past_the_gap_threshold(tmp_path):
    t, fired = [0.0], []
    ctl = _meeting(tmp_path, t, fired, max_seconds=100.0)
    ctl.start()
    _chunks(ctl, t, 90)  # 90 s of audio, 90 s of wall clock
    t[0] += 9.0  # a 9 s hiccup: elapsed 99 s, gap below the 10 s floor
    ctl.tick()
    assert fired == []
    t[0] += 0.9  # elapsed 99.9 s: still under the cap
    ctl.tick()
    assert fired == []
    t[0] += 0.6  # elapsed 100.5 s, audio 90 s, gap 10.5 s -> a real gap now
    ctl.tick()
    assert len(fired) == 1


def test_tick_is_a_noop_after_capture_stopped_and_without_a_cap(tmp_path):
    t, fired = [0.0], []
    ctl = _meeting(tmp_path, t, fired)
    ctl.start()
    ctl.stop_capture()
    t[0] = 9999.0
    ctl.tick()
    assert fired == []
    ctl2 = _meeting(tmp_path, t, fired, max_seconds=0.0)
    ctl2.start()
    t[0] = 99999.0
    ctl2.tick()
    assert fired == []


def test_clockless_controller_cap_is_unchanged(tmp_path):
    fired = []
    cfg = _cfg(tmp_path)
    ctl = MeetingController(
        cfg, store.new_meeting(cfg, "m2"), "m2", engine=_Engine(),
        is_silent=lambda ch: False, sample_rate=SR, max_seconds=5.0,
        on_auto_stop=lambda: fired.append(1),
    )
    ctl.start()
    for _ in range(4):
        ctl.feed(np.ones(SR, dtype="float32"))
    ctl.tick()
    assert fired == []
    ctl.feed(np.ones(SR, dtype="float32"))
    assert fired == [1]


# ---- (b) the notification: once per stall, re-armed by resumed audio ---------------


def test_notice_fires_once_per_stall_and_rearms_after_audio_resumes():
    n = StallNotice()
    assert [n.observe(s) for s in (0.0, 0.0)] == [False, False]
    assert [n.observe(s) for s in (5.0, 29.9)] == [False, False]  # under 30 s: silent
    assert n.observe(STALL_NOTIFY_S) is True
    assert [n.observe(s) for s in (35.0, 600.0, 3000.0)] == [False, False, False]
    assert n.observe(0.0) is False  # audio is back
    assert n.observe(12.0) is False  # a short second stall: still silent
    assert n.observe(31.0) is True  # a long second stall: announced again


def test_notice_under_threshold_stall_never_fires():
    n = StallNotice()
    for s in (0.0, 6.0, 12.0, 29.0, 0.0, 8.0, 0.0):
        assert n.observe(s) is False


def _daemon(tmp_path):
    cfg = Config()
    cfg.meeting.output_dir = str(tmp_path)
    return Daemon(config=cfg, platform=get_platform())


class _FakeController:
    """Just the two methods the watchdog uses, driven by a script of stall readings."""

    def __init__(self, readings):
        self.readings = list(readings)
        self.ticks = 0

    def tick(self):
        self.ticks += 1

    def stalled_s(self):
        return self.readings.pop(0) if self.readings else 0.0


def test_daemon_watchdog_notifies_once_per_stall(tmp_path, monkeypatch):
    sent = []
    from yazses.system import notify as notify_mod

    monkeypatch.setattr(notify_mod, "notify", lambda title, body, **k: sent.append((title, body)))
    d = _daemon(tmp_path)
    ctl = _FakeController([0, 10, 31, 40, 50, 0, 20, 33, 0])
    notice = StallNotice()
    for _ in range(9):
        d._meeting_watch_tick(ctl, notice)
    assert ctl.ticks == 9  # the cap is re-checked on every pass
    assert sent == [(STALL_TITLE, STALL_BODY)] * 2  # two stalls over 30 s, two notices


def test_stall_notification_text_is_fixed_and_carries_nothing_private():
    text = f"{STALL_TITLE}\n{STALL_BODY}"
    assert "30 seconds" in STALL_BODY and "{" not in text and "%" not in text


def test_daemon_watchdog_never_raises_and_ends_with_the_meeting(tmp_path, monkeypatch):
    from yazses.system import notify as notify_mod

    def boom(*a, **k):
        raise RuntimeError("no dbus")

    monkeypatch.setattr(notify_mod, "notify", boom)
    d = _daemon(tmp_path)
    ctl = _FakeController([60.0])
    d._meeting_watch_tick(ctl, StallNotice())  # notify raises: swallowed

    class _Bad(_FakeController):
        def tick(self):
            raise RuntimeError("controller broke")

    d._meeting_watch_tick(_Bad([]), StallNotice())  # tick raises: swallowed

    d._meeting_controller = ctl
    passes = []
    ctl.tick = lambda: passes.append(1)
    th = threading.Thread(target=d._watch_meeting, args=(ctl, 0.001), daemon=True)
    th.start()
    while len(passes) < 3:
        pass
    d._meeting_controller = None  # meeting stopped
    th.join(timeout=5.0)
    assert not th.is_alive()


def test_daemon_start_launches_the_watchdog_for_the_new_controller(tmp_path, monkeypatch):
    from yazses.core import daemon as daemon_mod
    from yazses.ipc.protocol import Request
    from yazses.platform.base import TrayState

    class _Rec:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def stop(self):
            return np.array([], dtype="float32")

    seen = []
    done = threading.Event()

    def _spy(self, controller, interval=None):
        seen.append(controller)
        done.set()

    monkeypatch.setattr(daemon_mod, "AudioRecorder", _Rec)
    monkeypatch.setattr(Daemon, "_watch_meeting", _spy)
    d = _daemon(tmp_path)
    d._config.meeting.enabled = True
    d._config.meeting.live_transcript = False
    d._engine = _Engine()
    d._state.ready = True
    d._state.state = TrayState.IDLE
    assert d._handle_meeting_start(Request(method="meeting_start", params={}, id=1))["ok"]
    assert done.wait(5.0)
    assert seen == [d._meeting_controller]
    d._meeting_controller.stop_capture()
    d._meeting_controller = None


# ---- (c) recover keeps capture_gap_s ------------------------------------------------


def _finished_stalled_meeting(tmp_path):
    t, fired = [0.0], []
    ctl = _meeting(tmp_path, t, fired)
    ctl.start()
    _chunks(ctl, t, 10)
    t[0] += 3000.0
    ctl.finalize(read_wav_mono_f32(ctl.stop_capture()))
    return ctl.dir


def test_recover_carries_capture_gap_into_metadata_and_summary(tmp_path):
    d = _finished_stalled_meeting(tmp_path)
    assert json.loads((d / "meeting.json").read_text(encoding="utf-8"))["capture_gap_s"] == 3000.0
    recover.recover_meeting(d, _cfg(tmp_path), engine=_Engine(), sample_rate=SR)
    meta = json.loads((d / "meeting.json").read_text(encoding="utf-8"))
    assert meta["recovered"] is True
    assert meta["capture_gap_s"] == 3000.0  # carried, not recomputed
    assert "Audio stopped arriving" in (d / "summary.md").read_text(encoding="utf-8")


def test_recover_of_a_meeting_without_a_gap_adds_none(tmp_path):
    t, fired = [0.0], []
    ctl = _meeting(tmp_path, t, fired)
    ctl.start()
    _chunks(ctl, t, 10)
    ctl.finalize(read_wav_mono_f32(ctl.stop_capture()))
    recover.recover_meeting(ctl.dir, _cfg(tmp_path), engine=_Engine(), sample_rate=SR)
    meta = json.loads((ctl.dir / "meeting.json").read_text(encoding="utf-8"))
    assert "capture_gap_s" not in meta


def test_recover_drops_a_malformed_gap_instead_of_carrying_it(tmp_path):
    d = _finished_stalled_meeting(tmp_path)
    meta = store.read_meta(d)
    meta["capture_gap_s"] = "garbage"
    store.write_meta(d, meta)
    recover.recover_meeting(d, _cfg(tmp_path), engine=_Engine(), sample_rate=SR)
    assert "capture_gap_s" not in store.read_meta(d)


# ---- the toast must not promise a time limit that does not exist --------------------


def test_stall_body_is_honest_about_the_time_limit():
    assert stall_body(True) == STALL_BODY and "time limit" in STALL_BODY
    assert stall_body(False) == STALL_BODY_NO_LIMIT
    assert "time limit" not in STALL_BODY_NO_LIMIT
    assert "yazses meeting stop" in STALL_BODY_NO_LIMIT
    text = f"{STALL_TITLE}\n{STALL_BODY_NO_LIMIT}"
    assert "30 seconds" in STALL_BODY_NO_LIMIT and "{" not in text and "%" not in text


def test_controller_reports_whether_a_cap_will_end_a_stalled_meeting(tmp_path):
    t = [0.0]
    assert _meeting(tmp_path, t, [], max_seconds=3600.0).has_time_limit is True
    assert _meeting(tmp_path, t, [], max_seconds=0.0).has_time_limit is False
    no_hook = _meeting(tmp_path, t, [])
    no_hook._on_auto_stop = None  # a cap with nobody to call never fires
    assert no_hook.has_time_limit is False


def test_watchdog_toast_for_an_unlimited_meeting_promises_no_time_limit(tmp_path, monkeypatch):
    sent = []
    from yazses.system import notify as notify_mod

    monkeypatch.setattr(notify_mod, "notify", lambda title, body, **k: sent.append((title, body)))
    d = _daemon(tmp_path)
    t = [0.0]
    ctl = _meeting(tmp_path, t, [], max_seconds=0.0)  # [meeting] max_minutes = 0
    ctl.start()
    t[0] = 31.0  # no chunk ever arrived
    d._meeting_watch_tick(ctl, StallNotice())
    assert sent == [(STALL_TITLE, STALL_BODY_NO_LIMIT)]
    sent.clear()
    capped = _meeting(tmp_path, t, [], max_seconds=3600.0)
    capped.start()
    t[0] = 70.0
    d._meeting_watch_tick(capped, StallNotice())
    assert sent == [(STALL_TITLE, STALL_BODY)]
