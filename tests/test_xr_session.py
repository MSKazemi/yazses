"""yazses.xr.session — the composed session: frames in, events and resolutions out."""
from __future__ import annotations

import json
import math

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from yazses.xr.binding import (
    PanelObservation,
    bind_demonstrative,
    nearest_rival,
    sustained_departure,
)
from yazses.xr.confirm import ConfirmPolicy, ConfirmReason, Evidence, decide
from yazses.xr.ptt import PttMode
from yazses.xr.raycast import nearest_hit
from yazses.xr.session import (
    ResolutionSource,
    SessionConfig,
    SessionEvent,
    SessionEventKind,
    XrSession,
)
from yazses.xr.synth import fixation, make_scenarios
from yazses.xr.types import GestureEvent, GestureKind, Panel, RaySource, Vec3, XrSample
from yazses.xr.wire import PanelGone, PanelUpdate, encode_frame

K = SessionEventKind
UP = Vec3(0.0, 1.0, 0.0)
FACE = Vec3(0.0, 0.0, 1.0)
MARKER = "ZQXMARKER7731"


def panel(pid: str, x: float, label: str = "") -> Panel:
    return Panel(pid, Vec3(x, 1.6, -2.0), FACE, UP, 1.2, 0.8, label)


A = panel("A", -1.0)
B = panel("B", 1.0)


def kinds(events: list[SessionEvent]) -> list[SessionEventKind]:
    return [e.kind for e in events]


def feed(session: XrSession, frame: object, now: float) -> list[SessionEvent]:
    return session.feed_frame(encode_frame(frame), now)  # type: ignore[arg-type]


def feed_samples(session: XrSession, samples: list[XrSample]) -> None:
    for s in samples:
        feed(session, s, s.timestamp_s)


def feed_gesture(session: XrSession, t: float, kind: GestureKind) -> list[SessionEvent]:
    return feed(session, GestureEvent(t, kind), t)


def fresh(**kw: object) -> XrSession:
    """A session with panels A and B registered at t=0 and smoothing off (exact rays)."""
    cfg = SessionConfig(**{"smooth": False, **kw})  # type: ignore[arg-type]
    s = XrSession(cfg)
    feed(s, PanelUpdate(A), 0.0)
    feed(s, PanelUpdate(B), 0.0)
    return s


# ------------------------------------------------------------------ resolve: end to end


def test_look_at_a_say_this_binds_a() -> None:
    s = fresh()
    feed_samples(s, fixation(A, 0.3, 0.7, start_s=9.0, duration_s=1.4))
    r = s.resolve_demonstrative(10.0, 10.3)
    assert r.panel_id == "A"
    assert r.source is ResolutionSource.RAY
    assert r.decision.confirm is False and r.decision.reason is ConfirmReason.NONE
    assert r.panel_at_onset == "A" and r.panel_at_end == "A"
    snap = r.snapshot
    assert snap is not None and snap.point is not None and snap.space is not None
    assert snap.point.x == pytest.approx(0.3, abs=1e-6)
    assert snap.point.y == pytest.approx(0.3, abs=1e-6)  # 1 - v
    assert snap.space.name == "xr-panel:A"


def test_binding_confidence_and_margin_feed_the_confirm_policy() -> None:
    # Weak tracking (0.33, above the binder's 0.3 floor, below confirm's 0.35) on a clean
    # bind: the binder's own confidence is what reaches decide(), so the user is asked.
    weak = fresh()
    feed_samples(weak, fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.4, confidence=0.33))
    r = weak.resolve_demonstrative(10.0, 10.3)
    assert r.panel_id == "A"
    assert r.binding.confidence == pytest.approx(0.33)
    assert r.decision.confirm is True and r.decision.reason is ConfirmReason.LOW_CONFIDENCE

    strong = fresh()
    feed_samples(strong, fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.4, confidence=0.95))
    r = strong.resolve_demonstrative(10.0, 10.3)
    assert r.binding.confidence == pytest.approx(0.95)
    assert r.decision.confirm is False


def test_one_stray_ray_does_not_bind_through_the_session() -> None:
    s = fresh()
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=10.0, duration_s=0.012, hz=90.0, confidence=0.3))
    assert 1 <= s.sample_count < 3
    r = s.resolve_demonstrative(10.0, 10.3)
    assert r.panel_id is None and r.binding.outcome.value == "none"
    assert "insufficient evidence" in r.binding.reason


