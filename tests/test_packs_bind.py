"""ADR-028 M1: a pack that dropped its own ``onnxruntime.dll`` binds to the base's copy.

The diarization pack's ``sherpa_onnx`` must use the frozen base's Microsoft-signed ONNX
Runtime, never a second copy and never one found on the search path. These tests pin:

* ``pack.json``'s ``bind_to_base`` / ``bind_min_versions`` parsing;
* the pure decisions (one base copy or refuse, version floor, nothing else loaded);
* the first-use binder: nothing loads at start-up, the base's DLL loads **before** the
  pack's first module runs, and a refusal is an ``ImportError`` naming the reason;
* the probe and ``yazses packs verify`` reporting which file and version bound;
* the Windows backend's pieces that run off Windows (the folder walk, the ORT version
  read through a ctypes stand-in), and the still-unbuilt out-of-process seam.

No real DLL is loaded: the runtime is a fake that records what it was asked to load.
"""
from __future__ import annotations

import ctypes
import json
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.packs_fixtures import FakeRuntime, base, build_pack, index_dict, manifest_dict
from yazses.packs import bind as bind_mod
from yazses.packs.bind import (
    Binding,
    BindRequest,
    FirstUseBinder,
    bind_pack,
    choose_base_copy,
    judge_loaded,
    judge_version,
    parse_version,
    requests_for,
    top_level_names,
    version_at_least,
)
from yazses.packs.manifest import ManifestError, parse_manifest
from yazses.packs.probe import EXIT_CODES, run_probe

ORT = "onnxruntime.dll"
BASE_ORT = Path("/app/_internal/onnxruntime/capi/onnxruntime.dll")
#: A module the fake "creates" when it loads the base's DLL, so a pack module can prove
#: the binding happened before its own body ran.
MARKER = "_yazses_fake_base_ort_loaded"


class BindRuntime(FakeRuntime):
    """FakeRuntime plus the three binding calls."""

    def __init__(self, *, candidates=(BASE_ORT,), version="1.28.0", load_error=None,
                 extra_loaded=(), list_fails=False, **kw) -> None:
        super().__init__(**kw)
        self.candidates = list(candidates)
        self.version = version
        self.load_error = load_error
        self.extra_loaded = list(extra_loaded)
        self.list_fails = list_fails
        self.loads: list[Path] = []
        self.searched: list[str] = []

    def base_native_candidates(self, name: str) -> list[Path]:
        self.searched.append(name)
        return [p for p in self.candidates if p.name.casefold() == name.casefold()]

    def load_base_native(self, path: Path) -> tuple[object, str | None]:
        if self.load_error is not None:
            raise self.load_error
        self.loads.append(path)
        sys.modules[MARKER] = types.ModuleType(MARKER)
        return ("lib", str(path)), self.version

    def loaded_native_paths(self, name: str) -> list[Path] | None:
        if self.list_fails:
            return None
        return [p for p in [*self.loads, *self.extra_loaded]
                if p.name.casefold() == name.casefold()]


@pytest.fixture(autouse=True)
def _clean_modules(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "meta_path", list(sys.meta_path))
    monkeypatch.setattr(bind_mod, "BINDINGS", {})
    yield
    for mod in [m for m in sys.modules if m.startswith(("fakebind_", MARKER))]:
        del sys.modules[mod]


# ---- pack.json -----------------------------------------------------------------------

def _manifest(**over):
    return parse_manifest(json.dumps(manifest_dict("diarization", **over)))


def test_bind_fields_default_to_empty() -> None:
    m = _manifest()
    assert m.bind_to_base == () and m.bind_min_versions == ()
    assert requests_for(m) == ()


def test_bind_fields_parse_and_keep_the_list_spelling() -> None:
    m = _manifest(bind_to_base=["onnxruntime.dll"],
                  bind_min_versions={"ONNXRUNTIME.DLL": "1.28"})
    assert m.bind_to_base == ("onnxruntime.dll",)
    assert m.bind_min_versions == (("onnxruntime.dll", "1.28"),)
    assert requests_for(m) == (BindRequest("onnxruntime.dll", "1.28"),)


