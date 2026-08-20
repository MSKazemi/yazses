import os
import shutil

from yazses.inject.base import BaseInjector
from yazses.inject.clipboard import ClipboardInjector
from yazses.inject.wtype import WtypeInjector
from yazses.inject.xdotool import XdotoolInjector
from yazses.inject.ydotool import YdotoolInjector


def ydotool_socket_path() -> str:
    """The socket path ydotool's client uses (env override, else the default)."""
    sock = os.environ.get("YDOTOOL_SOCKET")
    if sock:
        return sock
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        # os.getuid is Unix-only; ydotool is Linux-only anyway, but keep this
        # importable/callable on Windows so cross-platform tests don't crash.
        uid = os.getuid() if hasattr(os, "getuid") else 0
        runtime = f"/run/user/{uid}"
    return os.path.join(runtime, ".ydotool_socket")


def ydotool_ready() -> bool:
    """True only when ydotool is installed AND ydotoold's socket is present.

    ydotool is useless without a running ydotoold (it fails with
    "failed to connect socket ... ydotool_socket"). Gating selection on the
    socket means we only pick ydotool when it will actually work, and otherwise
    fall through to wtype/clipboard.
    """
    return bool(shutil.which("ydotool")) and os.path.exists(ydotool_socket_path())


def wl_copy_ready() -> bool:
    """True when wl-copy is installed — required for clipboard-paste injection."""
    return bool(shutil.which("wl-copy"))


def get_injector(prefer: str = "auto") -> BaseInjector:
    """Select an injection backend.

    ``prefer`` = ``"auto"`` (default) | ``"type"``/``"ydotool"`` | ``"clipboard"``
    | ``"wtype"``. With ``"auto"`` an override may be supplied via the
    ``YAZSES_INJECTOR`` environment variable.

    On Wayland, ``auto`` **types** the text with ydotool — this works in *every*
    focused app, terminals included, and does not touch the clipboard.
    ``YdotoolInjector`` guards against the Ubuntu-26+ compositor occasionally
    dropping the final key-up (which otherwise leaves the last character
    auto-repeating — the ``mmmm…`` flood). ``clipboard`` forces wl-copy + Ctrl+V,
    which is instant but is a no-op in terminals (where Ctrl+V is literal) and
    overwrites the clipboard.
    """
    prefer = (prefer or "auto").strip().lower()
    if prefer == "auto":
        prefer = (os.environ.get("YAZSES_INJECTOR", "auto") or "auto").strip().lower()

    if prefer == "clipboard":
        return ClipboardInjector()

    is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    if is_wayland:
        if prefer == "wtype" and shutil.which("wtype"):
            return WtypeInjector()
        # auto / type / ydotool: prefer typing — works everywhere, incl. terminals.
        if ydotool_ready():
            return YdotoolInjector()
        if shutil.which("wtype"):
            return WtypeInjector()
    else:
        if shutil.which("xdotool"):
            return XdotoolInjector()
    return ClipboardInjector()


def apply_injection_config(injection: object) -> None:
    """Bridge ``[injection]`` into the environment `get_injector` reads.

    The two settings reach the backend through environment variables rather than a
    factory argument, because `platform.injector_factory` is a zero-argument protocol
    and every OS implements it. That is a reasonable design and it had one consequence
    nobody wired: **only the daemon set them**.

    So `yazses inject`, `yazses test` and `yazses verify --type` -- all three of them
    commands whose stated job is to *test the injector* -- built one with `auto`
    whatever the config said. A user who set ``backend = "clipboard"`` because typing
    does not reach their app had the three commands that would have shown that pick
    ydotool instead, and the one that certifies the pipeline (`verify --type`) certified
    a backend the daemon does not use.

    Idempotent, and only ever sets: an explicit ``auto`` must not clobber a
    ``YAZSES_INJECTOR`` the user exported into the shell, which is the documented way
    to override for one run.
    """
    backend = (getattr(injection, "backend", "") or "auto").strip().lower()
    if backend and backend != "auto":
        os.environ["YAZSES_INJECTOR"] = backend
    os.environ["YAZSES_INJECT_FALLBACK"] = (
        "1" if getattr(injection, "fallback_to_clipboard", True) else "0"
    )


def describe_injector(injector: object) -> str:
    """The concrete backend in use, not the wrapper that chose it.

    `LinuxInjector` is a selector: on this machine it wraps `XdotoolInjector`, and
    `type(...).__name__` says "LinuxInjector" -- true, useless, and identical on a box
    where the answer is `ClipboardInjector`. The daemon already preferred
    ``backend_name`` for exactly this reason (`status`, `doctor`); the CLI printed the
    wrapper, so `yazses inject` reported a backend that told the user nothing and could
    not be compared with what `yazses status` reported for the same machine.
    """
    return getattr(injector, "backend_name", None) or type(injector).__name__
