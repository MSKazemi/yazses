"""Linux openers. The BSDs use them too (``xdg-utils`` is in ports and pkgsrc).

:class:`LinuxFileOpener` opens a file with the default app. :class:`LinuxUrlOpener` hands a
custom-scheme URL (``claude://``, ``codex://``) to the program registered for it -- the
``UrlOpener`` seam ADR-031 §3 asks for.

**Two ways to hand the URL over, and why the order matters.** "Send to" puts the user's
dictation in the URL, percent-encoded, so *how* the URL reaches the desktop decides who
else can read it.

1. **The desktop portal, over D-Bus (preferred).** ``org.freedesktop.portal.OpenURI``'s
   ``OpenURI`` method, called on the session bus through ``jeepney`` -- the same client
   ``inject/portal.py`` uses for RemoteDesktop. The URL travels as a message body over the
   session-bus socket and no process of ours is started with it, so it is in nobody's
   ``/proc/<pid>/cmdline``. The session bus is the user's own: other local users cannot
   connect to it. What remains: a process of the *same* user can still watch the bus
   (``dbus-monitor``; the stock session-bus policy allows that), and the client the portal
   starts usually receives the URL as an argument (the ``%u`` in its ``.desktop`` file) --
   that second half is the client's, not ours.
2. **``xdg-open <url>`` (fallback only).** Used only when nothing received the URL from the
   portal attempt: ``jeepney`` missing, no session bus, no portal service, or no
   ``OpenURI`` on it. ``xdg-open`` takes the URL as a command-line argument, so while it
   runs the text is in ``/proc/<pid>/cmdline``: readable by every process of the same user
   and -- unless ``/proc`` is mounted with ``hidepid=`` -- by every local user.

**Once the portal has the URL, there is no fallback.** If the portal accepted the call and
then reports a failure, a cancelled app chooser, or does not answer in time, the URL is
already with the desktop: running ``xdg-open`` as well could open the client twice with the
same prompt, would override a user who pressed Cancel, and would put the text in an argv
for an attempt that resolves the scheme through the same ``mimeapps.list`` the portal just
used. So those cases are a failed (or, for "no answer yet", a pending) hand-off, never a
second one.

Neither path logs the URL, and no exception raised here quotes it: a D-Bus error's *name*
may be reported (it is restricted to ``[A-Za-z0-9_.]``), its message never is, because a
portal's error text can quote the URI it refused.
"""
from __future__ import annotations

import logging
import re
import secrets
import subprocess
import threading
from typing import Any

from yazses.platform.base import require_local_scheme

logger = logging.getLogger(__name__)

#: How long to wait for ``xdg-open`` to say whether it handed the URL off. It normally
#: exits within a second, with 0 or a failure status (4 when no program is registered
#: for the scheme). Some desktops' fallbacks run the handler in the foreground instead,
#: so a still-running ``xdg-open`` at this point counts as handed off and is left alone:
#: killing it could kill the client it is starting.
XDG_OPEN_WAIT_S = 5.0

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
OPENURI_IFACE = "org.freedesktop.portal.OpenURI"
REQUEST_IFACE = "org.freedesktop.portal.Request"

#: Budget for the ``OpenURI`` method *reply* (the Request handle), not for the client to
#: open. Longer than a warm call needs because the first call of a session may D-Bus-
#: activate ``xdg-desktop-portal`` itself.
PORTAL_CALL_TIMEOUT_S = 10.0
#: How long to wait for the Request's ``Response`` signal before calling the hand-off
#: pending -- the same budget ``xdg-open`` gets for its exit status.
PORTAL_RESPONSE_WAIT_S = XDG_OPEN_WAIT_S
#: How long a background thread keeps the bus connection open for a late ``Response``.
#: The portal ties a request to its caller's connection, and closing the connection
#: while an app chooser is still on screen can close that chooser; two minutes is the
#: budget ``inject/portal.py`` gives a human to answer a portal dialog.
PORTAL_LINGER_S = 120.0

#: ``Response`` codes, from the portal's Request interface: 0 success, 1 the user
#: cancelled the interaction, 2 the interaction ended some other way.
RESPONSE_SUCCESS = 0
RESPONSE_CANCELLED = 1

