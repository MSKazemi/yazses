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
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from yazses.inject.keysyms import char_to_keysym, name_to_keysym, parse_combo

logger = logging.getLogger(__name__)

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REMOTE_DESKTOP_IFACE = "org.freedesktop.portal.RemoteDesktop"
REQUEST_IFACE = "org.freedesktop.portal.Request"

DEVICE_KEYBOARD = 1
PERSIST_UNTIL_REVOKED = 2

KEY_RELEASED = 0
KEY_PRESSED = 1

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


def consent_explanation(*, can_avoid: bool = True) -> tuple[str, str]:
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
    `SelectDevices` asks for ``DEVICE_KEYBOARD`` and never ``DEVICE_POINTER``,
    the ScreenCast portal is never touched, the calls are session-bus D-Bus with
    no outbound primitive, and ``persist_mode=2`` is what makes "once" true.

    ``can_avoid`` is False where `yazses setup` cannot provision the machine --
    a strictly confined snap, which has no package manager and cannot install
    ``ydotoold``. Advice that cannot work there is worse than no advice.
    """
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
        #: Monotonic stamp of the last keystroke, for idle release. `None` means the
        #: session has never been used since it was opened.
        self._last_used: float | None = None

    # -- plumbing ---------------------------------------------------------

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

        The lock is acquired with the *same* budget as the negotiation, so a
        dictation arriving while `warm()` is still waiting on the consent dialog
        fails fast to the clipboard instead of queueing behind it. Blocking
        would be the worst of both: the user sees no dialog answer and no text.
        """
        if self._session_handle:
            return
        if not self._lock.acquire(timeout=start_timeout):
            raise PortalUnavailable(
                "another thread is still negotiating the portal session "
                "(the permission dialog is probably still waiting for an answer)"
            )
        try:
            if self._session_handle:
                return
            self._start_locked(start_timeout)
        finally:
            self._lock.release()

    def _start_locked(self, start_timeout: float = START_TIMEOUT_S) -> None:
        try:
            from jeepney.io.blocking import open_dbus_connection
        except Exception as exc:
            raise PortalUnavailable(
                "the `jeepney` D-Bus library is not installed, so the "
                "RemoteDesktop portal cannot be reached"
            ) from exc

        self._conn = open_dbus_connection(bus="SESSION")

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

        select: dict = {
            "types": ("u", DEVICE_KEYBOARD),
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

    def close(self) -> None:
        """Drop the session. Never raises -- called from shutdown paths."""
        with self._lock:
            self._session_handle = ""
            self._last_used = None
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
        with self._lock:
            if not self._session_handle or self._last_used is None:
                return False
            if not read_token():
                return False
            elapsed = (time.monotonic() if now is None else now) - self._last_used
            if elapsed < timeout_s:
                return False
        self.close()
        return True

    def notify_keysym(self, keysym: int, state: int) -> None:
        from jeepney import DBusAddress, new_method_call

        addr = DBusAddress(
            PORTAL_PATH, bus_name=PORTAL_BUS, interface=REMOTE_DESKTOP_IFACE
        )
        msg = new_method_call(
            addr,
            "NotifyKeyboardKeysym",
            "oa{sv}iu",
            (self._session_handle, {}, int(keysym), int(state)),
        )
        self._conn.send(msg)

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

    def close(self) -> None:
        self._session.close()


__all__ = [
    "PortalInjector",
    "PortalUnavailable",
    "consent_explanation",
    "key_delay",
    "portal_available",
    "read_token",
    "token_path",
    "write_token",
]