@pytest.mark.parametrize(
    ("over", "fragment"),
    [
        ({"bind_to_base": ["../onnxruntime.dll"]}, "invalid entry"),
        ({"bind_to_base": ["capi/onnxruntime.dll"]}, "invalid entry"),
        ({"bind_to_base": ["C:onnxruntime.dll"]}, "invalid entry"),
        ({"bind_to_base": ["a.dll", "A.DLL"]}, "duplicate"),
        ({"bind_to_base": "onnxruntime.dll"}, "not a list"),
        ({"bind_to_base": ["a.dll"], "bind_min_versions": {"b.dll": "1.0"}}, "does not list"),
        ({"bind_to_base": ["a.dll"], "bind_min_versions": {"a.dll": 1}}, "minimum version"),
        ({"bind_to_base": ["a.dll"], "bind_min_versions": ["a.dll"]}, "not an object"),
        ({"bind_to_base": ["a.dll"], "bind_min_versions": {"a.dll": "1", "A.dll": "2"}},
         "two minimum"),
    ],
)
def test_bad_bind_fields_refuse_the_manifest(over, fragment) -> None:
    with pytest.raises(ManifestError, match=fragment):
        _manifest(**over)


# ---- pure decisions --------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "want"),
    [("1.28.0", (1, 28, 0)), ("1.28.2-dev", (1, 28, 2)), ("v1.9", (1, 9)), ("", None),
     (None, None), ("unknown", None)],
)
def test_parse_version(text, want) -> None:
    assert parse_version(text) == want


@pytest.mark.parametrize(
    ("have", "minimum", "want"),
    [("1.28.0", "1.28", True), ("1.28", "1.28.0", True), ("1.28.2", "1.28.0", True),
     ("1.27.9", "1.28", False), ("1.9.0", "1.28.0", False), ("2.0", "1.28", True),
     (None, "1.28", None), ("garbage", "1.28", None)],
)
def test_version_at_least_compares_numbers_not_strings(have, minimum, want) -> None:
    assert version_at_least(have, minimum) is want


def test_choose_base_copy_needs_exactly_one() -> None:
    assert choose_base_copy(ORT, [BASE_ORT]) == (BASE_ORT, "")
    assert choose_base_copy(ORT, [BASE_ORT, BASE_ORT])[0] == BASE_ORT  # same file twice
    path, why = choose_base_copy(ORT, [])
    assert path is None and "does not contain onnxruntime.dll" in why
    assert "never uses another copy" in why
    other = Path("/app/_internal/sherpa/onnxruntime.dll")
    path, why = choose_base_copy(ORT, [other, Path("/app/_internal/x/onnxruntime.dll")])
    assert path is None and "2 files named onnxruntime.dll" in why and "guess" in why
    twin = Path("/app/_internal/onnxruntime/other/onnxruntime.dll")
    assert choose_base_copy(ORT, [BASE_ORT, twin])[0] is None, "two package copies: refuse"


def test_of_several_copies_the_one_the_base_package_loads_is_taken() -> None:
    """The build's spike (``spike_bind_request``) preloads the copy inside the
    ``onnxruntime`` package folder; the runtime must pick the same file, or the base's
    own ``import onnxruntime`` would add a second copy."""
    top = Path("/app/_internal/onnxruntime.dll")
    assert choose_base_copy(ORT, [top, BASE_ORT]) == (BASE_ORT, "")
    assert choose_base_copy("ONNXRUNTIME.DLL", [top, BASE_ORT]) == (BASE_ORT, "")


def test_judge_version() -> None:
    assert judge_version(ORT, "1.28.0", None) == ""
    assert judge_version(ORT, None, None) == "", "no floor stated: an unknown version binds"
    assert judge_version(ORT, "1.28.0", "1.28") == ""
    assert "is version 1.27.0; the add-on needs 1.28 or newer" in judge_version(
        ORT, "1.27.0", "1.28")
    assert "could not be read" in judge_version(ORT, None, "1.28")


