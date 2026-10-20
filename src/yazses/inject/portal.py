"""Wayland keystroke injection through the xdg-desktop-portal RemoteDesktop API.

This is the backend that lets a **strictly confined snap** type on Wayland, which
until now it could not do at all. The store listing said so in its own words --
"supports hold-to-talk dictation on X11 only" -- while 85% of the installed base
ran a Wayland-by-default desktop (ubuntu 24.04/26.04, zorin 18, debian 13). They
installed it, it could not type, and they removed it.

Why the portal and not the mechanism the unconfined install uses. The host path is
``ydotool`` writing to ``/dev/uinput``, and neither half of it survives
confinement: Ubuntu's ``ydotool`` package ships only ``/usr/bin/ydotool`` and no
``ydotoold`` to own the device, and ``/dev/uinput`` is ``0600 root:root``, so it
needs a udev rule that a strict snap has no way to install. ``wtype`` is worse --
it needs ``virtual-keyboard-manager-v1``, which wlroots compositors implement and
GNOME's Mutter and KDE's KWin deliberately do not, i.e. exactly the two desktops
this user base is on. The portal needs **no device node, no udev rule and no extra
``snap connect``**: access rides on the ``desktop`` plug, which is already
declared and auto-connected.

The cost is a consent dialog. ``persist_mode=2`` plus the returned restore token
makes it a once-ever dialog rather than a once-per-session one, which is the whole
reason the token is written to disk here.

Everything heavy is imported lazily and every failure is contained: this sits on
the dictation hot path, and an injector that raises loses the user's words.

**The pointer lives here too, in the same session (ADR-v2-146, rule 6).** The
`RemoteDesktop` interface that types is also the one that moves the pointer, and a
pointer-only client would mean a second consent dialog, a second restore token and two
sessions competing for the same compositor grant. So `PortalPointerSink` at the bottom of
this file is a `yazses.pointer.base.PointerSink` over the very session object the injector
already holds — `PortalInjector.pointer_sink()` is the whole wiring — and POINTER is added
to the *one* `SelectDevices` call, only when a pointer consumer has asked for it. The
sink is here rather than under `src/yazses/pointer/` because that package is a pure,
dependency-free boundary: it may not import this module, D-Bus, or anything else.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from yazses.inject.keysyms import char_to_keysym, name_to_keysym, parse_combo
from yazses.pointer.base import (
    MotionUnit,
    PointerBackendError,
    PointerButton,
    PointerCapabilities,
    PointerError,
    PointerUnsupportedError,
    check_finite,
    require_absolute,
    require_button,
    require_relative,
    require_scroll,
)
from yazses.pointer.consent import ConsentReport, classify_portal_session

logger = logging.getLogger(__name__)

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REMOTE_DESKTOP_IFACE = "org.freedesktop.portal.RemoteDesktop"
REQUEST_IFACE = "org.freedesktop.portal.Request"

DEVICE_KEYBOARD = 1
DEVICE_POINTER = 2
PERSIST_UNTIL_REVOKED = 2

KEY_RELEASED = 0
KEY_PRESSED = 1

BUTTON_RELEASED = 0
BUTTON_PRESSED = 1

# `NotifyPointerButton` takes a **Linux evdev button code**, not an X11 button number:
# the portal spec says so outright, and the two disagree on everything but left. X11
# numbers middle 2 and right 3; evdev has BTN_LEFT/RIGHT/MIDDLE adjacent from 0x110, so
# sending the X11 numbering would land a right-click on the middle button and a middle
# click on something no toolkit listens to.
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112

#: The evdev code each :class:`PointerButton` becomes on the wire.
POINTER_BUTTON_CODES = {
    PointerButton.LEFT: BTN_LEFT,
    PointerButton.RIGHT: BTN_RIGHT,
    PointerButton.MIDDLE: BTN_MIDDLE,
}

#: What the portal pointer path can do, and the one thing it cannot.
#:
#: Relative motion, all three buttons and both axes come with the POINTER device: the
#: interface defines `NotifyPointerMotion`, `NotifyPointerButton` and `NotifyPointerAxis`
#: unconditionally, and the compositor grants or refuses the device as a whole rather than
#: per method. Whether it granted it at all is *discovered*, not assumed — see
#: `_PortalSession.pointer_granted`, which reads the device mask out of the `Start`
#: response, and `open_pointer_sink`, which refuses to build a sink without it.
#:
#: Absolute motion is structurally absent. `NotifyPointerMotionAbsolute` takes a
#: ScreenCast **stream** node id as well as x/y, so it can only address a screen this
#: session is already capturing; YazSes never touches the ScreenCast portal, and asking
#: for a stream to do arithmetic on would turn a keyboard grant into real screen capture
#: and make the consent copy a lie. So it is an honest `PointerUnsupportedError`, which is
#: exactly the case ADR-v2-146 made `capabilities()` optional-aware for.
#:
#: Scroll axis signs need no conversion: the portal inherits Wayland's convention, where a
#: positive vertical value scrolls **down** and a positive horizontal one **right**. That
#: is already the boundary's convention, so the sign passes through untouched.
PORTAL_POINTER_CAPABILITIES = PointerCapabilities(
    backend="portal",
    relative_motion=True,
    absolute_motion=False,
    buttons=frozenset(POINTER_BUTTON_CODES),
    scroll_vertical=True,
    scroll_horizontal=True,
    # The RemoteDesktop portal specification describes motion in the logical coordinate
    # space; how a given compositor scales a relative delta on a fractionally scaled
    # output has not been measured here, so this names the specification's claim, not an
    # observation. Treat travel distances on a scaled Wayland session as unverified.
    motion_unit=MotionUnit.COMPOSITOR_LOGICAL,
)

TOKEN_FILENAME = "portal_remote_desktop_token"

# Seconds between the press and release of one character. The portal delivers
# events in order, so this is not needed for correctness; it exists because a
# burst of hundreds of events in a few milliseconds is the shape that made
# toolkits drop characters for the ydotool backend (which settled on 6 ms).
# Override with YAZSES_PORTAL_KEY_DELAY when a compositor wants it slower.
DEFAULT_KEY_DELAY_S = 0.004

# The consent dialog has to be found and clicked by a human, so the negotiation
# budget is generous -- but ONLY when it is being run ahead of time by `warm()`.
START_TIMEOUT_S = 120.0
REQUEST_TIMEOUT_S = 30.0

# The budget when a *dictation* finds the session not yet negotiated. It is two
# orders of magnitude smaller than START_TIMEOUT_S on purpose. Measured against
# the real portal: Start does not answer until the user clicks, and the portal
# log shows it cannot even parent its dialog to a window when parent_window is
# empty ("Failed to associate portal window with parent window"), so the dialog
# can be raised behind whatever the user is looking at. Waiting the full budget
# on the hot path would freeze the daemon mid-sentence for two minutes with no
# explanation. Failing fast hands the burst to the clipboard fallback instead,
# which is a visible, recoverable outcome.
HOT_PATH_TIMEOUT_S = 5.0


class PortalUnavailable(RuntimeError):
    """The portal cannot be used -- no jeepney, no bus, or no RemoteDesktop."""


def key_delay() -> float:
    """Per-keystroke delay, overridable for a compositor that needs it slower."""
    raw = os.environ.get("YAZSES_PORTAL_KEY_DELAY", "").strip()
    if not raw:
        return DEFAULT_KEY_DELAY_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_KEY_DELAY_S
    return value if value >= 0 else DEFAULT_KEY_DELAY_S


def token_path() -> Path:
    """Where the restore token lives.

    Honours ``YAZSES_DATA_DIR`` so a test never writes to the developer's own
    data directory -- the project has been bitten by a suite that read and wrote
    the host's real config.
    """
    override = os.environ.get("YAZSES_DATA_DIR", "").strip()
    if override:
        return Path(override) / TOKEN_FILENAME
    from platformdirs import PlatformDirs

    return Path(PlatformDirs("yazses", "yazses").user_data_dir) / TOKEN_FILENAME


def read_token() -> str:
    """The saved restore token, or ``""``. Never raises."""
    try:
        return token_path().read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def write_token(token: str) -> None:
    """Persist the restore token so consent is asked once, not once per session."""
    if not token:
        return
    try:
        path = token_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        # The token authorises silent input injection; keep it owner-only.
        path.chmod(0o600)
    except Exception as exc:  # pragma: no cover - disk/permission edge
        logger.debug("could not persist portal restore token: %s", exc)


def consent_explanation(
    *, can_avoid: bool = True, wants_pointer: bool = False
) -> tuple[str, str]:
    """What YazSes says *before* the desktop raises its permission dialog.

    The dialog GNOME and KDE raise for this portal is titled **"Remote Desktop"**
    and confirmed with a button marked **"Share"** -- wording inherited from the
    interface's original purpose, screen sharing. `RemoteDesktop` is the only
    Wayland API for synthetic input, so a daemon that types for you has no other
    door to knock on; it cannot ask for a narrower-sounding permission because
    none exists.

    Unexplained, the honest reading of that dialog is "the dictation app wants to
    share my screen", and the rational answer to it is Cancel -- from precisely
    the privacy-minded user this project is for, about an application whose whole
    promise is that nothing leaves the machine. Speaking first is the fix: the
    dialog then arrives as the expected second step rather than an ambush.

    Every claim in the copy is checked against what the client actually requests:
    `SelectDevices` asks for ``DEVICE_KEYBOARD`` -- and ``DEVICE_POINTER`` too, but
    only when a pointer consumer asked for it, which is what ``wants_pointer``
    selects the honest wording for -- the ScreenCast portal is never touched, the
    calls are session-bus D-Bus with no outbound primitive, and ``persist_mode=2``
    is what makes "once" true.

    ``wants_pointer`` must follow the request, not the feature's intentions: telling a
    privacy-minded user "no mouse" while the same `SelectDevices` asks for the pointer
    is the one mistake this whole function exists to prevent, and it would be found by
    nobody, because the dialog looks identical either way.

    ``can_avoid`` is False where `yazses setup` cannot provision the machine --
    a strictly confined snap, which has no package manager and cannot install
    ``ydotoold``. Advice that cannot work there is worse than no advice.
    """
    if wants_pointer:
        # Same shape as the keyboard-only copy: reassurance first (GNOME collapses the
        # rest), the dialog's own wording explained second, and under the 256 characters
        # a Windows balloon silently drops a notification for. `yazses setup` is not
        # offered here -- ydotoold would remove the *typing* prompt, and a pointer
        # consumer needs this session anyway, so the advice would not work.
        title = 'Approve "Remote Desktop" so YazSes can type and move the pointer'
        body = (
            "YazSes asks for the keyboard and the pointer: no screen capture, "
            'nothing sent anywhere. Your desktop calls it "Remote Desktop": Wayland\'s '
            "only way to type and move the pointer. Approve once; it is remembered."
        )
        return title, body

    title = 'Approve "Remote Desktop" so YazSes can type'
    # The reassurance leads. GNOME collapses a long body to its first line or
    # two until the user expands it, and "no screen capture" is the clause that
    # answers the fear the dialog's own title creates -- put second, it is the
    # half that does not get read. The whole body stays under the 256-character
    # ceiling a Windows balloon silently drops a notification for, so this copy
    # survives being reused when that backend lands.
    body = (
        "YazSes asks for the keyboard alone: no screen capture, no mouse, "
        'nothing sent anywhere. Your desktop calls it "Remote Desktop": Wayland\'s '
        "only way to type into another window. Approve once; it is remembered."
    )
    if can_avoid:
        # "then log out" is load-bearing, not politeness: `yazses setup` installs
        # ydotoold and a udev rule, and the rule only reaches your session after a
        # re-login. Promising "no prompt" without it was advice that cannot work --
        # the user re-runs setup, nothing changes, and the prompt returns.
        body += "\nAvoid it: run  yazses setup  then log out"
    return title, body


def portal_available() -> bool:
    """True when this session could plausibly use the RemoteDesktop portal.

    Deliberately cheap and side-effect free -- it is consulted by the backend
    probe and by ``yazses doctor``, and it must never pop the consent dialog.
    It answers "is the machinery present", not "will the user say yes".
    """
    if os.name != "posix":
        return False
    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return False
    try:
        import jeepney  # noqa: F401
        from jeepney.io.blocking import open_dbus_connection
    except Exception:
        return False
    try:
        conn = open_dbus_connection(bus="SESSION")
    except Exception:
        return False
    try:
        return _peer_owns_portal(conn)
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _peer_owns_portal(conn: Any) -> bool:
    """True when org.freedesktop.portal.Desktop has an owner on this bus."""
    from jeepney import DBusAddress, new_method_call
    from jeepney.bus_messages import message_bus
    from jeepney.io.blocking import Proxy

    if not Proxy(message_bus, conn).NameHasOwner(PORTAL_BUS)[0]:
        return False
    # Owning the name is not the same as implementing RemoteDesktop: a portal
    # backend that only does file chooser and screenshot owns it too. Ask for
    # the interface's version property, which only exists if it is implemented.
    addr = DBusAddress(PORTAL_PATH, bus_name=PORTAL_BUS, interface="org.freedesktop.DBus.Properties")
    msg = new_method_call(addr, "Get", "ss", (REMOTE_DESKTOP_IFACE, "version"))
    reply = conn.send_and_get_reply(msg, timeout=5)
    return bool(reply.body)


class _PortalSession:
    """One RemoteDesktop session: create, select keyboard, start, then notify.

    Held open for the life of the daemon. Re-negotiating per burst would show the
    consent dialog on a restore-token failure at the precise moment the user is
    mid-sentence, and would add a round trip to every hold-release.
    """

    def __init__(self) -> None:
        # `Any` rather than a jeepney type: jeepney ships no py.typed marker, so
        # a real annotation would resolve to Any anyway while making this module
        # fail to import wherever jeepney is absent.
        self._conn: Any = None
        self._session_handle = ""
        self._lock = threading.Lock()
        #: Guards `_pointer_consumers` and `_asked_pointer` only, and is held for a few
        #: instructions at a time. `_lock` is held for the whole negotiation -- up to
        #: START_TIMEOUT_S, the length of the consent dialog -- so anything that merely
        #: books a consumer must not queue on it: the daemon's start-up would sit behind
        #: a dialog, hotkey included.
        self._state_lock = threading.Lock()
        #: Monotonic stamp of the last keystroke, for idle release. `None` means the
        #: session has never been used since it was opened.
        self._last_used: float | None = None
        #: How many live pointer sinks want POINTER in this session. Zero is the whole
        #: of ADR-v2-146 rule 7: with no consumer, `SelectDevices` asks for the keyboard
        #: alone and a dictation-only install is byte-identical to before.
        self._pointer_consumers = 0
        #: Whether the compositor actually granted POINTER, read from `Start`. Never
        #: inferred from having asked.
        self._pointer_granted = False
        #: What the in-flight or finished negotiation put in its `SelectDevices` mask:
        #: ``None`` before the mask is sent, then whether POINTER was in it. Once it is
        #: ``False`` the mask cannot be widened -- that is the point at which a late
        #: consumer must be told "keyboard only" instead of being queued.
        self._asked_pointer: bool | None = None
        #: True only once `Start` has returned, i.e. the user has answered the dialog and the
        #: grant is known. `_session_handle` is set far earlier -- `CreateSession` succeeds
        #: before the dialog is raised -- so a handle says "a negotiation is in flight", not
        #: "a grant exists". Reading the handle as the grant made an unanswered dialog look
        #: like a keyboard-only refusal (found live, 2026-10-15).
        self._negotiated = False
        #: Bumped on every close, so a pointer sink can tell "the session I was granted
        #: on" from "a session that has since been re-negotiated behind my back".
        self._generation = 0
        #: Why the most recent negotiation failed ("" after a success or before any
        #: attempt). A pointer sink that is waiting on a session someone else is
        #: negotiating -- `warm()` on its own thread -- has no other way to tell "the
        #: dialog is still open" from "the user pressed Cancel".
        self._last_error = ""

    # -- plumbing ---------------------------------------------------------

    @property
    def generation(self) -> int:
        """Increments each time the session is closed. Identifies one grant."""
        return self._generation

    @property
    def started(self) -> bool:
        """True while a negotiated session is held. Never blocks, never negotiates."""
        return self._negotiated and bool(self._session_handle)

    @property
    def wants_pointer(self) -> bool:
        """True while a pointer consumer is registered, i.e. the next dialog asks for it."""
        return self._pointer_consumers > 0

    @property
    def last_error(self) -> str:
        """Why the last negotiation failed, or ``""``."""
        return self._last_error

    @property
    def pointer_granted(self) -> bool:
        """True only if a started session's `Start` response listed a pointer device."""
        return self._pointer_granted

    def _open_connection(self) -> Any:
        """Open the session bus. The single seam a test replaces the D-Bus layer at."""
        try:
            from jeepney.io.blocking import open_dbus_connection
        except Exception as exc:
            raise PortalUnavailable(
                "the `jeepney` D-Bus library is not installed, so the "
                "RemoteDesktop portal cannot be reached"
            ) from exc
        return open_dbus_connection(bus="SESSION")

    def _sender_token(self) -> str:
        """The bus-name fragment the portal builds Request object paths from."""
        unique = self._conn.unique_name
        return unique.lstrip(":").replace(".", "_")

    def _request_path(self, handle_token: str) -> str:
        return f"{PORTAL_PATH}/request/{self._sender_token()}/{handle_token}"

    def _call_with_response(
        self, member: str, signature: str, body: tuple, timeout: float
    ) -> dict:
        """Invoke a portal method and wait for its asynchronous Response signal.

        The match rule is installed and the filter opened **before** the method
        call goes out. The portal is free to answer before our reply lands, and
        a subscribe-after-send would lose that answer and then block until the
        timeout -- which for ``Start`` is two minutes of apparent hang.
        """
        from jeepney import DBusAddress, MatchRule, new_method_call
        from jeepney.bus_messages import message_bus
        from jeepney.io.blocking import Proxy

        handle_token = f"yazses{uuid.uuid4().hex[:16]}"
        path = self._request_path(handle_token)

        rule = MatchRule(
            type="signal", interface=REQUEST_IFACE, member="Response", path=path
        )
        bus = Proxy(message_bus, self._conn)
        bus.AddMatch(rule)
        try:
            with self._conn.filter(rule) as queue:
                addr = DBusAddress(
                    PORTAL_PATH, bus_name=PORTAL_BUS, interface=REMOTE_DESKTOP_IFACE
                )
                options = dict(body[-1])
                options["handle_token"] = ("s", handle_token)
                msg = new_method_call(addr, member, signature, (*body[:-1], options))
                self._conn.send_and_get_reply(msg, timeout=REQUEST_TIMEOUT_S)
                signal = self._conn.recv_until_filtered(queue, timeout=timeout)
        finally:
            try:
                bus.RemoveMatch(rule)
            except Exception:
                pass

        code, results = signal.body
        if code != 0:
            raise PortalUnavailable(
                f"{member} was refused by the portal (response code {code}; "
                "1 means the user cancelled the permission dialog)"
            )
        return results

    # -- lifecycle --------------------------------------------------------

    def ensure_started(self, start_timeout: float = START_TIMEOUT_S) -> None:
        """Negotiate the session if it is not already running. Idempotent.

        "Running" means *negotiated* -- `Start` returned -- and never merely "has a
        handle". `CreateSession` answers at once and `Start` is held open for the consent
        dialog, so a handle exists for the whole time the user is deciding; reading it
        as readiness let a dictation burst, or a pointer's first event, go out on a
        session the compositor had not authorised (found auditing #403).

        The lock is acquired with the *same* budget as the negotiation, so a
        dictation arriving while `warm()` is still waiting on the consent dialog
        fails fast to the clipboard instead of queueing behind it. Blocking
        would be the worst of both: the user sees no dialog answer and no text. An
        answer that lands inside that budget is simply a normal start.
        """
        if self.started:
            return
        if not self._lock.acquire(timeout=start_timeout):
            raise PortalUnavailable(
                "another thread is still negotiating the portal session "
                "(the permission dialog is probably still waiting for an answer)"
            )
        try:
            if self.started:
                return
            self._start_locked(start_timeout)
        finally:
            self._lock.release()

    def _start_locked(self, start_timeout: float = START_TIMEOUT_S) -> None:
        """Negotiate, or leave nothing behind. Runs with the lock already held.

        The rollback is not tidiness. `CreateSession` succeeds before the consent dialog
        is ever raised, so a user who clicks Cancel used to leave `_session_handle` set on
        a session that was never started -- and `ensure_started` returns early on a
        non-empty handle, so every later keystroke was notified at a session the
        compositor had not authorised. Nothing raised, nothing was typed: precisely the
        failure shape that hid a dead Wayland injection path here for a year. A
        negotiation that did not finish must look exactly like one that never began.
        """
        try:
            self._negotiate_locked(start_timeout)
            self._last_error = ""
        except Exception as exc:
            self._last_error = str(exc) or type(exc).__name__
            self._session_handle = ""
            self._pointer_granted = False
            self._negotiated = False
            with self._state_lock:
                self._asked_pointer = None
            conn, self._conn = self._conn, None
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001 - the failure being handled is the news
                    pass
            raise

    def _negotiate_locked(self, start_timeout: float) -> None:
        self._conn = self._open_connection()

        session_token = f"yazses{uuid.uuid4().hex[:16]}"
        results = self._call_with_response(
            "CreateSession",
            "a{sv}",
            ({"session_handle_token": ("s", session_token)},),
            REQUEST_TIMEOUT_S,
        )
        handle = results.get("session_handle")
        # The value arrives as a variant; jeepney hands back (signature, value).
        session_handle = handle[1] if isinstance(handle, tuple) else handle
        if not session_handle:
            raise PortalUnavailable("the portal created no session handle")
        self._session_handle = str(session_handle)

        # One SelectDevices for both capabilities. POINTER joins the mask only while a
        # sink is asking for it, so nothing changes for a dictation-only install -- and
        # when it is asking, it rides the *same* request, the same dialog and the same
        # restore token rather than a second negotiation (ADR-v2-146, rule 6).
        types = DEVICE_KEYBOARD
        with self._state_lock:
            # Read and recorded together: a consumer that registers after this point is
            # told what the mask already says, rather than being promised a device the
            # request never asked for.
            self._asked_pointer = self._pointer_consumers > 0
        if self._asked_pointer:
            types |= DEVICE_POINTER
        select: dict = {
            "types": ("u", types),
            "persist_mode": ("u", PERSIST_UNTIL_REVOKED),
        }
        saved = read_token()
        if saved:
            select["restore_token"] = ("s", saved)
        self._call_with_response(
            "SelectDevices",
            "oa{sv}",
            (self._session_handle, select),
            REQUEST_TIMEOUT_S,
        )

        # parent_window is "" -- there is no yazses window to parent the dialog
        # to, and the portal is specified to accept an empty string for that.
        started = self._call_with_response(
            "Start", "osa{sv}", (self._session_handle, "", {}), start_timeout
        )
        token = started.get("restore_token")
        token_value = token[1] if isinstance(token, tuple) else token
        if token_value:
            write_token(str(token_value))

        # What was *granted*, not what was asked for. The compositor answers with the
        # device mask it actually gave, and the portals differ: a build with no pointer
        # support, or a user who narrowed the grant, returns keyboard alone. Having asked
        # proves nothing -- a method call that succeeds while nothing moves is the exact
        # shape of failure that hid a broken injection path here for a year -- so the
        # pointer is considered available only on the compositor's own say-so, and an
        # answer that omits the key is read as "not granted" rather than as consent.
        devices = started.get("devices")
        devices_value = devices[1] if isinstance(devices, tuple) else devices
        self._pointer_granted = bool(
            self._pointer_consumers
            and isinstance(devices_value, int)
            and int(devices_value) & DEVICE_POINTER
        )
        self._negotiated = True

    def request_pointer(self) -> None:
        """Register a pointer consumer, so the next negotiation asks for POINTER too.

        Must be called **before** the session is negotiated. Raises
        :class:`PortalUnavailable` when the session is already running on a
        keyboard-only grant: the portal has no way to widen a started session, and the
        alternatives are both worse than saying so. Tearing the session down to ask
        again would raise a second consent dialog -- mid-sentence, for a user who may be
        dictating -- and re-prompting is what ADR-v2-146 rejected "one session per
        capability" to avoid; continuing without the device would be the silent no-op the
        pointer boundary forbids. So the caller is told, and a daemon restart with the
        pointer consumer already enabled gets one dialog and one session.
        """
        with self._state_lock:
            # Never `_lock`: it is held for the length of the dialog, and registering a
            # consumer must answer at once (see `_state_lock`). Two cases cannot be
            # widened: a negotiated session that did not grant the pointer, and one
            # whose `SelectDevices` mask already went out without it.
            if (self._negotiated and not self._pointer_granted) or (
                not self._negotiated and self._asked_pointer is False
            ):
                raise PortalUnavailable(
                    "the RemoteDesktop session is already running for the keyboard "
                    "alone, and the portal cannot add the pointer to a started "
                    "session; restart YazSes with the pointer feature enabled so the "
                    "one permission dialog covers both"
                )
            self._pointer_consumers += 1

    def release_pointer(self) -> None:
        """Drop one pointer consumer. Never raises; the count floors at zero.

        The grant on the *running* session is left alone -- revoking it would mean
        re-negotiating, i.e. another dialog -- but once the count is back to zero any
        later negotiation asks for the keyboard alone again.
        """
        with self._state_lock:
            if self._pointer_consumers > 0:
                self._pointer_consumers -= 1

    def close(self) -> None:
        """Drop the session. Never raises -- called from shutdown paths."""
        with self._lock:
            self._session_handle = ""
            self._last_used = None
            self._pointer_granted = False
            self._negotiated = False
            with self._state_lock:
                self._asked_pointer = None
            self._generation += 1
            conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    # -- input ------------------------------------------------------------

    def touch(self) -> None:
        """Record use, so the idle reaper can tell a working session from a parked one."""
        self._last_used = time.monotonic()

    def release_if_idle(self, timeout_s: float, *, now: float | None = None) -> bool:
        """Close the session after *timeout_s* of no typing. Returns whether it closed.

        This is what stops the desktop's screen-sharing indicator being a permanent
        fixture: it is shown while a RemoteDesktop session is open, and nothing about
        dictation needs that session open between bursts.

        Held open when there is **no restore token**, whatever the timeout says. In
        that state re-opening would raise the consent dialog again, and doing so
        mid-sentence -- the one moment the user is watching the text field rather
        than hunting for a permission window -- is worse than the indicator.
        """
        if timeout_s <= 0:
            return False
        # Never queue behind a negotiation: a session whose dialog is still open is not
        # idle, it is undecided, and the reaper is a daemon thread that would otherwise
        # wait out the dialog for nothing.
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if not self.started or self._last_used is None:
                return False
            # A registered pointer consumer holds the session open. A head pointer that
            # sits still for a minute is not idle -- it is waiting for the next
            # movement -- and the grant cannot be re-made without another dialog, so
            # reaping here would end the pointer for good with nothing to say why.
            if self._pointer_consumers:
                return False
            if not read_token():
                return False
            elapsed = (time.monotonic() if now is None else now) - self._last_used
            if elapsed < timeout_s:
                return False
        finally:
            self._lock.release()
        self.close()
        return True

    def _send_notify(self, member: str, signature: str, body: tuple) -> None:
        """Fire one `Notify*` method at the portal. No reply is asked for or waited on.

        Every input event -- key, motion, button, axis -- leaves through here, which is
        also the seam the tests replace: a fake records `(member, signature, body)` and
        CI needs no bus, no compositor and no consent dialog.

        Worth naming what this cannot tell you: the portal's `Notify*` methods are
        fire-and-forget, so a send that raises nothing is **not** evidence that anything
        moved. A compositor that dropped the event and a compositor that acted on it look
        identical from this line.
        """
        from jeepney import DBusAddress, new_method_call

        addr = DBusAddress(
            PORTAL_PATH, bus_name=PORTAL_BUS, interface=REMOTE_DESKTOP_IFACE
        )
        self._conn.send(new_method_call(addr, member, signature, body))

    def notify_keysym(self, keysym: int, state: int) -> None:
        self._send_notify(
            "NotifyKeyboardKeysym",
            "oa{sv}iu",
            (self._session_handle, {}, int(keysym), int(state)),
        )

    def notify_pointer_motion(self, dx: float, dy: float) -> None:
        """Move the pointer by a delta. ``+dx`` is right, ``+dy`` is down."""
        self._send_notify(
            "NotifyPointerMotion",
            "oa{sv}dd",
            (self._session_handle, {}, float(dx), float(dy)),
        )

    def notify_pointer_button(self, button_code: int, state: int) -> None:
        """Press (``BUTTON_PRESSED``) or release an **evdev** button code."""
        self._send_notify(
            "NotifyPointerButton",
            "oa{sv}iu",
            (self._session_handle, {}, int(button_code), int(state)),
        )

    def notify_pointer_axis(self, dx: float, dy: float) -> None:
        """Scroll by a delta, in the portal's own axis signs: ``+dy`` is down."""
        self._send_notify(
            "NotifyPointerAxis",
            "oa{sv}dd",
            (self._session_handle, {}, float(dx), float(dy)),
        )

    def tap(self, keysym: int, delay: float) -> None:
        """Press and release one keysym."""
        self.notify_keysym(keysym, KEY_PRESSED)
        if delay:
            time.sleep(delay)
        self.notify_keysym(keysym, KEY_RELEASED)
        if delay:
            time.sleep(delay)


