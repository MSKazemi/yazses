"""Finding the socket ydotoold is really on, and refusing a dead one.

Debian/Ubuntu ship **ydotool 0.1.8**, which predates `--socket-path` and ignores it
silently. The unit `yazses setup` writes passes `--socket-path=%t/.ydotool_socket`;
0.1.8 starts anyway and listens on `/tmp/.ydotool_socket`. Verified on Ubuntu 24.04 —
`ydotoold --help` prints no help, it just runs and logs that path.

So probing only `$XDG_RUNTIME_DIR` answered "ydotool is not ready" on a machine where
ydotoold was installed, enabled and running, and dictation fell through to the portal
for a reason that had nothing to do with the portal.
"""

from __future__ import annotations

import os
import socket
import threading

import pytest

from yazses.inject import auto

_REAL_CANDIDATES = auto.ydotool_socket_candidates


@pytest.fixture
def live_socket(tmp_path):
    """A unix socket with a real acceptor behind it."""
    path = str(tmp_path / "live.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)

    stop = threading.Event()

    def _serve():
        server.settimeout(0.1)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
                conn.close()
            except OSError:
                continue

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    yield path
    stop.set()
    thread.join(timeout=2)
    server.close()


@pytest.fixture(autouse=True)
def _only_the_test_paths(monkeypatch):
    """Pin the candidate list to whatever the test sets.

    Without this the fallback candidate `/tmp/.ydotool_socket` is consulted — and on
    a developer machine running ydotoold that file really exists, so a test asserting
    "no socket is found" quietly found the host's. These tests passed in isolation and
    failed in the full suite, which is the signature of a test reading the host.
    """
    monkeypatch.setattr(
        auto, "ydotool_socket_candidates",
        lambda: [p for p in [os.environ.get("YDOTOOL_SOCKET")] if p],
    )


@pytest.fixture
def stale_socket(tmp_path):
    """A socket FILE with nothing behind it — what a dead ydotoold leaves."""
    path = str(tmp_path / "stale.sock")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(path)
    sock.close()  # the file survives; the listener does not
    assert os.path.exists(path)
    return path


@pytest.fixture
def real_candidates(monkeypatch):
    """Restore the genuine candidate builder for the tests that are about it."""
    monkeypatch.setattr(auto, "ydotool_socket_candidates", _REAL_CANDIDATES)


# ------------------------------------------------------------- candidates


def test_the_tmp_path_ubuntus_ydotoold_uses_is_a_candidate(real_candidates, monkeypatch):
    monkeypatch.delenv("YDOTOOL_SOCKET", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert "/tmp/.ydotool_socket" in auto.ydotool_socket_candidates()


def test_the_runtime_dir_is_preferred_over_tmp(real_candidates, monkeypatch):
    """/tmp is shared; the per-user runtime dir is the better home when both exist."""
    monkeypatch.delenv("YDOTOOL_SOCKET", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    candidates = auto.ydotool_socket_candidates()
    assert candidates.index("/run/user/1000/.ydotool_socket") < candidates.index(
        "/tmp/.ydotool_socket"
    )


def test_an_explicit_env_override_wins(real_candidates, monkeypatch):
    monkeypatch.setenv("YDOTOOL_SOCKET", "/custom/sock")
    assert auto.ydotool_socket_candidates()[0] == "/custom/sock"


def test_candidates_are_deduplicated(real_candidates, monkeypatch):
    monkeypatch.setenv("YDOTOOL_SOCKET", "/tmp/.ydotool_socket")
    candidates = auto.ydotool_socket_candidates()
    assert len(candidates) == len(set(candidates))


# ---------------------------------------------------------------- liveness


def test_a_live_socket_is_found(monkeypatch, live_socket):
    monkeypatch.setenv("YDOTOOL_SOCKET", live_socket)
    assert auto.find_ydotool_socket() == live_socket


def test_a_stale_socket_is_accepted_and_that_is_a_known_limit(monkeypatch, stale_socket):
    """A socket file outlives the daemon that bound it, and this check accepts it.

    Pinned deliberately rather than left unsaid. Telling a stale socket from a live
    one needs `connect()`, and reaching for `socket` here puts an outbound primitive
    into the injection hot path that `tests/test_egress_inventory.py` fails the build
    over (ADR-019). Registering an AF_UNIX connect as network egress to get past that
    guard would put a false line in an inventory whose whole value is that every line
    is true.

    It would also not have bought what it looks like it buys: a ydotoold that cannot
    open /dev/uinput binds the socket *first*, then aborts and restarts every two
    seconds, so a connect lands in a live window and answers yes regardless. What
    protects the user here is `fallback_to_clipboard`, not a cleverer probe.
    """
    monkeypatch.setenv("YDOTOOL_SOCKET", stale_socket)
    assert auto.find_ydotool_socket() == stale_socket


def test_a_missing_socket_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("YDOTOOL_SOCKET", str(tmp_path / "nope.sock"))
    assert auto.find_ydotool_socket() is None


def test_readiness_needs_both_the_binary_and_a_live_socket(monkeypatch, live_socket):
    monkeypatch.setenv("YDOTOOL_SOCKET", live_socket)
    # The uinput gate is a separate dimension, tested below; hold it open here so
    # this case is about the binary and the socket alone.
    monkeypatch.setattr(auto, "own_ydotoold_can_reach_uinput", lambda: True)
    monkeypatch.setattr(auto.shutil, "which", lambda _n: None)
    assert auto.ydotool_ready() is False

    monkeypatch.setattr(auto.shutil, "which", lambda n: f"/usr/bin/{n}")
    assert auto.ydotool_ready() is True


def test_a_socket_we_own_but_no_uinput_access_is_not_ready(monkeypatch, live_socket):
    """The state a real machine was found in: ydotoold installed and enabled, socket
    present, and /dev/uinput still 0600 root:root — so the daemon bound the socket,
    printed "listening", then aborted, 726 times. Choosing ydotool there loses the
    burst to a backend that cannot type."""
    monkeypatch.setenv("YDOTOOL_SOCKET", live_socket)
    monkeypatch.setattr(auto.shutil, "which", lambda n: f"/usr/bin/{n}")
    # Only /dev/uinput is denied — patching os.access wholesale would also break the
    # socket discovery this test depends on, and pass for the wrong reason.
    real_access = auto.os.access
    monkeypatch.setattr(
        auto.os, "access",
        lambda path, mode: False if str(path) == "/dev/uinput" else real_access(path, mode),
    )
    assert auto.ydotool_ready() is False


def test_a_root_owned_socket_is_not_judged_by_our_uinput_access(monkeypatch, live_socket):
    """A ydotoold run as root from a system unit opens the device with privileges we
    neither have nor need — demanding our own access would reject a working setup."""
    monkeypatch.setenv("YDOTOOL_SOCKET", live_socket)
    monkeypatch.setattr(auto.shutil, "which", lambda n: f"/usr/bin/{n}")
    real_access = auto.os.access
    monkeypatch.setattr(
        auto.os, "access",
        lambda path, mode: False if str(path) == "/dev/uinput" else real_access(path, mode),
    )
    monkeypatch.setattr(auto.os, "geteuid", lambda: 999999)  # not the socket's owner
    assert auto.ydotool_ready() is True


def test_probing_never_raises_on_a_path_that_is_not_a_socket(monkeypatch, tmp_path):
    """A regular file at the socket path must answer 'no', not explode."""
    plain = tmp_path / "regular.txt"
    plain.write_text("not a socket", encoding="utf-8")
    monkeypatch.setenv("YDOTOOL_SOCKET", str(plain))
    assert auto.find_ydotool_socket() is None


# ------------------------------------------------- selection pins the client


def test_selecting_ydotool_pins_the_client_to_the_socket_found(monkeypatch, live_socket):
    """Both halves of ydotool default to the same place, so this is usually a no-op --
    but when they disagree, the backend is chosen because a socket exists and then
    cannot reach it."""
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("YDOTOOL_SOCKET", live_socket)
    monkeypatch.setattr(auto.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(auto, "own_ydotoold_can_reach_uinput", lambda: True)

    injector = auto.get_injector("auto")

    assert type(injector).__name__ == "YdotoolInjector"
    assert os.environ["YDOTOOL_SOCKET"] == live_socket
