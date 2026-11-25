"""The autouse socket guard (tests/_net_guard.py): blocks real egress, spares local use."""

from __future__ import annotations

import socket
import threading

import pytest

from tests._net_guard import ADR, NetGuard, NetworkAccessBlocked, is_local_host


def test_the_guard_is_active_by_default() -> None:
    with pytest.raises(NetworkAccessBlocked):
        socket.create_connection(("203.0.113.1", 9), timeout=0.1)


def test_blocked_connect_names_the_host_and_the_adr() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkAccessBlocked) as exc:
            s.connect(("198.51.100.7", 80))
    finally:
        s.close()
    msg = str(exc.value)
    assert "198.51.100.7" in msg
    assert "adr-019" in msg
    assert ADR in msg


def test_connect_ex_and_udp_send_are_blocked() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(NetworkAccessBlocked):
            s.connect_ex(("198.51.100.7", 53))
        with pytest.raises(NetworkAccessBlocked):
            s.sendto(b"x", ("198.51.100.7", 53))
    finally:
        s.close()


def test_name_lookup_of_an_external_host_is_blocked() -> None:
    external = "example.com"
    with pytest.raises(NetworkAccessBlocked) as exc:
        socket.getaddrinfo(external, 443)
    assert external in exc.value.args[0]


def test_the_error_is_not_an_oserror() -> None:
    """Code under test that catches OSError must not swallow the guard."""
    assert not issubclass(NetworkAccessBlocked, OSError)


def test_loopback_server_is_reachable() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    got: list[bytes] = []

    def serve() -> None:
        conn, _ = srv.accept()
        with conn:
            got.append(conn.recv(4))

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        with socket.create_connection(("localhost", port), timeout=5) as c:
            c.sendall(b"ping")
        t.join(5)
    finally:
        srv.close()
    assert got == [b"ping"]


def test_loopback_udp_sendto_is_allowed() -> None:
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(5)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        tx.sendto(b"u", rx.getsockname())
        assert rx.recvfrom(4)[0] == b"u"
    finally:
        tx.close()
        rx.close()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no AF_UNIX on this platform")
def test_af_unix_connect_is_allowed(tmp_path) -> None:
    path = str(tmp_path / "s")
    if len(path) > 90:  # sun_path limit; fall back to an abstract-free short name
        pytest.skip("temp path too long for AF_UNIX")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(path)
        srv.listen(1)
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            c.connect(path)
        finally:
            c.close()
    finally:
        srv.close()


def test_socketpair_is_allowed() -> None:
    a, b = socket.socketpair()
    try:
        a.sendall(b"z")
        assert b.recv(1) == b"z"
    finally:
        a.close()
        b.close()


def test_the_local_host_classifier() -> None:
    for host in (
        "127.0.0.1",
        "127.9.9.9",
        "::1",
        "[::1]",
        "localhost",
        "LOCALHOST.",
        "::ffff:127.0.0.1",
        None,
        "",
    ):
        assert is_local_host(host), host
    for host in ("8.8.8.8", "example.com", "192.168.1.5", "10.0.0.1", "::ffff:8.8.8.8", 5):
        assert not is_local_host(host), host


@pytest.mark.allow_network
def test_the_marker_switches_the_guard_off() -> None:
    from tests._net_guard import GUARD

    assert GUARD.active
    assert not GUARD.enabled
    # A lookup of a non-local *literal* touches no network, so it is a safe probe.
    socket.getaddrinfo("203.0.113.1", 9)


@pytest.mark.allow_network  # the suite-wide guard sits underneath ours; switch it off
def test_a_disabled_guard_lets_calls_through_and_an_enabled_one_does_not() -> None:
    g = NetGuard()
    g.install()
    try:
        g.enabled = False
        socket.getaddrinfo("203.0.113.1", 9)  # literal: no network
        g.enabled = True
        with pytest.raises(NetworkAccessBlocked):
            socket.getaddrinfo("203.0.113.1", 9)
    finally:
        g.uninstall()


def test_a_stale_wrapper_restored_by_monkeypatch_is_harmless_once_the_guard_is_off(
    monkeypatch,
) -> None:
    """The ordering that broke tests/test_gaze_download.py in the first draft."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    assert socket.getaddrinfo("example.invalid", 1) == []


def test_install_and_uninstall_restore_the_originals() -> None:
    guard = NetGuard()
    # The autouse fixture already installed its own guard; stack ours on top and unwind it.
    before = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.socket.sendto,
        socket.getaddrinfo,
    )
    guard.install()
    assert guard.active
    assert socket.socket.connect is not before[0]
    guard.install()  # a second install must not stack
    guard.uninstall()
    assert not guard.active
    after = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.socket.sendto,
        socket.getaddrinfo,
    )
    assert after == before
    guard.uninstall()  # idempotent
