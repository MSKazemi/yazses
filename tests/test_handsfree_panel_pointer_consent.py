"""The hands-free controls window while the pointer is waiting for the desktop's permission.

The window lists the Head-Pointer and its Pointer output. With a Wayland pointer there is a
period when both are true at once: the pointer is built and the camera is tracking, and the
desktop has not been answered. That has to read as "needs your attention, here is what to do",
not as "connected" and not as a generic fault. Pure view-model; no Qt, no daemon, no socket.
"""
from __future__ import annotations

import pytest

from tests.test_handsfree_panel import _hp, _inputs, _safety
from yazses.handsfree.panel import build_panel
from yazses.handsfree.safety import SafetyState


def _rows(**hp):
    model = build_panel(
        _inputs(safety=_safety(SafetyState.ACTIVE), headpointer=True, hp=_hp(**{"backend": "portal", **hp}))
    )
    return {r.label: r for r in model.health}


def test_a_pointer_waiting_for_consent_needs_attention_and_says_what_to_do():
    rows = _rows(
        state="pending_consent", consent="pending_consent",
        consent_reason="waiting for you to answer the desktop's Remote Desktop permission dialog",
    )

    assert rows["Head-Pointer"].status == "attention"
    assert "pending_consent" in rows["Head-Pointer"].text
    assert "permission dialog" in rows["Head-Pointer"].remedy

    out = rows["Pointer output"]
    assert out.status == "attention"
    assert "portal" in out.text and "waiting for your permission" in out.text
    assert "starts by itself" in out.remedy


def test_pending_is_not_reported_as_connected_or_as_a_problem():
    out = _rows(state="pending_consent", consent="pending_consent")["Pointer output"]

    assert out.status not in ("ok", "problem")
    assert "connected" not in out.text


def test_a_refusal_needs_attention_with_the_way_to_be_asked_again():
    """NEEDS ATTENTION, not PROBLEM: `doctor` has always tagged a denied permission WARN
    (tests/test_doctor_pointer_output.py) and the window said PROBLEM for the same state --
    the contradiction tests/test_handsfree_surfaces_agree.py now forbids. The user's own
    answer to a dialog is not a malfunction, but it does need them to act, and the remedy
    below says how."""
    rows = _rows(state="denied", consent="denied", consent_reason="Start was refused")

    assert rows["Head-Pointer"].status == "attention"
    assert rows["Pointer output"].status == "attention"
    assert "permission was not given" in rows["Pointer output"].text
    assert "Restart" in rows["Pointer output"].remedy


def test_a_desktop_with_no_pointer_is_unavailable_not_a_problem():
    rows = _rows(state="unavailable", consent="unavailable")

    assert rows["Head-Pointer"].status == "unavailable"
    assert rows["Pointer output"].status == "unavailable"
    assert "dictation is unaffected" in rows["Head-Pointer"].remedy


def test_a_granted_pointer_says_so():
    out = _rows(consent="granted")["Pointer output"]

    assert out.status == "ok"
    assert "permission granted" in out.text


@pytest.mark.parametrize("consent", ["", "not_required"])
def test_a_backend_with_no_permission_step_still_reads_as_connected(consent):
    out = _rows(backend="x11", consent=consent)["Pointer output"]

    assert out.status == "ok" and "connected" in out.text


def test_every_consent_state_is_carried_by_a_word_not_only_a_colour():
    from yazses.handsfree.panel import STATUS_WORDS

    for state in ("pending_consent", "denied", "unavailable"):
        for row in _rows(state=state, consent=state).values():
            assert row.word == STATUS_WORDS[row.status] and row.word
