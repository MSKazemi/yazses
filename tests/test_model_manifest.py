"""scripts/check_model_manifest.py and scripts/model_manifest.py: the offline gate on the
model provenance manifest (issue #694).

Everything runs offline. The pure checks are exercised on deep copies of the real manifest
(each test breaks exactly one thing and expects exactly that to be reported) and on fixture
files in tmp_path. Nothing here downloads a model or imports a Hugging Face package, so no
`needs_faster_whisper` marker is needed and the FreeBSD dependency set runs it unchanged.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
HCI = ROOT / "design" / "hci-huggingface"


def _load(name: str):
    """Load scripts/<name>.py by path (see tests/test_hf_preflight.py for why not `import`)."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


mm = _load("model_manifest")
cli = _load("check_model_manifest")

SCHEMA = json.loads((HCI / "model-manifest.schema.json").read_text(encoding="utf-8"))
MANIFEST = mm.loads_strict((HCI / "model-manifest.json").read_text(encoding="utf-8"))
INVENTORY = (HCI / "model-provenance.md").read_text(encoding="utf-8")


def fresh() -> dict:
    return copy.deepcopy(MANIFEST)


def entry(doc: dict, ident: str) -> dict:
    return next(m for m in doc["models"] if m["id"] == ident)


def problems(doc: dict, *, inventory: str | None = None) -> list[str]:
    return mm.check_all(doc, SCHEMA, repo_root=ROOT, inventory_text=inventory)


def assert_only(doc: dict, needle: str, *, inventory: str | None = None) -> None:
    found = problems(doc, inventory=inventory)
    assert found, f"expected a problem mentioning {needle!r}, got none"
    assert any(needle in line for line in found), f"{needle!r} not in {found}"


# Stable fixtures drawn from the real manifest.
GIT = "systran--faster-whisper-base.en"  # git-commit revision, used-default, no artifacts
SILERO = "silero-vad-v6-faster-whisper-bundled"  # recorded sha256 + relative_path
MEDIAPIPE = "mediapipe-face-landmarker-float16"  # partial: md5 etag, unknown sha256
SHERPA = "sherpa-onnx-pyannote-segmentation-3-0"  # tag revision, unknown licence
NC = "braindecode--vemg2pose-emg2pose"  # cc-by-nc-sa-4.0 candidate


# --- the real manifest ---------------------------------------------------------------------


def test_real_manifest_is_clean() -> None:
    assert problems(MANIFEST, inventory=INVENTORY) == []


def test_real_manifest_covers_every_inventory_table() -> None:
    tables = {m["inventory_table"] for m in MANIFEST["models"]}
    assert tables == {"A1", "A2", "A3", "A4", "B"}
    assert len(MANIFEST["models"]) == len({m["id"] for m in MANIFEST["models"]})


def test_cli_passes_on_the_real_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "model entries valid" in capsys.readouterr().out


def test_inventory_states_what_the_manifest_records_about_pins() -> None:
    """model-provenance.md: 'No revision pins anywhere in the loaders'. If code ever starts
    passing a revision, flip `pinned_by_yazses` in the same change as the loader."""
    assert [m["id"] for m in MANIFEST["models"] if m["revision"]["pinned_by_yazses"]] == []
    assert "No revision pins anywhere in the loaders" in INVENTORY


def test_unknowns_are_written_down_not_guessed() -> None:
    unknown_lic = {m["id"] for m in MANIFEST["models"] if m["license"]["status"] == "unknown"}
    assert {SHERPA, SILERO, MEDIAPIPE, "l2cs-net", "silero-vad-package"} <= unknown_lic
    assert all("id" not in m["license"] for m in MANIFEST["models"] if m["id"] in unknown_lic)
    # The only sha256 the inventory computed is the bundled Silero file.
    hashed = [
        m["id"] for m in MANIFEST["models"] for a in m["artifacts"] if "sha256" in a
    ]
    assert hashed == [SILERO]
    # The mutable, tag- or path-versioned sources are labelled as such, never as git commits.
    assert entry(MANIFEST, SHERPA)["revision"]["kind"] == "tag"
    assert entry(MANIFEST, MEDIAPIPE)["revision"]["kind"] == "versioned-path"


def test_nothing_unlicensed_or_non_commercial_is_marked_redistributed() -> None:
    assert [m["id"] for m in MANIFEST["models"] if m["redistributed_by_yazses"]] == []
    assert entry(MANIFEST, NC)["license"]["id"] == "cc-by-nc-sa-4.0"
    assert entry(MANIFEST, NC)["status"] == "candidate-not-used"


