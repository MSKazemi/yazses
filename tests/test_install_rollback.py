"""A feature install that fails half-way, is interrupted, or breaks the base is undone.

The owner's complaint was that adding features made the application "quickly broken".
The mechanism, reproduced offline (uv 0.12.21, hand-built wheels): a plain install of a
feature that wants an older version of a base dependency *downgrades it and exits 0* —
dictation's own numpy, ctranslate2 or platformdirs moved under it by a feature toggle.

`install_packages` now treats an install as a transaction:

* YazSes's own requirements go to the installer as `--constraint`, so the resolver
  refuses such a feature before anything moves (verified in that experiment: the
  constrained install failed, nothing changed);
* the installed set is snapshotted, and a failure that changed things, an interrupt, or
  a success that left a base requirement unmet is undone — verified in the same
  experiment with the constraint removed: the downgrade happened, was detected, and the
  environment was restored exactly.

These tests pin that logic with the installer replaced; nothing is fetched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yazses.system import deps

BASE = ["numpy>=2.4.6", "platformdirs>=4.10.0"]
HEALTHY = {"numpy": "2.4.6", "platformdirs": "4.12.1", "yazses": "2.43.2"}


@pytest.fixture
def txn(monkeypatch, tmp_path):
    """A plain-venv install whose installed set the test scripts, snapshot by snapshot."""
    monkeypatch.setattr(deps, "install_blocked_reason", lambda packages, env=None: None)
    monkeypatch.setattr(deps, "daemon_interpreter_differs", lambda *a, **k: None)
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: None)
    monkeypatch.setattr(deps, "_pipx_venv", lambda: None)
    monkeypatch.setattr(deps, "_editable_checkout", lambda: False)
    monkeypatch.setattr(deps, "_yazses_requires", lambda: list(BASE))
    monkeypatch.setattr(deps.sys, "prefix", str(tmp_path))  # no pipx metadata here

    class State:
        snapshots: list[dict[str, str]] = []
        commands: list[list[str]] = []
        constraint_text = ""

    def snapshot():
        return dict(State.snapshots.pop(0)) if len(State.snapshots) > 1 else dict(
            State.snapshots[0]
        )

    monkeypatch.setattr(deps, "_installed_snapshot", snapshot)
    return State


def _installer(monkeypatch, txn, *, fails=False, raises=None, undo_fails=False):
    def run(cmd, check=True, **kwargs):
        txn.commands.append(list(cmd))
        if "--constraint" in cmd:
            path = Path(cmd[cmd.index("--constraint") + 1])
            txn.constraint_text = path.read_text(encoding="utf-8")
        is_undo = "uninstall" in cmd or "--no-deps" in cmd
        if raises is not None and not is_undo:
            raise raises
        if (fails and not is_undo) or (undo_fails and is_undo):
            raise deps.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(deps.subprocess, "run", run)


def test_the_base_requirements_reach_the_installer_as_a_constraint(monkeypatch, txn):
    txn.snapshots = [HEALTHY, {**HEALTHY, "noisereduce": "3.0.3"}]
    _installer(monkeypatch, txn)
    assert deps.install_packages(["noisereduce>=3.0.3"], echo=lambda *_: None) is True
    assert "numpy>=2.4.6" in txn.constraint_text
    assert "platformdirs>=4.10.0" in txn.constraint_text


def test_a_clean_success_runs_no_undo(monkeypatch, txn):
    txn.snapshots = [HEALTHY, {**HEALTHY, "noisereduce": "3.0.3"}]
    _installer(monkeypatch, txn)
    deps.install_packages(["noisereduce"], echo=lambda *_: None)
    assert len(txn.commands) == 1


def test_a_success_that_downgrades_the_base_is_undone(monkeypatch, txn):
    broken = {**HEALTHY, "numpy": "1.26.4", "wants-old": "1.0"}
    txn.snapshots = [HEALTHY, broken, broken, HEALTHY]
    _installer(monkeypatch, txn)
    said: list[str] = []
    assert deps.install_packages(["wants-old"], echo=said.append) is False
    text = "\n".join(said)
    assert "numpy 1.26.4 does not satisfy numpy>=2.4.6" in text
    assert "exactly as it was" in text
    undo = txn.commands[1:]
    assert any("uninstall" in c and "wants-old" in c for c in undo)
    assert any("--no-deps" in c and "numpy==2.4.6" in c for c in undo)


def test_a_base_requirement_broken_before_the_install_is_not_blamed_on_it(monkeypatch, txn):
    """The FreeBSD leg runs with faster-whisper absent; that is not this install's doing."""
    already = {k: v for k, v in HEALTHY.items() if k != "platformdirs"}
    txn.snapshots = [already, {**already, "noisereduce": "3.0.3"}]
    _installer(monkeypatch, txn)
    assert deps.install_packages(["noisereduce"], echo=lambda *_: None) is True
    assert len(txn.commands) == 1


