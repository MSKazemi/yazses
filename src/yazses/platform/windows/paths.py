"""Windows paths — %APPDATA% (config) and %LOCALAPPDATA% (cache, logs)."""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

from yazses.platform.base import Paths

_APP = "yazses"


def build_paths() -> Paths:
    # appauthor=False so platformdirs doesn't insert a vendor segment ("MSKazemi")
    # into the path; users get %APPDATA%\yazses\ directly.
    dirs = PlatformDirs(appname=_APP, appauthor=False, ensure_exists=False)
    return Paths(
        config_dir=Path(dirs.user_config_dir),
        # Use roaming config dir for state too — small files (PID, pipe metadata).
        state_dir=Path(dirs.user_config_dir),
        cache_dir=Path(dirs.user_cache_dir),
        log_dir=Path(dirs.user_log_dir),
        data_dir=Path(dirs.user_data_dir),
    )