def test_inventory_links_the_manifest_and_schema() -> None:
    assert "model-manifest.schema.json" in INVENTORY
    assert "check_model_manifest.py" in INVENTORY


# --- schema: one test per rule --------------------------------------------------------------


REQUIRED_MODEL_FIELDS = SCHEMA["$defs"]["model"]["required"]


@pytest.mark.parametrize("field", REQUIRED_MODEL_FIELDS)
def test_every_required_model_field_is_enforced(field: str) -> None:
    doc = fresh()
    del doc["models"][0][field]
    assert_only(doc, f"missing required field {field!r}")


@pytest.mark.parametrize("field", SCHEMA["required"])
def test_every_required_top_level_field_is_enforced(field: str) -> None:
    doc = fresh()
    del doc[field]
    assert_only(doc, f"missing required field {field!r}")


def test_unexpected_field_is_rejected() -> None:
    doc = fresh()
    doc["models"][0]["guessed_sha"] = "abc"
    assert_only(doc, "unexpected field 'guessed_sha'")


def test_wrong_schema_version() -> None:
    doc = fresh()
    doc["schema_version"] = 2
    assert_only(doc, "must be 1")


def test_boolean_is_not_an_integer_or_the_const_one() -> None:
    doc = fresh()
    doc["schema_version"] = True
    assert_only(doc, "must be 1")
    doc = fresh()
    entry(doc, SILERO)["artifacts"][0]["size_bytes"] = True
    assert_only(doc, "expected integer")


@pytest.mark.parametrize(
    "bad",
    [
        "d90ca5fe",  # abbreviated
        "D90CA5FE260221311C53C58E660288D3DEB8D356",  # upper case
        "g" * 40,  # not hex
        "d90ca5fe260221311c53c58e660288d3deb8d3560",  # 41 chars
        "main",  # a branch is not a revision
    ],
)
def test_git_commit_revision_must_be_a_full_lowercase_sha(bad: str) -> None:
    doc = fresh()
    entry(doc, GIT)["revision"]["value"] = bad
    assert_only(doc, "revision.value")


def test_git_commit_needs_an_observation_date() -> None:
    doc = fresh()
    del entry(doc, GIT)["revision"]["observed_on"]
    assert_only(doc, "missing required field 'observed_on'")


def test_unknown_revision_must_not_carry_a_value() -> None:
    doc = fresh()
    entry(doc, "l2cs-net")["revision"]["value"] = "0" * 40
    assert_only(doc, "not allowed here")


def test_known_revision_kind_needs_a_value() -> None:
    doc = fresh()
    del entry(doc, SHERPA)["revision"]["value"]
    assert_only(doc, "missing required field 'value'")


def test_revision_kind_is_a_closed_list() -> None:
    doc = fresh()
    entry(doc, GIT)["revision"]["kind"] = "latest"
    assert_only(doc, "revision.kind")


def test_only_a_git_commit_can_be_pinned() -> None:
    doc = fresh()
    entry(doc, SHERPA)["revision"]["pinned_by_yazses"] = True
    assert_only(doc, "revision.kind")


def test_bad_date() -> None:
    doc = fresh()
    entry(doc, GIT)["revision"]["observed_on"] = "28/10/2026"
    assert_only(doc, "observed_on")


def test_unknown_licence_value_is_rejected() -> None:
    doc = fresh()
    entry(doc, GIT)["license"]["id"] = "gpl-3.0-or-later"
    assert_only(doc, "license.id")


def test_stated_licence_needs_an_id() -> None:
    doc = fresh()
    del entry(doc, GIT)["license"]["id"]
    assert_only(doc, "missing required field 'id'")


def test_unknown_licence_must_not_carry_an_id() -> None:
    doc = fresh()
    entry(doc, SHERPA)["license"]["id"] = "mit"
    assert_only(doc, "license.id: not allowed here")


def test_licence_needs_its_wording() -> None:
    doc = fresh()
    entry(doc, GIT)["license"]["as_stated"] = ""
    assert_only(doc, "shorter than 1")


@pytest.mark.parametrize("bad", ["a" * 63, "A" * 64, "g" * 64, "sha256:" + "a" * 64])
def test_malformed_sha256(bad: str) -> None:
    doc = fresh()
    entry(doc, SILERO)["artifacts"][0]["sha256"] = bad
    assert_only(doc, "sha256")


def test_known_sha256_status_needs_a_hash() -> None:
    doc = fresh()
    del entry(doc, SILERO)["artifacts"][0]["sha256"]
    assert_only(doc, "missing required field 'sha256'")


