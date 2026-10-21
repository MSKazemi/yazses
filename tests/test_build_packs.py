"""scripts/build-packs.py -- the build side of ADR-028 feature add-on packs.

Everything here is offline. The pure functions (naming, hashing, the index contract,
the build rules, the packs.toml catalogue, the Phase 0 spike verdicts) are tested
directly; the ``build`` orchestration runs end to end against a synthetic one-folder
bundle with ``uv`` and the frozen probe replaced by fakes, because the property that
matters most -- a pack that fails anything is withheld and the base installer is left
byte-identical -- lives in the orchestration, not in any one helper.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-packs.py"
SPEC = ROOT / "packaging" / "windows" / "yazses.spec"
HOOK = ROOT / "packaging" / "packs" / "spike" / "rthook_pack_spike.py"
PS1 = ROOT / "scripts" / "build-windows.ps1"
BUILD_WINDOWS = ROOT / ".github" / "workflows" / "build-windows.yml"
SPIKE_WORKFLOW = ROOT / ".github" / "workflows" / "packs-spike.yml"


@pytest.fixture(scope="module")
def bp():
    spec = importlib.util.spec_from_file_location("build_packs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_packs"] = mod
    spec.loader.exec_module(mod)
    return mod


SHA = "a" * 64
BID = "sha256:" + "b" * 64
PY = {"cache_tag": "cpython-312", "version": "3.12.9", "abi": "cp312"}


# --- naming ------------------------------------------------------------------------


def test_asset_names_follow_the_adr(bp):
    assert bp.pack_asset_name("2.44.0", "windows", "x64", "parakeet") == (
        "YazSes-2.44.0-windows-x64-pack-parakeet.yazpack"
    )
    assert bp.index_asset_name("2.44.0", "windows", "x64") == "YazSes-2.44.0-windows-x64-packs.json"
    assert bp.provenance_asset_name("2.44.0", "windows", "x64") == (
        "YazSes-2.44.0-windows-x64-packs.intoto.jsonl"
    )


def test_pack_names_cannot_collide_with_the_installer_patterns(bp):
    """installer_update's `-windows-(x64|arm64)\\.exe$` and publish-channels' count."""
    name = bp.pack_asset_name("2.44.0", "windows", "x64", "parakeet")
    assert not name.endswith(".exe") and not name.endswith(".intoto.jsonl")
    assert not bp.index_asset_name("2.44.0", "windows", "x64").endswith(".exe")


@pytest.mark.parametrize(("tag", "word"), [
    ("win-amd64", "windows"), ("win-arm64", "windows"),
    ("macosx-14.0-arm64", "macos"), ("linux-x86_64", "linux"),
])
def test_os_token(bp, tag, word):
    assert bp.os_token(tag) == word


@pytest.mark.parametrize("args", [
    ("2.44.0", "windows", "x64", "Bad"), ("2.44.0", "windows", "x64", "../x"),
    ("2.44.0", "windows", "x 64", "a"), ("", "windows", "x64", "a"),
    ("2.44.0", "dos", "x64", "a"),
])
def test_bad_name_parts_are_refused(bp, args):
    with pytest.raises(ValueError):
        bp.pack_asset_name(*args)


def test_unknown_platform_has_no_os_token(bp):
    with pytest.raises(ValueError):
        bp.os_token("freebsd-14")


# --- hashing and the base manifest -------------------------------------------------


def test_base_manifest_is_order_independent_and_canonical(bp):
    a = bp.base_manifest([("b", 2, SHA), ("a/x.dll", 1, SHA)])
    b = bp.base_manifest([("a/x.dll", 1, SHA), ("b", 2, SHA)])
    assert a == b
    assert b" " not in a and json.loads(a)["files"][0]["path"] == "a/x.dll"
    assert bp.build_id_of(a) == "sha256:" + hashlib.sha256(a).hexdigest()


def test_base_manifest_changes_when_one_byte_changes(bp):
    assert bp.base_manifest([("a", 1, SHA)]) != bp.base_manifest([("a", 1, "c" * 64)])


def test_base_manifest_refuses_duplicates(bp):
    with pytest.raises(ValueError):
        bp.base_manifest([("a", 1, SHA), ("a", 1, SHA)])


# --- requirements export -------------------------------------------------------------

EXPORT = """\
numpy==2.4.6 \\
    --hash=sha256:1111 \\
    --hash=sha256:2222
    # via onnx-asr
onnx-asr==0.12.0 \\
    --hash=sha256:3333
    # via yazses
Sherpa_ONNX==1.13.8 ; sys_platform == 'win32' \\
    --hash=sha256:4444
-e .
"""


def test_export_parsing_joins_continuations_and_normalises_names(bp):
    blocks = bp.parse_requirements_export(EXPORT)
    assert set(blocks) == {"numpy", "onnx-asr", "sherpa-onnx"}
    assert "--hash=sha256:2222" in blocks["numpy"]
    assert "sys_platform == 'win32'" in blocks["sherpa-onnx"]
    assert "via" not in blocks["numpy"]


def test_marginal_requirements_subtract_the_base(bp):
    blocks = bp.parse_requirements_export(EXPORT)
    marginal = bp.marginal_requirements(blocks, {"numpy"})
    assert set(marginal) == {"onnx-asr", "sherpa-onnx"}
    rendered = bp.render_requirements(marginal)
    assert bp.parse_requirements_export(rendered) == marginal


# --- build rules -----------------------------------------------------------------------


def test_top_level_modules(bp):
    rels = [
        "onnx_asr/__init__.py", "onnx_asr/x.py", "six.py", "_cffi.cp312-win_amd64.pyd",
        "onnx_asr-0.12.0.dist-info/METADATA", "bin/onnx-asr", "__pycache__/six.cpython-312.pyc",
        "share/doc/readme.txt", "nspkg/sub/mod.py", "../../Scripts/x.exe",
    ]
    assert bp.top_level_modules(rels) == {"onnx_asr", "six", "_cffi", "nspkg"}


def test_module_collisions_are_case_insensitive(bp):
    assert bp.module_collisions({"NumPy", "onnx_asr"}, {"numpy"}) == ["NumPy"]
    assert bp.module_collisions({"onnx_asr"}, {"numpy"}) == []


def test_identical_dll_is_dropped_and_different_one_conflicts(bp):
    rep = bp.dll_collisions(
        {"site/a/onnxruntime.dll": SHA, "site/a/vcomp.dll": "c" * 64},
        {"_internal/onnxruntime/capi/onnxruntime.dll": "d" * 64,
         "_internal/vcomp.dll": "c" * 64},
    )
    assert rep.drop == ["site/a/vcomp.dll"]
    assert len(rep.conflicts) == 1 and "onnxruntime.dll" in rep.conflicts[0]


def test_dll_basename_rule_is_case_insensitive(bp):
    rep = bp.dll_collisions({"site/X/ONNXRUNTIME.DLL": SHA}, {"_internal/onnxruntime.dll": "e" * 64})
    assert rep.conflicts


def test_dll_rule_across_packs(bp):
    rep = bp.dll_collisions({"site/x/foo.dll": SHA}, {},
                            {"other": {"site/y/FOO.dll": SHA, "site/y/bar.dll": SHA}})
    assert rep.conflicts == [] and rep.shared_identical
    rep = bp.dll_collisions({"site/x/foo.dll": SHA}, {}, {"other": {"site/y/foo.dll": "f" * 64}})
    assert rep.conflicts


def test_two_different_copies_inside_one_pack_conflict(bp):
    rep = bp.dll_collisions({"site/a/foo.dll": SHA, "site/b/foo.dll": "f" * 64}, {})
    assert rep.conflicts


# --- bind_to_base: the reviewed allow-list (ADR-028 finding M1) -----------------------

#: sherpa-onnx-core 1.13.8 win_amd64 as measured: its own onnxruntime.dll in lib/ and a
#: duplicate under .data/data/Scripts/, plus a C-API DLL the base does not ship.
_SHERPA_DLLS = {
    "site/sherpa_onnx/lib/onnxruntime.dll": "1" * 64,
    "site/sherpa_onnx_core-1.13.8.data/data/Scripts/onnxruntime.dll": "1" * 64,
    "site/sherpa_onnx/lib/sherpa-onnx-c-api.dll": "2" * 64,
}
_BASE_DLLS = {
    "_internal/onnxruntime/capi/onnxruntime.dll": "9" * 64,
    "_internal/vcruntime140.dll": "8" * 64,
}


def test_without_the_allow_list_sherpas_onnxruntime_withholds_the_pack(bp):
    """The red half: today's rule, on the measured wheel, is a conflict."""
    rep = bp.dll_collisions(_SHERPA_DLLS, _BASE_DLLS)
    assert rep.conflicts and all("onnxruntime.dll" in c for c in rep.conflicts)
    assert rep.bound == [] and rep.bound_names() == []


