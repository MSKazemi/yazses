"""`snap/snapcraft.yaml`'s `version:` must equal the project's own version.

The tag workflow rewrites that line before it builds, so on `refs/tags/v*` the
committed value never mattered and nobody kept it current. The snapcraft.io
**build service** is the other publisher, it builds `main` exactly as committed,
and nothing rewrites anything for it -- so it stamped every one of its builds
with whatever this file happened to say.

It said `2.17.0` while the project shipped `2.29.0`: twelve releases stale, and
*lower* than the 2.19.0 that `latest/stable` was serving. `latest/edge` really
did end up advertising 2.17.0 against post-2.29 code.

A `version:` that is only correct on the one path that overwrites it is not a
version, so this pins it to the same authority every other surface is pinned to.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPCRAFT = ROOT / "snap" / "snapcraft.yaml"

# The tag workflow's rewrite is `sed -i "s/^version:.*/version: \"$VERSION\"/"`,
# so match what that sed matches -- a guard keyed off a different anchor than the
# thing that edits the file can pass while the edit misses.
_VERSION_LINE = re.compile(r'^version:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)


def _project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_snapcraft_declares_the_project_version() -> None:
    text = SNAPCRAFT.read_text(encoding="utf-8")
    found = _VERSION_LINE.findall(text)
    assert found, (
        "snap/snapcraft.yaml has no top-level `version:` line that "
        "`.github/workflows/snap.yml`'s sed would match -- the tag build would "
        "silently keep whatever the file already said."
    )
    assert len(found) == 1, f"snap/snapcraft.yaml declares {len(found)} `version:` lines: {found}"
    assert found[0] == _project_version(), (
        f"snap/snapcraft.yaml says version {found[0]!r}, pyproject.toml says "
        f"{_project_version()!r}. The snapcraft.io build service builds the repo as "
        "committed and stamps this value on every revision it uploads; bump it with "
        "the release."
    )
