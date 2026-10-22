"""ADR-028 §1: a pack loads only into the exact base build it names. Every mismatching
field gives its own reason; a matching build id with a different Python is still
refused; another build id is *stale*, not refused."""
from __future__ import annotations

import json

import pytest

from tests.packs_fixtures import OTHER_BUILD_ID, base, index_dict, manifest_dict
from yazses.packs.abi import OK, REFUSED, STALE, base_identity, match
from yazses.packs.manifest import IndexEntry, parse_index, parse_manifest


def _manifest(**over):
    return parse_manifest(json.dumps(manifest_dict(**over)))


def _entry(**over) -> IndexEntry:
    m = manifest_dict()
    data = dict(name="parakeet", asset="x", sha256="c" * 64, size=1,
                unpacked_bytes=m["unpacked_bytes"], files=m["files"],
                features=("stt-parakeet",))
    data.update(over)
    return IndexEntry(**data)


def test_a_matching_pack_is_ok() -> None:
    result = match(_manifest(), base(), _entry(), archive_sha256="c" * 64)
    assert result.status == OK and result.reasons == ()


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("python", {"cache_tag": "cpython-313", "version": "3.12.9", "abi": "cp312"},
         "cpython-313"),
        ("python", {"cache_tag": "cpython-312", "version": "3.12.8", "abi": "cp312"},
         "Python 3.12.8, this app runs 3.12.9"),
        ("platform", "win-arm64", "win-arm64"),
        ("arch", "arm64", "arm64"),
        ("app_version", "2.43.0", "YazSes 2.43.0"),
    ],
)
def test_every_field_mismatch_has_its_own_reason_and_refuses(field, value, fragment) -> None:
    """Same build id, one field different: refused (defence in depth), with a reason
    that names the field instead of a hash."""
    result = match(_manifest(**{field: value}), base(), _entry())
    assert result.status == REFUSED
    assert len(result.reasons) == 1
    assert fragment in result.reasons[0]


def test_two_mismatches_give_two_reasons() -> None:
    result = match(_manifest(arch="arm64", platform="win-arm64"), base(), _entry())
    assert result.status == REFUSED and len(result.reasons) == 2


def test_another_build_id_is_stale_not_refused() -> None:
    result = match(_manifest(base_build_id=OTHER_BUILD_ID, app_version="2.43.0"),
                   base(), _entry())
    assert result.status == STALE
    assert "another build" in result.reasons[0]
    assert any("2.43.0" in r for r in result.reasons)


def test_equal_build_id_with_a_different_python_is_still_refused() -> None:
    py = {"cache_tag": "cpython-312", "version": "3.12.1", "abi": "cp312"}
    assert match(_manifest(python=py), base(), _entry()).status == REFUSED


@pytest.mark.parametrize(
    ("entry", "fragment"),
    [
        (None, "not listed"),
        (_entry(files=999), "files"),
        (_entry(unpacked_bytes=999), "unpacks"),
        (_entry(features=("other",)), "different features"),
    ],
)
def test_index_disagreements_refuse(entry, fragment) -> None:
    result = match(_manifest(), base(), entry)
    assert result.status == REFUSED
    assert any(fragment in r for r in result.reasons)


def test_an_archive_hash_that_is_not_the_embedded_one_refuses() -> None:
    result = match(_manifest(), base(), _entry(), archive_sha256="d" * 64)
    assert result.status == REFUSED
    assert "built into this copy" in result.reasons[0]


def test_the_base_identity_reports_an_index_from_another_app() -> None:
    idx = parse_index(json.dumps(index_dict()))
    ident, problems = base_identity(
        idx, cache_tag="cpython-312", python_version="3.12.9", platform="win-amd64",
        arch="x64", app_version="2.44.0",
    )
    assert problems == () and ident.build_id == idx.base_build_id
    _, problems = base_identity(
        idx, cache_tag="cpython-313", python_version="3.13.0", platform="win-arm64",
        arch="arm64", app_version="2.45.0",
    )
    assert len(problems) == 5
