"""A feature install goes to the installer that *records* it, on every install channel.

Each non-frozen channel rebuilds its environment from its own record, and a package
that is not in that record is dropped on the rebuild:

* `uv tool upgrade` — from `uv-receipt.toml` (covered by `test_uv_tool_extras_persist.py`);
* `pipx reinstall` — from `pipx_metadata.json`. Reproduced offline with pipx 1.4.3: a
  package installed with the venv's own pip was gone afterwards, an injected one was
  put back. So a pipx venv is now installed into with `pipx inject`;
* `uv sync` — from the lockfile's extras, in a source checkout. Nothing YazSes can
  write keeps it there, so the user is told how.

Frozen bundles are out of scope here (ADR-028 add-on packs); they and the snap refuse
up front (`test_fixed_payload_feature_deps.py`, `test_snap_feature_deps.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from yazses.system import deps, install_txn, updater

# ---- every install method maps to a channel -----------------------------------------


def test_every_install_method_the_updater_can_name_has_a_feature_install_channel():
    """A new install method must say how features install on it, or this fails."""
    methods = {"snap", "uv", "pipx", "pip", *updater.GITHUB_METHODS}
    assert set(install_txn.METHOD_CHANNELS) == methods
    for method, channels in install_txn.METHOD_CHANNELS.items():
        assert channels and set(channels) <= set(install_txn.CHANNELS), method


@pytest.mark.parametrize(
    "path, method",
    [
        ("/snap/yazses/x/lib/yazses/__init__.py", "snap"),
        ("/home/u/.local/share/uv/tools/yazses/lib/yazses/__init__.py", "uv"),
        ("/home/u/.local/share/pipx/venvs/yazses/lib/yazses/__init__.py", "pipx"),
        ("/home/u/venv/lib/yazses/__init__.py", "pip"),
    ],
)
def test_the_detected_methods_are_all_mapped(path, method):
    got = updater.detect_install_method(path, frozen=False, choco=False, msix=False)
    assert got == method and got in install_txn.METHOD_CHANNELS


# ---- install_command carries the guard ------------------------------------------


def test_install_command_puts_the_constraint_before_the_packages(monkeypatch, tmp_path):
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv")
    c = tmp_path / "c.txt"
    cmd = deps.install_command(["pkg>=1"], constraints=c)
    assert cmd == ["uv", "pip", "install", "--python", sys.executable,
                   "--constraint", str(c), "pkg>=1"]
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    assert deps.install_command(["pkg"], no_deps=True) == [
        sys.executable, "-m", "pip", "install", "--no-deps", "pkg",
    ]


def test_uninstall_command_targets_this_interpreter(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv")
    assert deps.uninstall_command(["a"]) == ["uv", "pip", "uninstall", "--python",
                                             sys.executable, "a"]
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    assert deps.uninstall_command(["a"]) == [sys.executable, "-m", "pip", "uninstall", "-y", "a"]


# ---- pipx ------------------------------------------------------------------------


def _pretend_pipx(monkeypatch, tmp_path) -> Path:
    venv = tmp_path / "yazses"
    venv.mkdir()
    (venv / "pipx_metadata.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(deps.sys, "prefix", str(venv))
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: None)
    monkeypatch.setattr(deps, "daemon_interpreter_differs", lambda *a, **k: None)
    monkeypatch.setattr(deps, "install_blocked_reason", lambda packages, env=None: None)
    monkeypatch.setattr(deps, "_installed_snapshot", lambda: {})
    return venv


def test_a_pipx_venv_is_detected_by_its_metadata_and_named_for_inject(monkeypatch, tmp_path):
    _pretend_pipx(monkeypatch, tmp_path)
    assert deps._pipx_venv() == "yazses"
    assert deps.install_channel(receipt=None) == install_txn.PIPX


def test_pipx_inject_is_handed_only_the_specs_that_apply_here():
    cmd = deps.pipx_inject_command("yazses", [
        "a>=1; sys_platform == 'never-a-platform'", "b>=2",
    ])
    assert cmd == ["pipx", "inject", "yazses", "b>=2"]
    assert not any(arg.startswith("--pip-args") for arg in cmd), (
        "pipx stores pip args and replays them on reinstall; a temporary "
        "constraint path replayed after deletion dropped the package"
    )


def test_a_pipx_install_dry_runs_under_the_constraint_then_injects(monkeypatch, tmp_path):
    _pretend_pipx(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(deps.subprocess, "run", run)
    said: list[str] = []
    assert deps.install_packages(["noisereduce>=3.0.3"], echo=said.append) is True
    dry, inject = calls
    assert "--dry-run" in dry and "--constraint" in dry
    assert inject == ["pipx", "inject", "yazses", "noisereduce>=3.0.3"]
    assert any("pipx reinstall" in s for s in said)


def test_a_pipx_dry_run_that_fails_installs_nothing(monkeypatch, tmp_path):
    _pretend_pipx(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        return type("P", (), {
            "returncode": 1, "stdout": "",
            "stderr": "Because wants-old depends on numpy<2 and numpy>=2.4.6 ...",
        })()

    monkeypatch.setattr(deps.subprocess, "run", run)
    said: list[str] = []
    assert deps.install_packages(["wants-old"], echo=said.append) is False
    assert len(calls) == 1, "pipx inject must not run after a failed dry run"
    text = "\n".join(said)
    assert "nothing was changed" in text and "numpy<2" in text


# ---- a source checkout ------------------------------------------------------------


def test_a_checkout_is_told_how_to_keep_what_uv_sync_would_remove(monkeypatch):
    monkeypatch.setattr(deps, "_editable_checkout", lambda: True)
    monkeypatch.setattr(deps, "_yazses_requires",
                        lambda: ["kokoro-onnx>=0.5.0; extra == 'tts'"])
    said: list[str] = []
    deps._say_how_it_persists(["kokoro-onnx>=0.5.0"], echo=said.append)
    assert said and "uv sync --inexact" in said[0] and "--extra tts" in said[0]


def test_a_non_checkout_hears_nothing_about_uv_sync(monkeypatch):
    monkeypatch.setattr(deps, "_editable_checkout", lambda: False)
    said: list[str] = []
    deps._say_how_it_persists(["x"], echo=said.append)
    assert said == []


# ---- the system interpreter --------------------------------------------------------


def test_the_distributions_python_is_refused_with_a_remedy_that_works(monkeypatch, tmp_path):
    (tmp_path / "EXTERNALLY-MANAGED").write_text("[externally-managed]\n", encoding="utf-8")
    monkeypatch.setattr(deps.sys, "prefix", "/usr")
    monkeypatch.setattr(deps.sys, "base_prefix", "/usr")
    monkeypatch.setattr(deps.sysconfig, "get_paths",
                        lambda: {"stdlib": str(tmp_path), "purelib": str(tmp_path)})
    monkeypatch.setattr(deps, "fixed_payload_reason", lambda packages, env=None: None)
    reason = deps.install_blocked_reason(["noisereduce"], env={})
    assert reason and "PEP 668" in reason and "pipx install yazses" in reason
    assert "uv pip install --python" not in reason, "pip and uv both refuse that here"


def test_a_venv_is_never_treated_as_externally_managed(monkeypatch, tmp_path):
    (tmp_path / "EXTERNALLY-MANAGED").write_text("", encoding="utf-8")
    monkeypatch.setattr(deps.sysconfig, "get_paths", lambda: {"stdlib": str(tmp_path)})
    monkeypatch.setattr(deps.sys, "prefix", "/venv")
    monkeypatch.setattr(deps.sys, "base_prefix", "/usr")
    assert deps._externally_managed() is False