def test_the_bind_allow_list_drops_exactly_the_listed_name(bp):
    rep = bp.dll_collisions(_SHERPA_DLLS, _BASE_DLLS, bind_to_base=["onnxruntime.dll"])
    assert rep.conflicts == []
    both = ["site/sherpa_onnx/lib/onnxruntime.dll",
            "site/sherpa_onnx_core-1.13.8.data/data/Scripts/onnxruntime.dll"]
    assert sorted(rep.bound) == sorted(both)
    assert sorted(rep.drop) == sorted(both), "the C-API DLL must stay in the pack"
    assert rep.bound_names() == ["onnxruntime.dll"]
    assert rep.bind_unused == []


def test_a_bound_name_is_matched_case_insensitively(bp):
    rep = bp.dll_collisions({"site/x/OnnxRuntime.DLL": "1" * 64}, _BASE_DLLS,
                            bind_to_base=["ONNXRUNTIME.dll"])
    assert rep.conflicts == [] and rep.bound_names() == ["onnxruntime.dll"]


def test_any_other_collision_still_withholds_with_the_allow_list_present(bp):
    dlls = {**_SHERPA_DLLS, "site/sherpa_onnx/lib/vcruntime140.dll": "7" * 64}
    rep = bp.dll_collisions(dlls, _BASE_DLLS, bind_to_base=["onnxruntime.dll"])
    assert len(rep.conflicts) == 1 and "vcruntime140.dll" in rep.conflicts[0]
    assert rep.bound_names() == ["onnxruntime.dll"]


def test_two_differing_copies_of_a_bound_name_inside_the_pack_are_both_dropped(bp):
    dlls = {"site/a/onnxruntime.dll": "1" * 64, "site/b/onnxruntime.dll": "3" * 64}
    rep = bp.dll_collisions(dlls, _BASE_DLLS, bind_to_base=["onnxruntime.dll"])
    assert rep.conflicts == [] and sorted(rep.drop) == sorted(dlls)


def test_the_identical_copy_path_is_unchanged_by_the_allow_list(bp):
    dlls = {"site/x/vcruntime140.dll": "8" * 64, **_SHERPA_DLLS}
    rep = bp.dll_collisions(dlls, _BASE_DLLS, bind_to_base=["onnxruntime.dll"])
    assert "site/x/vcruntime140.dll" in rep.drop
    assert "site/x/vcruntime140.dll" not in rep.bound
    assert rep.bound_names() == ["onnxruntime.dll"]


def test_an_allow_list_entry_that_collides_with_nothing_changes_nothing(bp):
    rep = bp.dll_collisions({"site/x/foo.dll": "1" * 64}, _BASE_DLLS,
                            bind_to_base=["onnxruntime.dll", "foo.dll"])
    assert rep.drop == [] and rep.bound == [] and rep.conflicts == []
    assert rep.bind_unused == ["foo.dll", "onnxruntime.dll"]


def test_a_bound_dll_is_not_compared_against_other_packs(bp):
    rep = bp.dll_collisions({"site/x/onnxruntime.dll": "1" * 64}, _BASE_DLLS,
                            {"other": {"site/y/onnxruntime.dll": "4" * 64}},
                            bind_to_base=["onnxruntime.dll"])
    assert rep.conflicts == []


def test_native_dirs(bp):
    assert bp.native_dirs(["sherpa_onnx/lib/a.dll", "sherpa_onnx/lib/b.DLL", "top.dll",
                           "x/y.pyd"]) == ["site", "site/sherpa_onnx/lib"]


def test_pth_paths_become_entries_and_code_fails(bp):
    assert bp.pth_path_entries("# c\n\nvendored\n") == ["site/vendored"]
    with pytest.raises(bp.PackError):
        bp.pth_path_entries("import _virtualenv\n")
    with pytest.raises(bp.PackError):
        bp.pth_path_entries("../../outside\n")


@pytest.mark.parametrize("name", [
    "../x", "site/../../x", "/abs", "C:/x", "c:x", "//server/share/x", "site\\x.py",
    "site//x", "site/./x", "", "site/a:b", "site/" + "x" * 140,
])
def test_member_path_rules_refuse(bp, name):
    assert bp.member_path_errors(name)


def test_member_path_rules_accept_a_normal_name(bp):
    assert bp.member_path_errors("site/sherpa_onnx/lib/onnxruntime.dll") == []
    assert bp.member_path_errors("x" * 140) == []


def test_licence_members(bp):
    assert bp.licence_member("a.dist-info", "LICENSE")
    assert bp.licence_member("a.dist-info", "licenses/NOTICE.txt")
    assert bp.licence_member("a.dist-info", "COPYING.md")
    assert not bp.licence_member("a.dist-info", "METADATA")


@pytest.mark.parametrize(("size", "approved", "bad"), [
    (1, False, False), (600 * 1024**2, False, True), (600 * 1024**2, True, False),
    (2 * 1024**3, True, True),
])
def test_size_rules(bp, size, approved, bad):
    assert bool(bp.size_errors(size, approved)) is bad


# --- the archive -------------------------------------------------------------------


def _members(bp):
    payload = {
        "site/onnx_asr/__init__.py": b"import numpy\n",
        "site/onnx_asr/big.bin": b"\0" * 200_000,  # compresses > 100:1 -> stored
        "LICENSES/onnx-asr/LICENSE": b"MIT\n",
    }
    entries = [(n, len(d), hashlib.sha256(d).hexdigest()) for n, d in payload.items()]
    record = bp.record_json(entries)
    fields = bp.pack_fields(
        name="parakeet", extra="parakeet", features=["stt-parakeet"], app_version="2.44.0",
        base_build_id=BID, python=PY, platform_tag="win-amd64", arch="x64",
        distributions=[{"name": "onnx-asr", "version": "0.12.0"}], entry_modules=["onnx_asr"],
        native=[], path_entries=[],
    )
    pj = bp.pack_json(fields, sum(len(d) for d in payload.values()), len(payload), len(record))
    return {**payload, "RECORD.json": record, "pack.json": pj}


def test_pack_json_counts_every_member_including_itself(bp, tmp_path):
    members = _members(bp)
    dest = tmp_path / "p.yazpack"
    bp.write_deterministic_zip(dest, members)
    with zipfile.ZipFile(dest) as zf:
        infos = zf.infolist()
        doc = json.loads(zf.read("pack.json"))
        record = json.loads(zf.read("RECORD.json"))
        assert doc["files"] == len(infos)
        assert doc["unpacked_bytes"] == sum(i.file_size for i in infos)
        for f in record["files"]:
            assert hashlib.sha256(zf.read(f["path"])).hexdigest() == f["sha256"]
        assert {f["path"] for f in record["files"]} == {
            i.filename for i in infos} - {"pack.json", "RECORD.json"}
    for key in ("format", "name", "extra", "features", "app_version", "base_build_id",
                "python", "platform", "arch", "distributions", "entry_modules",
                "native_dirs", "unpacked_bytes", "files", "bind_to_base"):
        assert key in doc, key
    assert doc["bind_to_base"] == []


