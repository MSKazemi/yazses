"""Platform detection — picks the right concrete backend bundle."""

from __future__ import annotations

import sys
from functools import lru_cache

from yazses.platform.base import (
    FileOpener,
    HostInfo,
    PackRuntime,
    Paths,
    Platform,
    UnsupportedPlatformError,
    UrlOpener,
)

# What still works when there is no OS backend at all. Roughly half of YazSes
# never touches the platform layer: transcribing a file, and the text commands,
# are pure CPU work. A user on an unsupported system should be told that instead
# of being handed a traceback, because "it doesn't run here" and "the hold-to-talk
# half doesn't run here" are very different answers.
OS_INDEPENDENT_COMMANDS = (
    "yazses transcribe <file>   offline transcription of any audio/video file",
    "yazses reflow / table / shellpipe / gitvoice / braille / case",
    "yazses about / --version / --help",
)


def _unsupported(platform_name: str) -> UnsupportedPlatformError:
    """The error for a system with no backend, written to be actionable."""
    return UnsupportedPlatformError(
        f"YazSes has no hold-to-talk backend for sys.platform={platform_name!r}.\n"
        "Supported: Linux, macOS, Windows, and (experimental) FreeBSD / OpenBSD / "
        "NetBSD / DragonFly.\n\n"
        "These still work here, because they need no OS integration:\n"
        + "\n".join(f"  {line}" for line in OS_INDEPENDENT_COMMANDS)
        + "\n\nAdding a platform is contained: implement the Protocol interfaces in "
        "src/yazses/platform/<os>/ and register the sys.platform value in "
        "platform/factory.py. https://github.com/MSKazemi/yazses/issues"
    )


@lru_cache(maxsize=1)
def get_platform() -> Platform:
    if sys.platform == "linux":
        from yazses.platform.linux import build_platform
        return build_platform()
    if sys.platform == "darwin":
        from yazses.platform.macos import build_platform  # noqa: F401  (Phase 1)
        return build_platform()
    if sys.platform == "win32":
        from yazses.platform.windows import build_platform  # noqa: F401  (Phase 2)
        return build_platform()
    # Prefix match, not equality: sys.platform on a BSD carries the major version
    # ("freebsd14", "openbsd7"), so `== "freebsd"` would never fire.
    from yazses.platform.bsd import is_bsd

    if is_bsd():
        from yazses.platform.bsd import build_platform  # noqa: F811
        return build_platform()
    raise _unsupported(sys.platform)


def describe_host() -> HostInfo:
    """Facts about this machine's OS, resolvable on **any** OS and never cached.

    The seam for code that only needs to *describe* the host -- the camera packaging
    detector and the eye-control provenance collector -- so it does not branch on
    ``sys.platform`` itself. It is deliberately not `get_platform().host`: building a
    `Platform` imports the hotkey, injector and IPC stacks and raises on an OS with no
    backend, while a description is wanted precisely on the odd machines (a BSD, a CI
    runner, an unsupported OS) where a bug report must still say what it ran on. Each
    backend module imported here is light and import-safe; the heavy ones stay behind
    `build_platform`.

    Not cached because the answer is read from process state (`sys.platform`, files in
    `/etc`) that tests legitimately swap, and callers call it a handful of times per run.
    """
    if sys.platform == "darwin":
        from yazses.platform.macos.host import MacosHost
        return MacosHost().describe()
    if sys.platform == "win32":
        from yazses.platform.windows.host import WindowsHost
        return WindowsHost().describe()
    # Linux, the BSDs (which reuse the Linux backend wholesale) and any OS with no backend:
    # the Linux reader degrades to `platform.system()`/`release()` where /etc/os-release is
    # absent, and every one of its reads is optional.
    from yazses.platform.linux.host import LinuxHost
    return LinuxHost().describe()


def get_file_opener() -> FileOpener:
    """The "open with the default app" backend for this OS, for ``yazses fileopen``.

    Like :func:`describe_host`, a seam of its own rather than a field of `Platform`:
    opening a file needs no hotkey, injector or IPC stack, so building one should not
    import them. The BSDs share the Linux opener, as they share the rest of the Linux
    backend. An OS with no backend is refused with ``NotImplementedError`` naming
    ``sys.platform``, which is what ``yazses fileopen`` has always raised there.
    """
    from yazses.platform.bsd import is_bsd

    if sys.platform.startswith("linux") or is_bsd():
        from yazses.platform.linux.fileopen import LinuxFileOpener
        return LinuxFileOpener()
    if sys.platform == "darwin":
        from yazses.platform.macos.fileopen import MacosFileOpener
        return MacosFileOpener()
    if sys.platform == "win32":
        from yazses.platform.windows.fileopen import WindowsFileOpener
        return WindowsFileOpener()
    raise NotImplementedError(f"Unsupported platform: {sys.platform}")