def test_unknown_sha256_status_must_not_carry_a_hash() -> None:
    doc = fresh()
    entry(doc, MEDIAPIPE)["artifacts"][0]["sha256"] = "a" * 64
    assert_only(doc, "sha256: not allowed here")


def test_malformed_md5_etag() -> None:
    doc = fresh()
    entry(doc, MEDIAPIPE)["artifacts"][0]["md5_etag"] = "xyz"
    assert_only(doc, "md5_etag")


def test_negative_size() -> None:
    doc = fresh()
    entry(doc, SILERO)["artifacts"][0]["size_bytes"] = -1
    assert_only(doc, "below the minimum")


def test_not_recorded_hashes_cannot_list_artifacts() -> None:
    doc = fresh()
    entry(doc, GIT)["artifacts"] = [{"name": "model.bin", "sha256_status": "unknown"}]
    assert_only(doc, "allows at most 0 item")


def test_recorded_hashes_need_artifacts() -> None:
    doc = fresh()
    entry(doc, SILERO)["artifacts"] = []
    assert_only(doc, "needs at least 1 item")


def test_used_model_needs_a_code_reference() -> None:
    doc = fresh()
    entry(doc, GIT)["code_refs"] = []
    assert_only(doc, "needs at least 1 item")


def test_malformed_ids_and_sources() -> None:
    doc = fresh()
    entry(doc, GIT)["id"] = "Has Spaces"
    assert_only(doc, ".id")
    doc = fresh()
    entry(doc, GIT)["source"]["location"] = "not-a-repo-id"
    assert_only(doc, "source.location")
    doc = fresh()
    entry(doc, SHERPA)["source"]["location"] = "http://insecure.example/model"
    assert_only(doc, "source.location")
    doc = fresh()
    entry(doc, GIT)["source"]["kind"] = "carrier-pigeon"
    assert_only(doc, "source.kind")


def test_bad_enum_values() -> None:
    for key, bad in (("status", "recommended"), ("role", "tts"), ("inventory_table", "C")):
        doc = fresh()
        entry(doc, GIT)[key] = bad
        assert_only(doc, f".{key}")


def test_wrong_types_are_reported_once_not_cascaded() -> None:
    doc = fresh()
    entry(doc, GIT)["license"] = "mit"
    index = doc["models"].index(entry(doc, GIT))
    assert problems(doc) == [f"$.models[{index}].license: expected object, got str"]


def test_text_fields_cannot_be_blank_so_unknown_must_be_written() -> None:
    doc = fresh()
    entry(doc, GIT)["hardware"] = ""
    assert_only(doc, "shorter than 1")


# --- semantic rules --------------------------------------------------------------------------


def test_duplicate_id() -> None:
    doc = fresh()
    doc["models"][1]["id"] = doc["models"][0]["id"]
    assert_only(doc, "duplicate id")


def test_dangling_and_self_upstream() -> None:
    doc = fresh()
    entry(doc, GIT)["upstream_id"] = "no-such-model"
    assert_only(doc, "is not the id of any entry")
    doc = fresh()
    entry(doc, GIT)["upstream_id"] = GIT
    assert_only(doc, "its own upstream")


def test_redistribution_needs_a_stated_licence() -> None:
    doc = fresh()
    entry(doc, SHERPA)["redistributed_by_yazses"] = True
    assert_only(doc, "needs a stated licence")


def test_redistribution_refuses_non_commercial_licences() -> None:
    doc = fresh()
    entry(doc, NC)["redistributed_by_yazses"] = True
    assert_only(doc, "non-commercial licence")


def test_redistribution_refuses_candidates() -> None:
    doc = fresh()
    candidate = entry(doc, "braindecode--eegpt-pretrained")  # bsd-3-clause, stated
    assert candidate["license"]["status"] == "stated"
    candidate["redistributed_by_yazses"] = True
    assert_only(doc, "candidate-not-used model must not be redistributed")


def test_redistribution_of_a_stated_permissive_licence_is_allowed() -> None:
    doc = fresh()
    entry(doc, GIT)["redistributed_by_yazses"] = True
    assert problems(doc) == []


def test_hash_summary_must_agree_with_the_artifacts() -> None:
    doc = fresh()
    entry(doc, SILERO)["artifact_hashes_status"] = "partial"
    assert_only(doc, "'partial' but every artifact has a sha256")
    doc = fresh()
    entry(doc, MEDIAPIPE)["artifact_hashes_status"] = "recorded"
    assert_only(doc, "'recorded' but an artifact has no sha256")