def test_look_at_b_binds_b_and_pointing_at_nothing_is_no_target() -> None:
    s = fresh()
    feed_samples(s, fixation(B, 0.5, 0.5, start_s=9.0, duration_s=1.4))
    assert s.resolve_demonstrative(10.0, 10.3).panel_id == "B"

    s2 = fresh()
    from yazses.xr.types import Ray

    sky = [XrSample(9.0 + i / 90, RaySource.EYE, Ray(Vec3(0, 1.6, 0), UP), 1.0) for i in range(120)]
    feed_samples(s2, sky)
    r = s2.resolve_demonstrative(10.0, 10.2)
    assert r.panel_id is None and r.source is ResolutionSource.NONE
    assert r.decision.reason is ConfirmReason.NO_TARGET and r.snapshot is None


def _by_hand(samples: list[XrSample], panels: list[Panel], onset: float, end: float, cfg: SessionConfig):
    """The same answer from the lower modules directly (the oracle for the session)."""
    # The binder is handed every retained ray (rays just outside the window give each
    # in-window ray its held interval); it applies the window itself.
    obs = []
    for s in samples:
        hit = nearest_hit(s.ray, panels, cfg.max_ray_distance_m)
        rival = None if hit is None else nearest_rival(s.ray, hit.panel_id, panels, cfg.max_ray_distance_m)
        obs.append(PanelObservation(s.timestamp_s, hit, s.confidence, *(rival if rival else (None, None))))
    binding = bind_demonstrative(obs, onset, lead_s=cfg.lead_s, lag_s=cfg.lag_s, history_s=cfg.history_s)

    def under(t: float) -> str | None:
        near = min(samples, key=lambda s: abs(s.timestamp_s - t))
        if abs(near.timestamp_s - t) > cfg.edge_tolerance_s:
            return None
        h = nearest_hit(near.ray, panels, cfg.max_ray_distance_m)
        return h.panel_id if h else None

    evidence = Evidence()
    if binding.panel_id is not None:
        dpanel, dsec = sustained_departure(obs, binding.panel_id, onset, end)
        evidence = Evidence(
            panel_id=binding.panel_id, top_share=binding.top_share,
            runner_up=binding.candidates[1] if len(binding.candidates) > 1 else None,
            rival_id=binding.rival_id, rival_deg=binding.rival_deg, prior_panel=binding.prior_panel,
            settled_s=binding.settled_s, departure_s=dsec, departure_panel=dpanel,
        )
    decision = decide(
        outcome=binding.outcome.value, margin=binding.margin,
        confidence=binding.confidence, destructive=False,
        panel_at_onset=under(onset), panel_at_end=under(end),
        evidence=evidence,
        policy=ConfirmPolicy(error_budget_deg=cfg.error_budget_deg, settle_s=cfg.settle_s,
                             min_departure_s=cfg.min_departure_s),
    )
    return binding, decision


@pytest.mark.parametrize("noise", [0.0, 0.01])
def test_session_agrees_with_calling_the_modules_by_hand(noise: float) -> None:
    cfg = SessionConfig(smooth=False)
    bound = right = 0
    for sc in make_scenarios([A, B], 40, seed=7, noise_rad=noise):
        s = fresh()
        samples = list(sc.samples)
        feed_samples(s, samples)
        end = sc.word_onset_s + 0.3
        r = s.resolve_demonstrative(sc.word_onset_s, end)
        binding, decision = _by_hand(samples, [A, B], sc.word_onset_s, end, cfg)
        assert r.binding == binding
        assert r.panel_id == binding.panel_id
        assert r.decision == decision
        bound += r.panel_id is not None
        right += r.panel_id == sc.truth_panel_id
    assert bound >= 15 and right >= 10  # not vacuous: trials bind, and mostly to the truth


def test_gaze_moves_from_a_to_b_inside_the_lead_window_agrees_with_hand() -> None:
    cfg = SessionConfig(smooth=False)
    samples = fixation(A, 0.5, 0.5, start_s=9.8, duration_s=0.2) \
        + fixation(B, 0.5, 0.5, start_s=10.0, duration_s=0.2)
    s = fresh()
    feed_samples(s, samples)
    r = s.resolve_demonstrative(10.0, 10.2)
    binding, decision = _by_hand(samples, [A, B], 10.0, 10.2, cfg)
    assert (r.binding, r.decision) == (binding, decision)
    # 58% A vs 42% B: neither reaches the 60% share, so the session asks instead of guessing.
    assert r.panel_id is None and r.decision.reason is ConfirmReason.AMBIGUOUS_PANELS


