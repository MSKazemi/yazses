"""Gesture hold-to-talk state machine (pure): transitions, flicker grace, safety timeout."""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from yazses.xr.ptt import GesturePtt, PttAction, PttActionKind, PttMode
from yazses.xr.types import GestureEvent, GestureKind

START = PttActionKind.START
STOP = PttActionKind.STOP
CANCEL = PttActionKind.CANCEL

P_START = GestureKind.PINCH_START
P_END = GestureKind.PINCH_END
S_START = GestureKind.SQUEEZE_START
S_END = GestureKind.SQUEEZE_END
TAP = GestureKind.TAP


def ev(t: float, kind: GestureKind, conf: float = 1.0) -> GestureEvent:
    return GestureEvent(timestamp_s=t, kind=kind, confidence=conf)


def kinds(actions: list[PttAction]) -> list[PttActionKind]:
    return [a.kind for a in actions]


def pinch(**kw: float) -> GesturePtt:
    return GesturePtt(PttMode.HOLD_PINCH, **kw)


# --------------------------------------------------------------- construction


def test_defaults_idle():
    p = pinch()
    assert not p.is_listening
    assert p.mode is PttMode.HOLD_PINCH


@pytest.mark.parametrize(
    "kwargs",
    [
        {"debounce_s": -0.1},
        {"debounce_s": float("nan")},
        {"release_grace_s": -1.0},
        {"release_grace_s": float("inf")},
        {"max_hold_s": 0.0},
        {"max_hold_s": -5.0},
        {"min_confidence": 1.5},
        {"min_confidence": -0.1},
    ],
)
def test_bad_parameters_refused(kwargs):
    with pytest.raises(ValueError):
        GesturePtt(PttMode.HOLD_PINCH, **kwargs)


def test_mode_must_be_a_ptt_mode():
    with pytest.raises(ValueError):
        GesturePtt("hold_pinch")  # type: ignore[arg-type]


def test_tick_refuses_non_finite():
    p = pinch()
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            p.tick(bad)


# ------------------------------------------------------------- hold transitions


def test_pinch_start_emits_start_at_event_time():
    p = pinch()
    out = p.feed(ev(1.0, P_START))
    assert out == [PttAction(START, 1.0)]
    assert p.is_listening


def test_pinch_end_stops_only_after_grace():
    p = pinch(release_grace_s=0.12)
    p.feed(ev(1.0, P_START))
    assert p.feed(ev(2.0, P_END)) == []
    assert p.is_listening  # still in grace: mic stays open
    assert p.tick(2.11) == []
    assert p.is_listening
    out = p.tick(2.12)
    assert out == [PttAction(STOP, pytest.approx(2.12))]
    assert not p.is_listening


def test_stop_is_stamped_at_expiry_not_at_late_tick():
    p = pinch(release_grace_s=0.1)
    p.feed(ev(1.0, P_START))
    p.feed(ev(2.0, P_END))
    out = p.tick(50.0)
    assert out[0].timestamp_s == pytest.approx(2.1)


def test_zero_grace_stops_immediately():
    p = pinch(release_grace_s=0.0)
    p.feed(ev(1.0, P_START))
    assert p.feed(ev(2.0, P_END)) == [PttAction(STOP, 2.0)]
    assert not p.is_listening


def test_squeeze_mode_start_and_stop():
    p = GesturePtt(PttMode.HOLD_SQUEEZE, release_grace_s=0.0)
    assert kinds(p.feed(ev(1.0, S_START))) == [START]
    assert kinds(p.feed(ev(2.0, S_END))) == [STOP]


def test_stop_then_new_utterance():
    p = pinch(release_grace_s=0.1)
    p.feed(ev(1.0, P_START))
    p.feed(ev(2.0, P_END))
    p.tick(2.2)
    assert kinds(p.feed(ev(3.0, P_START))) == [START]
    assert p.is_listening


# -------------------------------------------------------------- flicker grace


