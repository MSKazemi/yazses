"""Pointer consent: telling "nobody has answered yet" from "no" from "there is no pointer".

Before this, the Wayland pointer discovered an unanswered permission dialog the hard way --
the first head movement called a sink that raised, the Head-Pointer faulted, and the user saw
a fault they could not act on while a dialog sat unanswered behind another window. The
classifier under test is pure (`yazses.pointer.consent`), so most of this file is a table.
The D-Bus layer is the injected `_FakePortalSession` from `tests/test_pointer_portal.py`: no
bus, no compositor, no dialog, and nothing here can move a real pointer.
"""
from __future__ import annotations

import pytest

from tests.test_pointer_portal import _FakePortalSession
from yazses.inject import portal
from yazses.pointer.consent import (
    ConsentReport,
    ConsentReporting,
    PointerConsent,
    classify_portal_session,
    consent_of,
)


def _classify(**kw) -> ConsentReport:
    base = {"closed": False, "started": False, "pointer_granted": False, "last_error": ""}
    return classify_portal_session(**{**base, **kw})


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        # Nothing negotiated, nothing failed: a dialog nobody has answered.
        ({}, PointerConsent.PENDING),
        # The user pressed Cancel: no session and a recorded reason.
        ({"last_error": "Start was refused (response code 1)"}, PointerConsent.DENIED),
        # A live session with a pointer device.
        ({"started": True, "pointer_granted": True}, PointerConsent.GRANTED),
        # A live session the compositor gave only the keyboard on.
        ({"started": True, "pointer_granted": False}, PointerConsent.UNAVAILABLE),
        # A closed sink is not asking anyone anything.
        ({"closed": True}, PointerConsent.UNAVAILABLE),
        # Released while idle after a grant: pending, but not a first-time dialog.
        ({"had_grant": True}, PointerConsent.PENDING),
        # A live session beats a stale error from an earlier attempt.
        ({"started": True, "pointer_granted": True, "last_error": "old"}, PointerConsent.GRANTED),
        # Closed beats everything.
        ({"closed": True, "started": True, "pointer_granted": True}, PointerConsent.UNAVAILABLE),
    ],
)
def test_classification_table(kwargs, expected) -> None:
    assert _classify(**kwargs).state is expected


def test_only_granted_and_not_required_allow_motion() -> None:
    allowed = {s for s in PointerConsent if ConsentReport(s).allows_motion}
    assert allowed == {PointerConsent.GRANTED, PointerConsent.NOT_REQUIRED}


def test_unknown_is_never_a_yes_and_never_pending() -> None:
    """"I could not read it" must not print as "waiting for you" or as permission."""
    unknown = ConsentReport(PointerConsent.UNKNOWN)
    assert unknown.allows_motion is False
    assert PointerConsent.UNKNOWN is not PointerConsent.PENDING


def test_every_report_carries_a_sentence_a_person_can_act_on() -> None:
    for kwargs in ({}, {"last_error": "x"}, {"started": True}, {"closed": True}, {"had_grant": True}):
        assert _classify(**kwargs).detail, kwargs


def test_the_denied_sentence_says_how_to_be_asked_again() -> None:
    assert "restart" in _classify(last_error="cancelled").detail


def test_the_error_text_is_bounded() -> None:
    assert len(_classify(last_error="x" * 5000).detail) < 300


# --------------------------------------------------------------------------- consent_of


class _Silent:
    """A sink with no permission step."""


class _Raises:
    def pointer_consent(self):
        raise RuntimeError("bus went away")


class _WrongType:
    def pointer_consent(self):
        return "granted"


def test_a_sink_with_no_consent_concept_is_none_not_not_required() -> None:
    assert consent_of(_Silent()) is None


def test_a_report_that_raises_is_unknown_and_does_not_propagate() -> None:
    report = consent_of(_Raises())
    assert report is not None
    assert report.state is PointerConsent.UNKNOWN
    assert "RuntimeError" in report.detail


def test_a_report_of_the_wrong_type_is_unknown() -> None:
    report = consent_of(_WrongType())
    assert report is not None and report.state is PointerConsent.UNKNOWN


# ------------------------------------------------------- the deferred Wayland sink, on fakes


def test_the_deferred_portal_sink_speaks_the_protocol() -> None:
    sink = portal.DeferredPortalPointerSink(_FakePortalSession())
    assert isinstance(sink, ConsentReporting)


def test_before_the_dialog_is_answered_the_sink_says_pending_and_negotiates_nothing() -> None:
    session = _FakePortalSession()
    sink = portal.DeferredPortalPointerSink(session)

    report = sink.pointer_consent()

    assert report.state is PointerConsent.PENDING
    assert session.calls == [], "asking about consent must never raise the dialog"
    assert session.connections == 0


def test_after_the_user_approves_the_sink_says_granted() -> None:
    session = _FakePortalSession()
    sink = portal.DeferredPortalPointerSink(session)
    session.ensure_started(1.0)

    assert sink.pointer_consent().state is PointerConsent.GRANTED


def test_a_cancelled_dialog_is_denied_and_a_retry_recovers() -> None:
    session = _FakePortalSession(refuse="Start")
    injector = portal.PortalInjector(session=session)
    sink = injector.deferred_pointer_sink()
    assert injector.warm() is False

    assert sink.pointer_consent().state is PointerConsent.DENIED

    session.refuse = ""
    assert injector.warm() is True
    assert sink.pointer_consent().state is PointerConsent.GRANTED


def test_a_keyboard_only_grant_is_unavailable_not_denied() -> None:
    session = _FakePortalSession(granted=portal.DEVICE_KEYBOARD)
    sink = portal.DeferredPortalPointerSink(session)
    session.ensure_started(1.0)

    assert sink.pointer_consent().state is PointerConsent.UNAVAILABLE


def test_a_closed_sink_is_unavailable() -> None:
    sink = portal.DeferredPortalPointerSink(_FakePortalSession())
    sink.close()
    assert sink.pointer_consent().state is PointerConsent.UNAVAILABLE


def test_an_idle_released_session_is_pending_again_without_a_first_time_story() -> None:
    session = _FakePortalSession()
    sink = portal.DeferredPortalPointerSink(session)
    session.ensure_started(1.0)
    sink.move_relative(1.0, 0.0)  # binds the grant
    session.close()

    report = sink.pointer_consent()

    assert report.state is PointerConsent.PENDING
    assert "released" in report.detail