def test_judge_loaded() -> None:
    assert judge_loaded(ORT, BASE_ORT, [BASE_ORT]) == ""
    assert "could not list" in judge_loaded(ORT, BASE_ORT, None)
    stray = Path("/pack/site/sherpa_onnx/lib/onnxruntime.dll")
    why = judge_loaded(ORT, BASE_ORT, [BASE_ORT, stray])
    assert str(stray) in why and "another onnxruntime.dll" in why
    assert "is not loaded" in judge_loaded(ORT, BASE_ORT, [])


def test_judge_loaded_ignores_the_long_path_prefix(monkeypatch) -> None:
    monkeypatch.setattr(bind_mod.os.path, "normcase", lambda s: s.lower())
    reported = Path("\\\\?\\" + str(BASE_ORT).upper())
    assert judge_loaded(ORT, BASE_ORT, [reported]) == ""


def test_top_level_names() -> None:
    listing = [("sherpa_onnx", True), ("sherpa_onnx-1.13.8.dist-info", True),
               ("__pycache__", True), ("_sherpa.cp312-win_amd64.pyd", False),
               ("six.py", False), ("README.txt", False), ("bin", True),
               ("foo.data", True), ("not-a-name", True)]
    assert top_level_names(listing) == {"sherpa_onnx", "_sherpa", "six", "bin"}


# ---- bind_pack ---------------------------------------------------------------------------

REQ = (BindRequest(ORT, "1.28"),)


def test_bind_pack_loads_the_base_copy_by_path_and_keeps_the_handle() -> None:
    rt, keep = BindRuntime(), []
    (b,) = bind_pack("diarization", REQ, rt, keep=keep)
    assert b.ok and b.path == BASE_ORT and b.version == "1.28.0"
    assert rt.loads == [BASE_ORT] and keep == [("lib", str(BASE_ORT))]
    assert str(BASE_ORT) in b.describe() and "1.28.0" in b.describe()


@pytest.mark.parametrize(
    ("kw", "fragment"),
    [
        ({"candidates": ()}, "does not contain onnxruntime.dll"),
        ({"load_error": OSError("[WinError 193] not a valid Win32 application")},
         "could not be loaded"),
        ({"version": "1.27.1"}, "needs 1.28 or newer"),
        ({"version": None}, "could not be read"),
        ({"extra_loaded": [Path("C:/Windows/System32/onnxruntime.dll")]},
         "another onnxruntime.dll"),
        ({"list_fails": True}, "could not list"),
    ],
)
def test_bind_pack_refuses_with_a_named_reason(kw, fragment) -> None:
    (b,) = bind_pack("diarization", REQ, BindRuntime(**kw), keep=[])
    assert not b.ok and fragment in b.reason
    assert "refused" in b.describe()


def test_bind_pack_never_raises_and_stops_at_the_first_refusal() -> None:
    class Boom(BindRuntime):
        def base_native_candidates(self, name):
            raise RuntimeError("walk failed")

    (b,) = bind_pack("diarization", (BindRequest(ORT), BindRequest("x.dll")), Boom(), keep=[])
    assert not b.ok and "RuntimeError: walk failed" in b.reason
    rt = BindRuntime(candidates=())
    out = bind_pack("diarization", (BindRequest(ORT), BindRequest("x.dll")), rt, keep=[])
    assert len(out) == 1 and rt.searched == [ORT]


# ---- the first-use binder -----------------------------------------------------------------

def _binder(rt, meta, refused=None):
    return FirstUseBinder("diarization", REQ, {"fakebind_pkg"}, rt, meta_path=meta, keep=[],
                          on_refused=(lambda p, w: refused.append((p, w)))
                          if refused is not None else None)


def test_other_imports_never_trigger_the_binding() -> None:
    rt, meta = BindRuntime(), []
    b = _binder(rt, meta)
    meta.append(b)
    assert b.find_spec("json") is None and b.find_spec("numpy.linalg") is None
    assert rt.loads == [] and rt.searched == [] and b in meta


def test_the_first_trigger_binds_once_and_the_finder_leaves() -> None:
    rt, meta = BindRuntime(), []
    b = _binder(rt, meta)
    meta.append(b)
    assert b.find_spec("fakebind_pkg.sub") is None
    assert rt.loads == [BASE_ORT] and b not in meta
    assert bind_mod.BINDINGS["diarization"][0].ok
    b.find_spec("fakebind_pkg")
    assert rt.loads == [BASE_ORT], "bound once"