def test_code_ref_must_name_a_real_repository_file() -> None:
    doc = fresh()
    entry(doc, GIT)["code_refs"][0]["path"] = "src/yazses/stt/does_not_exist.py"
    assert_only(doc, "is not a file inside the repository")


@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "src\\yazses\\config.py", "src/../../x"])
def test_code_ref_cannot_escape_the_repository(bad: str) -> None:
    doc = fresh()
    entry(doc, GIT)["code_refs"][0]["path"] = bad
    assert_only(doc, "is not a file inside the repository")


def test_code_ref_line_must_exist() -> None:
    doc = fresh()
    entry(doc, GIT)["code_refs"][0]["line"] = 10_000_000
    assert_only(doc, "is past the end of")


def test_semantics_are_not_run_on_a_document_of_the_wrong_shape() -> None:
    doc = fresh()
    doc["models"][1]["id"] = doc["models"][0]["id"]
    del doc["models"][0]["name"]
    found = problems(doc)
    assert found and not any("duplicate id" in line for line in found)


# --- traceability to the inventory ------------------------------------------------------------


def test_invented_commit_sha_is_not_traceable() -> None:
    doc = fresh()
    entry(doc, GIT)["revision"]["value"] = "0123456789abcdef0123456789abcdef01234567"
    assert_only(doc, "does not appear in the inventory document", inventory=INVENTORY)


def test_invented_hub_id_is_not_traceable() -> None:
    doc = fresh()
    entry(doc, GIT)["source"]["location"] = "invented/model-that-is-not-listed"
    assert_only(doc, "does not appear in the inventory document", inventory=INVENTORY)


def test_invented_hashes_are_not_traceable() -> None:
    doc = fresh()
    entry(doc, SILERO)["artifacts"][0]["sha256"] = "b" * 64
    assert_only(doc, "does not appear in the inventory document", inventory=INVENTORY)
    doc = fresh()
    entry(doc, MEDIAPIPE)["artifacts"][0]["md5_etag"] = "c" * 32
    assert_only(doc, "does not appear in the inventory document", inventory=INVENTORY)


def test_traceability_is_case_insensitive() -> None:
    assert mm.check_traceability(MANIFEST, INVENTORY.upper()) == []


# --- strict JSON --------------------------------------------------------------------------------


def test_duplicate_json_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        mm.loads_strict('{"a": 1, "a": 2}')


def test_non_json_constants_are_rejected() -> None:
    with pytest.raises(ValueError, match="NaN"):
        mm.loads_strict('{"size_bytes": NaN}')


# --- the schema interpreter ----------------------------------------------------------------------


def test_unsupported_schema_keyword_is_refused_not_ignored() -> None:
    with pytest.raises(mm.SchemaError, match="unsupported schema keyword"):
        mm.validate({}, {"type": "object", "patternProperties": {}}, {})


def test_remote_ref_is_refused() -> None:
    with pytest.raises(mm.SchemaError, match="local"):
        mm.validate({}, {"$ref": "https://example.com/schema.json"}, {})


def test_the_shipped_schema_uses_only_keywords_the_interpreter_implements() -> None:
    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, sub in node.items():
                if key in ("properties", "$defs"):
                    for child in sub.values():
                        walk(child)
                else:
                    assert key in mm._SUPPORTED_KEYWORDS, key
                    if key in ("items", "if", "then", "else", "additionalProperties", "allOf"):
                        for child in sub if isinstance(sub, list) else [sub]:
                            walk(child)

    walk(SCHEMA)


@pytest.mark.parametrize(
    ("schema", "good", "bad"),
    [
        ({"const": 1}, 1, True),
        ({"enum": ["a", "b"]}, "a", "c"),
        ({"type": "integer"}, 3, 3.5),
        ({"type": "string", "pattern": "^x"}, "xy", "yx"),
        ({"type": "array", "items": {"type": "integer"}}, [1], ["1"]),
        ({"type": "array", "maxItems": 1}, [1], [1, 2]),
        ({"type": "object", "additionalProperties": False}, {}, {"k": 1}),
        ({"type": "object", "additionalProperties": {"type": "integer"}}, {"k": 1}, {"k": "v"}),
        ({"if": {"properties": {"a": {"const": 1}}}, "then": {"required": ["b"]}}, {"a": 2}, {"a": 1}),
        ({"properties": {"a": False}}, {}, {"a": 1}),
    ],
)
def test_interpreter_keywords(schema: dict, good: object, bad: object) -> None:
    assert mm.validate(good, schema, schema) == []
    assert mm.validate(bad, schema, schema)


# --- local hash verification (fixtures only, nothing downloaded) -------------------------------------


