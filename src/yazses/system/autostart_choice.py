"""Remember that the user turned autostart off.

`yazses start` sets autostart up when it is missing (``cli._ensure_autostart``), so a
pipx, uv-tool or Scoop install survives a reboot the way a packaged install does. But
"never set up" and "the user ran `yazses autostart disable`" both look like a missing
entry, so the next `yazses start` quietly put it back, and then told the user to run
`yazses autostart disable` to undo it: the command they had just run. `doctor` had the
same blind spot and listed the choice as "1 problem to fix", every time, forever.

The choice is a marker file beside the other per-user state. Present means "off on
purpose"; `yazses autostart enable` removes it. Reading is total: a data directory
that cannot be read counts as no choice recorded, which is exactly the behaviour
before this module existed.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

FILENAME = "autostart-off"

_CONTENT = (
    "YazSes does not start at login: this was turned off with `yazses autostart disable`.\n"
    "`yazses autostart enable` turns it back on and removes this file.\n"
)


def opted_out(data_dir: Path) -> bool:
    """True when the user turned autostart off and has not turned it back on."""
    try:
        return (data_dir / FILENAME).is_file()
    except OSError:
        return False


def record_opt_out(data_dir: Path) -> None:
    """Remember the choice. Raises OSError when the directory cannot be written."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / FILENAME).write_text(_CONTENT, encoding="utf-8")


def clear_opt_out(data_dir: Path) -> None:
    """Forget the choice; a no-op when none was recorded."""
    try:
        (data_dir / FILENAME).unlink(missing_ok=True)
    except OSError:
        log.warning("Could not remove %s", data_dir / FILENAME, exc_info=True)