def test_a_refusal_raises_for_every_import_of_the_pack() -> None:
    rt, meta, refused = BindRuntime(version="1.20.0"), [], []
    b = _binder(rt, meta, refused)
    meta.append(b)
    for name in ("fakebind_pkg", "fakebind_pkg.core"):
        with pytest.raises(ImportError, match="refused the 'diarization' add-on.*1.28"):
            b.find_spec(name)
    assert b in meta, "a refused pack stays fenced off"
    assert len(refused) == 1 and refused[0][0] == "diarization"


def _pack_tree(tmp_path: Path, *, body: str) -> Path:
    site = tmp_path / "site"
    (site / "fakebind_pkg").mkdir(parents=True)
    (site / "fakebind_pkg" / "__init__.py").write_text(body, encoding="utf-8")
    return site


def test_through_the_real_import_system_the_dll_loads_before_the_pack_runs(tmp_path) -> None:
    """The ordering the whole fix rests on: sherpa's extension must find the base's
    onnxruntime.dll already loaded. The pack body imports the marker the fake creates on
    load; without the binder it would raise ModuleNotFoundError."""
    site = _pack_tree(tmp_path, body=f"import {MARKER}\nOK = True\n")
    rt = BindRuntime()
    sys.meta_path.insert(0, _binder(rt, sys.meta_path))
    sys.path.append(str(site))
    import fakebind_pkg  # type: ignore[import-not-found]

    assert fakebind_pkg.OK and rt.loads == [BASE_ORT]


# ---- mount -------------------------------------------------------------------------------

PAYLOAD = {
    "site/fakebind_pkg/__init__.py": f"import {MARKER}\nOK = True\n".encode(),
    "site/fakebind_pkg-1.0.dist-info/METADATA": b"Name: fake\nVersion: 1.0\n",
}


def _install(tmp_path: Path, manifest_over=None):
    """Install a synthetic pack for real (real extractor; fake fetch and probe) and write
    the embedded index. Returns ``(data_dir, index_path, index)``."""
    from yazses.packs.install import install_pack
    from yazses.packs.layout import PackLayout
    from yazses.packs.manifest import parse_index
    from yazses.packs.state import empty_state

    built = build_pack(tmp_path / "src" / "p.yazpack", manifest_over=manifest_over,
                       payload=PAYLOAD)
    index = built.index()

    def fetch(index, entry, dest, **k):
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / entry.asset
        out.write_bytes(built.path.read_bytes())
        return out

    data = tmp_path / "data"
    result = install_pack(index, index.packs[0], base(), PackLayout.under(data),
                          doc=empty_state(), probe=lambda n, s: (True, ""), fetch=fetch,
                          free_bytes=lambda p: 10**12)
    assert result.ok, result.message
    idx_path = tmp_path / "bundle" / "yazses-packs-index.json"
    idx_path.parent.mkdir(parents=True)
    idx_path.write_text(json.dumps(index_dict(built.entry())), encoding="utf-8")
    return data, idx_path, parse_index(idx_path.read_text(encoding="utf-8"))


def _mounted(tmp_path, monkeypatch, *, manifest_over=None, rt=None):
    """Install a synthetic pack, then plan and apply its mount with a local meta_path."""
    from yazses.packs.context import read_tree
    from yazses.packs.mount import apply, plan_mount
    from yazses.packs.policy import Capability

    data, _, index = _install(tmp_path, manifest_over)
    build_dir = next((data / "packs").glob("b-*"))
    trees = [read_tree(p) for p in sorted(build_dir.iterdir()) if p.is_dir()]
    plan = plan_mount(base=base(), base_problems=(), index=index, index_error=None,
                      trees=trees, env={}, capability=Capability(True))
    rt = rt or BindRuntime()
    meta: list = []
    report = apply(plan, rt, sys_path=sys.path, handles=[], meta_path=meta)
    return report, rt, meta, plan


