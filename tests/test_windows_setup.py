"""`yazses setup` on Windows: plan from probes, apply through an injected runner.

Runs on every OS -- the planner and applier take their probes and runner as arguments,
so no Windows host, pip, or winget is needed.
"""

from __future__ import annotations

import sys
import types

from yazses.system import winsetup as w


def _plan(missing=(), loads=True, frozen=False, arch="x64"):
    return w.build_windows_plan(
        find_spec=lambda m: None if m in missing else object(),
        decoder_loads=lambda: loads,
        frozen=frozen,
        arch=arch,
    )


def test_a_provisioned_machine_is_a_noop():
    assert _plan().is_noop


def test_missing_python_packages_are_planned_by_distribution_name():
    plan = _plan(missing={"win32api", "PIL"})
    assert plan.pip_packages == ["pywin32", "Pillow"]
    assert not plan.vc_redist


def test_a_frozen_build_never_plans_pip():
    """PyInstaller bundles its wheels and has no pip -- proposing it would be wrong."""
    assert _plan(missing={"win32api", "pystray", "PIL"}, frozen=True).pip_packages == []


def test_a_decoder_that_will_not_load_plans_the_vc_runtime():
    plan = _plan(loads=False)
    assert plan.vc_redist and plan.notes


def test_apply_runs_pip_then_winget_with_the_arch_specific_id():
    calls: list[list[str]] = []

    def runner(cmd, check):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0)

    plan = _plan(missing={"pystray"}, loads=False, arch="arm64")
    ok = w.apply_windows_plan(plan, runner=runner, echo=lambda _m: None, which=lambda _n: "winget")

    assert ok
    assert calls[0][1:4] == ["-m", "pip", "install"] and calls[0][-1] == "pystray"
    assert calls[1][:2] == ["winget", "install"] and "Microsoft.VCRedist.2015+.arm64" in calls[1]


def test_without_winget_it_prints_the_download_link_and_reports_failure():
    out: list[str] = []
    ok = w.apply_windows_plan(
        _plan(loads=False), runner=lambda *a, **k: None, echo=out.append, which=lambda _n: None
    )
    assert not ok and any("vc_redist" in line for line in out)


def test_winget_already_installed_code_counts_as_success():
    runner = lambda cmd, check: types.SimpleNamespace(returncode=-1978335135)  # noqa: E731
    assert w.apply_windows_plan(
        _plan(loads=False), runner=runner, echo=lambda _m: None, which=lambda _n: "winget"
    )


def test_a_runner_that_cannot_execute_never_raises():
    def boom(*_a, **_k):
        raise FileNotFoundError("winget")

    assert not w.apply_windows_plan(
        _plan(loads=False), runner=boom, echo=lambda _m: None, which=lambda _n: "winget"
    )


# ---------------------------------------------------------------- the CLI wiring


def _run_setup(monkeypatch, plan, *args):
    from typer.testing import CliRunner

    from yazses import cli
    from yazses.system import doctor

    applied: list[w.WindowsPlan] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(w, "build_windows_plan", lambda: plan)
    monkeypatch.setattr(w, "apply_windows_plan", lambda p, echo=print: applied.append(p) or True)
    monkeypatch.setattr(doctor, "run_doctor", lambda *a, **k: None)
    result = CliRunner().invoke(cli.app, ["setup", *args])
    return result, applied


def test_setup_on_windows_dry_run_changes_nothing(monkeypatch):
    result, applied = _run_setup(monkeypatch, _plan(missing={"pystray"}, loads=False), "--dry-run")
    assert result.exit_code == 0, result.output
    assert "pystray" in result.output and "Visual C++" in result.output
    assert applied == []


def test_setup_on_windows_applies_the_plan_and_runs_doctor(monkeypatch):
    result, applied = _run_setup(monkeypatch, _plan(loads=False))
    assert result.exit_code == 0, result.output
    assert len(applied) == 1 and applied[0].vc_redist
    assert "Linux" not in result.output