#: D-Bus errors that mean "there is no portal to ask" -- the message was never delivered
#: to anything that could act on the URL, so falling back to ``xdg-open`` cannot open
#: the client twice. Every other error came from the portal, which had the URL.
_PORTAL_ABSENT_ERRORS = frozenset(
    {
        "org.freedesktop.DBus.Error.ServiceUnknown",
        "org.freedesktop.DBus.Error.NameHasNoOwner",
        "org.freedesktop.DBus.Error.UnknownMethod",
        "org.freedesktop.DBus.Error.UnknownInterface",
        "org.freedesktop.DBus.Error.UnknownObject",
    }
)
#: The bus could not start the portal service (D-Bus activation failed).
_PORTAL_ABSENT_ERROR_PREFIX = "org.freedesktop.DBus.Error.Spawn."

_DBUS_ERROR_NAME = re.compile(r"[A-Za-z0-9_.]{1,255}")


class PortalUnavailable(Exception):
    """Nothing received the URL from the portal attempt, so ``xdg-open`` may be tried.

    Its message is a fixed phrase plus, at most, an exception *type* name or a D-Bus
    error *name* -- never the URL, never an error's free text.
    """


class LinuxFileOpener:
    def open(self, path: str) -> None:
        subprocess.run(["xdg-open", path], check=True)


class LinuxUrlOpener:
    def open_url(self, url: str) -> None:
        require_local_scheme(url)
        try:
            outcome = _portal_open_uri(url)
        except PortalUnavailable as why:
            logger.info(
                "Send to: the desktop portal is unavailable (%s); opening the link "
                "with xdg-open, whose argument list holds it while it runs.",
                why,
            )
            _xdg_open(url)
            return
        logger.info(
            "Send to: handed the link to the desktop portal (OpenURI, %s); no process "
            "was started with it.",
            outcome,
        )


# ---- the portal path ------------------------------------------------------------------


def _open_session_bus() -> Any:
    """Connect to the session bus. The single seam a test replaces the D-Bus layer at.

    ``Any`` rather than a jeepney type for the reason ``inject/portal.py`` gives: jeepney
    ships no ``py.typed`` marker, and it is absent off Linux and the BSDs.
    """
    try:
        from jeepney.io.blocking import open_dbus_connection
    except Exception:
        raise PortalUnavailable("the jeepney D-Bus library is not installed") from None
    try:
        return open_dbus_connection(bus="SESSION")
    except Exception as exc:
        raise PortalUnavailable(f"no session bus ({type(exc).__name__})") from None