def test_a_failure_part_way_is_undone(monkeypatch, txn):
    partial = {**HEALTHY, "torch": "2.9.0"}
    txn.snapshots = [HEALTHY, partial, partial, HEALTHY]
    _installer(monkeypatch, txn, fails=True)
    said: list[str] = []
    assert deps.install_packages(["speechbrain"], echo=said.append) is False
    text = "\n".join(said)
    assert "failed part-way" in text and "+torch" in text
    assert any("uninstall" in c and "torch" in c for c in txn.commands)


def test_a_failure_that_changed_nothing_has_nothing_to_undo(monkeypatch, txn):
    txn.snapshots = [HEALTHY, HEALTHY]
    _installer(monkeypatch, txn, fails=True)
    said: list[str] = []
    assert deps.install_packages(["x"], echo=said.append) is False
    assert len(txn.commands) == 1
    assert not any("Undo" in s for s in said)
    assert any("Install manually" in s for s in said)
    assert any("do not force it" in s for s in said), (
        "the printed manual command lacks the constraint, so it carries the warning"
    )


def test_an_interrupt_is_undone_and_still_interrupts(monkeypatch, txn):
    partial = {**HEALTHY, "torch": "2.9.0"}
    txn.snapshots = [HEALTHY, partial, HEALTHY]
    _installer(monkeypatch, txn, raises=KeyboardInterrupt())
    said: list[str] = []
    with pytest.raises(KeyboardInterrupt):
        deps.install_packages(["speechbrain"], echo=said.append)
    assert any("Interrupted" in s for s in said)
    assert any("uninstall" in c and "torch" in c for c in txn.commands)


def test_an_undo_that_cannot_finish_prints_the_commands(monkeypatch, txn):
    partial = {**HEALTHY, "torch": "2.9.0"}
    txn.snapshots = [HEALTHY, partial, partial, partial]
    _installer(monkeypatch, txn, fails=True, undo_fails=True)
    said: list[str] = []
    assert deps.install_packages(["speechbrain"], echo=said.append) is False
    text = "\n".join(said)
    assert "Could NOT fully undo" in text and "+torch" in text
    assert "uninstall" in text, "the user needs the command, not only the verdict"


def test_the_channel_record_is_restored_by_the_undo(monkeypatch, txn, tmp_path):
    """A uv tool receipt (or pipx metadata) rewritten by the failed install goes back."""
    receipt = tmp_path / "uv-receipt.toml"
    receipt.write_text("original\n", encoding="utf-8")
    partial = {**HEALTHY, "torch": "2.9.0"}
    txn.snapshots = [HEALTHY, partial, partial, HEALTHY]
    _installer(monkeypatch, txn, fails=True)
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: receipt)

    def persist(path, packages):
        path.write_text("rewritten\n", encoding="utf-8")
        return False  # and the fallback install fails too

    monkeypatch.setattr(deps, "_persist_uv_tool_extras", persist)
    monkeypatch.setattr("yazses.system.notify.notify_when_unattended", lambda *a, **k: False)
    deps.install_packages(["speechbrain"], echo=lambda *_: None)
    assert receipt.read_text(encoding="utf-8") == "original\n"


# ---- install_feature: installed means importable ---------------------------------------


def test_install_feature_reports_modules_that_still_do_not_import(monkeypatch):
    monkeypatch.setattr(deps, "install_packages", lambda packages, echo=print: True)
    monkeypatch.setattr(deps, "missing_modules", lambda modules: ["sherpa_onnx"])
    said: list[str] = []
    ok = deps.install_feature(["sherpa-onnx"], check_modules=["sherpa_onnx"], echo=said.append)
    assert ok is False and "dormant" in said[-1] and "sherpa_onnx" in said[-1]


def test_install_feature_succeeds_when_the_modules_import(monkeypatch):
    monkeypatch.setattr(deps, "install_packages", lambda packages, echo=print: True)
    monkeypatch.setattr(deps, "missing_modules", lambda modules: [])
    assert deps.install_feature(["x"], check_modules=["x"], echo=lambda *_: None) is True


def test_install_feature_passes_a_failed_install_through(monkeypatch):
    monkeypatch.setattr(deps, "install_packages", lambda packages, echo=print: False)
    monkeypatch.setattr(deps, "missing_modules", lambda m: pytest.fail("must not probe"))
    assert deps.install_feature(["x"], check_modules=["x"], echo=lambda *_: None) is False
