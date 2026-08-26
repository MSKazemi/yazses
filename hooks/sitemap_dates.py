"""Give sitemap entries truthful, per-page last-modified dates.

MkDocs initialises every ``Page.update_date`` to the build date. Its sitemap template
then publishes that value for every URL, so rebuilding the site makes hundreds of old
pages look newly edited. Search engines explicitly ignore ``lastmod`` when it is not
consistently accurate.

For tracked source pages, use the date of the latest commit that touched that path. For
generated or untracked pages, omit ``lastmod`` rather than inventing one. The hook changes
only sitemap metadata; the visible "last updated" text remains owned by the existing
git-revision-date plugin.
"""

from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


@lru_cache(maxsize=None)
def _git_last_modified(source: Path) -> str | None:
    """Return the latest committed date for *source*, or ``None`` if unavailable."""
    try:
        relative = source.resolve().relative_to(_REPO_ROOT).as_posix()
    except (OSError, ValueError):
        return None

    try:
        done = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "log", "-1", "--format=%cs", "--", relative],
            capture_output=True,
            check=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    value = done.stdout.strip()
    return value if _ISO_DATE.fullmatch(value) else None


def on_page_markdown(markdown: str, page: Any, **_: Any) -> str:
    """Set the value consumed by MkDocs' built-in sitemap template."""
    source = Path(page.file.abs_src_path)
    page.update_date = _git_last_modified(source) or ""
    return markdown