class PortalInjector:
    """``BaseInjector`` over the RemoteDesktop portal.

    Types by **keysym**, so it is layout-independent: the compositor is told
    which character to produce, not which physical key to pretend was hit. A
    keycode backend types ``qwerty`` into an AZERTY user's editor; this one does
    not, which matters more here than usual because dictation is the one input
    method whose user never chose the characters by position.
    """

    backend_name = "portal"

    def __init__(self, session: _PortalSession | None = None) -> None:
        self._session = session if session is not None else _PortalSession()

    def _ready(self) -> _PortalSession:
        """The hot path. Never waits on a human."""
        self._session.ensure_started(HOT_PATH_TIMEOUT_S)
        self._session.touch()
        return self._session

    def release_if_idle(self, timeout_s: float) -> bool:
        """Drop the portal session after *timeout_s* idle. Never raises."""
        try:
            return self._session.release_if_idle(timeout_s)
        except Exception:  # noqa: BLE001 - housekeeping must not break dictation
            logger.debug("portal idle release failed", exc_info=True)
            return False

    def warm(self) -> bool:
        """Negotiate the session ahead of time. Never raises.

        Called from daemon startup so the consent dialog is answered at login
        rather than in the middle of the user's first sentence. Without this the
        dialog is raised by the first hold-to-talk release -- the one moment the
        user is looking at the text field they just dictated into, not hunting
        for an unparented permission window.
        """
        try:
            self._session.ensure_started(START_TIMEOUT_S)
            return True
        except Exception as exc:
            logger.info("portal session not established: %s", exc)
            return False

    def inject(self, text: str) -> None:
        if not text:
            return
        session = self._ready()
        delay = key_delay()
        for char in text:
            try:
                keysym = char_to_keysym(char)
            except ValueError:  # pragma: no cover - char is always length 1 here
                continue
            session.tap(keysym, delay)

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        session = self._ready()
        delay = key_delay()
        backspace = name_to_keysym("backspace") or 0xFF08
        for _ in range(count):
            session.tap(backspace, delay)

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        session = self._ready()
        delay = key_delay()
        for combo in keys:
            parsed = parse_combo(combo)
            if parsed is None:
                logger.debug("portal injector: unrecognised key %r, skipped", combo)
                continue
            mods, key = parsed
            for mod in mods:
                session.notify_keysym(mod, KEY_PRESSED)
            session.tap(key, delay)
            for mod in reversed(mods):
                session.notify_keysym(mod, KEY_RELEASED)

    @property
    def wants_pointer(self) -> bool:
        """True while a pointer consumer is registered on this injector's session.

        The daemon reads it before `warm()` so the consent explanation describes the
        request that is actually about to be made (see `consent_explanation`).
        """
        return self._session.wants_pointer

    def deferred_pointer_sink(self) -> DeferredPortalPointerSink:
        """A `PointerSink` that rides this session without negotiating it, or waiting.

        `pointer_sink` blocks until the user answers the dialog, which is right for a
        caller that is allowed to wait and wrong for a daemon constructing its features:
        the hotkey must be live while the dialog is open. This registers the pointer
        consumer **now** -- so the dialog `warm()` raises on its own thread asks for the
        keyboard and the pointer together, once -- and defers everything else to first use.
        """
        return DeferredPortalPointerSink(self._session)

    def pointer_sink(
        self, *, start_timeout: float = START_TIMEOUT_S
    ) -> PortalPointerSink:
        """A `PointerSink` on **this injector's own session** -- never a second one.

        The one call a pointer consumer makes on Wayland. It hands
        `open_pointer_sink` the `_PortalSession` this injector already types through, so
        the pointer rides the session, the dialog and the restore token that dictation
        negotiated instead of opening a rival client on the same bus.
        """
        return open_pointer_sink(self._session, start_timeout=start_timeout)

    def close(self) -> None:
        self._session.close()