def _hash_doc(rel: str, payload: bytes, **over: object) -> dict:
    artifact = {
        "name": Path(rel).name,
        "relative_path": rel,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "sha256_status": "computed-locally",
    }
    artifact.update(over)
    return {"models": [{"id": "fixture", "artifacts": [artifact]}]}


def test_local_hash_match(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.bin").write_bytes(b"weights")
    report = mm.verify_local_hashes(_hash_doc("pkg/m.bin", b"weights"), tmp_path)
    assert report.errors == [] and len(report.checked) == 1 and report.skipped == []


def test_local_hash_mismatch(tmp_path: Path) -> None:
    (tmp_path / "m.bin").write_bytes(b"tampered")
    report = mm.verify_local_hashes(_hash_doc("m.bin", b"weights"), tmp_path)
    assert len(report.errors) == 1 and "sha256 of m.bin" in report.errors[0]
    assert report.checked == []


def test_local_size_mismatch(tmp_path: Path) -> None:
    (tmp_path / "m.bin").write_bytes(b"weights")
    report = mm.verify_local_hashes(_hash_doc("m.bin", b"weights", size_bytes=99), tmp_path)
    assert len(report.errors) == 1 and "bytes" in report.errors[0]


def test_absent_file_is_skipped_not_failed_and_not_fetched(tmp_path: Path) -> None:
    report = mm.verify_local_hashes(_hash_doc("missing/m.bin", b"weights"), tmp_path)
    assert report.errors == [] and report.checked == [] and len(report.skipped) == 1
    assert list(tmp_path.iterdir()) == []  # nothing was created


@pytest.mark.parametrize("bad", ["../m.bin", "/abs/m.bin", "a\\b.bin"])
def test_hash_relative_path_cannot_escape_the_root(tmp_path: Path, bad: str) -> None:
    report = mm.verify_local_hashes(_hash_doc(bad, b"x"), tmp_path)
    assert len(report.errors) == 1 and "escapes the artifact root" in report.errors[0]


def test_artifacts_without_a_path_or_hash_are_ignored(tmp_path: Path) -> None:
    doc = {"models": [{"artifacts": [{"name": "a", "sha256_status": "unknown"}]}]}
    report = mm.verify_local_hashes(doc, tmp_path)
    assert (report.errors, report.checked, report.skipped) == ([], [], [])


# --- the command-line wrapper ---------------------------------------------------------------------


def _write(tmp_path: Path, doc: dict) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_cli_exit_1_on_a_bad_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = fresh()
    entry(doc, GIT)["license"]["id"] = "proprietary"
    assert cli.main(["--manifest", str(_write(tmp_path, doc))]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "license.id" in out


def test_cli_exit_2_on_unreadable_or_unparsable_input(tmp_path: Path) -> None:
    assert cli.main(["--manifest", str(tmp_path / "absent.json")]) == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert cli.main(["--manifest", str(broken)]) == 2
    dup = tmp_path / "dup.json"
    dup.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
    assert cli.main(["--manifest", str(dup)]) == 2


def test_cli_verifies_local_hashes_when_asked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "site-packages"
    target = root / "faster_whisper" / "assets"
    target.mkdir(parents=True)
    (target / "silero_vad_v6.onnx").write_bytes(b"not the real file")
    argv = ["--manifest", str(HCI / "model-manifest.json"), "--artifact-root", str(root)]
    assert cli.main(argv) == 1
    assert "sha256 of faster_whisper/assets/silero_vad_v6.onnx" in capsys.readouterr().out
    assert cli.main(["--manifest", str(HCI / "model-manifest.json"), "--artifact-root", str(tmp_path / "e")]) == 0


# --- offline by construction ------------------------------------------------------------------------

FORBIDDEN_IMPORTS = {
    "socket", "ssl", "urllib", "http", "httpx", "requests", "aiohttp", "ftplib", "smtplib",
    "subprocess", "huggingface_hub", "faster_whisper", "ctranslate2", "onnxruntime", "onnx_asr",
    "moonshine_onnx", "torch", "transformers", "mediapipe", "yaml",
}


@pytest.mark.parametrize("name", ["model_manifest", "check_model_manifest"])
def test_scripts_import_nothing_that_can_reach_the_network_or_load_a_model(name: str) -> None:
    tree = ast.parse((SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(FORBIDDEN_IMPORTS), imported & FORBIDDEN_IMPORTS


def test_the_whole_check_runs_with_the_network_blocked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("the manifest check tried to use the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    assert cli.main([]) == 0
    assert "valid" in capsys.readouterr().out