def test_flicker_within_grace_continues_same_utterance():
    p = pinch(release_grace_s=0.12)
    assert kinds(p.feed(ev(1.0, P_START))) == [START]
    assert p.feed(ev(2.0, P_END)) == []
    assert p.feed(ev(2.05, P_START)) == []  # no STOP/START pair
    assert p.is_listening
    # ...and the grace timer is disarmed: nothing fires later.
    assert p.tick(10.0) == []
    assert p.is_listening


def test_restart_exactly_at_grace_deadline_still_continues():
    p = pinch(release_grace_s=0.1)
    p.feed(ev(1.0, P_START))
    p.feed(ev(2.0, P_END))
    assert p.feed(ev(2.1, P_START)) == []
    assert p.is_listening


def test_restart_after_grace_is_stop_then_start():
    p = pinch(release_grace_s=0.1, debounce_s=0.0)
    p.feed(ev(1.0, P_START))
    p.feed(ev(2.0, P_END))
    out = p.feed(ev(2.5, P_START))
    assert kinds(out) == [STOP, START]
    assert out[0].timestamp_s == pytest.approx(2.1)
    assert out[1].timestamp_s == 2.5


def test_repeated_flicker_does_not_extend_past_max_hold():
    p = pinch(release_grace_s=0.1, max_hold_s=1.0, debounce_s=0.0)
    p.feed(ev(0.0, P_START))
    t = 0.1
    while t < 0.95:
        p.feed(ev(t, P_END))
        p.feed(ev(t + 0.05, P_START))
        t += 0.2
    out = p.tick(1.0)
    assert kinds(out) == [STOP]
    assert out[0].timestamp_s == pytest.approx(1.0)


def test_continuation_does_not_resume_past_hold_deadline():
    p = pinch(release_grace_s=5.0, max_hold_s=1.0)
    p.feed(ev(0.0, P_START))
    p.feed(ev(0.9, P_END))
    # Restart inside the grace window but after the hold limit: limit wins.
    out = p.feed(ev(1.5, P_START))
    assert kinds(out)[0] == STOP
    assert out[0].timestamp_s == pytest.approx(1.0)


# ------------------------------------------------------------ safety timeout


def test_stuck_gesture_forces_stop_at_max_hold():
    p = pinch(max_hold_s=120.0)
    p.feed(ev(10.0, P_START))
    assert p.tick(129.9) == []
    assert p.is_listening
    out = p.tick(130.0)
    assert out == [PttAction(STOP, 130.0)]
    assert not p.is_listening


def test_hand_leaving_tracking_closes_mic_on_a_late_tick():
    p = pinch(max_hold_s=5.0)
    p.feed(ev(1.0, P_START))
    out = p.tick(1000.0)
    assert kinds(out) == [STOP]
    assert out[0].timestamp_s == pytest.approx(6.0)
    assert not p.is_listening


def test_event_after_hold_limit_triggers_stop_first():
    p = pinch(max_hold_s=5.0)
    p.feed(ev(1.0, P_START))
    out = p.feed(ev(20.0, P_END))  # late end: the limit already fired
    assert kinds(out) == [STOP]
    assert not p.is_listening


def test_late_end_after_forced_stop_is_ignored():
    p = pinch(max_hold_s=5.0)
    p.feed(ev(1.0, P_START))
    p.tick(10.0)
    assert p.feed(ev(11.0, P_END)) == []
    assert not p.is_listening


def test_max_hold_applies_in_toggle_mode():
    p = GesturePtt(PttMode.TOGGLE_TAP, max_hold_s=3.0)
    p.feed(ev(1.0, TAP))
    assert kinds(p.tick(4.0)) == [STOP]
    assert not p.is_listening


def test_tick_is_idempotent_after_stop():
    p = pinch(max_hold_s=1.0)
    p.feed(ev(0.0, P_START))
    assert kinds(p.tick(5.0)) == [STOP]
    assert p.tick(5.0) == []
    assert p.tick(9.0) == []


def test_tick_backwards_is_a_noop():
    p = pinch()
    p.feed(ev(5.0, P_START))
    p.tick(6.0)
    assert p.tick(1.0) == []
    assert p.is_listening


# ------------------------------------------------------------------- debounce