@contextmanager
def _as_pointer_error(what: str) -> Iterator[None]:
    """Translate a D-Bus failure into the pointer boundary's vocabulary.

    A dead bus, a closed connection, a serialisation refusal -- all of them mean "the
    platform failed this operation", which is :class:`PointerBackendError` and not
    :class:`PointerUnsupportedError`: the caller may retry, and the status surface should
    say the compositor went away rather than that this desktop has no pointer.
    """
    try:
        yield
    except PointerError:
        raise
    except Exception as exc:  # noqa: BLE001 - jeepney raises bare Exceptions
        raise PointerBackendError(f"the portal failed to {what}: {exc}") from exc


class PortalPointerSink:
    """``PointerSink`` over the RemoteDesktop session that already types.

    Constructed only by `open_pointer_sink`, which is what guarantees the two things a
    caller cannot check for itself: the session is *started* (so no event is ever sent
    before the user has answered the dialog) and the compositor actually *granted* the
    pointer device (so an ungranted desktop gets an error at open time rather than a
    pointer that never moves).

    It does not own the session. `close()` gives the pointer capability back and leaves
    dictation typing -- the session belongs to the injector, and a sink that tore it down
    would end the user's ability to type in order to tidy up after itself.
    """

    backend_name = "portal"

    def __init__(self, session: _PortalSession) -> None:
        self._session = session
        self._generation = session.generation
        self._closed = False

    # -- the protocol ------------------------------------------------------

    def capabilities(self) -> PointerCapabilities:
        return PORTAL_POINTER_CAPABILITIES

    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_relative(PORTAL_POINTER_CAPABILITIES)
        session = self._live()
        with _as_pointer_error("move the pointer"):
            session.notify_pointer_motion(dx, dy)

    def move_absolute(self, x: float, y: float) -> None:
        """Always :class:`PointerUnsupportedError` on this backend.

        `NotifyPointerMotionAbsolute` addresses a position *within a ScreenCast stream*,
        and this session captures no screen. See `PORTAL_POINTER_CAPABILITIES` for why
        acquiring one to move a pointer would be the wrong trade.
        """
        require_absolute(PORTAL_POINTER_CAPABILITIES)

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        require_button(PORTAL_POINTER_CAPABILITIES, button)
        code = POINTER_BUTTON_CODES[button]
        session = self._live()
        pressed = False
        with _as_pointer_error(f"click the {button.value} button"):
            try:
                session.notify_pointer_button(code, BUTTON_PRESSED)
                pressed = True
                session.notify_pointer_button(code, BUTTON_RELEASED)
                pressed = False
            finally:
                if pressed:
                    # A button held down because the release failed is the worst
                    # outcome available here: the desktop is now dragging, and the user
                    # this feature exists for may have no other pointer to stop it with.
                    # One best-effort release, and the original failure still surfaces.
                    try:
                        session.notify_pointer_button(code, BUTTON_RELEASED)
                    except Exception:  # noqa: BLE001 - nothing better is available
                        logger.warning(
                            "portal pointer: %s button may be left pressed -- the "
                            "release could not be sent",
                            button.value,
                        )

    def scroll(self, dx: float, dy: float) -> None:
        """Scroll by ``(dx, dy)``; signs reach the portal unchanged (``+dy`` is down)."""
        check_finite(dx=dx, dy=dy)
        require_scroll(PORTAL_POINTER_CAPABILITIES, dx, dy)
        session = self._live()
        with _as_pointer_error("scroll"):
            session.notify_pointer_axis(dx, dy)

    def close(self) -> None:
        """Give the pointer capability back. Idempotent; the session stays open."""
        if self._closed:
            return
        self._closed = True
        try:
            self._session.release_pointer()
        except Exception:  # noqa: BLE001 - cleanup must not raise on top of a failure
            logger.debug("portal pointer: releasing the capability failed", exc_info=True)

    # -- internals ---------------------------------------------------------

    def _live(self) -> _PortalSession:
        """The session this sink was granted on, or an explicit error.

        Checked before every operation because a grant does not outlive the session it
        was made on: the idle reaper closes the session after a quiet spell, and
        `PortalInjector.close()` closes it at shutdown. Silently re-negotiating would raise a consent dialog in the middle of
        a gesture, so a sink whose grant is gone says so and the caller opens a new one.
        """
        if self._closed:
            raise PointerBackendError("this portal pointer sink is closed")
        session = self._session
        if session.generation != self._generation or not session.pointer_granted:
            raise PointerBackendError(
                "the RemoteDesktop session this pointer sink was granted on has been "
                "closed (idle release, or shutdown); open a new sink rather than "
                "re-prompting for consent mid-gesture"
            )
        # Pointer use is use: without this the idle reaper would close the session out
        # from under a user who is moving the pointer but not dictating.
        session.touch()
        return session


