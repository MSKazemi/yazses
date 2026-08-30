"""One honest answer to "did git actually run?", shared by every guard that asks git.

About twenty tests in this suite establish a fact by shelling out to git: is this file
tracked, is this private tier absent from the index, does this design file reach the
published docs, what commit last touched this page. They are among the most valuable
tests here -- `test_private_tiers_stay_private` is the thing standing between a
marketing tree and a public repository -- and they share one failure mode.

When git cannot run, each of them fails in the vocabulary of its own subject. The
FreeBSD CI leg produced, in a single run:

    dryrun_wrap is now referenced from []
    design/packaging/ is tracked but not published
    design/ci-cd-audit.md is tracked but not published
    assert None is not None

Four different findings about the source tree, every one of them false, from a git that
never looked at the source tree. The rest raised `CalledProcessError: ... returned
non-zero exit status 128`, which is honest but names no cause -- 128 is git's catch-all,
and `capture_output=True` had already swallowed the line that would have named it.

`require_git()` asks git one question up front and, if git cannot answer it, fails with
what git actually said. The twenty confusing findings become twenty copies of one true
sentence, and the cause is in the first line of the first failure instead of being
absent from all of them.

Deliberately a **failure**, not a skip. These guards protect things that must not
silently stop being checked -- a skipped `test_no_private_path_is_tracked` is a repo
with no private-tier guard at all, and it would be reported as a green run.
"""

from __future__ import annotations

import functools
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


@functools.lru_cache(maxsize=1)
def _probe() -> str | None:
    """Return None when git can answer questions about this checkout, else why not."""
    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return "there is no `git` on PATH"
    except OSError as exc:  # pragma: no cover - platform-specific
        return f"`git` could not be executed: {exc}"
    except subprocess.SubprocessError as exc:  # pragma: no cover - timeout
        return f"`git` did not finish: {exc}"
    if done.returncode != 0:
        said = (done.stderr or done.stdout or "").strip() or "<it printed nothing>"
        return f"`git rev-parse` exited {done.returncode} and said: {said}"
    return None


def require_git() -> None:
    """Fail now, naming git's own complaint, rather than later in someone else's words."""
    why = _probe()
    if why is None:
        return
    raise AssertionError(
        f"This guard establishes its fact by asking git, and git cannot answer here: "
        f"{why}. Nothing below is evidence about the repository -- an unrun probe "
        f"returns the same empty result as a probe that ran and found nothing, and the "
        f"two mean opposite things. Fix git for this environment; do not weaken the "
        f"guard. (tests/gitprobe.py)"
    )