def test_bound_to_a_but_gaze_rests_on_b_forces_confirmation_and_offers_both() -> None:
    # B is held for 0.75 s by the end of the utterance: a rested look, not a glance.
    samples = fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.05) \
        + fixation(B, 0.5, 0.5, start_s=10.05, duration_s=0.8)
    s = fresh()
    feed_samples(s, samples)
    r = s.resolve_demonstrative(10.0, 10.8)
    assert r.panel_id == "A"
    assert r.panel_at_onset == "A" and r.panel_at_end == "B"
    assert r.decision.confirm and r.decision.reason is ConfirmReason.TARGET_CHANGED_DURING_UTTERANCE
    assert r.decision.candidates == ("A", "B")


def test_a_short_glance_at_b_after_the_word_is_not_a_changed_target() -> None:
    # Regression for the redesign: the old policy compared two instants and prompted here
    # (0.35 s on B at the end). A glance shorter than min_departure_s no longer holds.
    samples = fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.05) \
        + fixation(B, 0.5, 0.5, start_s=10.05, duration_s=0.35)
    s = fresh()
    feed_samples(s, samples)
    r = s.resolve_demonstrative(10.0, 10.4)
    assert r.panel_id == "A" and r.panel_at_end == "B"
    assert r.decision.confirm is False and r.decision.reason is ConfirmReason.NONE


def test_min_departure_is_configurable_and_zero_departure_never_holds() -> None:
    samples = fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.05) \
        + fixation(B, 0.5, 0.5, start_s=10.05, duration_s=0.35)
    s = fresh(min_departure_s=0.2)
    feed_samples(s, samples)
    assert s.resolve_demonstrative(10.0, 10.4).decision.reason is ConfirmReason.TARGET_CHANGED_DURING_UTTERANCE
    stay = fresh(min_departure_s=0.0)
    feed_samples(stay, fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.6))
    assert stay.resolve_demonstrative(10.0, 10.4).decision.confirm is False


# ----------------------------------------------------- the evidence rules, end to end

L = Panel("L", Vec3(-0.6, 1.6, -2.0), FACE, UP, 1.2, 0.8)
R = Panel("R", Vec3(0.6, 1.6, -2.0), FACE, UP, 1.2, 0.8)       # abuts L at x = 0


def abutting(**kw: object) -> XrSession:
    s = XrSession(SessionConfig(**{"smooth": False, **kw}))  # type: ignore[arg-type]
    feed(s, PanelUpdate(L), 0.0)
    feed(s, PanelUpdate(R), 0.0)
    return s


def test_a_ray_near_the_seam_of_abutting_panels_holds_and_offers_the_neighbour() -> None:
    s = abutting()
    # x = 0.08 m on R: atan(0.08 / 2) = 2.3 degrees from L, inside the 3 degree budget.
    feed_samples(s, fixation(R, 0.08 / 1.2, 0.5, start_s=9.0, duration_s=1.4))
    r = s.resolve_demonstrative(10.0, 10.3)
    assert r.panel_id == "R"                       # the verdict is unchanged
    assert r.binding.rival_id == "L" and r.binding.rival_deg == pytest.approx(2.29, abs=0.05)
    assert r.decision.confirm and r.decision.reason is ConfirmReason.NEAR_PANEL_EDGE
    assert r.decision.candidates == ("R", "L")


def test_a_ray_well_inside_abutting_panels_is_silent() -> None:
    s = abutting()
    feed_samples(s, fixation(R, 0.5, 0.5, start_s=9.0, duration_s=1.4))     # 0.6 m = 16.7 degrees from the seam
    r = s.resolve_demonstrative(10.0, 10.3)
    assert r.panel_id == "R" and r.decision.confirm is False


def test_the_error_budget_is_configurable_and_zero_turns_the_rule_off() -> None:
    samples = fixation(R, 0.08 / 1.2, 0.5, start_s=9.0, duration_s=1.4)
    tight = abutting(error_budget_deg=2.0)
    feed_samples(tight, samples)
    assert tight.resolve_demonstrative(10.0, 10.3).decision.confirm is False
    off = abutting(error_budget_deg=0.0)
    feed_samples(off, samples)
    assert off.resolve_demonstrative(10.0, 10.3).decision.confirm is False


