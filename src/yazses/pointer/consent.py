"""Pointer consent -- whether the platform has agreed to let YazSes move the pointer.

Most pointer backends have no such question (X11's XTEST, Windows' ``SendInput``): the call
either works or raises. The Wayland RemoteDesktop portal is the exception. The compositor
asks the *user*, in a dialog the daemon cannot answer, and until they do the pointer cannot
move -- and when they decline, it never will this session. Those are different situations
that all used to surface as the same thing: a pointer fault whose message nobody could act
on (``waiting for the desktop's Remote Desktop permission dialog``).

This module is the vocabulary for telling them apart, and nothing else. It is deliberately
pure: no D-Bus, no subprocess, no clock and no import beyond the standard library, so the
classification is unit-tested by calling it. A backend that has a consent step reports it
through the optional :class:`ConsentReporting` protocol; the Head-Pointer asks that and
declines to *try* to move the pointer while the answer is not yes, instead of trying,
failing and faulting.

It is a separate optional protocol, not a seventh method on :class:`~yazses.pointer.base.
PointerSink`, because ``PointerSink`` is ``runtime_checkable`` and growing it would silently
stop every existing backend matching ``isinstance``.

**Pending is a claim about the user, not about the code.** ``PENDING`` is reported only
when a negotiation is genuinely unanswered (no session and no recorded failure). It is never
the default for "I do not know" -- that is ``UNKNOWN`` -- because a status line that says
*waiting for you* when nothing is waiting sends a user looking for a dialog that does not
exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "ConsentReport",
    "ConsentReporting",
    "PointerConsent",
    "classify_portal_session",
    "consent_of",
]


class PointerConsent(str, Enum):
    """Where the pointer stands on the platform's permission, in the words status prints."""

    #: This backend has no permission step (X11, Windows, macOS here). Not "granted": nobody
    #: was asked, so there is nothing to have been granted.
    NOT_REQUIRED = "not_required"
    #: The user has not answered the permission dialog yet. The pointer cannot move until
    #: they do, and nothing is wrong.
    PENDING = "pending_consent"
    #: The platform granted a pointer device for this session.
    GRANTED = "granted"
    #: The user declined (or the dialog failed). No pointer this session; a restart asks again.
    DENIED = "denied"
    #: The platform answered, and has no pointer to give (a compositor that granted the
    #: keyboard only), or the output is closed. Not the user's doing.
    UNAVAILABLE = "unavailable"
    #: The state could not be read. Never rendered as a yes.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ConsentReport:
    """A consent state and one honest sentence about it. ``detail`` never carries a position."""

    state: PointerConsent
    detail: str = ""

    @property
    def allows_motion(self) -> bool:
        """True when the platform has not said no and nothing is waiting on the user."""
        return self.state in (PointerConsent.NOT_REQUIRED, PointerConsent.GRANTED)


@runtime_checkable
class ConsentReporting(Protocol):
    """Optional: a pointer sink that has a permission step says where it stands.

    Cheap and non-blocking by contract -- it is read on every Head-Pointer tick, so it must
    never negotiate, wait on the user or touch a bus. It may only read state the backend
    already holds.
    """

    def pointer_consent(self) -> ConsentReport:
        """Where this sink's permission stands right now."""
        ...


def consent_of(sink: object) -> ConsentReport | None:
    """What *sink* says about its permission, or ``None`` if it has no such concept.

    Never raises: a sink whose report fails is ``UNKNOWN``, which the caller must not read
    as a yes. ``None`` and ``NOT_REQUIRED`` differ on purpose -- ``None`` is "this sink does
    not speak of consent", while ``NOT_REQUIRED`` is a sink affirmatively saying nobody
    needs to be asked.
    """
    report: Any = getattr(sink, "pointer_consent", None)
    if not callable(report):
        return None
    try:
        result = report()
    except Exception as exc:  # noqa: BLE001 - a diagnostic must not take the pointer down
        return ConsentReport(
            PointerConsent.UNKNOWN, f"could not read the permission state ({type(exc).__name__})"
        )
    if isinstance(result, ConsentReport):
        return result
    return ConsentReport(PointerConsent.UNKNOWN, "the permission state was not a ConsentReport")


def classify_portal_session(
    *,
    closed: bool,
    started: bool,
    pointer_granted: bool,
    last_error: str,
    had_grant: bool = False,
) -> ConsentReport:
    """Classify a RemoteDesktop portal session. Pure; the same inputs give the same answer.

    *closed* is the sink's own closed flag. *started* is whether the session holds a
    negotiated session; *pointer_granted* whether that grant listed a pointer device;
    *last_error* why the last negotiation failed (``""`` after a success or before any
    attempt). *had_grant* is True when this sink once held a grant on a session that has
    since been closed (the idle release): it is then not a first-time dialog.

    The order is the contract: a closed sink is not asking anyone anything; a live session
    beats any stale error; an error with no session is a refusal; no session and no error
    is a dialog nobody has answered.
    """
    if closed:
        return ConsentReport(PointerConsent.UNAVAILABLE, "the pointer output is closed")
    if started:
        if pointer_granted:
            return ConsentReport(
                PointerConsent.GRANTED, "the desktop granted a pointer device for this session"
            )
        return ConsentReport(
            PointerConsent.UNAVAILABLE,
            "the desktop answered but granted no pointer device (keyboard only), so this "
            "compositor offers no portal pointer; dictation is unaffected",
        )
    if last_error:
        return ConsentReport(
            PointerConsent.DENIED,
            f"the permission was not given ({last_error[:80]}); restart YazSes and approve "
            "the dialog",
        )
    if had_grant:
        return ConsentReport(
            PointerConsent.PENDING,
            "the Remote Desktop session was released while idle and is not open; it re-opens "
            "on the next dictation, without a new dialog if you approved before",
        )
    return ConsentReport(
        PointerConsent.PENDING,
        "waiting for you to answer the desktop's Remote Desktop permission dialog",
    )