def test_blip_shorter_than_debounce_is_cancelled():
    p = pinch(debounce_s=0.05)
    assert kinds(p.feed(ev(1.0, P_START))) == [START]
    out = p.feed(ev(1.03, P_END))
    assert out == [PttAction(CANCEL, 1.03)]
    assert not p.is_listening
    assert p.tick(100.0) == []  # nothing left pending


def test_press_exactly_debounce_long_is_a_real_utterance():
    p = pinch(debounce_s=0.05, release_grace_s=0.0)
    p.feed(ev(1.0, P_START))
    assert kinds(p.feed(ev(1.05, P_END))) == [STOP]


def test_start_right_after_stop_is_chatter():
    p = pinch(debounce_s=0.2, release_grace_s=0.0)
    p.feed(ev(1.0, P_START))
    p.feed(ev(2.0, P_END))  # STOP at 2.0
    assert p.feed(ev(2.1, P_START)) == []
    assert not p.is_listening
    assert kinds(p.feed(ev(2.2, P_START))) == [START]


def test_zero_debounce_disables_chatter_filtering():
    p = pinch(debounce_s=0.0, release_grace_s=0.0)
    assert kinds(p.feed(ev(1.0, P_START))) == [START]
    assert kinds(p.feed(ev(1.0, P_END))) == [STOP]
    assert kinds(p.feed(ev(1.0, P_START))) == [START]


def test_toggle_double_registered_tap_is_ignored():
    p = GesturePtt(PttMode.TOGGLE_TAP, debounce_s=0.2)
    assert kinds(p.feed(ev(1.0, TAP))) == [START]
    assert p.feed(ev(1.1, TAP)) == []  # same physical tap seen twice
    assert p.is_listening
    assert kinds(p.feed(ev(2.0, TAP))) == [STOP]


# ------------------------------------------------------------- toggle behaviour


def test_toggle_tap_alternates_start_stop():
    p = GesturePtt(PttMode.TOGGLE_TAP)
    assert kinds(p.feed(ev(1.0, TAP))) == [START]
    assert p.is_listening
    assert p.feed(ev(2.0, TAP)) == [PttAction(STOP, 2.0)]  # no grace on a toggle
    assert not p.is_listening
    assert kinds(p.feed(ev(3.0, TAP))) == [START]


# -------------------------------------------------------- filtering / isolation


def test_low_confidence_events_ignored():
    p = pinch(min_confidence=0.5)
    assert p.feed(ev(1.0, P_START, 0.49)) == []
    assert not p.is_listening
    p.feed(ev(2.0, P_START, 0.5))  # boundary: accepted
    assert p.is_listening
    # (A weak RELEASE is deliberately not ignored: see the fail-safe tests below.)


def test_low_confidence_event_does_not_move_the_ordering_clock():
    p = pinch()
    p.feed(ev(1e9, P_START, 0.0))  # hostile far-future, rejected
    assert kinds(p.feed(ev(1.0, P_START))) == [START]


@pytest.mark.parametrize(
    "mode,wrong",
    [
        (PttMode.HOLD_PINCH, [S_START, S_END, TAP]),
        (PttMode.HOLD_SQUEEZE, [P_START, P_END, TAP]),
        (PttMode.TOGGLE_TAP, [P_START, P_END, S_START, S_END]),
    ],
)
def test_wrong_family_ignored_when_idle(mode, wrong):
    p = GesturePtt(mode)
    for i, k in enumerate(wrong):
        assert p.feed(ev(float(i + 1), k)) == []
    assert not p.is_listening


def test_wrong_family_does_not_disturb_a_live_utterance():
    p = pinch(release_grace_s=0.0)
    p.feed(ev(1.0, P_START))
    assert p.feed(ev(2.0, S_END)) == []
    assert p.feed(ev(2.1, TAP)) == []
    assert p.feed(ev(2.2, S_START)) == []
    assert p.is_listening
    assert kinds(p.feed(ev(3.0, P_END))) == [STOP]