def test_panels_farther_apart_than_the_budget_never_trigger_the_edge_rule() -> None:
    s = fresh()                                    # A and B are 22 degrees apart
    feed_samples(s, fixation(A, 0.97, 0.5, start_s=9.0, duration_s=1.4))    # at A's far edge, 3 degrees from nothing
    r = s.resolve_demonstrative(10.0, 10.3)
    assert r.panel_id == "A" and r.decision.confirm is False


def test_a_gaze_that_just_arrived_from_another_panel_holds_and_offers_both() -> None:
    s = fresh()
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=8.5, duration_s=1.25)
                 + fixation(B, 0.5, 0.5, start_s=9.75, duration_s=1.0))
    r = s.resolve_demonstrative(10.0, 10.3)
    assert r.panel_id == "B" and r.binding.prior_panel == "A"
    assert r.decision.confirm and r.decision.reason is ConfirmReason.RECENT_PANEL_SWITCH
    assert r.decision.candidates == ("B", "A")


def test_a_settled_gaze_after_a_switch_is_silent() -> None:
    s = fresh()
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=8.5, duration_s=0.9)
                 + fixation(B, 0.5, 0.5, start_s=9.4, duration_s=1.2))
    r = s.resolve_demonstrative(10.0, 10.3)
    assert r.panel_id == "B" and r.binding.settled_s is not None and r.binding.settled_s > 0.3
    assert r.decision.confirm is False


def test_settle_zero_turns_the_switch_rule_off() -> None:
    s = fresh(settle_s=0.0)
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=8.5, duration_s=1.25)
                 + fixation(B, 0.5, 0.5, start_s=9.75, duration_s=1.0))
    assert s.resolve_demonstrative(10.0, 10.3).decision.confirm is False


def test_look_then_look_away_before_the_word_prompts_instead_of_binding_silently() -> None:
    # The user fixates A, glances over to B, and says "this" with the gaze just arrived on B.
    # The pre-redesign policy bound B without a word; now the user is offered A or B.
    s = fresh()
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=9.0, duration_s=0.78)
                 + fixation(B, 0.5, 0.5, start_s=9.78, duration_s=0.8))
    r = s.resolve_demonstrative(10.0, 10.3)
    assert r.panel_id in ("B", None)
    assert r.decision.confirm is True
    assert set(r.decision.candidates) <= {"A", "B"} and r.decision.candidates


@pytest.mark.parametrize("bad", [{"error_budget_deg": -1.0}, {"settle_s": -0.1}, {"min_departure_s": -1.0},
                                 {"history_s": 0.0}, {"history_s": float("nan")}, {"settle_s": float("inf")}])
def test_new_config_fields_are_validated(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        SessionConfig(**bad)  # type: ignore[arg-type]



def test_destructive_ray_target_confirms() -> None:
    s = fresh()
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.4))
    r = s.resolve_demonstrative(10.0, 10.3, destructive=True)
    assert r.panel_id == "A" and r.decision.reason is ConfirmReason.DESTRUCTIVE_ACTION


def test_primary_source_ignores_other_rays() -> None:
    eye = fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.4, source=RaySource.EYE)
    hand = fixation(B, 0.5, 0.5, start_s=9.0, duration_s=1.4, source=RaySource.HAND)
    s = fresh(primary_source=RaySource.EYE)
    feed_samples(s, sorted(eye + hand, key=lambda x: x.timestamp_s))
    assert s.resolve_demonstrative(10.0, 10.3).panel_id == "A"


def test_smoothing_on_still_binds_a_noisy_fixation() -> None:
    s = XrSession()
    feed(s, PanelUpdate(A), 0.0)
    feed(s, PanelUpdate(B), 0.0)
    feed_samples(s, fixation(B, 0.5, 0.5, start_s=9.0, duration_s=1.4, noise_rad=0.01, seed=3))
    assert s.resolve_demonstrative(10.0, 10.3).panel_id == "B"


def test_resolve_is_deterministic_and_changes_nothing() -> None:
    s = fresh()
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.4))
    n = s.sample_count
    assert s.resolve_demonstrative(10.0, 10.3) == s.resolve_demonstrative(10.0, 10.3)
    assert s.sample_count == n


