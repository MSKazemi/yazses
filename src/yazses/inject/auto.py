import os
import shutil

from yazses.inject.base import BaseInjector

# Re-exported on purpose, not leftovers. `inject/registry.py` probes call
# `auto.portal_available()` rather than importing it from `portal` directly, and the
# suite patches these names here -- one seam instead of two that can disagree.
# `ruff --fix` will prune them as unused without the noqa.
from yazses.inject.portal import portal_available  # noqa: F401


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


def ydotool_socket_candidates() -> list[str]:
    """Every path ydotoold might be listening on, best first.

    Debian/Ubuntu ship **ydotool 0.1.8**, which predates `--socket-path` and
    ignores it silently: the unit `yazses setup` writes passes
    `--socket-path=%t/.ydotool_socket`, and 0.1.8 starts anyway and logs
    "listening on socket /tmp/.ydotool_socket". Verified on Ubuntu 24.04 —
    `ydotoold --help` does not print help, it just runs.

    So probing only `$XDG_RUNTIME_DIR` answered "ydotool is not ready" on a machine
    where ydotoold was installed, enabled and running, and dictation fell through to
    the portal for a reason that had nothing to do with the portal. The `/tmp` socket
    is created `0600` by the user's own daemon, so preferring the runtime dir but
    accepting `/tmp` costs nothing: a socket another user owns is not ours to use,
    and `os.access` below keeps it that way.
    """
    seen: list[str] = []
    explicit = os.environ.get("YDOTOOL_SOCKET")
    if explicit:
        seen.append(explicit)
    seen.append(ydotool_socket_path())
    seen.append("/tmp/.ydotool_socket")
    out: list[str] = []
    for path in seen:
        if path and path not in out:
            out.append(path)
    return out


def _is_socket(path: str) -> bool:
    """True when *path* is a unix socket rather than an ordinary file.

    Deliberately a `stat`, not a `connect`. A connect probe would distinguish a
    stale socket file from a live one, which is a real distinction -- but reaching
    for `socket` here puts an outbound primitive into the injection hot path, and
    `tests/test_egress_inventory.py` fails the build for exactly that (ADR-019).
    Registering an AF_UNIX connect as network egress to satisfy the guard would be
    a false entry in an inventory whose value is that every line in it is true.

    It would also not have bought what it looked like it bought: measured on the
    machine this was written for, a ydotoold that cannot open /dev/uinput *binds the
    socket first*, prints "listening", then aborts -- 726 restarts at two seconds
    apart -- so a connect lands in a live window and answers yes anyway. The cure
    for that state is the udev rule `yazses setup` installs. If it is hit regardless,
    injection fails and `fallback_to_clipboard` carries the burst.
    """
    import stat as _stat

    try:
        return _stat.S_ISSOCK(os.stat(path).st_mode)
    except OSError:
        return False


def find_ydotool_socket() -> str | None:
    """The socket ydotoold is actually listening on, or None. Never raises."""
    for path in ydotool_socket_candidates():
        try:
            if not os.path.exists(path):
                continue
            if not os.access(path, os.R_OK | os.W_OK):
                continue
            if _is_socket(path):
                return path
        except OSError:  # pragma: no cover - a stat that cannot run is a "no"
            continue
    return None


def ydotool_ready() -> bool:
    """True only when ydotool is installed AND ydotoold's socket is present.

    ydotool is useless without a running ydotoold (it fails with
    "failed to connect socket ... ydotool_socket"). Gating selection on the
    socket means we only pick ydotool when it will actually work, and otherwise
    fall through to wtype/clipboard.

    Writability, not mere existence: a stale socket left by a crashed ydotoold
    still stats fine, and choosing ydotool on the strength of it would lose the
    user's words to a backend that cannot deliver them.

    The uinput check belongs here rather than in the caller so there is exactly ONE
    readiness function: `doctor` and `get_injector` both consult it, and a second
    check outside it is how the two come to name different backends.
    """
    if not shutil.which("ydotool"):
        return False
    if find_ydotool_socket() is None:
        return False
    return own_ydotoold_can_reach_uinput()


def own_ydotoold_can_reach_uinput() -> bool:
    """False when *our own* ydotoold provably cannot type, whatever its socket says.

    A socket file is not a working daemon. Measured on a real machine: ydotoold
    binds the socket, prints "listening", then aborts because /dev/uinput is
    `0600 root:root` -- 726 restarts -- leaving a socket that passes every cheap
    check while nothing behind it can inject. Selecting ydotool there sends the
    user's words to a backend that drops them.

    Only applied to a **user-owned** socket. A ydotoold run as root from a system
    unit opens the device with privileges we neither have nor need, and demanding
    our own access would wrongly reject a setup that works.
    """
    if not hasattr(os, "geteuid"):  # pragma: no cover - non-POSIX
        return True
    path = find_ydotool_socket()
    if path is None:
        return True
    try:
        if os.stat(path).st_uid != os.geteuid():
            return True  # someone else's daemon; its device access is its business
    except OSError:  # pragma: no cover
        return True
    try:
        return os.access("/dev/uinput", os.W_OK)
    except OSError:  # pragma: no cover
        return True


def wl_copy_ready() -> bool:
    """True when wl-copy is installed — required for clipboard-paste injection."""
    return bool(shutil.which("wl-copy"))


def get_injector(prefer: str = "auto") -> BaseInjector:
    """Select an injection backend.

    ``prefer`` = ``"auto"`` (default) | ``"type"``/``"ydotool"`` | ``"clipboard"``
    | ``"wtype"`` | ``"portal"`` | ``"unicode"``. With ``"auto"`` an override may be
    supplied via the ``YAZSES_INJECTOR`` environment variable.

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

    from yazses.inject import registry

    env = registry.Env.detect(
        prefer,
        consent=(os.environ.get("YAZSES_PORTAL_CONSENT", "ask") or "ask"),
    )
    chosen = registry.select(env).chosen

    if chosen.name == "ydotool":
        # Pin the client to the socket the daemon is really on. Both halves of
        # ydotool default to the same place, so this is usually a no-op -- but
        # when it is not (a 0.1.8 daemon on /tmp while the client looks in
        # XDG_RUNTIME_DIR, or the reverse), the failure is a backend that was
        # selected because a socket exists and then cannot reach it.
        found = find_ydotool_socket()
        if found:
            os.environ["YDOTOOL_SOCKET"] = found

    return registry.build(chosen)


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
    # Same bridge, same reason: the three commands whose job is to test the injector
    # must see the same consent the daemon does, or `yazses inject` demonstrates a
    # backend the daemon will not choose.
    consent = (getattr(injection, "portal_consent", "") or "ask").strip().lower()
    os.environ["YAZSES_PORTAL_CONSENT"] = consent


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