def test_pack_json_records_the_bound_dlls_sorted_and_lower_case(bp):
    fields = bp.pack_fields(
        name="diarization", extra="diarization", features=["diarize"], app_version="2.44.0",
        base_build_id=BID, python=PY, platform_tag="win-amd64", arch="x64",
        distributions=[], entry_modules=["sherpa_onnx"], native=[], path_entries=[],
        bind_to_base=["OnnxRuntime.dll", "onnxruntime.dll", "abc.dll"],
    )
    assert fields["bind_to_base"] == ["abc.dll", "onnxruntime.dll"]
    sys.path.insert(0, str(ROOT / "src"))
    from yazses.packs.manifest import parse_manifest

    # The runtime parser must still accept a pack.json that carries the new key.
    pj = bp.pack_json(fields, 0, 0, 0)
    assert parse_manifest(pj).name == "diarization"


def test_zip_is_deterministic_sorted_and_has_no_directories(bp, tmp_path):
    members = _members(bp)
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    bp.write_deterministic_zip(a, members)
    bp.write_deterministic_zip(b, dict(reversed(list(members.items()))))
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as zf:
        infos = zf.infolist()
    assert [i.filename for i in infos] == sorted(members)
    assert all(not i.is_dir() and i.date_time == (1980, 1, 1, 0, 0, 0) for i in infos)
    by = {i.filename: i for i in infos}
    assert by["site/onnx_asr/big.bin"].compress_type == zipfile.ZIP_STORED
    ratio = max(i.file_size / max(i.compress_size, 1) for i in infos)
    assert ratio <= bp.MAX_MEMBER_RATIO


def test_zip_refuses_a_bad_member_name(bp, tmp_path):
    with pytest.raises(bp.PackError):
        bp.write_deterministic_zip(tmp_path / "x.zip", {"../evil.py": b""})


def test_safe_extract_refuses_traversal(bp, tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escape.txt", b"x")
    with pytest.raises(bp.PackError):
        bp.safe_extract(evil, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


# --- the index -----------------------------------------------------------------------


def _entry(bp, name="parakeet", version="2.44.0"):
    return bp.index_entry(
        name=name, asset=bp.pack_asset_name(version, "windows", "x64", name), sha256=SHA,
        size=10, unpacked_bytes=20, files=3, features=["stt-parakeet"],
    )


def _index(bp, entries=None):
    return bp.build_index(app_version="2.44.0", base_build_id=BID, python=PY,
                          platform_tag="win-amd64", arch="x64",
                          entries=entries if entries is not None else
                          [_entry(bp, "parakeet"), _entry(bp, "diarization")])


def test_index_matches_the_spec_contract(bp):
    doc = _index(bp)
    assert bp.validate_index(doc) == []
    assert [p["name"] for p in doc["packs"]] == ["diarization", "parakeet"]
    assert set(doc) == {"format", "app_version", "base_build_id", "python", "platform",
                        "arch", "packs"}
    assert set(doc["packs"][0]) == {"name", "asset", "sha256", "size", "unpacked_bytes",
                                    "files", "features"}
    assert bp.index_bytes(doc) == bp.index_bytes(json.loads(bp.index_bytes(doc)))


def test_index_unknown_keys_are_ignored(bp):
    doc = _index(bp)
    doc["future"] = 1
    doc["packs"][0]["future"] = 2
    assert bp.validate_index(doc) == []


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(format=2),
    lambda d: d.pop("base_build_id"),
    lambda d: d.update(base_build_id="sha256:xyz"),
    lambda d: d.update(platform="beos"),
    lambda d: d["python"].pop("abi"),
    lambda d: d["packs"][0].update(asset="YazSes-2.44.0-windows-x64-pack-other.yazpack"),
    lambda d: d["packs"][0].update(sha256="A" * 64),
    lambda d: d["packs"][0].update(size=True),
    lambda d: d["packs"][0].update(files=-1),
    lambda d: d["packs"][0].pop("features"),
    lambda d: d["packs"].append(dict(d["packs"][0])),
    lambda d: d.update(packs={}),
])
def test_index_refusals(bp, mutate):
    doc = json.loads(bp.index_bytes(_index(bp)))
    mutate(doc)
    assert bp.validate_index(doc)


def test_build_index_raises_on_an_invalid_entry(bp):
    bad = dict(_entry(bp), asset="nope.yazpack")
    with pytest.raises(ValueError):
        _index(bp, [bad])


# --- the release check ---------------------------------------------------------------


def _release(bp):
    doc = _index(bp)
    data = bp.index_bytes(doc)
    idx = bp.index_asset_name("2.44.0", "windows", "x64")
    sums = {idx: hashlib.sha256(data).hexdigest(), **{p["asset"]: p["sha256"] for p in doc["packs"]}}
    assets = [idx, *[p["asset"] for p in doc["packs"]], "SHA256SUMS.txt"]
    return doc, data, idx, sums, assets


def test_check_release_passes_a_complete_release(bp):
    doc, data, idx, sums, assets = _release(bp)
    assert bp.check_release(doc, idx, sums, assets, hashlib.sha256(data).hexdigest()) == []


def test_check_release_finds_each_gap(bp):
    doc, data, idx, sums, assets = _release(bp)
    pack = doc["packs"][0]["asset"]
    assert bp.check_release(doc, idx, sums, [a for a in assets if a != pack])
    assert bp.check_release(doc, idx, {k: v for k, v in sums.items() if k != pack}, assets)
    assert bp.check_release(doc, idx, dict(sums, **{pack: "0" * 64}), assets)
    assert bp.check_release(doc, idx, {k: v for k, v in sums.items() if k != idx}, assets)
    assert bp.check_release(doc, "renamed.json", sums, assets)
    assert bp.check_release(doc, idx, sums, assets, "0" * 64)
    assert bp.check_release(_index(bp, []), idx, sums, assets)


def test_parse_sha256sums(bp):
    text = f"{'A' * 64}  YazSes-1.exe\n{'b' * 64} *YazSes-2.yazpack\nnoise\n"
    assert bp.parse_sha256sums(text) == {"YazSes-1.exe": "a" * 64, "YazSes-2.yazpack": "b" * 64}


def test_check_release_command(bp, tmp_path):
    doc, data, idx, sums, assets = _release(bp)
    (tmp_path / idx).write_bytes(data)
    (tmp_path / "SHA256SUMS.txt").write_text(
        "".join(f"{v}  {k}\n" for k, v in sums.items()), encoding="utf-8")
    (tmp_path / "assets.txt").write_text("\n".join(assets), encoding="utf-8")
    argv = ["check-release", "--sums", str(tmp_path / "SHA256SUMS.txt"),
            "--assets", str(tmp_path / "assets.txt"), str(tmp_path / idx)]
    assert bp.main(argv) == 0
    (tmp_path / "assets.txt").write_text(idx, encoding="utf-8")
    assert bp.main(argv) == 1


# --- packs.toml ----------------------------------------------------------------------


def _repo_inputs(bp):
    sys.path.insert(0, str(ROOT / "src"))
    from yazses.system import features

    _, extras = bp.read_project()
    return extras, features._FEATURE_DEPS, features._UNWIRED