def test_wrong_family_does_not_move_the_ordering_clock():
    p = pinch()
    p.feed(ev(500.0, TAP))
    assert kinds(p.feed(ev(1.0, P_START))) == [START]


# ----------------------------------------------------- duplicates / ordering


def test_duplicate_start_ignored():
    p = pinch()
    p.feed(ev(1.0, P_START))
    assert p.feed(ev(1.5, P_START)) == []
    assert p.is_listening


def test_duplicate_end_ignored_and_does_not_extend_grace():
    p = pinch(release_grace_s=0.5)
    p.feed(ev(1.0, P_START))
    p.feed(ev(2.0, P_END))
    assert p.feed(ev(2.3, P_END)) == []  # must not push the deadline to 2.8
    out = p.tick(2.5)
    assert kinds(out) == [STOP]
    assert out[0].timestamp_s == pytest.approx(2.5)


def test_end_without_start_ignored():
    p = pinch()
    assert p.feed(ev(1.0, P_END)) == []
    assert not p.is_listening


def test_out_of_order_start_ignored_without_corruption():
    p = pinch(release_grace_s=0.0, debounce_s=0.0)
    p.feed(ev(5.0, P_START))
    p.feed(ev(6.0, P_END))
    assert p.feed(ev(4.0, P_START)) == []  # older than last accepted: dropped
    assert not p.is_listening
    assert kinds(p.feed(ev(7.0, P_START))) == [START]


def test_equal_timestamps_are_in_order():
    p = pinch(release_grace_s=0.0, debounce_s=0.0)
    p.feed(ev(5.0, P_START))
    assert kinds(p.feed(ev(5.0, P_END))) == [STOP]


def test_event_older_than_a_tick_but_newer_than_last_event_is_still_honoured():
    # Transport latency: the host ticks at wall time 10 before an event stamped 9.9
    # arrives. The event is in order on the event stream and must not be dropped.
    p = pinch(release_grace_s=0.0, debounce_s=0.0)
    p.feed(ev(9.0, P_START))
    p.tick(10.0)
    out = p.feed(ev(9.9, P_END))
    assert kinds(out) == [STOP]
    assert out[0].timestamp_s == 10.0  # stamped monotonically, never before the tick


def test_action_timestamps_non_decreasing_across_late_event():
    p = pinch(release_grace_s=0.0, debounce_s=0.0, max_hold_s=0.5)
    p.feed(ev(9.0, P_START))
    assert p.tick(10.0) == [PttAction(STOP, 9.5)]  # hold limit fired
    out = p.feed(ev(9.9, P_START))  # fresh utterance, stamped at the tick time
    assert out == [PttAction(START, 10.0)]


# ---------------------------------------------------------------------- reset


def test_reset_idle_returns_nothing():
    p = pinch()
    assert p.reset() == []


def test_reset_cancels_live_utterance_and_restarts_timeline():
    p = pinch()
    p.feed(ev(100.0, P_START))
    out = p.reset(now_s=105.0)
    assert out == [PttAction(CANCEL, 105.0)]
    assert not p.is_listening
    # A reconnecting device may restart its clock near zero.
    assert kinds(p.feed(ev(0.5, P_START))) == [START]


def test_reset_during_grace_cancels():
    p = pinch(release_grace_s=1.0)
    p.feed(ev(1.0, P_START))
    p.feed(ev(2.0, P_END))
    assert kinds(p.reset()) == [CANCEL]
    assert p.tick(10.0) == []


# ------------------------------------------------------------------ properties

_KINDS = list(GestureKind)

_step = st.one_of(
    st.tuples(
        st.just("event"),
        st.sampled_from(_KINDS),
        st.floats(min_value=-0.5, max_value=3.0, allow_nan=False),  # dt, may go backwards
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False),   # confidence
    ),
    st.tuples(
        st.just("tick"),
        st.just(None),
        st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
        st.just(0.0),
    ),
)


def _legal(actions: list[PttAction]) -> bool:
    """START opens, STOP/CANCEL closes; never a close without an open or two opens."""
    open_ = False
    last_t = float("-inf")
    for a in actions:
        if a.timestamp_s < last_t:
            return False
        last_t = a.timestamp_s
        if a.kind is START:
            if open_:
                return False
            open_ = True
        else:
            if not open_:
                return False
            open_ = False
    return True


