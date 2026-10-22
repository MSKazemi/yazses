"""The import probe (ADR-028 §6) and the Phase 0 risks it must name, not swallow:
a stdlib gap, missing distribution metadata, a pruned base submodule and a native
library that fails to load (the expected sherpa-onnx-core / onnxruntime.dll clash)."""
from __future__ import annotations

import importlib.metadata
import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.packs_fixtures import FakeRuntime, manifest_dict
from yazses.packs.probe import (
    EXIT_CODES,
    ProbeResult,
    classify_failure,
    describe_exit,
    run_probe,
)


def _err(name: str) -> ModuleNotFoundError:
    exc = ModuleNotFoundError(f"No module named {name!r}")
    exc.name = name
    return exc


@pytest.mark.parametrize(
    ("exc", "kind", "fragment"),
    [
        (_err("_lzma"), "stdlib-gap", "standard-library module '_lzma'"),
        (_err("xml.dom.minidom"), "stdlib-gap", "stdlib/ supplement"),
        (importlib.metadata.PackageNotFoundError("numpy"), "missing-metadata", "'numpy'"),
        (_err("numpy.random._pickle"), "pruned-submodule", "base package 'numpy'"),
        (ImportError("DLL load failed while importing _sherpa: The specified module could "
                     "not be found."), "native-load", "onnxruntime.dll"),
        (OSError("[WinError 126] The specified module could not be found"), "native-load",
         "native library"),
        (_err("totally_absent"), "import-error", "totally_absent"),
        (ValueError("boom"), "error", "ValueError"),
    ],
)
def test_each_failure_gets_a_named_kind(exc, kind, fragment) -> None:
    got_kind, message = classify_failure(
        "sherpa_onnx", exc, is_present=lambda name: name == "numpy"
    )
    assert got_kind == kind
    assert fragment in message


def test_exit_codes_are_distinct_and_round_trip() -> None:
    assert len(set(EXIT_CODES.values())) == len(EXIT_CODES)
    for kind, code in EXIT_CODES.items():
        if kind == "ok":
            continue
        line = ProbeResult(False, kind, "m", f"msg for {kind}").line()
        assert describe_exit(code, f"noise\n{line}\n") == (kind, f"msg for {kind}")
    assert describe_exit(99, "")[0] == "error"


def _staged(tmp_path: Path, *, name="parakeet", module="fakeprobe_ok", body="X = 1\n",
            path_entries=()) -> Path:
    root = tmp_path / "staged"
    (root / "site" / module).mkdir(parents=True)
    (root / "site" / module / "__init__.py").write_text(body, encoding="utf-8")
    for p in path_entries:
        (root / p).mkdir(parents=True, exist_ok=True)
    (root / "pack.json").write_text(json.dumps(manifest_dict(
        name, entry_modules=[module], path_entries=list(path_entries),
    )), encoding="utf-8")
    return root


@pytest.fixture
def clean_sys(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield
    for mod in [m for m in sys.modules if m.startswith("fakeprobe_")]:
        del sys.modules[mod]


def test_a_good_tree_imports_and_appends_site_then_path_entries(tmp_path, clean_sys) -> None:
    root = _staged(tmp_path, path_entries=["site/extra"])
    before = list(sys.path)
    result = run_probe("parakeet", root, runtime=FakeRuntime(), sys_path=sys.path)
    assert result.ok, result
    assert sys.path[: len(before)] == before, "appended, never prepended"
    assert sys.path[len(before):] == [str(root / "site"), str(root / "site" / "extra")]


def test_a_failing_import_is_classified(tmp_path, clean_sys) -> None:
    root = _staged(tmp_path, module="fakeprobe_bad", body="import _definitely_absent_x\n")
    result = run_probe("parakeet", root, runtime=FakeRuntime(), sys_path=sys.path)
    assert not result.ok and result.kind == "import-error"
    assert result.module == "fakeprobe_bad"


def test_the_probe_refuses_a_tree_of_another_name(tmp_path, clean_sys) -> None:
    root = _staged(tmp_path)
    result = run_probe("diarization", root, runtime=FakeRuntime(), sys_path=[])
    assert result.kind == "refused"


def test_the_probe_runs_on_an_elevated_ci_runner(tmp_path, clean_sys) -> None:
    """The release build probes on a Windows runner whose account is an administrator.
    The probe loads only the directory it was given; refusing would withhold every pack.
    The *startup mount* and *install* still refuse elevation."""
    root = _staged(tmp_path, module="fakeprobe_elev")
    assert run_probe("parakeet", root, runtime=FakeRuntime(elevated=True),
                     sys_path=sys.path).ok


def test_the_cli_command_the_build_calls(tmp_path, clean_sys, monkeypatch) -> None:
    """`yazses-cli.exe --cli packs probe <name> --staged <dir>` (build item 10)."""
    from yazses.cli import app

    monkeypatch.setattr("yazses.platform.factory.get_pack_runtime", lambda: FakeRuntime())
    root = _staged(tmp_path, module="fakeprobe_cli")
    ok = CliRunner().invoke(app, ["packs", "probe", "parakeet", "--staged", str(root)])
    assert ok.exit_code == 0, ok.output
    assert "YAZSES-PROBE ok" in ok.output
    bad = _staged(tmp_path / "b", module="fakeprobe_cli_bad", body="import _nope_zz\n")
    res = CliRunner().invoke(app, ["packs", "probe", "parakeet", "--staged", str(bad)])
    assert res.exit_code == EXIT_CODES["import-error"]
    assert "_nope_zz" in res.output