class DeferredPortalPointerSink:
    """``PointerSink`` that joins the injector's session now and opens on first use.

    The blocking `open_pointer_sink` is the wrong shape for a daemon that builds its
    features at start-up: it would hold the whole process until a human answered a
    compositor dialog. This registers the pointer consumer immediately (cheap, and
    refused at once if the session already started keyboard-only), then leaves the dialog
    to whoever negotiates the session -- the daemon's `warm()` thread, with its consent
    explanation -- and reads the outcome when the first event is sent.

    **Until the session exists it fails loudly rather than waiting or dropping events**:
    a pointer that silently swallows motion is what ADR-v2-146 forbids. The message says
    which of "dialog still open" and "dialog refused" it is, from the session's own
    record, so the Head-Pointer's fault line tells the user what to do. Nothing is ever
    sent before the compositor granted the pointer device, and nothing here negotiates,
    so this class cannot raise a consent dialog by itself.
    """

    backend_name = "portal"

    def __init__(self, session: _PortalSession) -> None:
        try:
            session.request_pointer()
        except PortalUnavailable as exc:
            raise PointerBackendError(str(exc)) from exc
        self._session = session
        self._inner: PortalPointerSink | None = None
        self._generation = -1
        self._closed = False

    def capabilities(self) -> PointerCapabilities:
        return PORTAL_POINTER_CAPABILITIES

    def pointer_consent(self) -> ConsentReport:
        """Where the desktop's permission stands, read from the session's own record.

        The optional :class:`~yazses.pointer.consent.ConsentReporting` seam: the
        Head-Pointer asks this *before* it tries to move, so a dialog the user has not yet
        answered is reported as pending rather than discovered as a fault on the first head
        movement. Non-blocking and negotiation-free -- it reads three properties and calls
        the pure classifier, so it cannot raise a dialog.
        """
        session = self._session
        return classify_portal_session(
            closed=self._closed,
            started=session.started,
            pointer_granted=session.pointer_granted,
            last_error=session.last_error,
            had_grant=self._generation >= 0,
        )

    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_relative(PORTAL_POINTER_CAPABILITIES)
        self._ready().move_relative(dx, dy)

    def move_absolute(self, x: float, y: float) -> None:
        require_absolute(PORTAL_POINTER_CAPABILITIES)

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        require_button(PORTAL_POINTER_CAPABILITIES, button)
        self._ready().click(button)

    def scroll(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_scroll(PORTAL_POINTER_CAPABILITIES, dx, dy)
        self._ready().scroll(dx, dy)

    def close(self) -> None:
        """Hand the pointer consumer back exactly once. The session stays open."""
        if self._closed:
            return
        self._closed = True
        inner, self._inner = self._inner, None
        if inner is not None:
            inner.close()  # releases the registration this object made
            return
        try:
            self._session.release_pointer()
        except Exception:  # noqa: BLE001 - cleanup must not raise on top of a failure
            logger.debug("portal pointer: releasing the capability failed", exc_info=True)

    def _ready(self) -> PortalPointerSink:
        if self._closed:
            raise PointerBackendError("this portal pointer sink is closed")
        session = self._session
        inner = self._inner
        if inner is not None and session.generation == self._generation:
            return inner
        # No grant on a live session: either never opened, or the session closed and
        # was re-negotiated (the consumer count kept POINTER in that mask). Re-derive.
        self._inner = None
        if not session.started:
            if session.last_error:
                raise PointerBackendError(
                    "the RemoteDesktop permission was not given "
                    f"({session.last_error[:80]}); restart YazSes and approve the dialog"
                )
            raise PointerBackendError(
                "waiting for the desktop's Remote Desktop permission dialog; approve "
                "it and the pointer starts by itself"
            )
        if not session.pointer_granted:
            raise PointerUnsupportedError(
                "the RemoteDesktop portal did not grant a pointer device for this "
                "session, so this compositor offers no portal pointer output "
                "(dictation is unaffected)"
            )
        self._generation = session.generation
        self._inner = PortalPointerSink(session)
        return self._inner


def open_pointer_sink(
    session: _PortalSession, *, start_timeout: float = START_TIMEOUT_S
) -> PortalPointerSink:
    """Add the pointer to an existing RemoteDesktop *session* and return a sink.

    The order is the contract. `request_pointer` first, so POINTER is in the very
    `SelectDevices` the session negotiates with; `ensure_started` second, so the dialog
    is answered before any event could be sent; the granted-device check third, so a
    compositor that gave only the keyboard produces an error instead of a sink that
    sends into the void.

    The budget defaults to the generous `START_TIMEOUT_S` rather than the dictation hot
    path's five seconds: enabling a pointer feature is a deliberate act, and the dialog
    it raises has to be found and clicked by a human.

    Raises :class:`~yazses.pointer.base.PointerUnsupportedError` when this desktop has no
    portal pointer to give, and :class:`~yazses.pointer.base.PointerBackendError` when it
    has one but this attempt failed -- a cancelled dialog, a session already running
    keyboard-only, a bus that is not there.
    """
    try:
        session.request_pointer()
    except PortalUnavailable as exc:
        raise PointerBackendError(str(exc)) from exc

    try:
        session.ensure_started(start_timeout)
    except Exception as exc:  # noqa: BLE001 - every failure means "no pointer today"
        session.release_pointer()
        raise PointerBackendError(
            f"the RemoteDesktop portal session could not be started: {exc}"
        ) from exc

    if not session.pointer_granted:
        session.release_pointer()
        raise PointerUnsupportedError(
            "the RemoteDesktop portal did not grant a pointer device for this session, "
            "so this compositor offers no portal pointer output (dictation is "
            "unaffected)"
        )
    return PortalPointerSink(session)


__all__ = [
    "PORTAL_POINTER_CAPABILITIES",
    "DeferredPortalPointerSink",
    "POINTER_BUTTON_CODES",
    "PortalInjector",
    "PortalPointerSink",
    "PortalUnavailable",
    "consent_explanation",
    "key_delay",
    "open_pointer_sink",
    "portal_available",
    "read_token",
    "token_path",
    "write_token",
]
