"""Fetch the MediaPipe FaceLandmarker model for the gaze backend.

A single ~3.7 MB TFLite model (``face_landmarker.task``) drives the iris-based
gaze estimate. It is cached under the user cache dir and downloaded once on first
use; everything afterwards is fully offline (ADR-011 — nothing leaves the machine
at run time).

The fetch is deliberately more careful than ``urlretrieve``. On a network whose IPv6
route black-holes, ``urlretrieve`` resolves the AAAA records first, has no timeout and
walks every dead address in turn, so the first run appears frozen for minutes while
``curl`` (which falls back to IPv4) finishes in a second. So: a connect timeout on every
address, IPv4 tried first, and a ``.part`` file that is checked and renamed into place so
a truncated download can never be cached as the model.
"""
from __future__ import annotations

import http.client
import os
import socket
import ssl
import urllib.request
from pathlib import Path

from platformdirs import PlatformDirs

# Pinned Google-hosted release asset (float16 FaceLandmarker bundle, incl. iris).
FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)

#: Seconds allowed per connect attempt and per socket read. Short enough that a dead
#: address costs a few seconds, long enough for a slow link to deliver 3.7 MB.
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 30.0

#: The real asset is ~3.76 MB. Anything far below that is an error page or a cut-off
#: transfer, and caching it would make the backend fail on every later start.
MIN_MODEL_BYTES = 1_000_000


def model_dir() -> Path:
    """Return the per-user cache directory holding gaze models."""
    dirs = PlatformDirs(appname="yazses", appauthor=False, ensure_exists=False)
    return Path(dirs.user_cache_dir) / "models"


def ipv4_first(infos: list) -> list:
    """Order ``getaddrinfo`` results so IPv4 comes before IPv6, otherwise stable.

    A broken IPv6 route is the common failure, IPv4 is the path that works on it, and a
    one-time model download has no use for IPv6's advantages.
    """
    return sorted(infos, key=lambda info: 0 if info[0] == socket.AF_INET else 1)


def connect_ipv4_first(host: str, port: int, timeout: float) -> socket.socket:
    """Open a TCP connection, trying IPv4 addresses first, each with its own timeout."""
    last: OSError | None = None
    for family, socktype, proto, _canon, addr in ipv4_first(
        socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ):
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(addr)
        except OSError as exc:
            last = exc
            sock.close()
            continue
        return sock
    raise last or OSError(f"no address found for {host}")


class _FallbackHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS over :func:`connect_ipv4_first`, with TLS verified as the default context does."""

    def connect(self) -> None:
        sock = connect_ipv4_first(self.host, self.port, CONNECT_TIMEOUT_S)
        sock.settimeout(READ_TIMEOUT_S)
        context = self._context  # type: ignore[attr-defined]
        self.sock = context.wrap_socket(sock, server_hostname=self.host)


class _FallbackHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self) -> None:
        super().__init__(context=ssl.create_default_context())

    def https_open(self, req):  # noqa: ANN001, ANN201
        return self.do_open(_FallbackHTTPSConnection, req, context=self._context)  # type: ignore[attr-defined]


def _open(url: str):  # noqa: ANN202
    """Open ``url`` with the fallback connection; split out so tests can replace it."""
    opener = urllib.request.build_opener(_FallbackHTTPSHandler())
    return opener.open(url, timeout=READ_TIMEOUT_S)  # noqa: S310 - fixed https asset


def _fetch(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest`` atomically, or raise and leave nothing behind."""
    part = dest.with_name(dest.name + ".part")
    try:
        with _open(url) as resp, open(part, "wb") as out:
            expected = resp.headers.get("Content-Length")
            written = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
        if written < MIN_MODEL_BYTES:
            raise OSError(f"model download too small ({written} bytes); not caching it")
        if expected is not None and expected.isdigit() and int(expected) != written:
            raise OSError(f"model download truncated ({written} of {expected} bytes)")
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)


def ensure_face_landmarker(dest: Path | None = None, *, echo=None) -> Path:
    """Return the FaceLandmarker model path, downloading it once if absent."""
    dest = dest or (model_dir() / "face_landmarker.task")
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if echo:
        echo(f"Downloading gaze model (~3.7 MB) → {dest} ...")
    _fetch(FACE_LANDMARKER_URL, dest)
    return dest