def _portal_open_uri(url: str) -> str:
    """Ask the desktop portal to open *url*. Returns ``"opened"``, ``"accepted"`` or
    ``"pending"``.

    * ``"opened"`` -- the Request answered ``Response`` 0.
    * ``"accepted"`` -- the call returned a Request handle other than the one predicted
      from ``handle_token`` (a portal older than the token scheme), so its ``Response``
      cannot be matched safely; the portal has the URL.
    * ``"pending"`` -- no ``Response`` within :data:`PORTAL_RESPONSE_WAIT_S` (an app
      chooser may be on screen); a background thread keeps the connection open for it.

    Raises :class:`PortalUnavailable` only when the URL reached nothing that could act on
    it, so the caller may fall back. Raises :class:`OSError` -- never quoting the URL --
    once the portal has the URL and failed, was cancelled, or did not reply.
    """
    try:
        from jeepney import DBusAddress, HeaderFields, MatchRule, MessageType, new_method_call
        from jeepney.bus_messages import message_bus
        from jeepney.io.blocking import Proxy
    except Exception:
        raise PortalUnavailable("the jeepney D-Bus library is not installed") from None

    conn = _open_session_bus()
    lingering = False
    try:
        handle_token = f"yazses{secrets.token_hex(8)}"
        sender = str(conn.unique_name).lstrip(":").replace(".", "_")
        request_path = f"{PORTAL_PATH}/request/{sender}/{handle_token}"

        # Subscribe before calling: the portal may answer before its method reply lands
        # (the same ordering `inject/portal.py::_call_with_response` keeps).
        rule = MatchRule(
            type="signal", interface=REQUEST_IFACE, member="Response", path=request_path
        )
        try:
            Proxy(message_bus, conn, timeout=PORTAL_CALL_TIMEOUT_S).AddMatch(rule)
        except Exception as exc:
            raise PortalUnavailable(
                f"the session bus refused a match rule ({type(exc).__name__})"
            ) from None
        responses = conn.filter(rule)

        msg = new_method_call(
            DBusAddress(PORTAL_PATH, bus_name=PORTAL_BUS, interface=OPENURI_IFACE),
            "OpenURI",
            "ssa{sv}",
            ("", url, {"handle_token": ("s", handle_token)}),
        )
        # From here on the URL is on the bus.
        try:
            reply = conn.send_and_get_reply(msg, timeout=PORTAL_CALL_TIMEOUT_S)
        except Exception as exc:
            # A timeout or a dropped bus: the portal may have the URL. No fallback.
            raise OSError(
                f"the desktop portal did not reply to OpenURI ({type(exc).__name__})"
            ) from None

        if reply.header.message_type == MessageType.error:
            name = _safe_error_name(reply.header.fields.get(HeaderFields.error_name))
            if _portal_is_absent(name):
                raise PortalUnavailable(f"no OpenURI portal on the session bus ({name})")
            raise OSError(f"the desktop portal refused OpenURI ({name})")

        handle = reply.body[0] if reply.body else ""
        if handle != request_path:
            logger.debug("Send to: the portal returned an unpredicted Request handle; "
                         "not waiting for its Response.")
            return "accepted"

        try:
            signal = conn.recv_until_filtered(responses.queue, timeout=PORTAL_RESPONSE_WAIT_S)
        except TimeoutError:
            _linger(conn, responses)
            lingering = True
            return "pending"
        except Exception as exc:
            raise OSError(
                f"the desktop portal connection failed while opening ({type(exc).__name__})"
            ) from None

        code = _response_code(signal)
        if code == RESPONSE_SUCCESS:
            return "opened"
        if code == RESPONSE_CANCELLED:
            raise OSError("the desktop's app chooser was cancelled (portal response 1)")
        raise OSError(f"the desktop portal could not open the link (portal response {code})")
    finally:
        if not lingering:
            _close_quietly(conn)


def _safe_error_name(name: object) -> str:
    """A D-Bus error name fit for a log line; anything else becomes a placeholder."""
    if isinstance(name, str) and _DBUS_ERROR_NAME.fullmatch(name):
        return name
    return "unnamed D-Bus error"


def _portal_is_absent(error_name: str) -> bool:
    return error_name in _PORTAL_ABSENT_ERRORS or error_name.startswith(
        _PORTAL_ABSENT_ERROR_PREFIX
    )


def _response_code(signal: Any) -> int | str:
    """The ``u`` of a ``Response(u response, a{sv} results)`` signal. Never its results."""
    body = getattr(signal, "body", None)
    if isinstance(body, tuple) and body and isinstance(body[0], int):
        return body[0]
    return "malformed"


def _linger(conn: Any, responses: Any) -> None:
    """Keep *conn* open on a daemon thread until the late ``Response`` or the budget."""

    def wait() -> None:
        try:
            signal = conn.recv_until_filtered(responses.queue, timeout=PORTAL_LINGER_S)
            logger.debug("Send to: the desktop portal answered OpenURI late (response %s).",
                         _response_code(signal))
        except Exception as exc:  # noqa: BLE001 - a background wait reports, never raises
            logger.debug("Send to: no OpenURI response from the desktop portal (%s).",
                         type(exc).__name__)
        finally:
            _close_quietly(conn)

    threading.Thread(target=wait, name="openuri-portal-linger", daemon=True).start()


def _close_quietly(conn: Any) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001 - closing a dead connection is not a failure
        pass


# ---- the xdg-open fallback ------------------------------------------------------------


def _xdg_open(url: str) -> None:
    # One argv element, no shell. stdout/stderr discarded: xdg-open quotes its
    # argument in its error messages, and the daemon's stderr is its log.
    proc = subprocess.Popen(
        ["xdg-open", url],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    try:
        status = proc.wait(timeout=XDG_OPEN_WAIT_S)
    except subprocess.TimeoutExpired:
        # Still running: handed to a handler that has not returned yet. Reap it in
        # the background so it does not linger as a zombie.
        threading.Thread(target=proc.wait, name="xdg-open-reaper", daemon=True).start()
        return
    if status != 0:
        # The status only -- a CalledProcessError would carry the argv, i.e. the URL.
        raise OSError(f"xdg-open exited with status {status}")
