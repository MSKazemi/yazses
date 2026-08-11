"""A single, dismissible pointer back to the project after something works.

Why this exists
---------------
PyPI reports ~583 real downloads a week (mirror traffic excluded) against 4 GitHub
stars. Those numbers are not in tension because the software is disliked -- they are in
tension because **nothing in the product ever mentions that the project exists**. Someone
installs it, dictates into their editor, is happy, and has no reason to load a web page
again. The loop is open, and no amount of promotion closes it; only the product can.

The rules this module exists to enforce
---------------------------------------
This is the part of growth work that most easily turns into user-hostile nagging, so the
constraints are encoded here rather than left to the caller's good intentions:

1. **Nothing is ever sent anywhere.** There is no network code in this module and there
   must never be. A tool whose entire pitch is "your voice never leaves your machine"
   cannot measure its users, and a counter that phoned home would discredit the claim the
   project is built on. The only state is a local marker file.
2. **Only after something succeeded.** Never on failure, never on first launch, never
   during a task. Asking someone for attention while they are trying to fix a broken
   microphone is how you earn an uninstall.
3. **Once, ever.** The marker is written the first time it shows. There is no second
   showing, no "remind me later", no re-arming on upgrade.
4. **Trivially silenceable in advance**, for people who script this tool or who simply do
   not want it: ``YAZSES_NO_NUDGE=1``.
5. **No star-begging.** It points at where to report problems and how to help, which is
   information a new user genuinely lacks. Asking strangers for stars is the kind of
   signal-manufacturing this project does not do.

Everything here is pure except :func:`mark_shown`, so the policy is testable without a
filesystem.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["MARKER_NAME", "message", "mark_shown", "should_show"]

MARKER_NAME = "shown-project-pointer"

# Kept deliberately short. This appears after a success, so it is competing with the
# user's actual task; three lines they read once is the whole budget.
_MESSAGE = """\
  ─────────────────────────────────────────────────────────────────
  YazSes is free and open source, built in the open by a handful of
  people. If it misheard you, that is a bug worth reporting — those
  reports are what makes it better:

      Report a problem   https://github.com/MSKazemi/yazses/issues
      Help out           https://mskazemi.com/yazses/contribute/start.html

  Shown once. Set YAZSES_NO_NUDGE=1 to disable these entirely.
  ─────────────────────────────────────────────────────────────────"""


def message() -> str:
    """The text to show. Constant -- exposed as a function so callers cannot mutate it."""
    return _MESSAGE


def should_show(
    data_dir: Path,
    *,
    succeeded: bool,
    interactive: bool = True,
    env: dict[str, str] | None = None,
) -> bool:
    """Decide whether to show the pointer.

    Every condition is a veto, so adding a future reason to stay quiet cannot
    accidentally widen when this fires.

    Args:
        data_dir: where the marker lives.
        succeeded: whether the thing that just happened actually worked. Passing
            ``False`` is always silent -- this is the rule that keeps the pointer from
            appearing next to an error message.
        interactive: ``False`` for non-TTY runs, so it never lands in a log file, a
            pipeline, or a JSON payload someone is parsing.
        env: environment to read (injected for testing).
    """
    environ = os.environ if env is None else env

    if not succeeded:
        return False
    if not interactive:
        return False
    if environ.get("YAZSES_NO_NUDGE"):
        return False
    # Respect the broad convention too: anyone setting CI or NO_COLOR-style automation
    # flags is not a human reading a terminal.
    if environ.get("CI"):
        return False
    return not (data_dir / MARKER_NAME).exists()


def mark_shown(data_dir: Path) -> None:
    """Record that it has been shown, so it never appears again.

    Failure is deliberately swallowed. A read-only or missing data directory is a fine
    reason to skip bookkeeping and a terrible reason to fail a command that already
    succeeded -- the worst outcome here is that the pointer shows a second time.
    """
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / MARKER_NAME).write_text("", encoding="utf-8")
    except OSError:
        pass
