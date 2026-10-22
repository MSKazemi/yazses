"""ADR-028 §2: mounting at process start, through a fake ``PackRuntime``.

Appended (never prepended) to ``sys.path``; native-dir handles retained; nothing mounted
when elevated, with ``YAZSES_NO_PACKS``, without a ``COMPLETE`` marker, or for a tree
that disagrees with this base; and no exception ever escapes ``mount_at_startup``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.packs_fixtures import FakeRuntime, base, build_pack
from yazses.packs import mount as mount_mod
from yazses.packs.context import InstalledTree, SysFacts, read_tree
from yazses.packs.install import install_pack
from yazses.packs.layout import PackLayout
from yazses.packs.mount import apply, mount_at_startup, plan_mount
from yazses.packs.policy import Capability
from yazses.packs.state import empty_state

COMP = "b-" + "a" * 12
FACTS = SysFacts("cpython-312", "3.12.9", "win-amd64", "x64", "2.44.0")


def _installed(tmp_path: Path, *, native_dirs=(), payload=None):
    """Install a synthetic pack for real (real extractor, fake fetch and probe) and
    write the embedded index beside it. Returns (data_dir, index_path, built)."""
    over = {"native_dirs": list(native_dirs)} if native_dirs else None
    built = build_pack(tmp_path / "src" / "p.yazpack", manifest_over=over, payload=payload)
    index = built.index()
    data = tmp_path / "data"

    def fetch(index, entry, dest, **k):
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / entry.asset
        out.write_bytes(built.path.read_bytes())
        return out

    result = install_pack(index, index.packs[0], base(), PackLayout.under(data),
                          doc=empty_state(), probe=lambda n, s: (True, ""), fetch=fetch,
                          free_bytes=lambda p: 10**12)
    assert result.ok, result.message
    idx_path = tmp_path / "bundle" / "yazses-packs-index.json"
    idx_path.parent.mkdir(parents=True)
    idx_path.write_text(json.dumps({**json.loads(json.dumps(_index_dict(built)))}),
                        encoding="utf-8")
    return data, idx_path, built


def _index_dict(built):
    from tests.packs_fixtures import index_dict

    return index_dict(built.entry())


def _start(tmp_path, data, idx_path, *, env=None, runtime=None, sys_path=None,
           monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr("yazses.packs.context.sys_facts", lambda: FACTS)
        monkeypatch.setattr("yazses.system.updater.detect_install_method",
                            lambda *a, **k: "windows-installer")
    return mount_at_startup(
        env={"YAZSES_PACKAGE_FORMAT": "windows-exe", **(env or {})},
        runtime=runtime or FakeRuntime(index_path=idx_path),
        data_dir=data,
        frozen=True,
        sys_path=sys_path if sys_path is not None else ["/frozen/base.pyz", "/frozen"],
    )


def test_a_good_pack_is_appended_after_the_base(tmp_path, monkeypatch) -> None:
    data, idx, _ = _installed(tmp_path)
    path = ["/frozen/base.pyz", "/frozen"]
    report = _start(tmp_path, data, idx, sys_path=path, monkeypatch=monkeypatch)
    assert report is not None and report.mounted == ["parakeet"], report
    assert path[:2] == ["/frozen/base.pyz", "/frozen"], "the base must stay first"
    assert path[2].endswith(str(Path(COMP) / "parakeet" / "site"))


def test_native_dirs_go_through_the_runtime_and_handles_are_kept(tmp_path, monkeypatch) -> None:
    data, idx, _ = _installed(tmp_path, native_dirs=["site/fakepkg_parakeet"])
    runtime = FakeRuntime(index_path=idx)
    before = len(mount_mod._HANDLES)
    report = _start(tmp_path, data, idx, runtime=runtime, monkeypatch=monkeypatch)
    assert report.mounted == ["parakeet"]
    assert runtime.native_dirs and runtime.native_dirs[0].name == "fakepkg_parakeet"
    assert len(mount_mod._HANDLES) == before + 1, "the handle must outlive the call"


def test_elevated_means_nothing_is_mounted(tmp_path, monkeypatch) -> None:
    data, idx, _ = _installed(tmp_path)
    path: list[str] = []
    report = _start(tmp_path, data, idx, runtime=FakeRuntime(index_path=idx, elevated=True),
                    sys_path=path, monkeypatch=monkeypatch)
    assert path == [] and report.mounted == []
    assert "administrator" in report.plan.reason


def test_no_packs_env_means_nothing_is_mounted(tmp_path, monkeypatch) -> None:
    data, idx, _ = _installed(tmp_path)
    path: list[str] = []
    report = _start(tmp_path, data, idx, env={"YAZSES_NO_PACKS": "1"}, sys_path=path,
                    monkeypatch=monkeypatch)
    assert path == [] and "YAZSES_NO_PACKS" in report.plan.reason


def test_a_missing_complete_marker_means_no_mount(tmp_path, monkeypatch) -> None:
    data, idx, _ = _installed(tmp_path)
    (PackLayout.under(data).pack_dir(COMP, "parakeet") / "COMPLETE").unlink()
    path: list[str] = []
    report = _start(tmp_path, data, idx, sys_path=path, monkeypatch=monkeypatch)
    assert path == [] and report.plan.skipped[0][0] == "parakeet"


def test_a_tampered_complete_hash_is_refused_for_quarantine(tmp_path, monkeypatch) -> None:
    data, idx, _ = _installed(tmp_path)
    marker = PackLayout.under(data).pack_dir(COMP, "parakeet") / "COMPLETE"
    marker.write_text("sha256 " + "0" * 64 + "\n", encoding="utf-8")
    path: list[str] = []
    report = _start(tmp_path, data, idx, sys_path=path, monkeypatch=monkeypatch)
    assert path == []
    assert report.plan.quarantine and "SHA-256" in report.plan.quarantine[0][1]


def test_an_index_from_another_app_mounts_nothing(tmp_path, monkeypatch) -> None:
    data, idx, _ = _installed(tmp_path)
    monkeypatch.setattr("yazses.packs.context.sys_facts",
                        lambda: SysFacts("cpython-312", "3.12.10", "win-amd64", "x64", "2.44.0"))
    monkeypatch.setattr("yazses.system.updater.detect_install_method",
                        lambda *a, **k: "windows-installer")
    path: list[str] = []
    report = mount_at_startup(env={"YAZSES_PACKAGE_FORMAT": "windows-exe"},
                              runtime=FakeRuntime(index_path=idx), data_dir=data,
                              frozen=True, sys_path=path)
    assert path == [] and "3.12.10" in report.plan.reason


def test_a_failing_native_dir_keeps_that_pack_off_sys_path(tmp_path, monkeypatch) -> None:
    data, idx, _ = _installed(tmp_path, native_dirs=["site/fakepkg_parakeet"])
    path: list[str] = []
    report = _start(tmp_path, data, idx, runtime=FakeRuntime(index_path=idx, fail_native=True),
                    sys_path=path, monkeypatch=monkeypatch)
    assert path == [] and report.failed and report.mounted == []


def test_not_frozen_or_unsupported_or_no_folder_is_a_cheap_no_op(tmp_path) -> None:
    assert mount_at_startup(env={}, runtime=FakeRuntime(), data_dir=tmp_path,
                            frozen=False, sys_path=[]) is None
    assert mount_at_startup(env={}, runtime=FakeRuntime(supported=False),
                            data_dir=tmp_path, frozen=True, sys_path=[]) is None
    assert mount_at_startup(env={}, runtime=FakeRuntime(), data_dir=tmp_path / "none",
                            frozen=True, sys_path=[]) is None


def test_an_exception_inside_the_plan_never_escapes(tmp_path, monkeypatch) -> None:
    data, idx, _ = _installed(tmp_path)

    def boom(**kwargs):
        raise RuntimeError("bug in the planner")

    monkeypatch.setattr(mount_mod, "plan_mount", boom)
    report = _start(tmp_path, data, idx, monkeypatch=monkeypatch)
    assert report is not None and "RuntimeError" in report.error
    assert mount_mod.LAST is report


def test_plan_mount_is_pure_and_orders_by_name(tmp_path) -> None:
    built = build_pack(tmp_path / "p.yazpack")
    tree_dir = tmp_path / "tree" / "parakeet"
    tree_dir.mkdir(parents=True)
    (tree_dir / "pack.json").write_text(json.dumps(built.manifest), encoding="utf-8")
    (tree_dir / "COMPLETE").write_text(f"sha256 {built.sha256}\n", encoding="utf-8")
    tree = read_tree(tree_dir)
    plan = plan_mount(base=base(), base_problems=(), index=built.index(), index_error=None,
                      trees=[tree], env={}, capability=Capability(True))
    assert [i.name for i in plan.items] == ["parakeet"]
    assert plan.items[0].paths == (tree_dir / "site",)
    absent = InstalledTree("ghost", tmp_path, None, None)
    plan = plan_mount(base=base(), base_problems=(), index=built.index(), index_error=None,
                      trees=[absent], env={}, capability=Capability(True))
    assert plan.items == () and plan.skipped


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_the_recovery_switch_spellings(value) -> None:
    plan = plan_mount(base=base(), base_problems=(), index=None, index_error=None, trees=[],
                      env={"YAZSES_NO_PACKS": value}, capability=Capability(True))
    assert "YAZSES_NO_PACKS" in plan.reason


def test_apply_appends_and_never_duplicates(tmp_path) -> None:
    from yazses.packs.mount import MountItem, MountPlan

    plan = MountPlan(items=(MountItem("x", (tmp_path / "site",), ()),))
    path = ["/base", str(tmp_path / "site")]
    apply(plan, FakeRuntime(), sys_path=path, handles=[])
    assert path == ["/base", str(tmp_path / "site")]


def test_the_runtime_hook_swallows_everything(tmp_path, monkeypatch) -> None:
    """The hook file runs before main; a pack must never stop YazSes from starting."""
    import runpy

    hook = Path(__file__).resolve().parents[1] / "packaging/windows/rthook_yazses_packs.py"

    def boom(**kwargs):
        raise RuntimeError("anything")

    monkeypatch.setattr(mount_mod, "mount_at_startup", boom)
    runpy.run_path(str(hook))  # must not raise
