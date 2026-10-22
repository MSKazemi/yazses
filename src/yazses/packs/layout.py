"""Where packs live below ``data_dir/packs``, and the path-length budget (pure).

::

    <data_dir>/packs/
      state.json                 installed packs per build, last results, started-ok
      b-<12hex>/<name>/          one tree per pack per base build (COMPLETE written last)
      staging/<name>.<token>/    extraction in progress; deleted on any failure
      downloads/<asset>.part     ADR-027 download_verified's bounded .part file
      quarantine/<name>-<UTC>/   a tree that failed a check, + reason.txt
      <name>.lock                O_CREAT|O_EXCL single-flight; stale after 2 h

**Path budget.** The build rejects any path inside a pack longer than
:data:`MAX_PACK_RELPATH` characters. The components above are kept short so that
``<%LOCALAPPDATA%>\\yazses\\packs\\<component>\\<name>\\<140 chars>`` stays under Windows'
``MAX_PATH`` without the opt-in long-path mode (ADR-028 §6). :func:`budget_problems`
proves it for the worst-case data directory.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "COMPLETE",
    "MAX_PACK_NAME",
    "MAX_PACK_RELPATH",
    "MAX_PATH",
    "STATE_FILE",
    "TOKEN_LEN",
    "WORST_CASE_DATA_DIR_LEN",
    "PackLayout",
    "budget_problems",
    "build_dir_name",
]

COMPLETE = "COMPLETE"
STATE_FILE = "state.json"
#: The longest relative path the build allows inside a pack (ADR-028 §6).
MAX_PACK_RELPATH = 140
#: The longest pack name `manifest._NAME_RE` allows. The longest qualifying extra today is
#: `diarization` (11); 16 is what the quarantine folder's budget leaves room for.
MAX_PACK_NAME = 16
#: Windows' MAX_PATH, including the terminating NUL — so a usable path is 259 characters.
MAX_PATH = 260
#: Length of the random staging token.
TOKEN_LEN = 8
#: The longest ``data_dir`` we budget for: ``C:\Users\<20-char user>.<15-char domain>
#: \AppData\Local\yazses`` is 66 characters (a user name is at most 20; Windows appends
#: ``.<DOMAIN>`` when a local and a domain profile collide). A redirected profile on a
#: deeper path is the user's long-path setting's job, not this budget's.
WORST_CASE_DATA_DIR_LEN = 66
#: Build-directory collision suffixes allowed before giving up (b-<12hex>, -2 … -9).
_MAX_SUFFIX = 9

_BUILD_HEX = re.compile(r"^sha256:([0-9a-f]{64})$")


def build_dir_name(build_id: str, claimed: Mapping[str, str]) -> str:
    """``b-<first 12 hex>``, or ``b-<12hex>-<n>`` when that name already belongs to a
    *different* build id in ``state.json`` (``claimed`` maps directory -> build id).

    Twelve hex digits is 48 bits; two build ids sharing them is not expected, but a
    collision would silently load one build's packs into another, so it is guarded
    rather than assumed away. Raises ``ValueError`` for a malformed id or after
    :data:`_MAX_SUFFIX` collisions.
    """
    m = _BUILD_HEX.match(build_id)
    if m is None:
        raise ValueError(f"not a build id: {build_id!r}")
    stem = f"b-{m.group(1)[:12]}"
    for n in range(1, _MAX_SUFFIX + 1):
        candidate = stem if n == 1 else f"{stem}-{n}"
        owner = claimed.get(candidate)
        if owner is None or owner == build_id:
            return candidate
    raise ValueError(f"too many build-directory collisions for {build_id!r}")


@dataclass(frozen=True)
class PackLayout:
    """Every path below ``<data_dir>/packs``. Pure: nothing here touches the disk."""

    root: Path

    @classmethod
    def under(cls, data_dir: Path) -> PackLayout:
        return cls(Path(data_dir) / "packs")

    @property
    def state_file(self) -> Path:
        return self.root / STATE_FILE

    @property
    def downloads(self) -> Path:
        return self.root / "downloads"

    @property
    def staging(self) -> Path:
        return self.root / "staging"

    @property
    def quarantine(self) -> Path:
        return self.root / "quarantine"

    def lock(self, name: str) -> Path:
        return self.root / f"{name}.lock"

    def build_dir(self, component: str) -> Path:
        return self.root / component

    def pack_dir(self, component: str, name: str) -> Path:
        return self.root / component / name

    def staging_dir(self, name: str, token: str) -> Path:
        return self.staging / f"{name}.{token}"

    def quarantine_dir(self, name: str, stamp: str) -> Path:
        return self.quarantine / f"{name}-{stamp}"


def budget_problems(data_dir_len: int = WORST_CASE_DATA_DIR_LEN) -> list[str]:
    """Every layout location whose longest possible file path breaks ``MAX_PATH``.

    Counted in characters with one separator per component, for the longest pack name,
    the longest build-directory suffix and a :data:`MAX_PACK_RELPATH` path inside the pack.
    """
    limit = MAX_PATH - 1
    root = data_dir_len + len("\\packs")
    name = "n" * MAX_PACK_NAME
    longest_build = f"b-{'0' * 12}-{_MAX_SUFFIX}"
    places = {
        "installed tree": [longest_build, name],
        "staging tree": ["staging", f"{name}.{'t' * TOKEN_LEN}"],
        "quarantine tree": ["quarantine", f"{name}-20991231T235959Z"],
    }
    problems = []
    for label, parts in places.items():
        total = root + sum(1 + len(p) for p in parts) + 1 + MAX_PACK_RELPATH
        if total > limit:
            problems.append(f"{label}: {total} characters > {limit}")
    return problems
