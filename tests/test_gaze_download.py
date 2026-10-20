"""The gaze model download must not hang, and must never cache a partial file.

Found on a real laptop: ``urlretrieve`` resolved the AAAA records first, had no timeout and
walked every dead IPv6 address in turn, so the first run of gaze looked frozen for minutes
while ``curl -4`` finished in a second. Nothing here touches the network; the connection and
the opener are replaced, so the suite stays offline.
"""
from __future__ import annotations

import socket

import pytest

from yazses.gaze import download

V4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))
V6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0))


def test_ipv4_is_tried_before_ipv6_and_order_is_otherwise_stable() -> None:
    v6b = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::2", 443, 0, 0))
    v4b = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.2", 443))
    assert download.ipv4_first([V6, v6b, V4, v4b]) == [V4, v4b, V6, v6b]


def test_empty_address_list_is_defined() -> None:
    assert download.ipv4_first([]) == []


class _Sock:
    """Records connect attempts; the families in ``dead`` refuse, like a black-holed route."""

    attempts: list[str] = []
    dead: set[int] = set()

    def __init__(self, family, socktype, proto) -> None:
        self.family = family
        self.timeout: float | None = None

    def settimeout(self, value) -> None:
        self.timeout = value

    def connect(self, addr) -> None:
        _Sock.attempts.append(addr[0])
        assert self.timeout is not None and self.timeout <= download.CONNECT_TIMEOUT_S
        if self.family in _Sock.dead:
            raise TimeoutError("timed out")

    def close(self) -> None:
        pass


@pytest.fixture
def fake_net(monkeypatch):
    _Sock.attempts, _Sock.dead = [], set()
    monkeypatch.setattr(socket, "socket", _Sock)
    return _Sock


def test_a_dead_ipv6_route_costs_nothing_because_ipv4_goes_first(fake_net, monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [V6, V4])
    fake_net.dead = {socket.AF_INET6}
    download.connect_ipv4_first("example.test", 443, 5.0)
    assert fake_net.attempts == ["192.0.2.1"]


def test_it_falls_back_to_ipv6_when_ipv4_is_the_dead_one(fake_net, monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [V6, V4])
    fake_net.dead = {socket.AF_INET}
    download.connect_ipv4_first("example.test", 443, 5.0)
    assert fake_net.attempts == ["192.0.2.1", "2001:db8::1"]


def test_every_address_dead_raises_instead_of_hanging(fake_net, monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [V6, V4])
    fake_net.dead = {socket.AF_INET, socket.AF_INET6}
    with pytest.raises(OSError):
        download.connect_ipv4_first("example.test", 443, 5.0)


def test_no_addresses_at_all_raises(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(OSError):
        download.connect_ipv4_first("example.test", 443, 5.0)


class _Resp:
    def __init__(self, body: bytes, length: str | None) -> None:
        self._chunks = [body[i : i + 65536] for i in range(0, len(body), 65536)]
        self.headers = {} if length is None else {"Content-Length": length}

    def read(self, _n: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _serve(monkeypatch, body: bytes, length: str | None) -> None:
    monkeypatch.setattr(download, "_open", lambda url: _Resp(body, length))


def test_a_complete_download_is_renamed_into_place(tmp_path, monkeypatch) -> None:
    body = b"x" * 2_000_000
    _serve(monkeypatch, body, str(len(body)))
    dest = tmp_path / "m" / "face_landmarker.task"
    assert download.ensure_face_landmarker(dest) == dest
    assert dest.read_bytes() == body
    assert not list(dest.parent.glob("*.part"))


def test_a_truncated_download_is_not_cached(tmp_path, monkeypatch) -> None:
    _serve(monkeypatch, b"x" * 2_000_000, "3758596")
    dest = tmp_path / "face_landmarker.task"
    with pytest.raises(OSError, match="truncated"):
        download.ensure_face_landmarker(dest)
    assert not dest.exists() and not list(tmp_path.glob("*.part"))


def test_an_error_page_is_not_cached_as_the_model(tmp_path, monkeypatch) -> None:
    _serve(monkeypatch, b"<html>403</html>", None)
    dest = tmp_path / "face_landmarker.task"
    with pytest.raises(OSError, match="too small"):
        download.ensure_face_landmarker(dest)
    assert not dest.exists() and not list(tmp_path.glob("*.part"))


def test_an_existing_model_is_never_refetched(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "face_landmarker.task"
    dest.write_bytes(b"already here")
    monkeypatch.setattr(download, "_open", lambda url: pytest.fail("must not touch the network"))
    assert download.ensure_face_landmarker(dest) == dest
