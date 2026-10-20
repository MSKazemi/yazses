"""The delivery proof: every way typing can "succeed" while the text goes nowhere.

The 2026-10-04 incident is the first case: the sender was healthy, the probe held focus,
and nothing arrived. A check that cannot tell that from success is the check that missed it.
"""
from __future__ import annotations

import pytest

from yazses.system.typing_canary import (
    DELIVERED,
    GARBLED,
    INCONCLUSIVE,
    NOT_DELIVERED,
    Delivery,
    prove_delivery,
    prove_with_heal,
)


class FakeProbe:
    def __init__(self, *, focused=True, arrives=None):
        self.focused = focused
        self.arrives = arrives  # what the window ends up holding after typing
        self.typed = False
        self.closed = False

    def wait_focused(self, timeout):
        return self.focused

    def wait_text(self, expected, timeout):
        return self.arrives if self.typed and self.arrives is not None else ""

    def close(self):
        self.closed = True


def _run(probe, text="hello world", type_text=None):
    def typer(t):
        probe.typed = True
        if type_text:
            type_text(t)

    return prove_delivery(text, open_probe=lambda: probe, type_text=typer)


def test_text_that_arrives_intact_is_delivered():
    probe = FakeProbe(arrives="hello world")
    result = _run(probe)
    assert result.verdict == DELIVERED and result.ok
    assert probe.closed


def test_focused_probe_and_nothing_arrives_is_NOT_delivered_never_ok():
    # The overlay-swallowed-it case: sender fine, window focused, nothing arrived.
    probe = FakeProbe(arrives="")
    result = _run(probe)
    assert result.verdict == NOT_DELIVERED
    assert not result.ok
    assert probe.closed


def test_partial_or_remapped_text_is_garbled_and_names_both_strings():
    probe = FakeProbe(arrives="hllo wrld")
    result = _run(probe)
    assert result.verdict == GARBLED and not result.ok
    assert "hello world" in result.detail and "hllo wrld" in result.detail


def test_a_probe_that_never_gets_focus_is_inconclusive_and_types_nothing():
    probe = FakeProbe(focused=False, arrives="hello world")
    typed: list[str] = []
    result = _run(probe, type_text=typed.append)
    assert result.verdict == INCONCLUSIVE and not result.ok
    assert typed == [], "typing into a window that is not focused would land in the user's app"
    assert probe.closed


def test_a_probe_that_cannot_open_is_inconclusive_not_a_crash():
    def boom():
        raise RuntimeError("no display")

    result = prove_delivery("x", open_probe=boom, type_text=lambda t: None)
    assert result.verdict == INCONCLUSIVE and "no display" in result.detail


def test_an_injector_that_raises_is_not_delivered_and_still_closes_the_probe():
    probe = FakeProbe(arrives="x")

    def bad(_t):
        raise OSError("socket gone")

    result = _run(probe, type_text=bad)
    assert result.verdict == NOT_DELIVERED and "socket gone" in result.detail
    assert probe.closed


# --- heal --------------------------------------------------------------------------


def _attempts(*verdicts):
    it = iter(verdicts)
    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        v = next(it)
        return Delivery(v, f"attempt-{calls['n']}", "")

    return attempt, calls


def test_a_delivered_first_try_never_heals():
    attempt, calls = _attempts(DELIVERED)
    healed: list[int] = []
    result = prove_with_heal(attempt, lambda: healed.append(1) or "did a thing")
    assert result.ok and calls["n"] == 1 and healed == []


@pytest.mark.parametrize("verdict", [GARBLED, INCONCLUSIVE])
def test_only_not_delivered_is_healed(verdict):
    # A layout mismatch is not fixed by restarting the sender; an unfocused probe says
    # nothing about the sender at all.
    attempt, calls = _attempts(verdict)
    result = prove_with_heal(attempt, lambda: pytest.fail("must not heal"))
    assert result.verdict == verdict and calls["n"] == 1


def test_not_delivered_then_healed_then_delivered_reports_what_was_done():
    attempt, calls = _attempts(NOT_DELIVERED, DELIVERED)
    result = prove_with_heal(attempt, lambda: "restarted the ydotoold user service")
    assert result.ok and calls["n"] == 2
    assert result.healed == "restarted the ydotoold user service"
    assert "after healing" in result.detail


def test_heal_that_does_not_help_stays_not_delivered_and_is_tried_once():
    attempt, calls = _attempts(NOT_DELIVERED, NOT_DELIVERED)
    n = {"heals": 0}

    def heal():
        n["heals"] += 1
        return "restarted"

    result = prove_with_heal(attempt, heal)
    assert result.verdict == NOT_DELIVERED and not result.ok
    assert calls["n"] == 2 and n["heals"] == 1, "one heal, one retry — no loop that hides a fault"
    assert "did not fix it" in result.detail


def test_nothing_to_heal_leaves_the_first_verdict_untouched():
    attempt, calls = _attempts(NOT_DELIVERED)
    result = prove_with_heal(attempt, lambda: None)
    assert result.verdict == NOT_DELIVERED and calls["n"] == 1


def test_no_healer_at_all_leaves_the_first_verdict_untouched():
    attempt, calls = _attempts(NOT_DELIVERED)
    assert prove_with_heal(attempt, None).verdict == NOT_DELIVERED and calls["n"] == 1


def test_a_failing_heal_does_not_mask_the_finding():
    attempt, calls = _attempts(NOT_DELIVERED)

    def heal():
        raise RuntimeError("systemctl failed")

    result = prove_with_heal(attempt, heal)
    assert result.verdict == NOT_DELIVERED and "systemctl failed" in result.detail
    assert calls["n"] == 1
