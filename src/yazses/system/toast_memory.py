"""Remember which warnings have already been shown, across daemon restarts.

`diagnosis.should_notify` rate-limits repeats correctly *within* one process, and
that covers the case it was written for: a microphone that fails on every burst must
not produce five identical toasts in a minute.

It cannot cover the case that matters at startup. `contrib/yazses.service` sets
``Restart=on-failure`` with ``StartLimitBurst=5`` inside ``StartLimitIntervalSec=60``,
so a fault that kills the daemon during startup gets five *fresh processes* in a
minute -- five empty in-memory dicts, and five identical toasts for one problem. That
is precisely the outcome ``REPEAT_SILENCE_S`` exists to prevent, arriving through the
one door it could not see.

**Wall clock, not monotonic.** `time.monotonic()` is measured from an arbitrary
origin that resets with the process, so persisting it across restarts would compare
two unrelated number lines. The trade is that a clock jump (NTP, a laptop waking,
a timezone-less RTC) can suppress a warning slightly early or release one slightly
late; a few minutes of imprecision on a 5-minute silence is worth far less than the
crash-loop spam it buys.

Total, like the rest of this layer: a corrupt, unreadable or absent file reads as
"nothing has been shown yet", which errs toward *speaking* rather than toward
silence. A warning shown twice is a nuisance; a warning swallowed because a JSON
file had a stray byte is the failure this whole subsystem exists to prevent.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

FILENAME = "shown_notices.json"

#: Entries older than this are dropped on save. Without it the file grows one key
#: per distinct fault forever, and a slug that fired once a year ago is not
#: information -- it is just something to carry.
KEEP_S = 7 * 24 * 60 * 60


def path_for(data_dir: Path | str) -> Path:
    return Path(data_dir) / FILENAME


def load(path: Path | str) -> dict[str, float]:
    """What has been shown, and when (epoch seconds). Never raises."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        # A hand-edited or partially-written file can carry anything. Keep the
        # rows that still mean something rather than discarding the whole record.
        if isinstance(key, str) and isinstance(value, (int, float)):
            out[key] = float(value)
    return out


def prune(state: dict[str, float], now: float, *, keep_s: float = KEEP_S) -> dict[str, float]:
    """Drop entries too old to affect any decision. Pure."""
    return {k: v for k, v in state.items() if now - v < keep_s}


def save(path: Path | str, state: dict[str, float], *, now: float | None = None) -> None:
    """Persist *state*. Never raises — a warning we could not record is still shown.

    Written to a temporary file in the same directory and then renamed, because the
    daemon is killed at arbitrary moments by exactly the crash loop this file exists
    to damp: a half-written JSON on that path would read back as "{}" and re-arm
    every toast it was meant to suppress.
    """
    import time as _time

    target = Path(path)
    kept = prune(state, _time.time() if now is None else now)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".notices-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(kept, handle)
            os.replace(tmp, target)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as exc:  # pragma: no cover - disk/permission edge
        log.debug("could not persist the shown-notice record: %s", exc)


__all__ = ["FILENAME", "KEEP_S", "load", "path_for", "prune", "save"]
