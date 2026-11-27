"""One settings window per user and config file: who opens it, and what a second launch says. Pure.

Two windows editing one ``config.toml`` can overwrite each other's settings, so a second
launch (the tray, ``yazses settings``, the app grid) opens nothing: it asks the window that is
already open to come to the front, on the page it was asked for, and exits.

Who is first is decided by an operating-system file lock
(:mod:`yazses.system.single_instance`), which is freed when its holder exits *or crashes*.
The local socket is only how the later launch talks to the holder, so a socket file a crashed
window left behind decides nothing.

No Qt and no I/O here; the lock, the socket and the window are
:mod:`yazses.settingsui.single_window_qt`.
"""
from __future__ import annotations

import enum
import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from yazses.settingsui.pages import resolve_page

#: How long a later launch keeps trying. Long enough for a window that is still being built.
WAIT_S = 10.0
#: The pause between attempts while the holder is starting up or on its way out.
RETRY_S = 0.1
#: A request is one short line; anything longer is not ours.
MAX_REQUEST_BYTES = 4096
#: What the open window answers once it has acted.
ACK = b"ok\n"
#: The token a Wayland compositor hands a launched program so it may take the focus.
ACTIVATION_ENV = "XDG_ACTIVATION_TOKEN"
_MAX_TOKEN = 1024

ALREADY_OPEN = "YazSes Settings is already open; it was asked to come to the front."


@dataclass(frozen=True)
class ShowRequest:
    """What a later launch asks of the open window."""

    #: A page key, or "" to leave the window on the page it shows.
    page: str = ""
    #: The later launch's activation token, or "".
    token: str = ""


class Outcome(enum.Enum):
    OWNER = "owner"  # open the window
    FORWARDED = "forwarded"  # the open window took the request
    UNANSWERED = "unanswered"  # another process holds the lock and did not answer


def encode_request(request: ShowRequest) -> bytes:
    """*request* as one line. ``json`` escapes newlines, so the line cannot be split."""
    payload = {"page": request.page, "token": request.token[:_MAX_TOKEN]}
    return json.dumps(payload).encode("ascii") + b"\n"


def decode_request(line: bytes) -> ShowRequest | None:
    """The request in *line*, or ``None`` if it is not one. Never raises.

    A page this version does not know becomes "": the window still comes to the front.
    """
    if len(line) > MAX_REQUEST_BYTES:
        return None
    try:
        payload = json.loads(line.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None
    page, token = payload.get("page"), payload.get("token", "")
    if not isinstance(page, str) or not isinstance(token, str):
        return None
    if len(token) > _MAX_TOKEN or not token.isprintable():
        token = ""
    return ShowRequest(resolve_page(page) or "", token)


def instance_tag(config_file: Path, user: str) -> str:
    """A short name for "this user's window on this config file".

    Part of the lock file's and the socket's names: a window on a throw-away config does not
    answer for the real one, and two users never share a Windows pipe name.
    """
    identity = f"{user}\0{os.path.normcase(os.path.abspath(config_file))}"
    return hashlib.sha256(identity.encode("utf-8", "surrogateescape")).hexdigest()[:12]


def lock_file(data_dir: Path, tag: str) -> Path:
    """The lock lives in the data directory, which does not move with the session."""
    return data_dir / f"settings-window-{tag}.lock"


def unanswered_message(holder: int | None) -> str:
    process = f" (process {holder})" if holder is not None and holder > 0 else ""
    return (
        "YazSes Settings is already open but did not answer, so a second window was not "
        f"opened.\nSwitch to the open window, or close it{process} and try again."
    )


def claim(
    acquire: Callable[[], bool],
    forward: Callable[[float], bool],
    *,
    wait_s: float = WAIT_S,
    retry_s: float = RETRY_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Outcome:
    """Become the window, or hand the request to the one that is open.

    *acquire* tries the lock; *forward* is given the seconds left and says whether the open
    window answered. Both are retried: a holder that has the lock but no socket yet is
    starting, and one that stops answering may be exiting, which frees the lock.
    """
    deadline = clock() + wait_s
    while True:
        if acquire():
            return Outcome.OWNER
        if forward(max(0.0, deadline - clock())):
            return Outcome.FORWARDED
        if clock() >= deadline:
            return Outcome.UNANSWERED
        sleep(retry_s)
