"""ADR-028 §6: archive members are checked before a byte is written, over plain tuples.
Traversal, drive and UNC prefixes, absolute paths, symlinks, over-long names, counts and
sizes that disagree with pack.json, decompression bombs and (case-insensitive)
duplicates are all refused."""
from __future__ import annotations

import json
import stat

import pytest

from tests.packs_fixtures import manifest_dict
from yazses.packs.archive import MAX_RATIO, check_tree, validate_members
from yazses.packs.manifest import Record, RecordEntry, parse_manifest

META = [("pack.json", 100, 80, False, 0), ("RECORD.json", 100, 80, False, 0)]
FILE_MODE = (stat.S_IFREG | 0o644) << 16
LINK_MODE = (stat.S_IFLNK | 0o777) << 16


def _manifest(files: int, size: int):
    return parse_manifest(json.dumps(manifest_dict(files=files, unpacked_bytes=size)))


def _check(*members, manifest=None):
    return validate_members([*META, *members], manifest)


def test_a_clean_archive_passes_and_counts_every_member() -> None:
    """Build item 1: the counts include pack.json and RECORD.json; directory entries
    (which the build never writes) are not counted."""
    report = _check(
        ("site/", 0, 0, True, 0),
        ("site/m/__init__.py", 10, 8, False, FILE_MODE),
        ("LICENSES/m.txt", 5, 5, False, 0),
        manifest=_manifest(4, 215),
    )
    assert report.ok, report.problems
    assert (report.payload_files, report.payload_bytes) == (4, 215)


@pytest.mark.parametrize(
    ("name", "fragment"),
    [
        ("../x", "unsafe"),
        ("site/../../x", "unsafe"),
        ("C:\\x", "drive"),
        ("C:/Windows/x.dll", "drive"),
        ("\\\\server\\share\\x", "UNC"),
        ("//server/share/x", "UNC"),
        ("/etc/passwd", "absolute"),
        ("\\x", "absolute"),
        ("site/a\\b.py", "unsafe"),
        ("site/a:stream", "unsafe"),
        ("site/CON.py", "reserved"),
        ("site/nul", "reserved"),
        ("site/trailing.", "rename"),
        ("site/trailing ", "rename"),
        ("bin/tool.exe", "top-level"),
        ("site/" + "a" * 140, "longer than 140"),
    ],
)
def test_a_bad_member_name_refuses(name: str, fragment: str) -> None:
    report = _check((name, 1, 1, False, 0))
    assert not report.ok
    assert any(fragment in p for p in report.problems), report.problems


def test_a_symlink_attribute_refuses() -> None:
    report = _check(("site/link", 4, 4, False, LINK_MODE))
    assert any("symbolic link" in p for p in report.problems)


def test_a_count_different_from_the_manifest_refuses() -> None:
    report = _check(("site/a.py", 5, 5, False, 0), manifest=_manifest(4, 205))
    assert any("holds 3 files" in p for p in report.problems)


def test_a_size_different_from_the_manifest_refuses() -> None:
    report = _check(("site/a.py", 5, 5, False, 0), manifest=_manifest(3, 206))
    assert any("unpacks to 205 bytes" in p for p in report.problems)


def test_the_ratio_cap_admits_every_member_the_build_can_produce() -> None:
    """Build item 3: a member whose DEFLATE ratio would exceed 100:1 is STORED, so the
    cap must be at least 100 or a genuine pack is refused."""
    assert MAX_RATIO >= 100
    big = 4 << 20
    assert _check(("site/a.bin", big, big // 100, False, 0)).ok


def test_a_ratio_over_the_cap_refuses_but_small_files_are_exempt() -> None:
    big = 4 << 20
    bomb = _check(("site/bomb.bin", big, big // (MAX_RATIO * 2), False, 0))
    assert any("decompression bomb" in p for p in bomb.problems)
    empty_ok = _check(("site/__init__.py", 0, 2, False, 0))
    assert empty_ok.ok, empty_ok.problems


def test_duplicate_and_case_insensitive_duplicate_names_refuse() -> None:
    dup = _check(("site/a.py", 1, 1, False, 0), ("site/a.py", 1, 1, False, 0))
    assert any("twice" in p for p in dup.problems)
    case = _check(("site/A.py", 1, 1, False, 0), ("site/a.py", 1, 1, False, 0))
    assert any("same file on Windows" in p for p in case.problems)


def test_missing_metadata_files_refuse() -> None:
    report = validate_members([("site/a.py", 1, 1, False, 0)], None)
    assert any("no pack.json" in p for p in report.problems)
    assert any("no RECORD.json" in p for p in report.problems)


def test_check_tree_finds_missing_resized_and_altered_files() -> None:
    record = Record((
        RecordEntry("site/a.py", 3, "a" * 64),
        RecordEntry("site/b.dll", 10, "b" * 64),
        RecordEntry("site/c.py", 4, "c" * 64),
    ))
    sizes = {"site/a.py": 3, "site/c.py": 5}
    problems = check_tree(record, sizes.get)
    assert problems == ["site/b.dll is missing", "site/c.py is 5 bytes, expected 4"]
    hashes = {"site/a.py": "f" * 64, "site/b.dll": "b" * 64, "site/c.py": "c" * 64}
    full = check_tree(record, {"site/a.py": 3, "site/b.dll": 10, "site/c.py": 4}.get,
                      hash_fn=hashes.get)
    assert full == ["site/a.py does not match its recorded SHA-256"]