def test_resolve_before_any_data_is_no_target() -> None:
    r = XrSession().resolve_demonstrative(1.0, 2.0)
    assert r.panel_id is None and r.decision.reason is ConfirmReason.NO_TARGET


@pytest.mark.parametrize("args", [(float("nan"), 1.0), (1.0, float("inf")), (-1.0, 1.0), (2.0, 1.0)])
def test_resolve_refuses_bad_times(args: tuple[float, float]) -> None:
    with pytest.raises(ValueError):
        XrSession().resolve_demonstrative(*args)


# ------------------------------------------------------------------------------ pinning


def test_pinned_target_wins_over_the_rays_and_needs_no_confirmation() -> None:
    s = fresh()
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.4))
    s.pin_panel("B")
    assert s.pinned() == "B"
    r = s.resolve_demonstrative(10.0, 10.3, destructive=True)
    assert r.panel_id == "B" and r.source is ResolutionSource.PINNED
    assert r.decision.confirm is False
    assert r.binding.panel_id == "A"  # the ray evidence is still reported
    s.unpin()
    assert s.resolve_demonstrative(10.0, 10.3).panel_id == "A"


def test_pin_expires_and_never_dangles() -> None:
    s = fresh(pin_ttl_s=5.0)
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.4))
    s.pin_panel("B", now_s=0.0)
    assert s.pinned() is None  # session time is already 10.4: the 5 s pin lapsed

    s2 = fresh()
    s2.pin_panel("B")
    feed(s2, PanelGone("B"), 1.0)
    assert s2.pinned() is None


def test_pin_of_unknown_or_stale_panel_is_refused() -> None:
    with pytest.raises(KeyError):
        XrSession().pin_panel("A")
    s = fresh()
    with pytest.raises(KeyError):
        s.pin_panel("nope")
    s.tick(100.0)  # both panels are long stale
    with pytest.raises(KeyError):
        s.pin_panel("A")


# ------------------------------------------------------------------------------ push to talk


def test_pinch_start_and_end_produce_start_then_stop() -> None:
    s = XrSession()
    assert kinds(feed_gesture(s, 1.0, GestureKind.PINCH_START)) == [K.PTT_START]
    assert s.is_listening
    assert feed_gesture(s, 2.0, GestureKind.PINCH_END) == []  # grace still running
    ev = s.tick(2.5)
    assert kinds(ev) == [K.PTT_STOP] and ev[0].timestamp_s == pytest.approx(2.12)
    assert not s.is_listening


def test_stuck_gesture_closes_the_mic_through_tick() -> None:
    s = XrSession(SessionConfig(max_hold_s=30.0))
    feed_gesture(s, 1.0, GestureKind.PINCH_START)
    assert s.tick(20.0) == [] and s.is_listening
    ev = s.tick(40.0)
    assert kinds(ev) == [K.PTT_STOP] and ev[0].timestamp_s == pytest.approx(31.0)
    assert not s.is_listening
    assert s.tick(41.0) == []


def test_chatter_is_cancelled_and_squeeze_mode_ignores_pinch() -> None:
    s = XrSession()
    feed_gesture(s, 1.0, GestureKind.PINCH_START)
    assert kinds(feed_gesture(s, 1.01, GestureKind.PINCH_END)) == [K.PTT_CANCEL]
    sq = XrSession(SessionConfig(ptt_mode=PttMode.HOLD_SQUEEZE))
    assert feed_gesture(sq, 1.0, GestureKind.PINCH_START) == []
    assert kinds(feed_gesture(sq, 2.0, GestureKind.SQUEEZE_START)) == [K.PTT_START]


def test_reset_cancels_a_live_utterance_and_reports_panels_gone() -> None:
    s = fresh()
    feed_gesture(s, 1.0, GestureKind.PINCH_START)
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=1.0, duration_s=0.5))
    ev = s.reset()
    assert K.PTT_CANCEL in kinds(ev)
    assert sorted(e.panel_id for e in ev if e.kind is K.PANEL_REMOVED) == ["A", "B"]
    assert not s.is_listening and s.sample_count == 0 and s.panels() == ()
    assert s.stats.frames_accepted == 0


# ------------------------------------------------------------------------------- panels