def test_the_real_catalogue_is_complete_and_consistent(bp):
    extras, deps, unwired = _repo_inputs(bp)
    doc = bp.load_catalog()
    assert bp.validate_catalog(doc, extras, deps, unwired) == []
    # ADR-028 Q1: parakeet and chinese ship inside the frozen base; Phase 1 packs only
    # diarization, whose sherpa onnxruntime.dll is bound to the base's.
    packs = {p.name: p for p in bp.packs_from_catalog(doc)}
    assert set(packs) == {"diarization"}
    assert packs["diarization"].bind_to_base == ("onnxruntime.dll",)
    assert {"desktop", "overlay", "parakeet", "chinese"} <= set(bp.bundled_extras(doc))


def test_bundled_extras_are_never_packs(bp):
    doc = bp.load_catalog()
    bundled = set(bp.bundled_extras(doc))
    assert bundled, "guard the guard: no bundled extra at all"
    assert not bundled & {p.extra for p in bp.packs_from_catalog(doc)}


def test_the_base_build_syncs_exactly_the_bundled_extras(bp):
    """build-windows.ps1 and the spike freeze the same base packs.toml describes."""
    _, extras = bp.read_project()
    doc = bp.load_catalog()
    for script in (PS1, SPIKE_WORKFLOW):
        synced = bp.ps1_synced_extras(script.read_text(encoding="utf-8"))
        assert synced == {"desktop", "parakeet", "chinese"}, (script.name, synced)
        assert bp.base_sync_problems(synced, doc, extras) == [], script.name


def test_the_base_sync_guard_catches_each_mismatch(bp):
    _, extras = bp.read_project()
    doc = bp.load_catalog()
    assert bp.base_sync_problems(set(), doc, extras)                          # blind
    missing = bp.base_sync_problems({"desktop", "parakeet"}, doc, extras)
    assert any("'chinese'" in e for e in missing)
    packed = bp.base_sync_problems({"desktop", "parakeet", "chinese", "diarization"},
                                   doc, extras)
    assert any("--extra diarization" in e and "'pack'" in e for e in packed)
    # `overlay` is satisfied by desktop's identical requirement, not by name.
    assert bp.base_sync_problems({"overlay", "parakeet", "chinese"}, doc, extras) == []


def test_the_frozen_spec_collects_what_bundled_onnx_asr_reads_at_runtime(bp):
    """onnx_asr/__init__ calls importlib.metadata.version("onnx-asr") on import and its
    preprocessors load data/*.onnx via importlib.resources; PyInstaller's import
    analysis finds neither, so a bundled parakeet without these lines would ship an
    engine that raises PackageNotFoundError the first time it is enabled."""
    if "parakeet" not in bp.bundled_extras(bp.load_catalog()):
        pytest.skip("parakeet is not bundled")
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    calls = {(n.func.id, n.args[0].value) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.args
             and isinstance(n.args[0], ast.Constant)}
    assert ("copy_metadata", "onnx-asr") in calls
    assert ("collect_data_files", "onnx_asr") in calls


def test_synced_extras_ignore_comment_lines(bp):
    text = "# uv sync --extra gaze\n  uv sync --no-dev --extra desktop --extra=chinese\n"
    assert bp.ps1_synced_extras(text) == {"desktop", "chinese"}


def test_validate_command_checks_the_base_script(bp, tmp_path):
    assert bp.main(["validate"]) == 0
    bad = tmp_path / "build-windows.ps1"
    bad.write_text("uv sync --no-dev --extra desktop\n", encoding="utf-8")
    assert bp.main(["validate", "--base-script", str(bad)]) == 1


def test_the_catalogue_guard_fails_on_an_empty_catalogue(bp):
    extras, deps, unwired = _repo_inputs(bp)
    assert bp.validate_catalog({"format": 1, "extras": {}}, extras, deps, unwired)
    assert bp.validate_catalog({}, extras, deps, unwired)


def test_the_catalogue_guard_catches_each_defect(bp):
    extras, deps, unwired = _repo_inputs(bp)
    good = bp.load_catalog()

    def errs(mutate):
        doc = json.loads(json.dumps(good))
        mutate(doc["extras"])
        return bp.validate_catalog(doc, extras, deps, unwired)

    assert errs(lambda e: e.pop("chinese"))                                   # missing extra
    assert errs(lambda e: e.update(ghost={"decision": "deferred", "reason": "x"}))
    assert errs(lambda e: e["prosody"].pop("reason"))                         # no reason
    assert errs(lambda e: e["prosody"].update(decision="maybe"))
    assert errs(lambda e: e["diarization"].update(features=["diarize"]))      # incomplete
    diar = ["diarize", "recimport", "meeting"]
    assert errs(lambda e: e["diarization"].update(features=[*diar, "agent"]))
    assert errs(lambda e: e["diarization"].update(features=[*diar, "stt-parakeet"]))
    assert errs(lambda e: e["diarization"].update(entry_modules=[]))
    assert errs(lambda e: e["diarization"].update(approved_large=True))       # no approver
    # bind_to_base: bare DLL basenames only, with the reviewed evidence, packs only.
    assert errs(lambda e: e["diarization"].update(bind_to_base=["lib/onnxruntime.dll"]))
    assert errs(lambda e: e["diarization"].update(bind_to_base=["onnxruntime"]))
    assert errs(lambda e: e["diarization"].update(bind_to_base="onnxruntime.dll"))
    assert errs(lambda e: e["diarization"].pop("bind_reason"))
    assert errs(lambda e: e["parakeet"].update(bind_to_base=["onnxruntime.dll"]))
    # A bundled extra that grew pack fields is a contradiction, not a pack.
    assert errs(lambda e: e["parakeet"].update(entry_modules=["onnx_asr"]))
    assert errs(lambda e: e["chinese"].update(features=["chinese-script"]))


# --- the Phase 0 spike: pure parts -----------------------------------------------------


def test_inject_runtime_hook_into_the_real_spec(bp):
    text = SPEC.read_text(encoding="utf-8")
    out = bp.inject_runtime_hook(text, "C:\\a\\rthook.py")
    ast.parse(out)
    assert "runtime_hooks=['C:\\\\a\\\\rthook.py', " in out
    assert out.replace("'C:\\\\a\\\\rthook.py', ", "") == text


def test_inject_runtime_hook_needs_exactly_one_list(bp):
    with pytest.raises(ValueError):
        bp.inject_runtime_hook("a = 1\n", "h.py")
    with pytest.raises(ValueError):
        bp.inject_runtime_hook("runtime_hooks=[]\nruntime_hooks=[]\n", "h.py")
    assert bp.inject_runtime_hook("runtime_hooks=['x']", "h") == "runtime_hooks=['h', 'x']"


def test_the_shipped_spec_never_carries_the_spike_hook():
    assert "rthook_pack_spike" not in SPEC.read_text(encoding="utf-8")


def test_scan_imports_and_candidates(bp):
    src = ("import os, numpy.linalg\nfrom huggingface_hub.utils import x\n"
           "from . import rel\nfrom onnx_asr.models import y\nimport json\n")
    found = bp.scan_imports(src)
    assert found == {"os", "numpy.linalg", "huggingface_hub.utils", "onnx_asr.models", "json"}
    std, subs = bp.spike_candidates(found, {"os", "json"}, {"onnx_asr"},
                                    {"numpy", "huggingface_hub"})
    assert std == ["json", "os"]
    assert subs == ["huggingface_hub.utils", "numpy.linalg"]
    assert bp.scan_imports("def (:\n") == set()


def _good_result():
    return {
        "frozen": True, "meipass": "C:/x/_internal",
        "entry": {"onnx_asr": {"ok": True, "file": "C:/p/site/onnx_asr/__init__.py"}},
        "sweep_imported": 5, "sweep_failures": [],
        "stdlib_checked": ["json"], "stdlib_missing": [],
        "base_submodules_checked": ["numpy.linalg"], "base_submodules_missing": [],
        "metadata": {"pack": {"onnx-asr": "0.12.0"}, "base": {"numpy": "2.4.6"}},
        "loaded_collisions": {},
    }