def test_mount_installs_the_binder_and_loads_nothing(tmp_path, monkeypatch) -> None:
    report, rt, meta, plan = _mounted(
        tmp_path, monkeypatch, manifest_over={"bind_to_base": [ORT],
                                              "bind_min_versions": {ORT: "1.28"}})
    assert report.mounted == ["parakeet"], report
    assert plan.items[0].binds == ((ORT, "1.28"),)
    assert len(meta) == 1 and isinstance(meta[0], FirstUseBinder)
    assert meta[0].triggers == {"fakebind_pkg"}
    assert rt.loads == [] and rt.searched == [], "start-up must not load or search"
    sys.meta_path.insert(0, meta[0])
    import fakebind_pkg  # type: ignore[import-not-found]

    assert fakebind_pkg.OK and rt.loads == [BASE_ORT]


def test_a_binding_pack_with_nothing_to_watch_is_not_mounted(tmp_path) -> None:
    """A binder that knows no module names would never fire, and the pack would import
    unbound. Fail closed: the pack stays off sys.path."""
    from yazses.packs.mount import MountItem, MountPlan, apply

    site = tmp_path / "site"
    site.mkdir()
    (site / "README.txt").write_text("not a module", encoding="utf-8")
    item = MountItem("diarization", (site,), (), ((ORT, None),), (site, tmp_path / "gone"))
    path, meta = ["/frozen"], []
    report = apply(MountPlan((item,)), BindRuntime(), sys_path=path, handles=[],
                   meta_path=meta)
    assert report.mounted == [] and path == ["/frozen"] and meta == []
    assert "no importable module" in report.failed[0][1]


def test_mount_refusal_is_an_import_error_and_a_report_entry(tmp_path, monkeypatch) -> None:
    report, rt, meta, _ = _mounted(
        tmp_path, monkeypatch, manifest_over={"bind_to_base": [ORT]},
        rt=BindRuntime(candidates=()))
    sys.meta_path.insert(0, meta[0])
    with pytest.raises(ImportError, match="does not contain onnxruntime.dll"):
        import fakebind_pkg  # type: ignore[import-not-found]  # noqa: F401
    assert report.failed and report.failed[0][0] == "parakeet"
    assert MARKER not in sys.modules


def test_a_pack_without_bind_to_base_never_imports_the_bind_module(
        tmp_path, monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "yazses.packs.bind")
    report, rt, meta, _ = _mounted(tmp_path, monkeypatch)
    assert report.mounted == ["parakeet"] and meta == []
    assert "yazses.packs.bind" not in sys.modules


def test_the_out_of_process_seam_skips_the_pack_until_it_is_built(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bind_mod, "bind_mode", lambda m: "out-of-process")
    report, rt, meta, plan = _mounted(tmp_path, monkeypatch,
                                      manifest_over={"bind_to_base": [ORT]})
    assert report.mounted == [] and meta == []
    assert "separate process" in plan.skipped[0][1]


# ---- the probe ------------------------------------------------------------------------

def _staged(tmp_path: Path, body: str, **over) -> Path:
    root = tmp_path / "staged"
    _pack_tree(root, body=body)
    (root / "pack.json").write_text(json.dumps(manifest_dict(
        "diarization", entry_modules=["fakebind_pkg"], **over)), encoding="utf-8")
    return root


def test_the_probe_binds_first_and_names_what_bound(tmp_path) -> None:
    root = _staged(tmp_path, f"import {MARKER}\n", bind_to_base=[ORT],
                   bind_min_versions={ORT: "1.28"})
    result = run_probe("diarization", root, runtime=BindRuntime(), sys_path=sys.path)
    assert result.ok, result
    assert f"onnxruntime.dll -> {BASE_ORT} (version 1.28.0, needs 1.28+)" in result.message
    assert "\n" not in result.line()


def test_the_probe_refuses_when_the_base_lacks_the_dll(tmp_path) -> None:
    root = _staged(tmp_path, f"import {MARKER}\n", bind_to_base=[ORT])
    result = run_probe("diarization", root, runtime=BindRuntime(candidates=()),
                       sys_path=sys.path)
    assert not result.ok and result.kind == "native-load"
    assert result.exit_code == EXIT_CODES["native-load"]
    assert "does not contain onnxruntime.dll" in result.message
    assert "fakebind_pkg" not in sys.modules, "the pack must not be imported unbound"