def test_panel_lifecycle_events() -> None:
    s = XrSession()
    ev = feed(s, PanelUpdate(A), 1.0)
    assert [(e.kind, e.panel_id) for e in ev] == [(K.PANEL_ADDED, "A")]
    assert feed(s, PanelUpdate(A), 2.0) == []  # a refresh is silent
    moved = panel("A", -0.5)
    assert feed(s, PanelUpdate(moved), 3.0) == []
    assert s.panels() == (moved,)
    ev = feed(s, PanelGone("A"), 4.0)
    assert [(e.kind, e.panel_id) for e in ev] == [(K.PANEL_REMOVED, "A")]
    assert feed(s, PanelGone("A"), 5.0) == []


def test_stale_panels_expire_on_tick_and_refresh_keeps_them() -> None:
    s = XrSession(SessionConfig(panel_stale_after_s=10.0))
    feed(s, PanelUpdate(A), 0.0)
    feed(s, PanelUpdate(B), 0.0)
    feed(s, PanelUpdate(B), 8.0)
    ev = s.tick(12.0)
    assert [(e.kind, e.panel_id) for e in ev] == [(K.PANEL_REMOVED, "A")]
    assert [p.panel_id for p in s.panels()] == ["B"]


def test_panel_flood_is_capped_and_reports_evictions() -> None:
    s = XrSession(SessionConfig(max_panels=4))
    removed = 0
    for i in range(200):
        ev = feed(s, PanelUpdate(panel(f"p{i}", i * 0.01)), float(i))
        removed += sum(e.kind is K.PANEL_REMOVED for e in ev)
        assert len(s.panels()) <= 4
    assert removed == 196


def test_moving_a_panel_changes_the_snapshot_space_version() -> None:
    s = fresh()
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.4))
    first = s.resolve_demonstrative(10.0, 10.3).snapshot
    feed(s, PanelUpdate(panel("A", -1.0, label="same geometry, new label")), 10.4)
    second = s.resolve_demonstrative(10.0, 10.3).snapshot
    assert first is not None and second is not None
    assert first.space is not None and second.space is not None
    assert second.space.version > first.space.version
    # An unchanged refresh keeps the version.
    feed(s, PanelUpdate(panel("A", -1.0, label="same geometry, new label")), 10.5)
    third = s.resolve_demonstrative(10.0, 10.3).snapshot
    assert third is not None and third.space == second.space


# ------------------------------------------------------------------------- retention


def test_retention_count_and_age_limits_hold() -> None:
    s = XrSession(SessionConfig(retention_max_samples=50, retention_window_s=2.0, smooth=False))
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=0.0, duration_s=10.0, hz=90.0))
    assert s.sample_count <= 50

    s2 = XrSession(SessionConfig(retention_window_s=2.0, smooth=False))
    feed_samples(s2, fixation(A, 0.5, 0.5, start_s=0.0, duration_s=10.0, hz=90.0))
    assert s2.sample_count <= 2.0 * 90 + 1
    s2.tick(1000.0)
    assert s2.sample_count == 0


def test_old_rays_are_gone_so_a_late_resolve_finds_nothing() -> None:
    s = fresh(retention_window_s=2.0)
    feed(s, PanelUpdate(A), 99.0)
    feed_samples(s, fixation(A, 0.5, 0.5, start_s=9.0, duration_s=1.0))
    s.tick(50.0)
    feed(s, PanelUpdate(A), 50.0)
    assert s.resolve_demonstrative(9.5, 9.8).panel_id is None


# ------------------------------------------------------- hostile companion: rejection


def test_malformed_frame_is_an_event_not_an_exception() -> None:
    s = XrSession()
    ev = s.feed_frame(b"not json at all", 1.0)
    assert kinds(ev) == [K.FRAME_REJECTED] and ev[0].detail == "invalid JSON"
    assert s.stats.frames_rejected == 1 and s.stats.consecutive_rejections == 1
    assert feed(s, PanelUpdate(A), 2.0) != [] and s.stats.consecutive_rejections == 0


def test_flood_of_garbage_is_bounded() -> None:
    s = XrSession()
    out: list[SessionEvent] = []
    for _ in range(5000):
        out += s.feed_frame(b"\xff\xfegarbage", 100.0)
    rejected = [e for e in out if e.kind is K.FRAME_REJECTED]
    assert len(rejected) <= 5  # the per-window cap
    assert [e.kind for e in out].count(K.COMPANION_MISBEHAVING) == 1  # one, then silence
    assert s.stats.frames_rejected == 5000 and s.stats.events_suppressed >= 4900
    # Still silent a moment later, speaks again after the interval.
    assert s.feed_frame(b"x", 105.0) == []
    again = s.feed_frame(b"x", 111.0)
    assert kinds(again) == [K.COMPANION_MISBEHAVING]