def _verdict(rows, prefix):
    hits = [v for p, v, _ in rows if p.startswith(prefix)]
    assert hits, prefix
    return hits


def test_spike_verdicts_cover_the_four_risks(bp):
    rows = bp.spike_verdicts({"dll_conflicts": [], "dll_dropped": []}, _good_result())
    for prefix in ("mount", "(a)", "(b)", "(c)", "(d)", "probe ran inside"):
        assert set(_verdict(rows, prefix)) == {bp.PASS}, prefix


def test_spike_verdicts_fail_where_the_risk_is_real(bp):
    r = _good_result()
    r["entry"]["onnx_asr"] = {"ok": False, "error": "x", "missing": "lzma", "kind": "stdlib"}
    r["metadata"]["base"]["numpy"] = None
    r["sweep_failures"] = [{"module": "onnx_asr.hub", "missing": "huggingface_hub.hf_api",
                            "kind": "base-submodule"}]
    r["frozen"] = False
    rows = bp.spike_verdicts({"dll_conflicts": ["onnxruntime.dll: differs"], "dll_dropped": []}, r)
    for prefix in ("mount", "(a)", "(c)", "(d)", "probe ran inside"):
        assert bp.FAIL in _verdict(rows, prefix), prefix
    assert _verdict(rows, "(b) importlib.metadata sees base") == [bp.FAIL]


def test_spike_verdicts_without_a_result_fail(bp):
    rows = bp.spike_verdicts({"dll_conflicts": []}, None)
    assert rows[0][1] == bp.FAIL
    assert bp.spike_verdicts({}, {"crash": "boom"})[0][1] == bp.FAIL


def test_summary_has_one_plain_pass_fail_line_per_probe(bp):
    rows = bp.spike_verdicts({"dll_conflicts": [], "dll_dropped": []}, _good_result())
    text = bp.render_summary("t", {"parakeet": rows})
    assert "PASS: parakeet: (a) stdlib modules present in the frozen app" in text
    assert text.count("PASS: parakeet:") == sum(1 for _, v, _ in rows if v == bp.PASS)


# --- probe (d) bind: sherpa_onnx on the base's onnxruntime ---------------------------

_BASE_ORT = "D:/a/dist/YazSes/_internal/onnxruntime/capi/onnxruntime.dll"
_BOUND_ENTRY = {
    "dll_conflicts": [],
    "dll_dropped": ["site/sherpa_onnx/lib/onnxruntime.dll"],
    "dll_bound_to_base": ["site/sherpa_onnx/lib/onnxruntime.dll"],
}


def _bound_result():
    r = _good_result()
    r["entry"] = {"sherpa_onnx": {"ok": True, "file": "D:/w/spike/diarization/site/x"}}
    r["bind"] = {
        "pack_root": "D:/w/spike/diarization",
        "preloaded": {"onnxruntime.dll": _BASE_ORT.replace("/", "\\")},
        "preload_errors": {},
        "loaded": {"onnxruntime.dll": [_BASE_ORT.replace("/", "\\")]},
        "expected_ort_version": "1.28.0",
        "ort": {"version": "1.28.0", "file": "D:/a/dist/YazSes/_internal/onnxruntime/__init__.pyc"},
        "ort_session": {"ok": True},
        "native_session": {"ok": True},
    }
    return r


def _bind_row(bp, result, entry=_BOUND_ENTRY):
    rows = [r for r in bp.spike_verdicts(entry, result) if r[0] == bp.BIND_PROBE]
    assert len(rows) == 1
    return rows[0]


def test_bind_probe_passes_and_names_the_loaded_dll_and_version(bp):
    _, verdict, detail = _bind_row(bp, _bound_result())
    assert verdict == bp.PASS, detail
    assert "onnxruntime\\capi\\onnxruntime.dll" in detail and "onnxruntime 1.28.0" in detail
    text = bp.render_summary("t", {"diarization": bp.spike_verdicts(_BOUND_ENTRY, _bound_result())})
    line = next(ln for ln in text.splitlines() if ln.startswith("PASS: diarization: (d) bind"))
    assert "onnxruntime.dll <- " in line and "1.28.0" in line


@pytest.mark.parametrize("breakage", [
    "two_copies", "from_pack", "wrong_version", "no_expected", "ort_session",
    "native_session", "not_preloaded", "entry_failed", "no_bind_result",
])
def test_bind_probe_fails_on_each_real_failure(bp, breakage):
    r = _bound_result()
    b = r["bind"]
    pack_copy = "D:\\w\\spike\\diarization\\site\\sherpa_onnx\\lib\\onnxruntime.dll"
    if breakage == "two_copies":
        b["loaded"]["onnxruntime.dll"].append("C:\\Windows\\System32\\onnxruntime.dll")
    elif breakage == "from_pack":
        b["loaded"]["onnxruntime.dll"] = [pack_copy]
    elif breakage == "wrong_version":
        b["ort"]["version"] = "1.28.2"
    elif breakage == "no_expected":
        b["expected_ort_version"] = ""
    elif breakage == "ort_session":
        b["ort_session"] = {"ok": False, "error": "InvalidGraph"}
    elif breakage == "native_session":
        b["native_session"] = {"ok": False, "error": "OrtGetApiBase returned NULL"}
    elif breakage == "not_preloaded":
        b["preloaded"] = {}
        b["preload_errors"] = {"onnxruntime.dll": "OSError(126)"}
    elif breakage == "entry_failed":
        r["entry"]["sherpa_onnx"] = {"ok": False, "error": "DLL load failed"}
    elif breakage == "no_bind_result":
        del r["bind"]
    assert _bind_row(bp, r)[1] == bp.FAIL


def test_the_bind_row_appears_only_for_a_pack_that_binds(bp):
    rows = bp.spike_verdicts({"dll_conflicts": [], "dll_dropped": []}, _good_result())
    assert bp.BIND_PROBE not in [p for p, _, _ in rows]


def test_spike_bind_request_puts_the_onnxruntime_package_copy_first(bp, tmp_path):
    base = ["_internal/onnxruntime.dll", "_internal/onnxruntime/capi/onnxruntime.dll",
            "_internal/other.dll"]
    req = bp.spike_bind_request(["OnnxRuntime.dll"], base, tmp_path)
    assert list(req) == ["onnxruntime.dll"]
    assert req["onnxruntime.dll"][0] == str(tmp_path / "_internal/onnxruntime/capi/onnxruntime.dll")
    assert len(req["onnxruntime.dll"]) == 2
    assert bp.spike_bind_request(["missing.dll"], base, tmp_path) == {"missing.dll": []}


# --- the spike hook itself, run unfrozen --------------------------------------------


def test_the_spike_hook_is_inert_without_its_variable():
    env = {k: v for k, v in os.environ.items() if k != "YAZSES_PACK_SPIKE_REQUEST"}
    out = subprocess.run([sys.executable, "-I", str(HOOK)], env=env, capture_output=True,
                         text=True, timeout=60, check=False)
    assert out.returncode == 0 and out.stdout == ""


