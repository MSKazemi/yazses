"""Windows paths — everything under %LOCALAPPDATA%\\yazses.

Note this is *local*, not roaming, despite the ``%APPDATA%`` shorthand often
used for it: platformdirs picks ``CSIDL_LOCAL_APPDATA`` unless ``roaming=True``
is passed, and it is not. That is the behaviour we want — the PID file and the
IPC metadata describe *this machine*, so a roaming profile syncing them to
another PC would make ``yazses status`` report on a daemon that is not here.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

from yazses.platform.base import Paths

_APP = "yazses"


def build_paths() -> Paths:
    # appauthor=False so platformdirs doesn't insert a vendor segment ("MSKazemi")
    # into the path; users get %LOCALAPPDATA%\yazses\ directly (see the module
    # docstring for why it is Local rather than Roaming).
    dirs = PlatformDirs(appname=_APP, appauthor=False, ensure_exists=False)
    return Paths(
        config_dir=Path(dirs.user_config_dir),
        # State sits beside config — small, machine-local files (PID, pipe
        # metadata). Both resolve to %LOCALAPPDATA%\yazses; see the module
        # docstring for why local rather than roaming matters here.
        state_dir=Path(dirs.user_config_dir),
        cache_dir=Path(dirs.user_cache_dir),
        log_dir=Path(dirs.user_log_dir),
        data_dir=Path(dirs.user_data_dir),
    )
