"""Speech guard (``yazses.biosignal.speechguard``): "is the user talking right now?".

Runs entirely on an injected clock with plain Python callables as sources: no audio, no
daemon, no hardware, no real sleeping.
"""

from __future__ import annotations

import logging
import math
import subprocess
import sys
import threading

import pytest

from yazses.biosignal.speechguard import (
    DEFAULT_HANGOVER_S,
    DEFAULT_LEAD_S,
    DEFAULT_MAX_STUCK_S,
    SpeechGuard,
    from_daemon_flags,
)

LOGGER = "yazses.biosignal.speechguard"


class Clock:
    """Manually advanced clock."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> float:
        self.t += dt
        return self.t


class Flag:
    """A mutable boolean source."""

    def __init__(self, value: bool = False) -> None:
        self.value = value

    def __call__(self) -> bool:
        return self.value


def _guard(clock: Clock, **kw) -> SpeechGuard:
    kw.setdefault("hangover_s", 0.5)
    kw.setdefault("lead_s", 0.25)
    return SpeechGuard(clock=clock, **kw)


def _raising() -> bool:
    raise RuntimeError("source exploded")


# --------------------------------------------------------------------------------------
# Truth table, hangover
# --------------------------------------------------------------------------------------


def test_guard_with_no_sources_is_never_speaking():
    g = _guard(Clock())
    assert g() is False


def test_true_while_any_source_is_true_and_false_when_all_false():
    clock = Clock()
    a, b = Flag(False), Flag(False)
    g = _guard(clock, hangover_s=0.0)
    g.add_source("a", a)
    g.add_source("b", b)
    assert g() is False
    a.value = True
    assert g() is True
    b.value = True
    assert g() is True
    a.value = False
    assert g() is True   # b still true
    b.value = False
    clock.advance(0.01)
    assert g() is False


def test_hangover_keeps_guard_true_then_expires():
    clock = Clock()
    src = Flag(True)
    g = _guard(clock, hangover_s=0.5)
    g.add_source("rec", src)
    assert g() is True
    src.value = False
    clock.advance(0.3)
    assert g() is True    # within the hangover
    clock.advance(0.2)
    assert g() is True    # exactly at the hangover edge (<=)
    clock.advance(0.01)
    assert g() is False   # expired


def test_a_new_true_reading_restarts_the_hangover():
    clock = Clock()
    src = Flag(True)
    g = _guard(clock, hangover_s=0.5)
    g.add_source("rec", src)
    g()
    src.value = False
    clock.advance(0.4)
    assert g() is True
    src.value = True
    clock.advance(0.4)
    assert g() is True
    src.value = False
    clock.advance(0.4)
    assert g() is True    # 0.4 s after the *second* true reading, not 0.8 s after the first
    clock.advance(0.2)
    assert g() is False


def test_zero_hangover_releases_immediately():
    clock = Clock()
    src = Flag(True)
    g = _guard(clock, hangover_s=0.0)
    g.add_source("rec", src)
    assert g() is True
    src.value = False
    clock.advance(0.001)
    assert g() is False


def test_non_bool_source_values_are_coerced():
    clock = Clock()
    g = _guard(clock, hangover_s=0.0)
    g.add_source("a", lambda: 1)       # type: ignore[arg-type,return-value]
    assert g() is True
    g2 = _guard(clock, hangover_s=0.0)
    g2.add_source("a", lambda: 0)      # type: ignore[arg-type,return-value]
    assert g2() is False


def test_defaults_are_the_documented_engineering_choices():
    g = SpeechGuard()
    assert g.hangover_s == DEFAULT_HANGOVER_S == 0.5
    assert g.lead_s == DEFAULT_LEAD_S == 0.25
    assert g.max_stuck_s == DEFAULT_MAX_STUCK_S == 120.0


def test_constructor_validates_arguments():
    with pytest.raises(ValueError):
        SpeechGuard(hangover_s=-0.1)
    with pytest.raises(ValueError):
        SpeechGuard(lead_s=-0.1)
    with pytest.raises(ValueError):
        SpeechGuard(max_stuck_s=0)
    with pytest.raises(ValueError):
        SpeechGuard(window_s=0)
    SpeechGuard(max_stuck_s=math.inf)   # infinity is the documented way to disable


# --------------------------------------------------------------------------------------
# Source management
# --------------------------------------------------------------------------------------


def test_sequence_sources_get_positional_names():
    g = SpeechGuard([Flag(), Flag()], clock=Clock())
    assert g.source_names == ("source0", "source1")


def test_duplicate_source_name_raises_value_error_and_keeps_the_first():
    g = _guard(Clock())
    first = Flag(True)
    g.add_source("vad", first)
    with pytest.raises(ValueError, match="vad"):
        g.add_source("vad", Flag(False))
    assert g.source_names == ("vad",)
    assert g() is True   # the original source is still the one consulted


def test_add_source_rejects_non_positive_watchdog():
    g = _guard(Clock())
    with pytest.raises(ValueError):
        g.add_source("x", Flag(), max_stuck_s=0)
    with pytest.raises(ValueError):
        g.add_source("x", Flag(), max_stuck_s=-5)
    assert g.source_names == ()


def test_remove_source_reports_existence_and_stops_it_counting():
    clock = Clock()
    g = _guard(clock, hangover_s=0.0)
    g.add_source("a", Flag(True))
    g.add_source("b", Flag(False))
    assert g() is True
    assert g.remove_source("a") is True
    assert g.remove_source("a") is False
    assert g.remove_source("never-added") is False
    assert g.source_names == ("b",)
    clock.advance(0.01)
    assert g() is False


def test_a_removed_name_can_be_registered_again():
    g = _guard(Clock())
    g.add_source("a", Flag(False))
    g.remove_source("a")
    g.add_source("a", Flag(True))
    assert g() is True


# --------------------------------------------------------------------------------------
# Fail closed
# --------------------------------------------------------------------------------------


def test_raising_source_fails_closed():
    g = _guard(Clock(), hangover_s=0.0)
    g.add_source("vad", _raising)
    assert g() is True


def test_raising_source_logs_once_not_on_every_call(caplog):
    clock = Clock()
    g = _guard(clock)
    g.add_source("vad", _raising)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for _ in range(50):
            clock.advance(0.01)
            assert g() is True
    raised = [r for r in caplog.records if "raised" in r.getMessage()]
    assert len(raised) == 1
    assert "vad" in raised[0].getMessage()
    assert "fail closed" in raised[0].getMessage()


def test_raising_source_logs_again_after_the_interval_with_a_count(caplog):
    clock = Clock()
    g = _guard(clock, max_stuck_s=math.inf)
    g.add_source("vad", _raising)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        g()
        for _ in range(9):
            clock.advance(1.0)
            g()
        clock.advance(61.0)
        g()
    raised = [r for r in caplog.records if "raised" in r.getMessage()]
    assert len(raised) == 2
    assert "10 more times" in raised[1].getMessage()   # 9 quiet ones plus this one


def test_raising_source_does_not_stop_other_sources_from_being_read():
    clock = Clock()
    polled = []
    g = _guard(clock, hangover_s=0.0)
    g.add_source("bad", _raising)
    g.add_source("good", lambda: polled.append(1) or False)
    assert g() is True
    assert polled == [1]


def test_source_that_recovers_stops_suppressing_after_the_hangover():
    clock = Clock()
    broken = {"on": True}

    def flaky() -> bool:
        if broken["on"]:
            raise OSError("device lost")
        return False

    g = _guard(clock, hangover_s=0.5)
    g.add_source("rec", flaky)
    assert g() is True
    broken["on"] = False
    clock.advance(0.6)
    assert g() is False


def test_error_is_visible_in_snapshot():
    clock = Clock()
    g = _guard(clock)
    g.add_source("vad", _raising)
    g()
    g()
    s = g.snapshot()["sources"]["vad"]
    assert s["errored"] is True
    assert s["error_count"] == 2
    assert s["value"] is True   # the recorded reading is the fail-closed one


# --------------------------------------------------------------------------------------
# Watchdog
# --------------------------------------------------------------------------------------


def test_stuck_source_is_ignored_after_max_stuck_s(caplog):
    clock = Clock()
    g = _guard(clock, hangover_s=0.5, max_stuck_s=10.0)
    g.add_source("rec", Flag(True))
    assert g() is True
    clock.advance(10.0)
    assert g() is True          # exactly max_stuck_s: not yet "over"
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        clock.advance(0.1)
        g()                      # crosses the limit: ignored from here on
    clock.advance(5.0)
    assert g() is False
    assert any("watchdog" in r.getMessage() for r in caplog.records)


def test_watchdog_warns_once_per_episode_and_snapshot_shows_it(caplog):
    clock = Clock()
    g = _guard(clock, max_stuck_s=5.0)
    src = Flag(True)
    g.add_source("rec", src)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        g()
        for _ in range(40):
            clock.advance(1.0)
            g()
    warns = [r for r in caplog.records if "watchdog" in r.getMessage()]
    assert len(warns) == 1
    s = g.snapshot()["sources"]["rec"]
    assert s["stuck"] is True
    assert s["stuck_episodes"] == 1
    assert s["max_stuck_s"] == 5.0


def test_stuck_source_is_ignored_until_it_reports_false_once_then_rearmed():
    clock = Clock()
    g = _guard(clock, hangover_s=0.0, max_stuck_s=5.0)
    src = Flag(True)
    g.add_source("rec", src)
    g()
    clock.advance(6.0)
    g()
    clock.advance(0.1)
    assert g() is False                       # stuck: ignored although still True
    assert g.snapshot()["sources"]["rec"]["stuck"] is True
    src.value = False
    clock.advance(0.1)
    assert g() is False
    assert g.snapshot()["sources"]["rec"]["stuck"] is False   # a false reading re-arms it
    src.value = True
    clock.advance(0.1)
    assert g() is True                        # suppresses again, it is a fresh run
    clock.advance(6.0)
    g()
    clock.advance(0.1)
    assert g() is False                       # and can get stuck a second time
    assert g.snapshot()["sources"]["rec"]["stuck_episodes"] == 2


def test_stuck_source_does_not_hide_a_second_source_that_is_really_speaking():
    clock = Clock()
    g = _guard(clock, hangover_s=0.0, max_stuck_s=5.0)
    g.add_source("rec", Flag(True))           # wedged
    vad = Flag(False)
    g.add_source("vad", vad)
    g()
    clock.advance(10.0)
    g()
    clock.advance(0.1)
    assert g() is False                       # only the wedged source is on: ignored
    vad.value = True
    assert g() is True                        # the VAD still suppresses during real speech


def test_continuously_erroring_source_is_also_stuck_eventually():
    clock = Clock()
    g = _guard(clock, hangover_s=0.0, max_stuck_s=5.0)
    g.add_source("vad", _raising)
    assert g() is True
    clock.advance(6.0)
    g()
    clock.advance(0.1)
    assert g() is False
    s = g.snapshot()["sources"]["vad"]
    assert s["stuck"] is True and s["errored"] is True


def test_a_true_gap_resets_the_stuck_clock():
    clock = Clock()
    g = _guard(clock, hangover_s=0.0, max_stuck_s=5.0)
    src = Flag(True)
    g.add_source("rec", src)
    for _ in range(4):
        g()
        clock.advance(3.0)
        src.value = False
        g()                                    # a single false reading ends the run
        clock.advance(0.1)
        src.value = True
    assert g.snapshot()["sources"]["rec"]["stuck_episodes"] == 0
    assert g() is True


def test_infinite_max_stuck_disables_the_watchdog():
    clock = Clock()
    g = _guard(clock, hangover_s=0.0, max_stuck_s=math.inf)
    g.add_source("rec", Flag(True))
    g()
    clock.advance(1e7)
    assert g() is True
    s = g.snapshot()["sources"]["rec"]
    assert s["stuck"] is False
    assert s["true_for_s"] == pytest.approx(1e7)


def test_per_source_limit_overrides_the_guard_wide_one():
    clock = Clock()
    g = _guard(clock, hangover_s=0.0, max_stuck_s=5.0)
    g.add_source("monologue", Flag(True), max_stuck_s=math.inf)
    g.add_source("short", Flag(True))
    g()
    clock.advance(100.0)
    g()
    snap = g.snapshot()["sources"]
    assert snap["monologue"]["stuck"] is False
    assert snap["short"]["stuck"] is True
    assert g() is True    # the exempt source keeps suppressing


# --------------------------------------------------------------------------------------
# was_speaking (retrospective)
# --------------------------------------------------------------------------------------


def _record_speech(clock: Clock, g: SpeechGuard, src: Flag, start: float, stop: float) -> None:
    """Poll the guard every 0.1 s over [start, stop], true throughout."""
    clock.t = start
    src.value = True
    while clock.t <= stop + 1e-9:
        g()
        clock.advance(0.1)
    src.value = False


def test_was_speaking_is_false_when_nothing_was_observed():
    g = _guard(Clock())
    g.add_source("rec", Flag(False))
    g()
    assert g.was_speaking(0.0, 1e9) is False


def test_was_speaking_backdates_a_rising_edge_by_lead_s():
    clock = Clock()
    src = Flag()
    g = _guard(clock, hangover_s=0.5, lead_s=0.25)
    g.add_source("rec", src)
    _record_speech(clock, g, src, 10.0, 10.2)    # segment [10.0, 10.2]
    assert g.was_speaking(9.8, 9.9) is True      # begins inside the 0.25 s pre-roll
    assert g.was_speaking(9.0, 9.7) is False     # before the pre-roll
    assert g.was_speaking(9.0, 9.74) is False
    assert g.was_speaking(9.0, 9.76) is True


def test_was_speaking_without_a_pre_roll_does_not_backdate():
    clock = Clock()
    src = Flag()
    g = _guard(clock, hangover_s=0.5, lead_s=0.0)
    g.add_source("rec", src)
    _record_speech(clock, g, src, 10.0, 10.2)
    assert g.was_speaking(9.8, 9.9) is False
    assert g.was_speaking(9.8, 10.0) is True


def test_was_speaking_extends_the_tail_by_hangover_s():
    clock = Clock()
    src = Flag()
    g = _guard(clock, hangover_s=0.5, lead_s=0.25)
    g.add_source("rec", src)
    _record_speech(clock, g, src, 10.0, 10.2)
    assert g.was_speaking(10.6, 10.65) is True    # inside 10.2 + 0.5
    assert g.was_speaking(10.8, 11.0) is False    # after it


def test_was_speaking_default_end_is_now():
    clock = Clock()
    src = Flag()
    g = _guard(clock, hangover_s=0.5, lead_s=0.25)
    g.add_source("rec", src)
    _record_speech(clock, g, src, 10.0, 10.2)
    clock.t = 10.4
    assert g.was_speaking(10.3) is True
    clock.t = 30.0
    assert g.was_speaking(20.0) is False


def test_was_speaking_separates_distant_segments():
    clock = Clock()
    src = Flag()
    g = _guard(clock, hangover_s=0.5, lead_s=0.25)
    g.add_source("rec", src)
    _record_speech(clock, g, src, 10.0, 10.5)
    _record_speech(clock, g, src, 20.0, 20.5)
    assert g.was_speaking(15.0, 16.0) is False
    assert g.was_speaking(10.2, 10.3) is True
    assert g.was_speaking(20.4, 20.6) is True
    assert g.was_speaking(0.0, 100.0) is True


def test_was_speaking_does_not_poll_sources():
    clock = Clock()
    calls = []
    g = _guard(clock)
    g.add_source("rec", lambda: calls.append(1) or True)
    assert g.was_speaking(0.0, 10_000_000_000.0) is False
    assert calls == []


def test_was_speaking_ignores_a_watchdog_ignored_source():
    clock = Clock()
    g = _guard(clock, hangover_s=0.0, lead_s=0.0, max_stuck_s=2.0)
    g.add_source("rec", Flag(True))
    g()
    for _ in range(40):
        clock.advance(0.5)
        g()
    # Speech was recorded only until the watchdog tripped (about 2 s after the first poll).
    assert g.was_speaking(1015.0, 1020.0) is False
    assert g.was_speaking(1000.0, 1001.0) is True


# --------------------------------------------------------------------------------------
# suppressed_fraction
# --------------------------------------------------------------------------------------


def test_suppressed_fraction_is_none_when_nothing_was_observed():
    g = _guard(Clock())
    g.add_source("rec", Flag(True))
    assert g.suppressed_fraction() is None


def test_suppressed_fraction_is_none_once_observations_age_out():
    clock = Clock()
    g = _guard(clock)
    g.add_source("rec", Flag(True))
    for _ in range(10):
        g()
        clock.advance(0.1)
    assert g.suppressed_fraction() is not None
    clock.advance(1000.0)
    assert g.suppressed_fraction() is None


def test_suppressed_fraction_all_true_and_all_false():
    clock = Clock()
    src = Flag(True)
    g = _guard(clock, hangover_s=0.0)
    g.add_source("rec", src)
    for _ in range(20):
        g()
        clock.advance(0.1)
    assert g.suppressed_fraction() == pytest.approx(1.0)

    clock2 = Clock()
    g2 = _guard(clock2, hangover_s=0.0)
    g2.add_source("rec", Flag(False))
    for _ in range(20):
        g2()
        clock2.advance(0.1)
    assert g2.suppressed_fraction() == pytest.approx(0.0)


def test_suppressed_fraction_is_time_weighted_not_poll_weighted():
    """3 sparse polls cover 1.8 s of suppression; 100 dense polls cover 1.0 s of quiet."""
    clock = Clock()
    src = Flag(True)
    g = _guard(clock, hangover_s=0.0)
    g.add_source("rec", src)
    for _ in range(3):          # polls at +0, +0.6, +1.2
        g()
        clock.advance(0.6)
    g()                         # +1.8 (still true)
    src.value = False
    for _ in range(100):        # dense false polls over the next second
        clock.advance(0.01)
        g()
    frac = g.suppressed_fraction()
    assert frac == pytest.approx(1.8 / 2.8, abs=0.03)   # poll-weighted would be ~4/104


def test_suppressed_fraction_excludes_stretches_nobody_polled():
    clock = Clock()
    src = Flag(True)
    g = _guard(clock, hangover_s=0.0)
    g.add_source("rec", src)
    for _ in range(11):          # 1.0 s fully suppressed, polled every 0.1 s
        g()
        clock.advance(0.1)
    clock.advance(30.0)          # nobody asks for 30 s
    src.value = False
    for _ in range(11):          # 1.0 s fully quiet
        g()
        clock.advance(0.1)
    # The unobserved half minute is neither suppressed nor quiet: about half and half.
    assert g.suppressed_fraction(window_s=100.0) == pytest.approx(0.5, abs=0.06)


def test_suppressed_fraction_window_restricts_to_recent_time():
    clock = Clock()
    src = Flag(True)
    g = _guard(clock, hangover_s=0.0)
    g.add_source("rec", src)
    for _ in range(11):
        g()
        clock.advance(0.1)
    src.value = False
    for _ in range(11):
        g()
        clock.advance(0.1)
    recent = g.suppressed_fraction(window_s=0.5)
    whole = g.suppressed_fraction(window_s=60.0)
    assert recent == pytest.approx(0.0, abs=0.01)
    assert 0.3 < whole < 0.7


def test_suppressed_fraction_rejects_non_positive_window():
    g = _guard(Clock())
    with pytest.raises(ValueError):
        g.suppressed_fraction(0)
    with pytest.raises(ValueError):
        g.suppressed_fraction(-1.0)


def test_suppressed_fraction_counts_the_hangover_as_suppression():
    clock = Clock()
    src = Flag(True)
    g = _guard(clock, hangover_s=0.55)
    g.add_source("rec", src)
    g()
    src.value = False
    for _ in range(5):          # 0.5 s of pure hangover, polled every 0.1 s
        clock.advance(0.1)
        g()
    assert g.suppressed_fraction() == pytest.approx(1.0)


# --------------------------------------------------------------------------------------
# snapshot
# --------------------------------------------------------------------------------------


def test_snapshot_has_the_documented_top_level_fields():
    clock = Clock()
    g = _guard(clock, hangover_s=0.7, lead_s=0.3, window_s=30.0)
    snap = g.snapshot()
    assert set(snap) == {
        "speaking",
        "hangover_s",
        "lead_s",
        "window_s",
        "last_speech_t",
        "last_speech_age_s",
        "suppressed_fraction",
        "sources",
    }
    assert snap["hangover_s"] == 0.7 and snap["lead_s"] == 0.3 and snap["window_s"] == 30.0
    assert snap["speaking"] is None
    assert snap["last_speech_t"] is None and snap["last_speech_age_s"] is None
    assert snap["suppressed_fraction"] is None
    assert snap["sources"] == {}


def test_snapshot_is_passive_by_default_and_polls_on_request():
    clock = Clock()
    calls = []
    g = _guard(clock)
    g.add_source("rec", lambda: calls.append(1) or True)
    snap = g.snapshot()
    assert calls == [] and snap["speaking"] is None
    assert snap["sources"]["rec"]["polls"] == 0
    assert snap["sources"]["rec"]["value"] is None
    snap = g.snapshot(poll=True)
    assert calls == [1] and snap["speaking"] is True
    assert snap["sources"]["rec"]["polls"] == 1


def test_snapshot_reports_per_source_fields():
    clock = Clock()
    src = Flag(True)
    g = _guard(clock, hangover_s=0.5)
    g.add_source("rec", src)
    g()
    for _ in range(4):          # polled every 0.5 s so the runs stay contiguous
        clock.advance(0.5)
        g()
    snap = g.snapshot()
    s = snap["sources"]["rec"]
    assert set(s) == {
        "value", "last_true_t", "last_true_age_s", "true_for_s", "stuck",
        "stuck_episodes", "max_stuck_s", "errored", "error_count", "polls",
    }
    assert s["value"] is True
    assert s["polls"] == 5
    assert s["true_for_s"] == pytest.approx(2.0)
    assert s["last_true_age_s"] == pytest.approx(0.0)
    assert s["stuck"] is False and s["errored"] is False and s["error_count"] == 0
    assert s["max_stuck_s"] == g.max_stuck_s
    assert snap["speaking"] is True
    assert snap["last_speech_t"] == pytest.approx(clock.t)
    assert snap["suppressed_fraction"] == pytest.approx(1.0)

    src.value = False
    clock.advance(3.0)
    g()
    snap = g.snapshot()
    assert snap["speaking"] is False
    assert snap["sources"]["rec"]["true_for_s"] is None
    assert snap["last_speech_age_s"] == pytest.approx(3.0)
    assert snap["sources"]["rec"]["last_true_age_s"] == pytest.approx(3.0)


# --------------------------------------------------------------------------------------
# from_daemon_flags
# --------------------------------------------------------------------------------------


def test_from_daemon_flags_names_only_the_sources_given():
    assert from_daemon_flags(Flag()).source_names == ("recording",)
    assert from_daemon_flags(Flag(), Flag()).source_names == ("recording", "vad")
    assert from_daemon_flags(Flag(), None, Flag()).source_names == ("recording", "tts")
    assert from_daemon_flags(Flag(), Flag(), Flag()).source_names == ("recording", "vad", "tts")


def test_from_daemon_flags_returns_a_speech_guard_honouring_keywords():
    clock = Clock()
    rec, vad, tts = Flag(), Flag(), Flag()
    g = from_daemon_flags(rec, vad, tts, hangover_s=0.2, lead_s=0.1, clock=clock, window_s=9.0)
    assert isinstance(g, SpeechGuard)
    assert (g.hangover_s, g.lead_s, g.window_s) == (0.2, 0.1, 9.0)
    assert g() is False
    for flag in (rec, vad, tts):
        flag.value = True
        assert g() is True
        flag.value = False
        clock.advance(0.5)
        assert g() is False


def test_from_daemon_flags_shares_the_guard_wide_watchdog():
    clock = Clock()
    g = from_daemon_flags(Flag(True), clock=clock, max_stuck_s=3.0, hangover_s=0.0)
    g()
    clock.advance(5.0)
    g()
    clock.advance(0.1)
    assert g() is False
    assert g.snapshot()["sources"]["recording"]["max_stuck_s"] == 3.0


# --------------------------------------------------------------------------------------
# Concurrency and independence
# --------------------------------------------------------------------------------------


def test_slow_source_does_not_block_snapshot():
    """Sources run outside the lock: a source stuck in a call must not freeze status output."""
    entered = threading.Event()
    release = threading.Event()

    def slow() -> bool:
        entered.set()
        release.wait(timeout=10.0)
        return True

    g = SpeechGuard(clock=Clock())
    g.add_source("slow", slow)
    worker = threading.Thread(target=g, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=5.0)
        out: dict = {}
        reader = threading.Thread(target=lambda: out.update(g.snapshot()), daemon=True)
        reader.start()
        reader.join(timeout=5.0)
        assert not reader.is_alive(), "snapshot() blocked behind a slow source"
        assert out["sources"]["slow"]["polls"] == 0
        # Registration is not blocked either.
        g.add_source("other", Flag())
        assert g.remove_source("other") is True
    finally:
        release.set()
        worker.join(timeout=5.0)
    assert not worker.is_alive()


def test_source_may_call_back_into_the_guard_without_deadlock():
    g = SpeechGuard(clock=Clock())
    seen = []

    def reentrant() -> bool:
        seen.append(g.snapshot()["hangover_s"])
        seen.append(g.source_names)
        return False

    g.add_source("re", reentrant)
    done = threading.Thread(target=g, daemon=True)
    done.start()
    done.join(timeout=5.0)
    assert not done.is_alive()
    assert seen == [g.hangover_s, ("re",)]


def test_concurrent_callers_and_mutators_do_not_corrupt_state():
    g = SpeechGuard(clock=Clock(), hangover_s=0.0)
    g.add_source("a", Flag(True))
    g.add_source("b", Flag(False))
    errors: list[BaseException] = []

    def hammer(i: int) -> None:
        try:
            for k in range(200):
                assert g() is True
                g.snapshot()
                g.suppressed_fraction()
                g.was_speaking(0.0, 1e9)
                name = f"t{i}-{k % 3}"
                try:
                    g.add_source(name, Flag(False))
                except ValueError:
                    pass
                g.remove_source(name)
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(i,), daemon=True) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    assert not any(t.is_alive() for t in threads)
    assert errors == []
    assert g.snapshot()["sources"]["a"]["polls"] == 800


def test_module_imports_without_audio_daemon_or_hardware_modules():
    code = (
        "import sys; import yazses.biosignal.speechguard as m;"
        "bad = [n for n in sys.modules if n.split('.')[0] in "
        "('sounddevice','brainflow','serial','torch','faster_whisper') "
        "or n in ('yazses.core.daemon','yazses.audio')];"
        "print(','.join(bad))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=True
    )
    assert out.stdout.strip() == ""