def test_the_probe_catches_a_second_copy_loaded_by_the_import(tmp_path) -> None:
    """If the pack still carried its own onnxruntime.dll, importing it would load a
    second module of that name. The post-import check is what proves the binding held."""
    stray = Path("/pack/site/sherpa_onnx/lib/onnxruntime.dll")
    rt = BindRuntime()
    sys.modules["_yazses_fake_runtime"] = types.SimpleNamespace(rt=rt, stray=stray)
    body = "import _yazses_fake_runtime as f\nf.rt.extra_loaded.append(f.stray)\n"
    try:
        root = _staged(tmp_path, body, bind_to_base=[ORT])
        result = run_probe("diarization", root, runtime=rt, sys_path=sys.path)
    finally:
        del sys.modules["_yazses_fake_runtime"]
    assert not result.ok and result.kind == "native-load"
    assert "after importing fakebind_pkg" in result.message and str(stray) in result.message


def test_a_pack_without_bind_to_base_probes_as_before(tmp_path) -> None:
    root = _staged(tmp_path, "X = 1\n")
    rt = BindRuntime()
    result = run_probe("diarization", root, runtime=rt, sys_path=sys.path)
    assert result.ok and "bound" not in result.message and rt.searched == []


def test_the_probe_refuses_when_the_out_of_process_route_is_needed(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("yazses.packs.probe.bind_mode", lambda m: "out-of-process")
    root = _staged(tmp_path, "X = 1\n", bind_to_base=[ORT])
    result = run_probe("diarization", root, runtime=BindRuntime(), sys_path=sys.path)
    assert result.kind == "refused" and "separate process" in result.message


def test_the_probe_cli_prints_the_binding(tmp_path, monkeypatch) -> None:
    from yazses.cli import app

    monkeypatch.setattr("yazses.platform.factory.get_pack_runtime", lambda: BindRuntime())
    root = _staged(tmp_path, f"import {MARKER}\n", bind_to_base=[ORT])
    res = CliRunner().invoke(app, ["packs", "probe", "diarization", "--staged", str(root)])
    assert res.exit_code == 0, res.output
    assert f"onnxruntime.dll -> {BASE_ORT} (version 1.28.0)" in res.output


# ---- yazses packs verify ------------------------------------------------------------------

def _verify_ctx(tmp_path, monkeypatch, rt_kw=None, manifest_over=None):
    from tests.test_packs_mount import FACTS
    from yazses.packs.context import load_context

    over = {"bind_to_base": [ORT], "bind_min_versions": {ORT: "1.28"}}
    over.update(manifest_over or {})
    data, idx, _ = _install(tmp_path, over)
    monkeypatch.setattr("yazses.packs.context.sys_facts", lambda: FACTS)
    monkeypatch.setattr("yazses.system.updater.detect_install_method",
                        lambda *a, **k: "windows-installer")
    rt = BindRuntime(index_path=idx, **(rt_kw or {}))
    ctx = load_context(env={"YAZSES_PACKAGE_FORMAT": "windows-exe"}, runtime=rt,
                       data_dir=data, frozen=True)
    return ctx, rt


def test_verify_reports_the_bound_file_and_version(tmp_path, monkeypatch) -> None:
    from yazses.cli import app

    ctx, rt = _verify_ctx(tmp_path, monkeypatch)
    monkeypatch.setattr("yazses.cli._packs_context", lambda: ctx)
    res = CliRunner().invoke(app, ["packs", "verify"])
    assert res.exit_code == 0, res.output
    assert f"parakeet: onnxruntime.dll -> {BASE_ORT} (version 1.28.0, needs 1.28+)" in res.output
    assert "Every installed add-on matches its record." in res.output


def test_verify_fails_on_a_refused_binding_without_setting_the_pack_aside(
        tmp_path, monkeypatch) -> None:
    from yazses.cli import app

    ctx, rt = _verify_ctx(tmp_path, monkeypatch, rt_kw={"version": "1.20.0"})
    monkeypatch.setattr("yazses.cli._packs_context", lambda: ctx)
    res = CliRunner().invoke(app, ["packs", "verify"])
    assert res.exit_code == 1, res.output
    assert "needs 1.28 or newer" in res.output and "not set aside" in res.output
    assert (ctx.build_dir / "parakeet").is_dir(), "a base fault is not the pack's damage"


def test_check_bindings_skips_packs_without_bind_to_base(tmp_path, monkeypatch) -> None:
    from yazses.packs.manage import check_bindings

    ctx, rt = _verify_ctx(tmp_path, monkeypatch,
                          manifest_over={"bind_to_base": [], "bind_min_versions": {}})
    assert check_bindings(ctx) == [] and rt.searched == []


# ---- the Windows backend, the parts that run anywhere ------------------------------------

def test_windows_candidates_walk_only_the_bundle(tmp_path, monkeypatch) -> None:
    from yazses.platform.windows.packs import WindowsPackRuntime

    internal = tmp_path / "_internal"
    (internal / "onnxruntime" / "capi").mkdir(parents=True)
    (internal / "onnxruntime" / "capi" / "ONNXRUNTIME.DLL").write_bytes(b"x")
    (tmp_path / "onnxruntime.dll").write_bytes(b"outside the bundle")
    rt = WindowsPackRuntime()
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert rt.base_native_candidates(ORT) == [], "not frozen: no base to share"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    assert rt.base_native_candidates(ORT) == [internal / "onnxruntime" / "capi" /
                                              "ONNXRUNTIME.DLL"]


def test_windows_load_refuses_a_bare_name(tmp_path) -> None:
    """A bare name would make the loader *search*: exactly the fallback M1 forbids."""
    from yazses.platform.windows.packs import WindowsPackRuntime

    with pytest.raises(OSError, match="not an absolute path"):
        WindowsPackRuntime().load_base_native(Path(ORT))


@pytest.mark.skipif(sys.platform == "win32", reason="checks the off-Windows answer")
def test_windows_loaded_list_fails_closed_off_windows() -> None:
    from yazses.platform.windows.packs import WindowsPackRuntime

    assert WindowsPackRuntime().loaded_native_paths(ORT) is None


class _FakeOrtLib:
    """Stands in for a loaded onnxruntime.dll: ``OrtGetApiBase`` returns a real ctypes
    ``OrtApiBase`` whose ``GetVersionString`` is a real C callback."""

    def __init__(self, version: bytes | None) -> None:
        self._version = version
        self._keep: list[object] = []
        lib = self

        class _Fn:
            restype = None
            argtypes = None

            def __call__(self):
                struct = self.restype._type_()
                cb = ctypes.CFUNCTYPE(ctypes.c_char_p)(lambda: lib._version)
                lib._keep.append(cb)
                struct.GetVersionString = cb
                lib._keep.append(struct)
                return ctypes.pointer(struct)

        self.OrtGetApiBase = _Fn()


@pytest.mark.filterwarnings("ignore:memory leak in callback function:RuntimeWarning")
def test_ort_version_reads_the_c_api_version_string() -> None:
    from yazses.platform.windows.packs import ort_version

    assert ort_version(_FakeOrtLib(b"1.28.0")) == "1.28.0"
    assert ort_version(_FakeOrtLib(None)) is None
    assert ort_version(object()) is None, "a DLL without the export has no ORT version"


def test_every_backend_answers_the_binding_calls() -> None:
    from yazses.platform.linux.packs import UnsupportedPackRuntime
    from yazses.platform.macos.packs import MacosPackRuntime

    for rt in (UnsupportedPackRuntime(), MacosPackRuntime()):
        assert rt.base_native_candidates(ORT) == []
        assert rt.loaded_native_paths(ORT) is None
        with pytest.raises(OSError):
            rt.load_base_native(BASE_ORT)


def test_binding_describe_is_one_line() -> None:
    ok = Binding("p", ORT, BASE_ORT, "1.28.0")
    assert "\n" not in ok.describe() and "version 1.28.0" in ok.describe()
    assert Binding("p", ORT, BASE_ORT, None).describe().count("unknown") == 1


def test_index_fixture_is_untouched() -> None:
    """The bind fields live in pack.json only; the index format is unchanged."""
    assert "bind_to_base" not in json.dumps(index_dict())
