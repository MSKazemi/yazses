"""YazSes speaks before the desktop raises its "Remote Desktop" dialog.

`RemoteDesktop` is the only Wayland API for synthetic input, so a dictation
daemon that types for you must use it -- but the desktop titles the consent
dialog "Remote Desktop" and confirms it with "Share". Read cold, by someone who
installed an offline-by-design dictation tool, that says the opposite of what is
happening, and Cancel is the rational answer.

These tests pin the two places the explanation has to arrive: the terminal, when
`yazses start` reports the missing prerequisite, and the desktop, immediately
before the dialog itself. They also pin the two silences that matter -- no
advice a confined snap cannot follow, and no toast when no dialog is coming.
"""

from __future__ import annotations

import types

import pytest

from yazses.core.daemon import Daemon
from yazses.inject.portal import consent_explanation
from yazses.system import notify as notify_mod
from yazses.system import setup

# ---------------------------------------------------------------- the copy


def test_the_explanation_names_the_wording_the_user_will_actually_see():
    """It must quote the dialog's own title, or it explains a different dialog."""
    title, body = consent_explanation()
    assert "Remote Desktop" in title
    assert "Remote Desktop" in body


@pytest.mark.parametrize("claim", ["keyboard", "no screen capture", "nothing sent anywhere"])
def test_the_explanation_states_what_is_actually_requested(claim):
    """Each claim is checked against the client: DEVICE_KEYBOARD only, no
    ScreenCast, session-bus D-Bus with no outbound primitive."""
    _, body = consent_explanation()
    assert claim in body


def test_it_offers_the_way_to_never_see_the_prompt():
    _, body = consent_explanation(can_avoid=True)
    assert "yazses setup" in body


def test_the_reassurance_is_read_before_the_body_is_collapsed():
    """GNOME shows a long body's first line or two until the user expands it.
    The clause that answers the fear the dialog's title creates has to be in
    that visible part, not after the explanation of the wording."""
    _, body = consent_explanation()
    assert body.index("no screen capture") < body.index("Remote Desktop")


@pytest.mark.parametrize("can_avoid", [True, False])
def test_the_body_survives_a_balloon_that_drops_long_text(can_avoid):
    """A Windows balloon over 256 characters vanishes outright -- no error, no
    truncation. The Windows backend does not exist yet; the copy is written to
    outlive its arrival rather than to be re-measured then."""
    _, body = consent_explanation(can_avoid=can_avoid)
    assert len(body) <= 256, f"body is {len(body)} chars"


def test_a_confined_snap_is_not_told_to_run_a_command_it_cannot_run():
    """A strict snap has no package manager and cannot install ydotoold.
    Advice that cannot work there is worse than no advice."""
    _, body = consent_explanation(can_avoid=False)
    assert "yazses setup" not in body


# ------------------------------------------------- the terminal (yazses start)


def _wayland_plan():
    return setup.SetupPlan(setup_ydotoold=True, session="wayland")


def test_start_names_the_consequence_of_skipping_setup(monkeypatch):
    """The advice and the dialog otherwise land in the same second, and the
    modal wins: the user is told to run `yazses setup` by a line they never get
    to act on before the scary prompt arrives."""
    monkeypatch.setattr(setup, "input_group_pending_relogin", lambda: False)
    hints = setup.preflight_hints({}, plan=_wayland_plan(), pending_relogin=False)

    joined = "\n".join(hints)
    assert "ydotoold" in joined
    assert "Remote Desktop" in joined
    assert "no screen capture" in joined


def test_no_portal_consequence_is_claimed_when_ydotoold_is_not_the_gap(monkeypatch):
    """An X11 machine is never asked for this permission -- promising it a
    dialog it will not see is a false statement in the one place people look."""
    monkeypatch.setattr(setup, "input_group_pending_relogin", lambda: False)
    plan = setup.SetupPlan(apt_packages=["xdotool"], session="x11")
    hints = setup.preflight_hints({}, plan=plan, pending_relogin=False)

    assert "Remote Desktop" not in "\n".join(hints)


# ------------------------------------------------------- the desktop (daemon)


class _RunNow:
    """A Thread stand-in that runs the target inline, so ordering is assertable."""

    def __init__(self, target=None, **_kw):
        self._target = target

    def start(self):
        if self._target is not None:
            self._target()


def _daemon_with_portal(warm_result=True, events=None):
    def _warm():
        if events is not None:
            events.append("dialog")
        return warm_result

    return types.SimpleNamespace(_injector=types.SimpleNamespace(warm=_warm))


def _no_token(monkeypatch):
    import yazses.inject.portal as portal_mod

    monkeypatch.setattr(portal_mod, "read_token", lambda: "")


def test_yazses_explains_itself_before_the_dialog_opens(monkeypatch):
    events: list[str] = []
    _no_token(monkeypatch)
    monkeypatch.setattr("yazses.core.daemon.threading.Thread", _RunNow)
    monkeypatch.setattr(
        notify_mod, "notify", lambda title, body, **kw: events.append(("toast", title, body))
    )

    Daemon._warm_portal_session(_daemon_with_portal(events=events))

    assert [e[0] if isinstance(e, tuple) else e for e in events][:2] == ["toast", "dialog"], (
        "the explanation must precede the ask; after it, the user has already decided"
    )
    assert "Remote Desktop" in events[0][2]


def test_nothing_is_said_when_no_dialog_is_coming(monkeypatch):
    """With a restore token on disk the portal asks nothing, so a toast on every
    daemon start would be pure noise -- and noise is how a real warning gets
    dismissed unread."""
    import yazses.inject.portal as portal_mod

    toasts: list[tuple] = []
    monkeypatch.setattr(portal_mod, "read_token", lambda: "a-saved-token")
    monkeypatch.setattr("yazses.core.daemon.threading.Thread", _RunNow)
    monkeypatch.setattr(notify_mod, "notify", lambda *a, **kw: toasts.append(a))

    Daemon._warm_portal_session(_daemon_with_portal())

    assert toasts == []


def test_a_failing_explanation_never_blocks_the_permission_ask(monkeypatch):
    """The toast is a courtesy; the dialog is the functional path. If libnotify
    is missing or throws, dictation must still get its permission."""
    events: list[str] = []
    _no_token(monkeypatch)
    monkeypatch.setattr("yazses.core.daemon.threading.Thread", _RunNow)

    def _boom(*_a, **_kw):
        raise RuntimeError("no notification daemon")

    monkeypatch.setattr(notify_mod, "notify", _boom)

    Daemon._warm_portal_session(_daemon_with_portal(events=events))

    assert events == ["dialog"]


def test_a_backend_without_warm_is_left_alone(monkeypatch):
    """X11 picks xdotool, which has no portal session and needs no consent."""
    toasts: list[tuple] = []
    monkeypatch.setattr(notify_mod, "notify", lambda *a, **kw: toasts.append(a))

    Daemon._warm_portal_session(types.SimpleNamespace(_injector=types.SimpleNamespace()))

    assert toasts == []