def test_misbehaving_fires_at_the_threshold_and_a_good_frame_resets_the_count() -> None:
    s = XrSession(SessionConfig(misbehave_after=3, reject_events_per_window=100))
    assert kinds(s.feed_frame(b"x", 1.0)) == [K.FRAME_REJECTED]
    assert kinds(s.feed_frame(b"x", 1.1)) == [K.FRAME_REJECTED]
    feed(s, PanelUpdate(A), 1.2)  # good frame resets the run
    assert kinds(s.feed_frame(b"x", 1.3)) == [K.FRAME_REJECTED]
    assert kinds(s.feed_frame(b"x", 1.4)) == [K.FRAME_REJECTED]
    assert kinds(s.feed_frame(b"x", 1.5)) == [K.COMPANION_MISBEHAVING]


def test_alternating_good_and_bad_frames_still_cannot_flood_events() -> None:
    s = XrSession()
    n = 0
    for i in range(2000):
        n += len(s.feed_frame(b"bad", 50.0))
        feed(s, PanelUpdate(A), 50.0)
    assert n <= 5


def test_oversized_frame_and_wrong_type_are_rejected() -> None:
    s = XrSession(SessionConfig(max_frame_bytes=100))
    assert s.feed_frame(b"{" + b" " * 500 + b"}", 1.0)[0].detail == "frame too large"
    assert s.feed_frame(12345, 2.0)[0].kind is K.FRAME_REJECTED  # type: ignore[arg-type]


HOSTILE = [
    f'{{"v":1,"t":"{MARKER}"}}',
    f'{{"v":["{MARKER}"],"t":"sample"}}',
    f'{{"v":"{MARKER}","t":"sample"}}',
    f'{{"v":1,"t":"sample","{MARKER}":1}}',
    f'{{"v":1,"t":"gesture","device_time_s":1,"kind":"{MARKER}","confidence":1}}',
    f'{{"v":1,"t":"sample","device_time_s":1,"source":"{MARKER}","origin":[0,0,0],'
    f'"direction":[0,0,-1],"confidence":1}}',
    f'{{"v":1,"t":"sample","t":"{MARKER}"}}',
    f'{{"v":1,"t":"panel_gone","panel_id":"{MARKER}\\u0007"}}',
    f'{{"v":1,"t":"gesture","device_time_s":"{MARKER}","kind":"tap","confidence":1}}',
    f'{{"v":1,"t":"sample","device_time_s":1,"source":"eye","origin":["{MARKER}",0,0],'
    f'"direction":[0,0,-1],"confidence":1}}',
    f'{{"v":1,"t":"panel","panel_id":"p","center":[0,0,0],"normal":[0,0,1],"up":[0,1,0],'
    f'"width":1,"height":1,"label":"{MARKER}\\u0000"}}',
    f"{MARKER} {{{{",
    f"[[[[{MARKER}",
    f'{{"v":1,"t":"sample","device_time_s":NaN,"{MARKER}":1}}',
]


@pytest.mark.parametrize("payload", HOSTILE)
def test_rejected_frame_event_never_carries_payload_text(payload: str) -> None:
    s = XrSession()
    ev = s.feed_frame(payload, 1.0) + s.feed_frame(payload.encode(), 1.1)
    assert ev, "the hostile frame must be reported, not silently dropped"
    assert all(e.kind is K.FRAME_REJECTED for e in ev)
    for e in ev:
        assert MARKER not in repr(e)
    assert MARKER not in repr(s.stats)


def test_misbehaving_event_never_carries_payload_text() -> None:
    s = XrSession(SessionConfig(misbehave_after=2))
    ev = [e for p in HOSTILE[:4] for e in s.feed_frame(p, 1.0)]
    assert any(e.kind is K.COMPANION_MISBEHAVING for e in ev)
    assert all(MARKER not in repr(e) for e in ev)


def test_clock_jump_is_a_rejection_until_reset() -> None:
    s = XrSession()
    feed_gesture(s, 1.0, GestureKind.PINCH_START)
    ev = s.feed_frame(encode_frame(GestureEvent(500.0, GestureKind.PINCH_END)), 2.0)
    assert kinds(ev) == [K.FRAME_REJECTED] and ev[0].detail == "device clock jumped"
    assert s.is_listening  # the forged end did not close the utterance
    s.reset()
    assert kinds(feed_gesture(s, 500.0, GestureKind.PINCH_START)) == [K.PTT_START]