@settings(max_examples=300, deadline=None)
@given(
    mode=st.sampled_from(list(PttMode)),
    debounce=st.sampled_from([0.0, 0.05, 0.3]),
    grace=st.sampled_from([0.0, 0.12, 1.0]),
    max_hold=st.sampled_from([0.5, 2.0, 120.0]),
    min_conf=st.sampled_from([0.0, 0.5, 1.0]),
    steps=st.lists(_step, max_size=60),
)
def test_actions_alternate_legally_and_safety_timeout_always_closes(
    mode, debounce, grace, max_hold, min_conf, steps
):
    p = GesturePtt(
        mode,
        debounce_s=debounce,
        release_grace_s=grace,
        max_hold_s=max_hold,
        min_confidence=min_conf,
    )
    actions: list[PttAction] = []
    clock = 0.0
    for tag, kind, a, b in steps:
        if tag == "event":
            clock = max(0.0, clock + a)
            actions += p.feed(ev(clock, kind, b))
        else:
            clock += a
            actions += p.tick(clock)
        # The machine's own view agrees with the action stream at every step.
        assert p.is_listening == _open_after(actions)
    assert _legal(actions)

    # Stuck-gesture safety: past the hold limit (and any grace) the mic is closed.
    actions += p.tick(clock + max_hold + grace + 1.0)
    assert not p.is_listening
    assert _legal(actions)
    assert not _open_after(actions)
    assert p.tick(clock + 10 * (max_hold + grace + 1.0)) == []


def _open_after(actions: list[PttAction]) -> bool:
    return bool(actions) and actions[-1].kind is START


@settings(max_examples=200, deadline=None)
@given(start=st.floats(min_value=0.0, max_value=1e4, allow_nan=False), max_hold=st.floats(min_value=0.01, max_value=500.0))
def test_listening_never_survives_the_hold_limit(start, max_hold):
    p = GesturePtt(PttMode.HOLD_PINCH, max_hold_s=max_hold)
    p.feed(ev(start, P_START))
    p.tick(start + max_hold)
    assert not p.is_listening


# ------------------------------------------- fail-safe: stop events always close


def test_low_confidence_release_still_closes_the_mic():
    p = pinch(min_confidence=0.5)
    p.feed(ev(1.0, P_START))
    assert p.feed(ev(2.0, P_END, 0.2)) == []  # grace running
    assert p.tick(50.0) == [PttAction(STOP, pytest.approx(2.12))]
    assert not p.is_listening


def test_low_confidence_squeeze_release_closes_the_mic():
    p = GesturePtt(PttMode.HOLD_SQUEEZE, min_confidence=0.5)
    p.feed(ev(1.0, S_START))
    p.feed(ev(2.0, S_END, 0.0))
    assert kinds(p.tick(50.0)) == [STOP]


def test_low_confidence_tap_toggles_off_but_never_on():
    p = GesturePtt(PttMode.TOGGLE_TAP, min_confidence=0.5)
    assert p.feed(ev(1.0, TAP, 0.1)) == []  # a weak tap must not open the mic
    assert not p.is_listening
    p.feed(ev(2.0, TAP))
    assert p.is_listening
    assert kinds(p.feed(ev(3.0, TAP, 0.1))) == [STOP]  # but may close it
    assert not p.is_listening


def test_low_confidence_release_while_idle_touches_nothing():
    p = pinch(min_confidence=0.5)
    assert p.feed(ev(1e9, P_END, 0.0)) == []
    assert kinds(p.feed(ev(1.0, P_START))) == [START]  # ordering clock not moved


# ----------------------------------------- fail-safe: ordering clock cannot wedge


def test_far_future_start_cannot_pin_the_clock_when_armed():
    p = pinch(release_grace_s=0.0, debounce_s=0.0)
    p.tick(0.0)  # arm the future bound
    out = p.feed(ev(1e9, P_START))
    assert out == [PttAction(START, 5.0)]  # clamped to reference + max_future_s
    assert kinds(p.feed(ev(5.0, P_END))) == [STOP]
    assert not p.is_listening


