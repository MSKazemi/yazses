"""ADR-028 pack index / pack.json / RECORD.json parsing: valid input, unknown format,
missing keys, wrong types, and the asset name re-derived rather than trusted."""
from __future__ import annotations

import json

import pytest

from tests.packs_fixtures import BUILD_ID, VERSION, entry_dict, index_dict, manifest_dict
from yazses.packs.manifest import (
    ManifestError,
    expected_asset_name,
    parse_index,
    parse_manifest,
    parse_record,
)


def test_a_valid_index_parses() -> None:
    idx = parse_index(json.dumps(index_dict()))
    assert idx.app_version == VERSION
    assert idx.base_build_id == BUILD_ID
    assert idx.for_feature("stt-parakeet").name == "parakeet"
    assert idx.for_feature("gaze") is None
    assert idx.entry("parakeet").size == 312345


def test_unknown_keys_are_ignored() -> None:
    data = index_dict(entry_dict(future_field=1), something_new={"x": 1})
    assert parse_index(json.dumps(data)).packs[0].name == "parakeet"


def test_a_newer_format_says_to_update() -> None:
    with pytest.raises(ManifestError, match="newer YazSes"):
        parse_index(json.dumps(index_dict(format=2)))


@pytest.mark.parametrize("fmt", [0, "1", True, None, 1.0])
def test_an_unknown_format_refuses(fmt) -> None:
    with pytest.raises(ManifestError):
        parse_index(json.dumps(index_dict(format=fmt)))


@pytest.mark.parametrize(
    "key", ["app_version", "base_build_id", "python", "platform", "arch", "packs"]
)
def test_a_missing_index_key_refuses(key: str) -> None:
    data = index_dict()
    del data[key]
    with pytest.raises(ManifestError, match=key if key != "python" else "python"):
        parse_index(json.dumps(data))


@pytest.mark.parametrize(
    "key", ["name", "asset", "sha256", "size", "unpacked_bytes", "files", "features"]
)
def test_a_missing_entry_key_refuses(key: str) -> None:
    entry = entry_dict()
    del entry[key]
    with pytest.raises(ManifestError):
        parse_index(json.dumps(index_dict(entry)))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("size", "312345"), ("size", True), ("size", 0), ("size", -1),
        ("files", 1.5), ("sha256", "C" * 64), ("sha256", "c" * 63),
        ("features", "stt-parakeet"), ("features", []), ("name", "Parakeet"),
        ("name", "../x"), ("name", "a" * 17),
    ],
)
def test_wrong_entry_types_refuse(key: str, value) -> None:
    with pytest.raises(ManifestError):
        parse_index(json.dumps(index_dict(entry_dict(**{key: value}))))


def test_the_asset_name_is_rederived_not_trusted() -> None:
    assert expected_asset_name(VERSION, "win-amd64", "x64", "parakeet") == (
        "YazSes-2.44.0-windows-x64-pack-parakeet.yazpack"
    )
    for wrong in (
        "YazSes-2.43.0-windows-x64-pack-parakeet.yazpack",   # another version
        "YazSes-2.44.0-windows-arm64-pack-parakeet.yazpack",  # another arch
        "YazSes-2.44.0-windows-x64-pack-gaze.yazpack",        # another pack
        "YazSes-2.44.0-windows-x64.exe",                      # the installer
        "../YazSes-2.44.0-windows-x64-pack-parakeet.yazpack",
    ):
        with pytest.raises(ManifestError, match="expects"):
            parse_index(json.dumps(index_dict(entry_dict(asset=wrong))))


def test_an_unknown_platform_refuses() -> None:
    with pytest.raises(ManifestError, match="platform"):
        parse_index(json.dumps(index_dict(platform="plan9-amd64")))


def test_a_pack_listed_twice_or_a_feature_in_two_packs_refuses() -> None:
    with pytest.raises(ManifestError, match="twice"):
        parse_index(json.dumps(index_dict(entry_dict(), entry_dict())))
    other = entry_dict("diarization", features=["stt-parakeet"])
    with pytest.raises(ManifestError, match="two packs"):
        parse_index(json.dumps(index_dict(entry_dict(), other)))


@pytest.mark.parametrize("text", ["", "not json", "[]", "null", b"\xff\xfe"])
def test_garbage_is_a_manifest_error_never_another_exception(text) -> None:
    for parser in (parse_index, parse_manifest, parse_record):
        with pytest.raises(ManifestError):
            parser(text)


def test_a_valid_manifest_parses() -> None:
    m = parse_manifest(json.dumps(manifest_dict(native_dirs=["site/sherpa_onnx/lib"])))
    assert m.name == "parakeet"
    assert m.entry_modules == ("fakepkg_parakeet",)
    assert m.native_dirs == ("site/sherpa_onnx/lib",)
    assert m.distributions == (("onnx-asr", "0.12.0"),)


@pytest.mark.parametrize(
    "native", ["../x", "/abs", "C:/x", "site/../../x", "site\\x", "other/x", ""]
)
def test_a_native_dir_outside_the_pack_refuses(native: str) -> None:
    with pytest.raises(ManifestError, match="native"):
        parse_manifest(json.dumps(manifest_dict(native_dirs=[native])))


@pytest.mark.parametrize("module", ["", "1abc", "os; rm", "a..b", "a-b"])
def test_an_invalid_entry_module_refuses(module: str) -> None:
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps(manifest_dict(entry_modules=[module])))


def test_record_parses_and_refuses_unsafe_or_duplicate_paths() -> None:
    good = {"format": 1, "files": [{"path": "site/a.py", "size": 3, "sha256": "d" * 64}]}
    rec = parse_record(json.dumps(good))
    assert rec.total_bytes == 3
    for bad_path in ("../a.py", "/a.py", "C:\\a.py", "pack.json", "RECORD.json"):
        bad = {"format": 1, "files": [{"path": bad_path, "size": 1, "sha256": "d" * 64}]}
        with pytest.raises(ManifestError):
            parse_record(json.dumps(bad))
    dup = {"format": 1, "files": [
        {"path": "site/A.py", "size": 1, "sha256": "d" * 64},
        {"path": "site/a.py", "size": 1, "sha256": "d" * 64},
    ]}
    with pytest.raises(ManifestError, match="twice"):
        parse_record(json.dumps(dup))
