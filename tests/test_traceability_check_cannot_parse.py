"""A traceability check that cannot parse its manifest must fail, not report compliance.

`load_manifest` used to return `{}` for any non-mapping document. The validator happened to
reject `{}`, so the exit code was right by accident -- but the reason printed was a misleading
"version must be 1", an unreadable file was never named, and the manifest

    version: 1
    entries: []

passed with no per-entry check ever running: zero entries is vacuously compliant. That is the
"a check that cannot parse its input reports compliance" shape (see the memory entry of that
name): every failure below must exit non-zero with its own reason, and a control proves the
same entry point still exits 0 on the committed manifest, so the failures are the manifests'
doing and not the script being broken for everything.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-traceability.py"
MANIFEST = ROOT / "design" / "traceability.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_traceability_cannot_parse", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(path: Path) -> tuple[int, str]:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, timeout=60
    )
    return done.returncode, done.stderr + done.stdout


@pytest.mark.parametrize(
    "text",
    ["", "null\n", "[]\n", "- a\n- b\n", "just a string\n", "42\n", ": : :\n[\n"],
    ids=["empty-file", "null", "list", "list-of-strings", "scalar-string", "scalar-int", "bad-yaml"],
)
def test_a_manifest_that_is_not_a_mapping_fails_loudly(tmp_path, text):
    bad = tmp_path / "traceability.yml"
    bad.write_text(text, encoding="utf-8")

    checker = _load_checker()  # one load: each load makes its own ManifestError class
    with pytest.raises(checker.ManifestError):
        checker.load_manifest(bad)
    code, output = _run(bad)
    assert code != 0, output
    assert "Planning traceability errors" in output
    assert "structurally valid" not in output


def test_a_missing_or_undecodable_manifest_fails_loudly(tmp_path):
    checker = _load_checker()
    with pytest.raises(checker.ManifestError):
        checker.load_manifest(tmp_path / "does-not-exist.yml")
    binary = tmp_path / "binary.yml"
    binary.write_bytes(b"\xff\xfe\x00\x80 not utf-8")
    with pytest.raises(checker.ManifestError):
        checker.load_manifest(binary)
    assert _run(binary)[0] != 0
    assert _run(tmp_path / "does-not-exist.yml")[0] != 0


@pytest.mark.parametrize("text", ["version: 1\nentries: []\n", "version: 1\nentries:\n"])
def test_an_empty_manifest_is_not_silently_compliant(tmp_path, text):
    """Zero entries means zero checks ran; that must not read as a pass."""
    path = tmp_path / "traceability.yml"
    path.write_text(text, encoding="utf-8")

    code, output = _run(path)

    assert code != 0, output
    assert "structurally valid" not in output


def test_validate_manifest_itself_rejects_an_empty_entry_list():
    errors = _load_checker().validate_manifest({"version": 1, "entries": []})
    assert any("empty" in error for error in errors), errors


def test_the_committed_manifest_still_passes_the_command_line_check():
    """The control for everything above."""
    code, output = _run(MANIFEST)
    assert code == 0, output
    assert "structurally valid" in output
    assert len(yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["entries"]) > 0