def get_url_opener() -> UrlOpener:
    """The "hand this URL to its registered program" backend for this OS (ADR-031 §3).

    Built for "send to", whose URL carries the user's dictation; see
    :class:`~yazses.platform.base.UrlOpener` for the rules every backend keeps. A seam of
    its own, like :func:`get_file_opener` and for the same reason: a CLI hand-off should
    not import the hotkey, injector or IPC stacks. The BSDs share the Linux opener
    (``xdg-open``). An OS with no backend is refused with ``NotImplementedError`` naming
    ``sys.platform`` -- the caller reports that as a failed hand-off, never as a fallback
    to a browser.
    """
    from yazses.platform.bsd import is_bsd

    if sys.platform.startswith("linux") or is_bsd():
        from yazses.platform.linux.fileopen import LinuxUrlOpener
        return LinuxUrlOpener()
    if sys.platform == "darwin":
        from yazses.platform.macos.fileopen import MacosUrlOpener
        return MacosUrlOpener()
    if sys.platform == "win32":
        from yazses.platform.windows.fileopen import WindowsUrlOpener
        return WindowsUrlOpener()
    raise NotImplementedError(f"Unsupported platform: {sys.platform}")


def get_pack_runtime() -> PackRuntime:
    """The add-on pack backend for this OS (ADR-028 §2), resolvable on **any** OS.

    Like `describe_host`, deliberately not part of `get_platform()`: the PyInstaller
    runtime hook calls this before `main` runs, in every YazSes process, and building a
    `Platform` would import the hotkey, injector and IPC stacks first. Each module
    imported here is light. Every OS without a pack loader answers `supported() ->
    False`, so callers never need to know which those are.
    """
    if sys.platform == "win32":
        from yazses.platform.windows.packs import WindowsPackRuntime
        return WindowsPackRuntime()
    if sys.platform == "darwin":
        from yazses.platform.macos.packs import MacosPackRuntime
        return MacosPackRuntime()
    from yazses.platform.linux.packs import UnsupportedPackRuntime
    return UnsupportedPackRuntime()


def get_pack_paths() -> Paths:
    """Directory layout for the pack loader, without building a `Platform`.

    `get_paths()` goes through `get_platform()` first, which is exactly the heavy import
    the runtime hook must avoid. On Windows `build_paths` is a `platformdirs` call, so it
    is used directly; everywhere else (no pack loader) `get_paths()` is fine.
    """
    if sys.platform == "win32":
        from yazses.platform.windows.paths import build_paths
        return build_paths()
    return get_paths()


@lru_cache(maxsize=1)
def get_paths() -> Paths:
    """Directory layout, resolvable on **any** OS.

    Where a backend exists this is exactly `get_platform().paths`, so macOS keeps
    `~/Library/Application Support` and Windows keeps `%LOCALAPPDATA%` (Local, not
    Roaming -- see `platform/windows/paths.py`). Where one does
    not, it falls back to `platformdirs` directly — which has a sensible answer
    for every OS it runs on.

    This exists because the OS-independent half of YazSes (`transcribe`, the text
    commands) needs somewhere to read config from and nothing else from the
    platform layer. Routing those through `get_platform()` made them raise
    `UnsupportedPlatformError` — while that very error told the user
    `yazses transcribe` still worked here. It did not. Paths are not a backend;
    asking for one to get a directory is what created the contradiction.
    """
    try:
        return get_platform().paths
    except UnsupportedPlatformError:
        pass

    from pathlib import Path

    from platformdirs import PlatformDirs

    dirs = PlatformDirs(appname="yazses", appauthor=False, ensure_exists=False)
    return Paths(
        config_dir=Path(dirs.user_config_dir),
        state_dir=Path(dirs.user_runtime_dir or dirs.user_state_dir),
        cache_dir=Path(dirs.user_cache_dir),
        log_dir=Path(dirs.user_log_dir),
        data_dir=Path(dirs.user_data_dir),
    )


def reset_platform_cache() -> None:
    """Drop the cached Platform — useful in tests that swap sys.platform."""
    get_platform.cache_clear()
    get_paths.cache_clear()
