"""The recovery hierarchy as a rule (roadmap Phase 6, ADR-v2-148) -- and its one live wiring.

    1. the high-confidence preferred signal;
    2. a lower-risk alternate modality;
    3. the focused / current target;
    4. an explicit "cannot act".

"Never silently switch from a failed gaze route to a destructive action on another window."
The pure rule is tested on fabricated signals; the wiring is tested where that sentence used to
be false: `Daemon._try_deixis`, which ran "close this" on the focused window whenever gaze had
not chosen one (ADR-v2-010's frictionless fallback). That behaviour is kept for installs that did
not ask for the hands-free floor, and refused for the ones that did.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from yazses.activation.confirm import Consequence
from yazses.config import Config, GazeConfig
from yazses.gaze.route import RouteDecision
from yazses.handsfree.recovery import Route, Signal, recover
from yazses.platform import get_platform

GOOD = Signal("gaze", "browser", usable=True)
FAILED = Signal("gaze", None, usable=False)
REV, IRREV = Consequence.REVERSIBLE, Consequence.IRREVERSIBLE


# --------------------------------------------------------------------------- the rule


def test_the_preferred_signal_wins_when_it_is_usable():
    r = recover(REV, GOOD, [Signal("voice", "editor", usable=True, explicit=True)], focused="term")
    assert (r.route, r.target, r.degraded, r.feedback) == (Route.PREFERRED, "browser", False, "")


def test_a_usable_signal_without_a_target_is_not_usable():
    r = recover(REV, Signal("gaze", None, usable=True), focused="term")
    assert r.route is Route.FOCUSED


def test_the_alternate_modality_comes_before_the_focused_target():
    r = recover(REV, FAILED, [Signal("pointer", "editor", usable=True)], focused="term")
    assert (r.route, r.target) == (Route.ALTERNATE, "editor")
    assert r.degraded and "gaze" in r.feedback and "pointer" in r.feedback


def test_alternates_are_tried_in_order_and_unusable_ones_skipped():
    alts = [Signal("pointer", "a", usable=False), Signal("voice", "b", usable=True)]
    assert recover(REV, FAILED, alts).target == "b"


def test_a_reversible_action_may_fall_back_to_the_focused_target_and_says_so():
    r = recover(REV, FAILED, focused="term")
    assert (r.route, r.target, r.degraded) == (Route.FOCUSED, "term", True)
    assert r.feedback


def test_a_destructive_action_never_falls_back_to_the_focused_target():
    r = recover(IRREV, FAILED, focused="term")
    assert r.route is Route.NONE and not r.acts and r.target is None


def test_a_destructive_action_does_not_use_an_inferred_alternate():
    # Only a target the user named or pointed at is a choice they made.
    r = recover(IRREV, FAILED, [Signal("recent window", "editor", usable=True)], focused="term")
    assert r.route is Route.NONE


def test_a_destructive_action_may_use_an_explicit_alternate_and_still_confirms():
    r = recover(IRREV, FAILED, [Signal("voice", "editor", usable=True, explicit=True)], focused="term")
    assert (r.route, r.target) == (Route.ALTERNATE, "editor")
    assert r.requires_confirmation and r.degraded and r.feedback


def test_a_destructive_action_on_the_preferred_route_still_confirms():
    assert recover(IRREV, GOOD).requires_confirmation is True
    assert recover(REV, GOOD).requires_confirmation is False


def test_cannot_act_is_an_explicit_message_not_silence():
    for consequence in (REV, IRREV):
        r = recover(consequence, FAILED, focused=None if consequence is REV else "term")
        assert r.route is Route.NONE
        assert r.feedback and "nothing was done" in r.feedback
    assert "cannot be undone" in recover(IRREV, FAILED).feedback


def test_every_degraded_result_carries_feedback():
    cases = [
        recover(REV, FAILED, [Signal("v", "x", usable=True)]),
        recover(REV, FAILED, focused="t"),
        recover(IRREV, FAILED),
        recover(REV, FAILED),
    ]
    assert all(c.degraded and c.feedback for c in cases)


def test_recovery_is_total_on_odd_input():
    recover(REV, Signal("", None), [], None)
    recover(IRREV, Signal("", None), (), None)


# --------------------------------------------------------------------------- the wiring


class _Targeter:
    def __init__(self, decision):
        self.last_decision = decision
        self.actions = []

    def window_action(self, action, target):
        self.actions.append((action, target))
        return True


def _daemon(**gaze):
    from yazses.core.daemon import Daemon

    cfg = replace(Config(), gaze=replace(GazeConfig(), enabled=True, deixis=True, **gaze))
    return Daemon(config=cfg, platform=get_platform())


FALLBACK = RouteDecision(target="editor", used_gaze=False, confident=False)
ROUTED = RouteDecision(target="browser", used_gaze=True, confident=True)


def test_with_the_floor_on_close_this_after_a_failed_gaze_route_closes_nothing(mocker):
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(refuse_destructive_fallback=True)
    d._gaze_targeter = _Targeter(FALLBACK)
    event: dict = {}
    assert d._try_deixis("close this", event) is True, "consumed, so it is not typed literally"
    assert d._gaze_targeter.actions == []
    assert event["discard_reason"] == "deixis_gaze_unavailable"
    assert notify.called, "the refusal must be told to the user, not only logged"
    assert "nothing was done" in notify.call_args.args[1]


def test_with_the_floor_on_close_this_with_no_target_at_all_is_also_announced(mocker):
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(refuse_destructive_fallback=True)
    d._gaze_targeter = _Targeter(RouteDecision(None, False, False))
    assert d._try_deixis("close this", {}) is True
    assert d._gaze_targeter.actions == [] and notify.called


def test_with_the_floor_on_a_gaze_routed_close_still_goes_through_the_confirmation(mocker):
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(refuse_destructive_fallback=True)
    d._gaze_targeter = _Targeter(ROUTED)
    assert d._try_deixis("close this", {})
    assert d._gaze_targeter.actions == [] and notify.called  # waiting on the confirm toast
    assert "looked at" in notify.call_args.args[0]


@pytest.mark.parametrize("phrase,action", [("focus this", "focus"), ("minimize this", "minimize")])
def test_with_the_floor_on_non_destructive_deixis_still_falls_back_to_the_focused_window(phrase, action):
    d = _daemon(refuse_destructive_fallback=True)
    d._gaze_targeter = _Targeter(FALLBACK)
    assert d._try_deixis(phrase, {})
    assert d._gaze_targeter.actions == [(action, "editor")]


def test_with_the_floor_off_the_adr_010_behaviour_is_unchanged():
    d = _daemon()
    assert d._config.gaze.refuse_destructive_fallback is False
    d._gaze_targeter = _Targeter(FALLBACK)
    assert d._try_deixis("close this", {})
    assert d._gaze_targeter.actions == [("close", "editor")]