def test_bad_host_clock_is_a_host_bug() -> None:
    s = XrSession()
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            s.feed_frame(b"{}", bad)
        with pytest.raises(ValueError):
            s.tick(bad)


@pytest.mark.parametrize(
    "kwargs",
    [{"max_panels": 0}, {"retention_window_s": 0.0}, {"retention_max_samples": -1},
     {"lead_s": -1.0}, {"misbehave_after": 0}, {"max_frame_bytes": 0},
     {"ptt_mode": "pinch"}, {"primary_source": "eye"}, {"pin_ttl_s": float("nan")}],
)
def test_bad_config_refused(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SessionConfig(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- hypothesis


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    chunks=st.lists(st.one_of(st.binary(max_size=300), st.text(max_size=300)), max_size=12),
    start=st.floats(min_value=0, max_value=1e6, allow_nan=False),
)
def test_session_never_raises_on_arbitrary_bytes_or_text(chunks: list[bytes | str], start: float) -> None:
    s = XrSession(SessionConfig(max_panels=4, retention_max_samples=8))
    t = start
    for c in chunks:
        t += 0.01
        ev = s.feed_frame(c, t)
        assert isinstance(ev, list) and all(isinstance(e, SessionEvent) for e in ev)
        assert all(len(e.detail) <= 120 for e in ev)
        s.tick(t)
    assert len(s.panels()) <= 4 and s.sample_count <= 8
    s.resolve_demonstrative(0.0, 1.0)


_num = st.one_of(
    st.floats(allow_nan=True, allow_infinity=True), st.integers(-10**30, 10**30),
    st.text(max_size=8), st.booleans(), st.none(),
)
_val = st.recursive(_num, lambda c: st.one_of(st.lists(c, max_size=4),
                                              st.dictionaries(st.text(max_size=6), c, max_size=4)), max_leaves=4)
_frame_types = st.sampled_from(["sample", "gesture", "panel", "panel_gone", "x"])


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(
    frames=st.lists(
        st.fixed_dictionaries(
            {"v": st.sampled_from([1, 1, 2, "1"]), "t": _frame_types},
            optional={k: _val for k in ("device_time_s", "source", "origin", "direction", "confidence",
                                        "kind", "panel_id", "center", "normal", "up", "width",
                                        "height", "label")},
        ),
        max_size=10,
    ),
)
def test_session_never_raises_on_structured_junk(frames: list[dict[str, object]]) -> None:
    s = XrSession(SessionConfig(max_panels=3, retention_max_samples=8))
    for i, f in enumerate(frames):
        try:
            text = json.dumps(f)
        except (ValueError, TypeError):
            continue
        s.feed_frame(text, 1.0 + i * 0.01)
    assert len(s.panels()) <= 3 and s.sample_count <= 8
    assert math.isfinite(s.stats.frames_rejected)


_VALID = [
    encode_frame(XrSample(1.0, RaySource.EYE, fixation(A, 0.5, 0.5, start_s=1.0, duration_s=0.02)[0].ray, 0.9)),
    encode_frame(GestureEvent(1.0, GestureKind.PINCH_START)),
    encode_frame(PanelUpdate(A)),
    encode_frame(PanelGone("A")),
]


@settings(max_examples=300, deadline=None)
@given(
    which=st.integers(0, len(_VALID) - 1),
    edits=st.lists(st.tuples(st.integers(0, 400), st.integers(0, 255)), max_size=4),
    cut=st.one_of(st.none(), st.integers(0, 400)),
)
def test_session_survives_mutated_valid_frames(which: int, edits: list[tuple[int, int]], cut: int | None) -> None:
    raw = bytearray(_VALID[which])
    for pos, byte in edits:
        if pos < len(raw):
            raw[pos] = byte
    data = bytes(raw if cut is None else raw[:cut])
    s = XrSession()
    feed(s, PanelUpdate(A), 0.5)
    ev = s.feed_frame(data, 1.0)
    assert all(isinstance(e, SessionEvent) for e in ev)
    s.tick(2.0)
    s.resolve_demonstrative(1.0, 1.5)