def test_the_spike_hook_mounts_imports_and_reports(tmp_path):
    site = tmp_path / "site"
    (site / "fakepack").mkdir(parents=True)
    (site / "fakepack" / "__init__.py").write_text("import json\nVALUE = 7\n", encoding="utf-8")
    (site / "fakepack" / "sub.py").write_text("import nonexistent_dep_xyz\n", encoding="utf-8")
    di = site / "fakepack-1.0.dist-info"
    di.mkdir()
    (di / "METADATA").write_text("Metadata-Version: 2.1\nName: fakepack\nVersion: 1.0\n",
                                 encoding="utf-8")
    result = tmp_path / "result.json"
    req = tmp_path / "req.json"
    req.write_text(json.dumps({
        "site": str(site), "native_dirs": [], "entry_modules": ["fakepack"],
        "pack_packages": ["fakepack"], "distributions": ["fakepack"],
        "base_requires": ["definitely-not-installed-xyz"], "stdlib_candidates": ["json"],
        "base_submodule_candidates": [], "base_modules": [], "collided_dlls": [],
        "result": str(result),
    }), encoding="utf-8")
    env = dict(os.environ, YAZSES_PACK_SPIKE_REQUEST=str(req))
    out = subprocess.run([sys.executable, "-I", str(HOOK)], env=env, capture_output=True,
                         text=True, timeout=120, check=False)
    assert out.returncode == 0, out.stderr
    data = json.loads(result.read_text(encoding="utf-8"))
    assert data["entry"]["fakepack"]["ok"]
    assert data["sys_path_after"][-1] == str(site), "the pack must be APPENDED to sys.path"
    assert data["metadata"]["pack"] == {"fakepack": "1.0"}
    assert data["metadata"]["base"] == {"definitely-not-installed-xyz": None}
    assert [f["missing"] for f in data["sweep_failures"]] == ["nonexistent_dep_xyz"]
    assert data["stdlib_missing"] == []
    assert data["bind"]["preloaded"] == {}, "no bind request, nothing preloaded"
    assert "ort" not in data["bind"], "onnxruntime is imported only for a binding pack"


def test_the_spike_hook_records_a_bind_attempt_and_never_crashes(tmp_path):
    """Off Windows the preload cannot work; the hook must say so in the JSON, not die."""
    site = tmp_path / "site"
    site.mkdir()
    result = tmp_path / "result.json"
    req = tmp_path / "req.json"
    req.write_text(json.dumps({
        "site": str(site), "native_dirs": [], "entry_modules": [], "pack_packages": [],
        "distributions": [], "base_requires": [], "stdlib_candidates": [],
        "base_submodule_candidates": [], "base_modules": [], "collided_dlls": [],
        "bind_to_base": {"onnxruntime.dll": [str(tmp_path / "base" / "onnxruntime.dll")]},
        "expected_ort_version": "1.28.0", "session_model": None, "result": str(result),
    }), encoding="utf-8")
    env = dict(os.environ, YAZSES_PACK_SPIKE_REQUEST=str(req))
    out = subprocess.run([sys.executable, "-I", str(HOOK)], env=env, capture_output=True,
                         text=True, timeout=120, check=False)
    assert out.returncode == 0, out.stderr
    bind = json.loads(result.read_text(encoding="utf-8"))["bind"]
    assert bind["pack_root"] == str(tmp_path)
    assert bind["expected_ort_version"] == "1.28.0"
    if sys.platform != "win32":
        assert "onnxruntime.dll" in bind["preload_errors"]
    assert bind["ort_session"] == {"ok": False, "error": "no --session-model given"}
    assert bind["native_session"]["ok"] is False
    assert "onnxruntime.dll" in bind["loaded"]


# --- the build orchestration, with uv and the probe faked ----------------------------


class _FakeDist:
    def __init__(self, files):
        self.files = files


def _fake_bundle(tmp_path):
    dist = tmp_path / "dist" / "YazSes"
    (dist / "_internal" / "numpy").mkdir(parents=True)
    (dist / "_internal" / "numpy" / "__init__.pyc").write_bytes(b"np")
    (dist / "_internal" / "onnxruntime.dll").write_bytes(b"base-ort")
    (dist / "yazses-cli.exe").write_bytes(b"exe")
    return dist


#: requirement name -> files `uv pip install --target` would lay down.
_WHEELS = {
    "onnx-asr": {"onnx_asr/__init__.py": b"import numpy\n"},
    "sherpa-onnx": {"sherpa_onnx/__init__.py": b"x = 1\n",
                    "sherpa_onnx/lib/sherpa-onnx-c-api.dll": b"dll"},
}


class _Probes(list):
    """The pack names the fake probe saw, plus ``.exports``: every `uv export` call."""

    exports: list[list[str]]


#: A two-pack catalogue (the pre-Q1 shape), so the orchestration tests can exercise
#: withholding one pack while the other ships. The real packs.toml is used where the
#: test says so (``real_catalog=True``).
_SYNTH_CATALOG = """format = 1
[extras.desktop]
decision = "bundled"
reason = "the frozen base"
[extras.parakeet]
decision = "pack"
features = ["stt-parakeet"]
entry_modules = ["onnx_asr"]
[extras.diarization]
decision = "pack"
features = ["diarize"]
entry_modules = ["sherpa_onnx"]
"""

#: What each extra adds to `uv export`; numpy stands for the shared transitive base.
_EXPORT_LINES = {
    "desktop": "pyside6==6.11.1 \\\n    --hash=sha256:44\n",
    "overlay": "pyside6==6.11.1 \\\n    --hash=sha256:44\n",
    "parakeet": "onnx-asr==0.12.0 \\\n    --hash=sha256:22\n",
    "chinese": "opencc-python-reimplemented==0.1.7 \\\n    --hash=sha256:55\n",
    "diarization": "sherpa-onnx==1.13.8 \\\n    --hash=sha256:33\n",
}
_FAKE_EXTRAS = {
    "desktop": ["PySide6>=6.11.1"], "overlay": ["PySide6>=6.11.1"],
    "parakeet": ["onnx-asr[cpu,hub]>=0.12"],
    "chinese": ["opencc-python-reimplemented>=0.1.7"],
    "diarization": ["sherpa-onnx>=1.13.6"],
}