def test_far_future_start_listening_is_bounded_by_ticks():
    p = pinch()
    p.tick(10.0)
    p.feed(ev(1e9, P_START))
    p.tick(10.0 + 5.0 + 120.0)
    assert not p.is_listening


def test_accepted_far_future_start_then_early_end_still_closes():
    # Reviewer repro: START@1e9, END@5, tick(10), tick(1000) all returned [] and the
    # mic stayed open. Unarmed, the first event is taken as given; the END must close.
    p = pinch()
    p.feed(ev(1e9, P_START))
    out = p.feed(ev(5.0, P_END))
    assert kinds(out) in ([STOP], [CANCEL])
    assert not p.is_listening
    assert p.tick(10.0) == []
    assert p.tick(1000.0) == []


def test_far_future_release_is_honoured_at_bounded_time():
    p = pinch(release_grace_s=0.0)
    p.tick(0.0)
    p.feed(ev(1.0, P_START))
    out = p.feed(ev(1e9, P_END))
    assert out == [PttAction(STOP, 6.0)]  # 1.0 + 5.0 s bound, no grace
    assert not p.is_listening
    # The ordering clock was not pinned at 1e9: a later honest press still starts.
    assert kinds(p.feed(ev(8.0, P_START))) == [START]


def test_end_stamped_slightly_before_its_start_closes_the_mic():
    # Reviewer repro (b): START@10.0, END@9.9 was dropped as out-of-order; the mic then
    # stayed open for max_hold_s. Now the end is honoured at the current time.
    p = pinch()
    assert kinds(p.feed(ev(10.0, P_START))) == [START]
    out = p.feed(ev(9.9, P_END))
    assert kinds(out) in ([STOP], [CANCEL])
    assert out[0].timestamp_s == 10.0  # never before time already seen
    assert not p.is_listening
    assert p.tick(10.0) == []


def test_out_of_order_end_after_real_hold_is_a_stop_not_a_cancel():
    p = pinch()
    p.feed(ev(10.0, P_START))
    p.tick(14.0)
    out = p.feed(ev(9.0, P_END))
    assert out == [PttAction(STOP, 14.0)]


def test_out_of_order_tap_toggles_off_even_inside_the_tap_debounce():
    p = GesturePtt(PttMode.TOGGLE_TAP, debounce_s=0.05)
    p.feed(ev(10.0, TAP))
    out = p.feed(ev(9.99, TAP))
    assert kinds(out) == [STOP]
    assert not p.is_listening


def test_out_of_order_tap_while_idle_is_still_ignored():
    p = GesturePtt(PttMode.TOGGLE_TAP)
    p.feed(ev(10.0, TAP))
    p.feed(ev(11.0, TAP))  # off
    assert p.feed(ev(5.0, TAP)) == []
    assert not p.is_listening


def test_tap_far_future_stamp_toggle_off_closes():
    p = GesturePtt(PttMode.TOGGLE_TAP)
    p.tick(0.0)
    p.feed(ev(1.0, TAP))
    assert kinds(p.feed(ev(1e9, TAP))) == [STOP]


def test_max_future_s_is_validated_and_configurable():
    with pytest.raises(ValueError):
        GesturePtt(PttMode.HOLD_PINCH, max_future_s=-1.0)
    with pytest.raises(ValueError):
        GesturePtt(PttMode.HOLD_PINCH, max_future_s=float("inf"))
    p = pinch(max_future_s=1.0)
    p.tick(0.0)
    assert p.feed(ev(100.0, P_START)) == [PttAction(START, 1.0)]


# ------------------------------------------- re-press after a completed STOP


def test_repress_after_grace_expired_with_no_tick_starts_a_new_utterance():
    # Reviewer repro: START@0, END@1, START@1.14 (no tick) emitted STOP@1.12 and then
    # dropped the new START under debounce, leaving the user pinching with the mic closed.
    p = pinch()
    p.feed(ev(0.0, P_START))
    p.feed(ev(1.0, P_END))
    out = p.feed(ev(1.14, P_START))
    assert out == [PttAction(STOP, pytest.approx(1.12)), PttAction(START, 1.14)]
    assert p.is_listening


