"""Runtime backstop for the offline promise: no test may reach a non-local host.

ADR-019 enforces the egress inventory by AST, which sees *our* code only. This is the
runtime half: while a test runs, ``socket.socket.connect`` / ``connect_ex`` / ``sendto``
refuse any address that is not loopback or AF_UNIX, and ``socket.getaddrinfo`` refuses
any host name that is not ``localhost``. ``socket.socketpair`` makes AF_UNIX (or, on
Windows, a loopback TCP pair) and never reaches a remote address, so it is unaffected.
``create_connection`` resolves then connects, so both hooks cover it.

A test that genuinely needs the network (none today) opts out with
``@pytest.mark.allow_network``. The error is a ``RuntimeError``, deliberately not an
``OSError``: code under test that catches ``OSError`` must not swallow the guard and let
the test pass quietly.

No POSIX-only calls: ``AF_UNIX`` is looked up with ``getattr`` because it is absent on
some Windows Pythons.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

ADR = "design/adr/adr-019-egress-inventory-and-escalation.md"

_LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})
_AF_UNIX = getattr(socket, "AF_UNIX", None)
#: Patch and restore the real class, never whatever `socket.socket` is at that moment: a
#: test may swap in a fake class, and writing our wrappers onto it corrupts the fake.
_REAL_SOCKET = socket.socket


class NetworkAccessBlocked(RuntimeError):  # noqa: N818 -- reads better as a noun phrase
    """A test tried to reach a non-local host."""


def _is_loopback_literal(host: str) -> bool:
    host = host.split("%", 1)[0].strip("[]")  # drop an IPv6 zone id and brackets
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped.is_loopback
    return ip.is_loopback


def is_local_host(host: Any) -> bool:
    """True for loopback addresses, ``localhost`` and the empty/wildcard host."""
    if host is None or host in ("", b""):
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host in ("0.0.0.0", "::"):  # noqa: S104 -- wildcard; connecting to it is local
        return True
    return host.lower().rstrip(".") in _LOCAL_NAMES or _is_loopback_literal(host)


def _block(what: str, host: Any) -> NetworkAccessBlocked:
    return NetworkAccessBlocked(
        f"test attempted a real network {what} to {host!r}. YazSes is offline by design: "
        f"tests may only use loopback, AF_UNIX or a socketpair. Mock the call, or mark "
        f"the test @pytest.mark.allow_network if it really must. See {ADR}."
    )


def _check_address(sock: socket.socket, address: Any, what: str) -> None:
    if _AF_UNIX is not None and sock.family == _AF_UNIX:
        return
    if isinstance(address, (str, bytes)):  # a path on an unusual family
        return
    host = address[0] if isinstance(address, tuple) and address else address
    if not is_local_host(host):
        raise _block(what, host)


class NetGuard:
    """Install/uninstall the patches. A second install while active is a no-op.

    The wrappers only refuse while ``enabled`` is true. The suite installs them once and
    flips ``enabled`` per test, rather than installing and uninstalling around each test:
    a test's own ``monkeypatch.setattr(socket, "getaddrinfo", ...)`` is undone *after* a
    late-defined autouse fixture finishes, and would put a stale wrapper back with no one
    left to remove it. A permanent wrapper that is switched off is harmless there.
    """

    def __init__(self) -> None:
        self._saved: dict[str, Any] | None = None
        self.enabled = True

    @property
    def active(self) -> bool:
        return self._saved is not None

    def install(self) -> None:
        if self._saved is not None:
            return
        cls = _REAL_SOCKET
        saved = {
            "connect": cls.connect,
            "connect_ex": cls.connect_ex,
            "sendto": cls.sendto,
            "getaddrinfo": socket.getaddrinfo,
        }
        self._saved = saved

        def connect(self_: socket.socket, address: Any) -> Any:
            if self.enabled:
                _check_address(self_, address, "connect")
            return saved["connect"](self_, address)

        def connect_ex(self_: socket.socket, address: Any) -> Any:
            if self.enabled:
                _check_address(self_, address, "connect")
            return saved["connect_ex"](self_, address)

        def sendto(self_: socket.socket, data: Any, *args: Any) -> Any:
            if self.enabled and args:  # sendto(data, address) or sendto(data, flags, address)
                _check_address(self_, args[-1], "send")
            return saved["sendto"](self_, data, *args)

        def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
            if self.enabled and not is_local_host(host):
                raise _block("name lookup", host)
            return saved["getaddrinfo"](host, *args, **kwargs)

        cls.connect = connect  # type: ignore[method-assign,assignment]
        cls.connect_ex = connect_ex  # type: ignore[method-assign,assignment]
        cls.sendto = sendto  # type: ignore[method-assign,assignment]
        socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]

    def uninstall(self) -> None:
        saved, self._saved = self._saved, None
        if saved is None:
            return
        cls = _REAL_SOCKET
        cls.connect = saved["connect"]  # type: ignore[method-assign]
        cls.connect_ex = saved["connect_ex"]  # type: ignore[method-assign]
        cls.sendto = saved["sendto"]  # type: ignore[method-assign]
        socket.getaddrinfo = saved["getaddrinfo"]


#: The suite-wide instance, installed once by `tests/conftest.py` and switched per test.
GUARD = NetGuard()