def _install_fake(monkeypatch, bp, tmp_path, *, fail_probe=(), probe_hook=None, extra_files=None,
                  real_catalog=False, venv_missing=()):
    (tmp_path / "packs.toml").write_text(
        bp.PACKS_TOML.read_text(encoding="utf-8") if real_catalog else _SYNTH_CATALOG,
        encoding="utf-8")
    exports_seen = []

    def fake_export(extras):
        extras = list(extras)
        exports_seen.append(extras)
        text = "numpy==2.4.6 \\\n    --hash=sha256:11\n" + "".join(
            _EXPORT_LINES[x] for x in sorted(set(extras)))
        return bp.parse_requirements_export(text)

    monkeypatch.setattr(bp, "uv_export", fake_export)
    venv = {"numpy": _FakeDist(["numpy/__init__.py"]),
            "pyside6": _FakeDist(["PySide6/__init__.py"]),
            "onnx-asr": _FakeDist(["onnx_asr/__init__.py"]),
            "opencc-python-reimplemented": _FakeDist(["opencc/__init__.py"])}
    for name in venv_missing:
        venv.pop(name)
    monkeypatch.setattr(bp, "installed_distributions", lambda: dict(venv))
    # The build runs on the Windows release runner; pin that, or a leg whose platform has
    # no asset OS token (FreeBSD) withholds every pack and the assertions below test nothing.
    monkeypatch.setattr(bp, "host_platform", lambda: "win-amd64")
    monkeypatch.setattr(bp, "read_project", lambda: ("9.9.9", dict(_FAKE_EXTRAS)))
    probes = _Probes()

    def fake_run(cmd, **kw):
        if cmd[:3] == ["uv", "pip", "install"]:
            target = Path(cmd[cmd.index("--target") + 1])
            names = bp.parse_requirements_export(
                Path(cmd[cmd.index("-r") + 1]).read_text(encoding="utf-8"))
            for name in names:
                files = {**_WHEELS[name], **(extra_files or {}).get(name, {})}
                for rel, data in files.items():
                    (target / rel).parent.mkdir(parents=True, exist_ok=True)
                    (target / rel).write_bytes(data)
                di = target / f"{name.replace('-', '_')}-1.0.dist-info"
                di.mkdir(exist_ok=True)
                (di / "METADATA").write_text(
                    f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\nLicense: MIT\n",
                    encoding="utf-8")
                (di / "LICENSE").write_text("MIT\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        name = cmd[cmd.index("probe") + 1]
        staged = Path(cmd[cmd.index("--staged") + 1])
        assert (staged / "pack.json").is_file(), "the probe must get the extracted pack root"
        assert kw["env"]["LOCALAPPDATA"] != os.environ.get("LOCALAPPDATA"), "sandboxed data dir"
        probes.append(name)
        if probe_hook:
            probe_hook(name)
        return subprocess.CompletedProcess(cmd, 1 if name in fail_probe else 0, "", "")

    monkeypatch.setattr(bp, "_run", fake_run)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    probes.exports = exports_seen
    return probes


def _argv(tmp_path, dist, *extra):
    return ["build", "--dist", str(dist), "--out", str(tmp_path / "out"),
            "--work", str(tmp_path / "work"), "--arch", "x64",
            "--catalog", str(tmp_path / "packs.toml"),
            "--probe-exe", str(dist / "yazses-cli.exe"), *extra]


def _tree(dist):
    return {p.relative_to(dist).as_posix(): p.read_bytes()
            for p in dist.rglob("*") if p.is_file()}


def test_build_publishes_probed_packs_and_embeds_the_same_index(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    before = _tree(dist)
    probes = _install_fake(monkeypatch, bp, tmp_path)
    assert bp.main(_argv(tmp_path, dist)) == 0
    assert sorted(probes) == ["diarization", "parakeet"]
    out = tmp_path / "out"
    os_tok = bp.os_token(bp.host_platform())
    idx_name = bp.index_asset_name("9.9.9", os_tok, "x64")
    embedded = dist / bp.EMBEDDED_INDEX
    assert embedded.read_bytes() == (out / idx_name).read_bytes()
    doc = json.loads(embedded.read_bytes())
    assert bp.validate_index(doc) == []
    assert [p["name"] for p in doc["packs"]] == ["diarization", "parakeet"]
    manifest = (tmp_path / "work" / "base-manifest.json").read_bytes()
    assert doc["base_build_id"] == bp.build_id_of(manifest)
    for p in doc["packs"]:
        archive = out / p["asset"]
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == p["sha256"]
        assert archive.stat().st_size == p["size"]
        with zipfile.ZipFile(archive) as zf:
            pj = json.loads(zf.read("pack.json"))
            assert pj["base_build_id"] == doc["base_build_id"]
            assert pj["files"] == p["files"] == len(zf.infolist())
            assert any(n.startswith("LICENSES/") for n in zf.namelist())
            if p["name"] == "diarization":
                assert pj["native_dirs"] == ["site/sherpa_onnx/lib"]
    after = _tree(dist)
    after.pop(bp.EMBEDDED_INDEX)
    assert after == before, "pack production changed the base bundle"


def test_a_pack_that_fails_its_probe_is_withheld(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path, fail_probe={"diarization"})
    assert bp.main(_argv(tmp_path, dist)) == 0
    doc = json.loads((dist / bp.EMBEDDED_INDEX).read_bytes())
    assert [p["name"] for p in doc["packs"]] == ["parakeet"]
    assert not list((tmp_path / "out").glob("*diarization*"))
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    assert "probe" in report["withheld"]["diarization"]


def test_no_pack_passing_means_nothing_embedded_or_published(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path, fail_probe={"diarization", "parakeet"})
    assert bp.main(_argv(tmp_path, dist)) == 0
    assert not (dist / bp.EMBEDDED_INDEX).exists()
    assert not (tmp_path / "out").exists()
    assert bp.main(_argv(tmp_path, dist, "--strict")) == 1


def test_a_module_or_dll_collision_withholds_the_pack(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path, extra_files={
        "onnx-asr": {"numpy/__init__.py": b"shadow"},
        "sherpa-onnx": {"sherpa_onnx/lib/onnxruntime.dll": b"other-ort"},
    })
    assert bp.main(_argv(tmp_path, dist)) == 0
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    assert "numpy" in report["withheld"]["parakeet"]
    assert "onnxruntime.dll" in report["withheld"]["diarization"]
    assert not (dist / bp.EMBEDDED_INDEX).exists()


def test_an_identical_dll_is_dropped_not_refused(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path, extra_files={
        "sherpa-onnx": {"sherpa_onnx/lib/onnxruntime.dll": b"base-ort"}})
    assert bp.main(_argv(tmp_path, dist)) == 0
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    entry = report["packs"]["diarization"]
    assert entry["dll_dropped"] == ["site/sherpa_onnx/lib/onnxruntime.dll"]
    with zipfile.ZipFile(entry["archive"]) as zf:
        assert "site/sherpa_onnx/lib/onnxruntime.dll" not in zf.namelist()


_SHERPA_ORT = {"sherpa-onnx": {
    "sherpa_onnx/lib/onnxruntime.dll": b"sherpa-ort-1.28.2",
    "sherpa_onnx_core-1.13.8.data/data/Scripts/onnxruntime.dll": b"sherpa-ort-1.28.2",
}}


def test_bundled_extras_are_never_packed_and_are_subtracted(bp, tmp_path, monkeypatch):
    """ADR-028 Q1 on the real packs.toml: one pack, built against the bundled base."""
    dist = _fake_bundle(tmp_path)
    probes = _install_fake(monkeypatch, bp, tmp_path, real_catalog=True, extra_files=_SHERPA_ORT)
    assert bp.main(_argv(tmp_path, dist)) == 0
    assert list(probes) == ["diarization"]
    bundled = sorted(bp.bundled_extras(bp.load_catalog(tmp_path / "packs.toml")))
    assert probes.exports[0] == bundled, "the base is measured from the bundled extras"
    assert probes.exports[1] == [*bundled, "diarization"]
    assert len(probes.exports) == 2, "no export for a bundled extra as a pack"
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    assert report["base_extras"] == bundled
    assert set(report["packs"]) == {"diarization"} and report["withheld"] == {}
    assert report["packs"]["diarization"]["requirements"] == ["sherpa-onnx"]
    doc = json.loads((dist / bp.EMBEDDED_INDEX).read_bytes())
    assert [p["name"] for p in doc["packs"]] == ["diarization"]
    assert not [p for p in (tmp_path / "out").iterdir() if "parakeet" in p.name
                or "chinese" in p.name]


def test_a_venv_without_a_bundled_extra_withholds_every_pack(bp, tmp_path, monkeypatch, capsys):
    """build-windows.ps1 forgot --extra parakeet: the packs' "minus the base" is wrong."""
    dist = _fake_bundle(tmp_path)
    before = _tree(dist)
    probes = _install_fake(monkeypatch, bp, tmp_path, real_catalog=True,
                           extra_files=_SHERPA_ORT, venv_missing=("onnx-asr",))
    assert bp.main(_argv(tmp_path, dist)) == 0
    assert bp.main(_argv(tmp_path, dist, "--strict")) == 1
    assert list(probes) == []
    assert "onnx-asr" in capsys.readouterr().err
    assert not (dist / bp.EMBEDDED_INDEX).exists() and not (tmp_path / "out").exists()
    assert _tree(dist) == before


def test_the_diarization_pack_binds_onnxruntime_to_the_base(bp, tmp_path, monkeypatch):
    """M1: sherpa's own onnxruntime.dll (both copies) is dropped and pack.json says so."""
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path, real_catalog=True, extra_files=_SHERPA_ORT)
    assert bp.main(_argv(tmp_path, dist)) == 0
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    entry = report["packs"]["diarization"]
    bound = ["site/sherpa_onnx/lib/onnxruntime.dll",
             "site/sherpa_onnx_core-1.13.8.data/data/Scripts/onnxruntime.dll"]
    assert sorted(entry["dll_bound_to_base"]) == sorted(bound)
    assert entry["dll_conflicts"] == [] and entry["dll_bind_unused"] == []
    with zipfile.ZipFile(entry["archive"]) as zf:
        names = zf.namelist()
        assert not [n for n in names if n.lower().endswith("onnxruntime.dll")]
        assert "site/sherpa_onnx/lib/sherpa-onnx-c-api.dll" in names
        pj = json.loads(zf.read("pack.json"))
    assert pj["bind_to_base"] == ["onnxruntime.dll"]
    assert pj["native_dirs"] == ["site/sherpa_onnx/lib"]
    assert entry["pack_json"]["bind_to_base"] == ["onnxruntime.dll"]


def test_without_the_allow_list_the_same_build_withholds_diarization(bp, tmp_path, monkeypatch):
    """The red half of the bind test: drop `bind_to_base` and the pack is withheld."""
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path, real_catalog=True, extra_files=_SHERPA_ORT)
    toml = tmp_path / "packs.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        'bind_to_base = ["onnxruntime.dll"]', ""), encoding="utf-8")
    assert bp.main(_argv(tmp_path, dist)) == 0
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    assert "onnxruntime.dll" in report["withheld"]["diarization"]