def test_repress_after_ticked_stop_starts_a_new_utterance():
    p = pinch()
    p.feed(ev(0.0, P_START))
    p.feed(ev(1.0, P_END))
    assert kinds(p.tick(1.13)) == [STOP]
    assert kinds(p.feed(ev(1.14, P_START))) == [START]


def test_chatter_after_a_zero_grace_release_is_still_debounced():
    p = pinch(debounce_s=0.2, release_grace_s=0.0)
    p.feed(ev(1.0, P_START))
    p.feed(ev(2.0, P_END))
    assert p.feed(ev(2.1, P_START)) == []
    assert kinds(p.feed(ev(2.2, P_START))) == [START]


def test_chatter_right_after_release_with_short_grace_is_debounced():
    # grace (0.02) shorter than debounce (0.2): the STOP is emitted lazily at 2.02, but
    # the press at 2.1 is only 0.1 s after the release gesture, so it is chatter.
    p = pinch(debounce_s=0.2, release_grace_s=0.02)
    p.feed(ev(1.0, P_START))
    p.feed(ev(2.0, P_END))
    assert p.feed(ev(2.1, P_START)) == [PttAction(STOP, pytest.approx(2.02))]
    assert not p.is_listening
    assert kinds(p.feed(ev(2.25, P_START))) == [START]


def test_chatter_after_hold_limit_stop_is_still_debounced():
    p = pinch(debounce_s=0.5, max_hold_s=5.0)
    p.feed(ev(1.0, P_START))
    p.tick(6.0)  # forced STOP at 6.0
    assert p.feed(ev(6.2, P_START)) == []
    assert kinds(p.feed(ev(6.6, P_START))) == [START]


def test_flicker_inside_grace_is_not_a_repress():
    p = pinch()
    p.feed(ev(0.0, P_START))
    p.feed(ev(1.0, P_END))
    assert p.feed(ev(1.05, P_START)) == []  # continuation, no STOP/START pair
    assert p.is_listening


# ------------------------------------------------- property: the clock cannot wedge

_ts = st.floats(min_value=0.0, max_value=1e15, allow_nan=False, allow_infinity=False)
_wild_step = st.one_of(
    st.tuples(st.just("event"), st.sampled_from(_KINDS), _ts, st.floats(0.0, 1.0)),
    st.tuples(st.just("tick"), st.just(None), _ts, st.just(0.0)),
)


@settings(max_examples=400, deadline=None)
@given(
    mode=st.sampled_from(list(PttMode)),
    debounce=st.sampled_from([0.0, 0.05, 0.3]),
    grace=st.sampled_from([0.0, 0.12, 1.0]),
    max_hold=st.sampled_from([0.5, 2.0, 120.0]),
    min_conf=st.sampled_from([0.0, 0.5, 1.0]),
    max_future=st.sampled_from([0.0, 5.0, 100.0]),
    armed=st.booleans(),
    steps=st.lists(_wild_step, max_size=40),
)
def test_arbitrary_timestamps_never_leave_the_mic_open(
    mode, debounce, grace, max_hold, min_conf, max_future, armed, steps
):
    p = GesturePtt(
        mode,
        debounce_s=debounce,
        release_grace_s=grace,
        max_hold_s=max_hold,
        min_confidence=min_conf,
        max_future_s=max_future,
    )
    actions: list[PttAction] = []
    seen = 0.0
    if armed:
        actions += p.tick(0.0)
    for tag, kind, t, conf in steps:
        seen = max(seen, t)
        if tag == "event":
            actions += p.feed(ev(t, kind, conf))
        else:
            actions += p.tick(t)
        assert p.is_listening == _open_after(actions)
    actions += p.tick(seen + max_hold + 1.0)
    assert not p.is_listening
    assert _legal(actions)
    assert not _open_after(actions)
