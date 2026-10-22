"""Validate a pack archive's members and an installed tree (pure; ADR-028 §6).

Extraction is defensive even though the archive is hash-verified first: Python's own
documentation says "never extract archives from untrusted sources without prior
inspection" and names decompression bombs. So every member is checked **before** a
single byte is written, over plain tuples rather than a ``ZipFile``, which is why the
tests need no real archive.

A member is ``(name, size, compressed, is_dir, external_attr)`` — the fields
``zipfile.ZipInfo`` exposes as ``filename``, ``file_size``, ``compress_size``,
``is_dir()`` and ``external_attr``.
"""
from __future__ import annotations

import stat
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from yazses.packs.layout import MAX_PACK_RELPATH
from yazses.packs.manifest import PackManifest, Record, is_safe_relpath

__all__ = [
    "MAX_MEMBERS",
    "MAX_RATIO",
    "META_FILES",
    "TOP_LEVEL",
    "Member",
    "MemberReport",
    "check_tree",
    "validate_members",
]

Member = tuple[str, int, int, bool, int]

#: The only top-level names a pack may contain.
TOP_LEVEL = frozenset({"pack.json", "RECORD.json", "site", "stdlib", "LICENSES"})
#: Files that are metadata, not payload: counted in ``files``/``unpacked_bytes``, but
#: not listed in ``RECORD.json`` (see manifest's counting convention).
META_FILES = frozenset({"pack.json", "RECORD.json"})
#: Uncompressed:compressed cap per member. Python source compresses ~5-10x and padded
#: native code rarely beyond 50x; a bomb is hundreds to thousands. Members under
#: :data:`_RATIO_FLOOR` bytes are exempt (an empty file has an infinite ratio).
MAX_RATIO = 200
_RATIO_FLOOR = 1 << 20
#: Far above any real pack (gaze, the largest planned, is thousands of files).
MAX_MEMBERS = 200_000

#: Device names Windows reserves in every directory, with or without an extension.
_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


def _name_problem(name: str) -> str | None:
    if not isinstance(name, str) or not name:
        return "an empty member name"
    if name.startswith("\\\\") or name.startswith("//"):
        return f"a UNC path: {name!r}"
    if len(name) >= 2 and name[1] == ":":
        return f"a drive-qualified path: {name!r}"
    if name.startswith(("/", "\\")):
        return f"an absolute path: {name!r}"
    trimmed = name[:-1] if name.endswith("/") else name
    if not is_safe_relpath(trimmed, max_len=MAX_PACK_RELPATH):
        if len(trimmed) > MAX_PACK_RELPATH:
            return f"a path longer than {MAX_PACK_RELPATH} characters: {name[:60]!r}…"
        return f"an unsafe path: {name!r}"
    for seg in trimmed.split("/"):
        if seg.endswith((" ", ".")):
            return f"a name Windows would silently rename: {name!r}"
        if seg.split(".", 1)[0].casefold() in _RESERVED:
            return f"a reserved Windows device name: {name!r}"
    top = trimmed.split("/", 1)[0]
    if top not in TOP_LEVEL:
        return f"an unexpected top-level entry: {top!r}"
    return None


def _kind_problem(name: str, is_dir: bool, external_attr: int) -> str | None:
    mode = (external_attr >> 16) & 0xFFFF
    if not mode:
        return None  # written by a tool that records no Unix mode: regular file/dir
    kind = stat.S_IFMT(mode)
    if stat.S_ISLNK(mode):
        return f"a symbolic link: {name!r}"
    if is_dir and kind not in (0, stat.S_IFDIR):
        return f"a directory entry with an odd file type: {name!r}"
    if not is_dir and kind not in (0, stat.S_IFREG):
        return f"a member that is not a regular file: {name!r}"
    return None


@dataclass(frozen=True)
class MemberReport:
    problems: tuple[str, ...]
    #: Every regular-file member, metadata included — what pack.json's counts state.
    payload_files: int
    payload_bytes: int

    @property
    def ok(self) -> bool:
        return not self.problems


def validate_members(
    members: Iterable[Member],
    manifest: PackManifest | None,
    *,
    max_ratio: int = MAX_RATIO,
    max_members: int = MAX_MEMBERS,
) -> MemberReport:
    """Every reason these members must not be extracted. Empty ``problems`` means go.

    With a manifest, the payload's file count and total size must equal what it states.
    Without one (``pack.json`` could not be read), only the per-member checks run and
    the caller must refuse anyway.
    """
    problems: list[str] = []
    seen_exact: set[str] = set()
    seen_folded: dict[str, str] = {}
    count = 0
    files = 0
    total = 0
    has_manifest = has_record = False
    for name, size, compressed, is_dir, external_attr in members:
        count += 1
        if count > max_members:
            problems.append(f"more than {max_members} members")
            break
        problem = _name_problem(name) or _kind_problem(name, is_dir, external_attr)
        if problem:
            problems.append(f"the archive contains {problem}")
            continue
        key = name[:-1] if name.endswith("/") else name
        if key in seen_exact:
            problems.append(f"the archive contains {key!r} twice")
            continue
        folded = key.casefold()
        if folded in seen_folded:
            problems.append(
                f"the archive contains {seen_folded[folded]!r} and {key!r}, which are the "
                "same file on Windows"
            )
            continue
        seen_exact.add(key)
        seen_folded[folded] = key
        if is_dir:
            continue
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            problems.append(f"the archive gives {key!r} an invalid size")
            continue
        if size >= _RATIO_FLOOR and (compressed <= 0 or size > compressed * max_ratio):
            problems.append(
                f"{key!r} expands more than {max_ratio}:1, which is how a decompression "
                "bomb looks"
            )
        if key == "pack.json":
            has_manifest = True
        elif key == "RECORD.json":
            has_record = True
        # Every member counts, the two metadata files included (build item 1).
        files += 1
        total += size
    if not has_manifest:
        problems.append("the archive has no pack.json")
    if not has_record:
        problems.append("the archive has no RECORD.json")
    if manifest is not None and not problems:
        if files != manifest.files:
            problems.append(
                f"the archive holds {files} files; pack.json says {manifest.files}"
            )
        if total != manifest.unpacked_bytes:
            problems.append(
                f"the archive unpacks to {total} bytes; pack.json says "
                f"{manifest.unpacked_bytes}"
            )
    return MemberReport(tuple(problems), files, total)


def check_tree(
    record: Record,
    stat_fn: Callable[[str], int | None],
    *,
    hash_fn: Callable[[str], str | None] | None = None,
    limit: int = 20,
) -> list[str]:
    """Every way an installed tree differs from its ``RECORD.json``.

    ``stat_fn(relpath)`` returns the file's size or ``None`` when it is missing.
    ``hash_fn(relpath)``, when given, returns its SHA-256 (the full check that
    ``yazses packs verify`` and an import failure run; startup never hashes). Stops
    after ``limit`` problems — one missing DLL is enough to call a tree damaged.
    """
    problems: list[str] = []
    for entry in record.files:
        size = stat_fn(entry.path)
        if size is None:
            problems.append(f"{entry.path} is missing")
        elif size != entry.size:
            problems.append(f"{entry.path} is {size} bytes, expected {entry.size}")
        elif hash_fn is not None:
            digest = hash_fn(entry.path)
            if digest is None or digest.lower() != entry.sha256:
                problems.append(f"{entry.path} does not match its recorded SHA-256")
        if len(problems) >= limit:
            break
    return problems