def test_another_dll_collision_still_withholds_a_binding_pack(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    (dist / "_internal" / "vcruntime140.dll").write_bytes(b"base-vc")
    _install_fake(monkeypatch, bp, tmp_path, real_catalog=True, extra_files={"sherpa-onnx": {
        **_SHERPA_ORT["sherpa-onnx"], "sherpa_onnx/lib/vcruntime140.dll": b"other-vc"}})
    assert bp.main(_argv(tmp_path, dist)) == 0
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    why = report["withheld"]["diarization"]
    assert "vcruntime140.dll" in why and "onnxruntime.dll" not in why
    assert not (dist / bp.EMBEDDED_INDEX).exists()


def test_a_base_that_changed_during_packing_fails_the_build(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path,
                  probe_hook=lambda name: (dist / "_internal" / "stray.txt").write_text(
                      "x", encoding="utf-8"))
    assert bp.main(_argv(tmp_path, dist)) == 1
    assert not (dist / bp.EMBEDDED_INDEX).exists()


def test_an_unexpected_error_ships_the_base_without_packs(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("index writer exploded")

    monkeypatch.setattr(bp, "build_index", boom)
    assert bp.main(_argv(tmp_path, dist)) == 0
    assert not (dist / bp.EMBEDDED_INDEX).exists()
    assert not (tmp_path / "out").exists()


def test_skip_probe_embeds_and_publishes_nothing(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    probes = _install_fake(monkeypatch, bp, tmp_path)
    argv = _argv(tmp_path, dist)
    argv[argv.index("--probe-exe"):argv.index("--probe-exe") + 2] = ["--skip-probe"]
    assert bp.main(argv) == 0
    assert probes == []
    assert not (dist / bp.EMBEDDED_INDEX).exists() and not (tmp_path / "out").exists()
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    assert set(report["packs"]) == {"diarization", "parakeet"}


# --- wiring into the Windows build ---------------------------------------------------


def test_build_windows_ps1_builds_and_probes_packs_between_pyinstaller_and_inno():
    text = PS1.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    pyi = code.index("uv run pyinstaller")
    packs = code.index("scripts\\build-packs.py build")
    inno = code.index("& $Iscc")
    assert pyi < packs < inno
    block = code[packs:inno]
    assert "--probe-exe" in block and "--skip-probe" not in block
    assert "$LASTEXITCODE" in block


def test_release_workflow_attests_and_attaches_the_packs(bp):
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(BUILD_WINDOWS.read_text(encoding="utf-8"))
    steps = doc["jobs"]["build"]["steps"]
    names = [s.get("name", "") for s in steps]
    attest = steps[names.index("Attest build provenance for the add-on packs")]
    subject = attest["with"]["subject-path"]
    attach = steps[names.index("Attach add-on packs to release (tag builds only)")]
    files = attach["with"]["files"]
    import fnmatch

    for sample in (bp.pack_asset_name("2.44.0", "windows", "x64", "parakeet"),
                   bp.index_asset_name("2.44.0", "windows", "x64")):
        for patterns in (subject, files):
            pats = [p.strip().replace("${{ matrix.arch }}", "x64")
                    for p in patterns.splitlines() if p.strip()]
            assert any(fnmatch.fnmatch(f"dist/packs/{sample}", p) for p in pats), (sample, pats)
    assert bp.provenance_asset_name("2.44.0", "windows", "x64").replace("2.44.0", "*") in (
        files.replace("${{ matrix.arch }}", "x64"))
    # The installer is attached BEFORE the packs, so a pack problem cannot cost it.
    assert names.index("Attach to release (tag builds only)") < names.index(
        "Attach add-on packs to release (tag builds only)")


def test_the_spike_workflow_is_manual_read_only_and_never_publishes():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(SPIKE_WORKFLOW.read_text(encoding="utf-8"))
    triggers = doc.get(True, doc.get("on"))
    assert set(triggers) == {"workflow_dispatch"}
    assert doc["permissions"] == {"contents": "read"}
    job = doc["jobs"]["spike"]
    assert "permissions" not in job and job["runs-on"].startswith("windows")
    text = SPIKE_WORKFLOW.read_text(encoding="utf-8")
    assert "spike-spec" in text and "spike-probe" in text and "--skip-probe" in text
    assert "action-gh-release" not in text and "gh release" not in text
    assert "yazses.spec --out packaging/windows/yazses-spike.spec" in text


def test_the_build_script_runs_on_the_standard_library_alone():
    """It must run under a bare python3 in release-complete.yml (no uv sync there)."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    tops = {
        (n.module if isinstance(n, ast.ImportFrom) else a.name).split(".")[0]
        for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [SimpleNamespace(name=n.module)])
        if not (isinstance(n, ast.ImportFrom) and n.module == "__future__")
    }
    assert tops <= set(sys.stdlib_module_names), tops - set(sys.stdlib_module_names)


def test_a_relative_preload_matching_the_loaded_base_copy_passes(bp):
    """windows-latest run 39631811305: the hook recorded the request as given
    (``dist\\YazSes\\_internal\\...``) and the loader reported the same file absolutely
    (``D:\\a\\...\\dist\\YazSes\\_internal\\...``); a correct bind was reported FAIL."""
    r = _bound_result()
    rel = "dist\\YazSes\\_internal\\onnxruntime\\capi\\onnxruntime.dll"
    r["bind"]["preloaded"] = {"onnxruntime.dll": rel}
    r["bind"]["loaded"] = {"onnxruntime.dll": ["D:\\a\\yazses\\yazses\\" + rel]}
    _, verdict, detail = _bind_row(bp, r)
    assert verdict == bp.PASS, detail


def test_a_relative_preload_does_not_excuse_a_different_file(bp):
    r = _bound_result()
    r["bind"]["preloaded"] = {"onnxruntime.dll": "dist\\YazSes\\_internal\\onnxruntime\\capi\\onnxruntime.dll"}
    r["bind"]["loaded"] = {"onnxruntime.dll": ["D:\\elsewhere\\onnxruntime.dll"]}
    assert _bind_row(bp, r)[1] == bp.FAIL
    # Nor a path that only shares a suffix without a directory boundary.
    r["bind"]["loaded"] = {"onnxruntime.dll": ["D:\\a\\xdist\\YazSes\\_internal\\onnxruntime\\capi\\onnxruntime.dll"]}
    assert _bind_row(bp, r)[1] == bp.FAIL
