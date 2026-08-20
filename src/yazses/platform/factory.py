"""Platform detection — picks the right concrete backend bundle."""

from __future__ import annotations

import sys
from functools import lru_cache

from yazses.platform.base import Paths, Platform, UnsupportedPlatformError

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
