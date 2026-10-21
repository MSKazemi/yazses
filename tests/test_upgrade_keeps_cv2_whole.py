"""An upgrade must not leave OpenCV (cv2) half-deleted.

`opencv-python` and `opencv-contrib-python` are separate distributions that write the
same `cv2/` package. Up to 2.43.2 a camera feature installed both; the release after
names only contrib. `uv tool upgrade yazses` then removes `opencv-python`, and
uninstalling it deletes every file in its RECORD -- including the ones contrib also
wrote. What is left of `cv2/` is a namespace package: `import cv2` exits 0 and
`cv2.VideoCapture` is an AttributeError.

Reproduced once, offline, outside this suite (which never runs uv): Linux, Python
3.12, uv 0.12.21, the 5.0.0.93 wheels from the uv cache, a hand-built tool whose 1.0
required both builds and whose 2.0 required contrib only.

* `uv tool upgrade camtool` and `uv tool install --upgrade --with numpy camtool`: exit
  0, `- opencv-python==5.0.0.93`, and `cv2.VideoCapture` is gone;
* the same two commands with `--reinstall-package opencv-contrib-python` before the
  target: `~ opencv-contrib-python==5.0.0.93` beside the removal, and cv2 works;
* `uv pip install --python <env python> --reinstall --no-deps
  opencv-contrib-python==5.0.0.93` repairs the broken environment afterwards.

These tests pin the decisions around those facts: which command each surface shows and
runs, in which order the two upgrade rewrites apply, and what an upgrade that left cv2
broken reports.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yazses.system import deps, updater

BOTH = {"opencv-contrib-python": "5.0.0.93", "opencv-python": "5.0.0.93"}
CONTRIB_ONLY = {"opencv-contrib-python": "5.0.0.93"}
FLAG = ["--reinstall-package", "opencv-contrib-python"]
PLAIN_UV = ["uv", "tool", "upgrade", "yazses"]


def _status(method="uv", command=None, **kw):
    return updater.UpdateStatus(
        method=method, current="2.43.2", latest="2.44.0", available=True,
        command=command if command is not None else updater.upgrade_command(method), **kw,
    )


class _Probe:
    """A scripted OpenCVProbe: versions/works answer from lists, calls are recorded."""

    def __init__(self, before=None, after=None, works=(True, True), camera=False):
        self.before = dict(before or {})
        self.after = dict(after if after is not None else self.before)
        self.works_answers = list(works)
        self.camera = camera
        self.calls: list[str] = []

    def as_probe(self) -> updater.OpenCVProbe:
        return updater.OpenCVProbe(
            python="/env/bin/python",
            versions=self._versions,
            works=self._works,
            camera_enabled=self._camera,
        )

    def _versions(self, fresh: bool) -> dict[str, str]:
        self.calls.append(f"versions(fresh={fresh})")
        return dict(self.after if fresh else self.before)

    def _works(self):
        self.calls.append("works")
        return self.works_answers.pop(0) if self.works_answers else True

    def _camera(self) -> bool:
        self.calls.append("camera_enabled")
        return self.camera


# ---- the pure decisions -----------------------------------------------------


def test_two_owners_with_contrib_need_the_reinstall():
    assert updater.needs_contrib_reinstall(BOTH)
    assert updater.needs_contrib_reinstall(
        {"opencv-contrib-python": "5", "opencv-python-headless": "5"}
    )


@pytest.mark.parametrize("versions", [
    {}, CONTRIB_ONLY, {"opencv-python": "5.0.0.93"},
    {"opencv-python": "5", "opencv-python-headless": "5"},  # no contrib to reinstall
])
def test_one_owner_or_no_contrib_needs_nothing(versions):
    assert not updater.needs_contrib_reinstall(versions)


def test_the_flag_goes_before_the_target_of_a_plain_upgrade():
    assert updater.with_contrib_reinstall(PLAIN_UV) == [
        "uv", "tool", "upgrade", *FLAG, "yazses",
    ]


def test_the_flag_goes_before_the_target_of_the_rewritten_install():
    cmd = ["uv", "tool", "install", "--upgrade", "--with", "onnx-asr", "yazses[desktop]"]
    assert updater.with_contrib_reinstall(cmd) == [
        "uv", "tool", "install", "--upgrade", "--with", "onnx-asr", *FLAG, "yazses[desktop]",
    ]


def test_adding_the_flag_is_idempotent():
    once = updater.with_contrib_reinstall(PLAIN_UV)
    assert updater.with_contrib_reinstall(once) == once


@pytest.mark.parametrize("command", [
    ["pipx", "upgrade", "yazses"], ["pip", "install", "--upgrade", "yazses"],
    ["sudo", "snap", "refresh", "yazses"],
])
def test_no_other_command_gets_the_uv_flag(command):
    assert updater.with_contrib_reinstall(command) == command


def test_the_uv_repair_pins_the_version_read_after_the_upgrade():
    after = {"opencv-contrib-python": "5.0.1.1"}
    assert updater.cv2_repair_command("uv", after, python="/t/bin/python") == [
        "uv", "pip", "install", "--python", "/t/bin/python", "--reinstall", "--no-deps",
        "opencv-contrib-python==5.0.1.1",
    ]


def test_the_pipx_repair_runs_pip_inside_the_pipx_venv():
    assert updater.cv2_repair_command("pipx", CONTRIB_ONLY, python="/p/bin/python") == [
        "pipx", "runpip", "yazses", "install", "--force-reinstall", "--no-deps",
        "opencv-contrib-python==5.0.0.93",
    ]


def test_the_pip_repair_uses_the_environments_own_interpreter():
    """Not a bare `pip`: that is whichever pip is first on PATH, maybe another env."""
    assert updater.cv2_repair_command("pip", CONTRIB_ONLY, python="/v/bin/python") == [
        "/v/bin/python", "-m", "pip", "install", "--force-reinstall", "--no-deps",
        "opencv-contrib-python==5.0.0.93",
    ]


def test_without_contrib_the_repair_reinstalls_the_owner_that_is_there():
    cmd = updater.cv2_repair_command("pip", {"opencv-python": "4.9"}, python="py")
    assert cmd[-1] == "opencv-python==4.9"
    assert updater.cv2_repair_command("pip", {}, python="py")[-1] == "opencv-contrib-python"


def test_verification_needs_an_opencv_distribution_and_never_reads_config_without_one():
    asked = []
    assert not updater.should_verify_cv2([], True, lambda: asked.append(1) or True)
    assert asked == []


def test_verification_when_cv2_loaded_before_does_not_read_config():
    assert updater.should_verify_cv2(["opencv-contrib-python"], True, lambda: pytest.fail("config"))


def test_verification_when_cv2_was_already_broken_depends_on_a_camera_feature():
    assert updater.should_verify_cv2(["opencv-contrib-python"], False, lambda: True)
    assert not updater.should_verify_cv2(["opencv-contrib-python"], False, lambda: False)
    assert not updater.should_verify_cv2(["opencv-contrib-python"], None, lambda: False)


# ---- the cv2 step on its own --------------------------------------------------


def test_a_uv_upgrade_with_both_owners_reinstalls_contrib():
    out = updater.keep_cv2_whole(_status(), opencv=_Probe(BOTH).as_probe())
    assert out.command == ["uv", "tool", "upgrade", *FLAG, "yazses"]


def test_a_uv_upgrade_with_contrib_alone_is_unchanged():
    status = _status()
    assert updater.keep_cv2_whole(status, opencv=_Probe(CONTRIB_ONLY).as_probe()) is status


@pytest.mark.parametrize("method", ["pipx", "pip", "snap"])
def test_pip_and_pipx_never_remove_a_dependency_so_their_command_is_unchanged(method):
    status = _status(method)
    probe = _Probe(BOTH)
    assert updater.keep_cv2_whole(status, opencv=probe.as_probe()) is status
    assert probe.calls == []


def test_a_probe_that_fails_never_breaks_the_update():
    def boom(fresh):
        raise RuntimeError("no metadata")

    probe = updater.OpenCVProbe("py", boom, lambda: True, lambda: False)
    status = _status()
    assert updater.keep_cv2_whole(status, opencv=probe) is status


# ---- pitfall: the order of the two rewrites ------------------------------------

_RECEIPT_BARE = """
[tool]
requirements = [{ name = "yazses", extras = ["desktop"] }]
"""
_PARAKEET = ("onnx-asr[cpu,hub]>=0.12",)


@pytest.fixture
def receipt_missing_parakeet(monkeypatch, tmp_path):
    """A uv tool install whose receipt does not list the enabled Parakeet engine."""
    receipt = tmp_path / "uv-receipt.toml"
    receipt.write_text(_RECEIPT_BARE, encoding="utf-8")
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: receipt)
    monkeypatch.setattr(deps, "_extra_requirement_names", lambda extras: set())
    monkeypatch.setattr(updater, "_enabled_requirements", lambda: _PARAKEET)
    return receipt


def test_a_missing_feature_and_both_owners_give_both_rewrites(receipt_missing_parakeet):
    out = updater.resolve_upgrade_command(_status(), opencv=_Probe(BOTH).as_probe())
    assert out.command == [
        "uv", "tool", "install", "--upgrade", "--with", _PARAKEET[0], *FLAG, "yazses[desktop]",
    ]


def test_resolving_twice_changes_nothing(receipt_missing_parakeet):
    probe = _Probe(BOTH).as_probe()
    once = updater.resolve_upgrade_command(_status(), opencv=probe)
    twice = updater.resolve_upgrade_command(once, opencv=probe)
    assert twice.command == once.command


def test_the_cv2_step_first_would_switch_off_feature_preservation(receipt_missing_parakeet):
    """Why the order is fixed in one function: preserve_enabled_features recognises only
    the plain `uv tool upgrade yazses`, so a flag added before it hides the drop."""
    wrong = updater.preserve_enabled_features(
        updater.keep_cv2_whole(_status(), opencv=_Probe(BOTH).as_probe())
    )
    assert "--with" not in wrong.command
    right = updater.resolve_upgrade_command(_status(), opencv=_Probe(BOTH).as_probe())
    assert "--with" in right.command


def test_upgrade_command_itself_stays_plain():
    """The repair must never live in upgrade_command: the preservation step compares to it."""
    assert updater.upgrade_command("uv") == PLAIN_UV


# ---- after the upgrade: exit 0 is not proof -----------------------------------


def _run(status, probe, *, code=0, after="2.44.0"):
    ran: list[list[str] | None] = []
    outcome = updater.run_upgrade_checked(
        status,
        upgrade=lambda s: ran.append(s.command) or code,
        read_version=lambda: after,
        opencv=probe.as_probe(),
    )
    return outcome, ran


def test_a_cv2_that_broke_is_reported_with_its_repair_not_as_updated(monkeypatch):
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: None)
    probe = _Probe(BOTH, after={"opencv-contrib-python": "5.0.1.1"}, works=(True, False))
    outcome, ran = _run(_status(), probe)
    assert ran == [["uv", "tool", "upgrade", *FLAG, "yazses"]]
    assert outcome.code == 0 and outcome.changed
    assert not outcome.ok
    assert outcome.cv2_repair == [
        "uv", "pip", "install", "--python", "/env/bin/python", "--reinstall", "--no-deps",
        "opencv-contrib-python==5.0.1.1",
    ]
    assert "versions(fresh=True)" in probe.calls  # read after, by a new process


def test_a_cv2_that_still_works_is_a_plain_success(monkeypatch):
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: None)
    outcome, _ = _run(_status(), _Probe(BOTH, works=(True, True)))
    assert outcome.ok and outcome.cv2_repair is None


def test_no_opencv_means_no_import_and_no_config_read(monkeypatch):
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: None)
    probe = _Probe({})
    outcome, _ = _run(_status(), probe)
    assert outcome.ok
    assert "works" not in probe.calls and "camera_enabled" not in probe.calls


def test_a_cv2_broken_before_with_no_camera_feature_is_not_this_upgrades_report(monkeypatch):
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: None)
    outcome, _ = _run(_status(), _Probe(CONTRIB_ONLY, works=(False, False), camera=False))
    assert outcome.ok and outcome.cv2_repair is None


def test_a_camera_feature_on_checks_cv2_even_if_it_was_broken_before(monkeypatch):
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: None)
    outcome, _ = _run(_status(), _Probe(CONTRIB_ONLY, works=(False, False), camera=True))
    assert outcome.cv2_repair is not None and not outcome.ok


def test_a_failed_upgrade_is_not_also_blamed_on_cv2(monkeypatch):
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: None)
    outcome, _ = _run(_status(), _Probe(BOTH, works=(True, False)), code=2)
    assert outcome.code == 2 and outcome.cv2_repair is None


def test_pipx_is_verified_and_repaired_with_the_after_version():
    probe = _Probe(BOTH, after={"opencv-contrib-python": "5.0.2.0"}, works=(True, False))
    outcome, ran = _run(_status("pipx"), probe)
    assert ran == [["pipx", "upgrade", "yazses"]]
    assert outcome.cv2_repair == [
        "pipx", "runpip", "yazses", "install", "--force-reinstall", "--no-deps",
        "opencv-contrib-python==5.0.2.0",
    ]


def test_snap_is_never_probed():
    probe = _Probe(BOTH, works=(False, False), camera=True)
    outcome, _ = _run(_status("snap"), probe)
    assert probe.calls == [] and outcome.cv2_repair is None


# ---- what the user is told -----------------------------------------------------


def _broken_outcome():
    return updater.UpgradeOutcome(
        code=0, before="2.43.2", after="2.44.0", expected="2.44.0", method="uv",
        command=PLAIN_UV,
        cv2_repair=["uv", "pip", "install", "--python", "/env/bin/python", "--reinstall",
                    "--no-deps", "opencv-contrib-python==5.0.0.93"],
    )


def test_the_tray_and_settings_never_say_updated_and_quote_the_repair():
    from yazses.settingsui.maintenance import describe_upgrade
    from yazses.tray.about import upgrade_result_message

    title, body = upgrade_result_message(_broken_outcome())
    assert "Updated" not in title + body
    assert "uv pip install --python /env/bin/python --reinstall --no-deps " \
           "opencv-contrib-python==5.0.0.93" in body
    text, offer_restart = describe_upgrade(_broken_outcome())
    assert "opencv-contrib-python==5.0.0.93" in text and offer_restart is False


def test_a_repair_path_with_a_space_is_quoted():
    from yazses.tray.about import cv2_repair_message

    outcome = _broken_outcome()
    outcome.cv2_repair = ["C:\\Program Files\\py\\python.exe", "-m", "pip", "install", "x"]
    assert '"C:\\Program Files\\py\\python.exe" -m pip install x' in cv2_repair_message(outcome)


def test_yazses_update_reports_the_repair_and_exits_nonzero(monkeypatch):
    from typer.testing import CliRunner

    from yazses import cli

    monkeypatch.setattr(cli, "_installed_version", lambda: "2.43.2")
    monkeypatch.setattr(updater, "check_update", lambda current: _status("pip"))
    monkeypatch.setattr(updater, "run_upgrade_checked", lambda status: _broken_outcome())
    monkeypatch.setattr(updater, "default_opencv_probe", lambda prefix=None: _Probe().as_probe())
    result = CliRunner().invoke(cli.app, ["update", "--yes"])
    assert result.exit_code == 1, result.output
    assert "Updated to" not in result.output
    assert "opencv-contrib-python==5.0.0.93" in result.output


# ---- one command, four surfaces ---------------------------------------------------


def test_cli_settings_tray_and_the_run_all_use_the_same_command(
    monkeypatch, receipt_missing_parakeet
):
    """`yazses update`, the Settings window and the tray each show a command; the
    upgrade they start must run exactly that one -- with both rewrites."""
    from typer.testing import CliRunner

    import yazses.system.installer_update as iu
    import yazses.tray.updates as updates
    from yazses import cli
    from yazses.settingsui import maintenance_panel as mp
    from yazses.tray.about import update_message
    from yazses.tray.controller import TrayController

    expected = [
        "uv", "tool", "install", "--upgrade", "--with", _PARAKEET[0], *FLAG, "yazses[desktop]",
    ]
    monkeypatch.setattr(
        updater, "default_opencv_probe", lambda prefix=None: _Probe(BOTH).as_probe()
    )
    monkeypatch.setattr(updater, "check_update", lambda current, **kw: _status())
    monkeypatch.setattr(updates, "check_updates", lambda current=None: _status())
    monkeypatch.setattr(cli, "_installed_version", lambda: "2.43.2")
    monkeypatch.setattr(cli, "_update_launcher", lambda: None)
    monkeypatch.setattr(iu, "one_click_offer", lambda status, launcher: None)

    # 1. `yazses update --check` prints it.
    result = CliRunner().invoke(cli.app, ["update", "--check"])
    assert result.exit_code == 0, result.output
    from yazses.system.remedy import render_command

    assert f"Command: {render_command(expected)}" in result.output
    # Pasteable: a requirement with `>=` or `[...]` is quoted, never bare in a shell.
    assert f'"{_PARAKEET[0]}"' in result.output
    assert "Reinstalling OpenCV" in result.output
    assert "Keeping your enabled features" in result.output

    # 2. The Settings window shows it.
    shown_settings = mp._default_check()[0]
    assert shown_settings.command == expected

    # 3. The tray's dialog shows it.
    shown_tray = TrayController(SimpleNamespace()).check_updates()
    assert shown_tray.command == expected
    # Quoted for pasting (`>=` redirects and `[...]` globs in a shell, unquoted).
    from yazses.system.remedy import render_command

    assert render_command(expected) in update_message(shown_tray)[1]

    # 3b. The Windows/macOS tray balloon shows it too, not the plain command.
    balloon = updates.describe_update(status=_status(), opener=lambda url: False)[1]
    assert render_command(expected) in balloon

    # 4. What each of them hands to the upgrade runs it unchanged.
    for shown in (shown_settings, shown_tray, _status()):
        ran: list[list[str] | None] = []
        updater.run_upgrade_checked(
            shown,
            upgrade=lambda s: ran.append(s.command) or 0,
            read_version=lambda: "2.44.0",
            opencv=_Probe(BOTH).as_probe(),
        )
        assert ran == [expected]


# ---- the real probes, with the subprocess injected ---------------------------------


def test_env_python_is_built_from_the_prefix(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "python").write_text("", encoding="utf-8")
    assert updater.env_python(str(tmp_path), platform="linux") == str(tmp_path / "bin" / "python")
    (tmp_path / "Scripts").mkdir()
    (tmp_path / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    assert updater.env_python(str(tmp_path), platform="win32") == str(
        tmp_path / "Scripts" / "python.exe"
    )


def test_env_python_falls_back_to_the_running_interpreter(tmp_path):
    import sys

    assert updater.env_python(str(tmp_path / "missing"), platform="linux") == sys.executable


def test_another_environment_is_asked_through_its_own_python(tmp_path):
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return SimpleNamespace(returncode=0, stdout='{"opencv-python": "5.0.0.93"}')

    got = updater._env_cv2_versions("/other/bin/python", prefix=str(tmp_path), runner=runner)
    assert got == {"opencv-python": "5.0.0.93"}
    assert seen[0][0] == "/other/bin/python"
    assert set(updater.CV2_DISTRIBUTIONS) <= set(seen[0])


def test_the_after_read_is_always_a_fresh_process():
    import sys

    seen = []
    updater._env_cv2_versions(
        "/env/bin/python", prefix=sys.prefix, fresh=True,
        runner=lambda argv, **kw: seen.append(argv) or SimpleNamespace(returncode=0, stdout="{}"),
    )
    assert seen, "fresh=True must not answer from the running process's metadata"


def test_the_running_environment_is_read_in_process_before_the_upgrade():
    import sys

    got = updater._env_cv2_versions(
        "/env/bin/python", prefix=sys.prefix,
        runner=lambda *a, **k: pytest.fail("spawned a process for the running env"),
    )
    assert isinstance(got, dict)


def test_an_unreadable_answer_is_none_installed(tmp_path):
    def runner(argv, **kw):
        raise OSError("no such interpreter")

    assert updater._env_cv2_versions("/x", prefix=str(tmp_path), runner=runner) == {}


def test_the_cv2_check_uses_the_attributes_not_a_bare_import():
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return SimpleNamespace(returncode=1)

    assert updater._env_cv2_works("/env/bin/python", runner=runner) is False
    argv = seen[0]
    assert argv[:2] == ["/env/bin/python", "-P"]
    assert "cv2.VideoCapture" in argv[-1] and "cv2.cvtColor" in argv[-1]


def test_a_check_that_cannot_run_is_unknown_not_broken():
    def runner(argv, **kw):
        raise OSError("gone")

    assert updater._env_cv2_works("/x", runner=runner) is None


def test_the_cv2_check_really_catches_a_namespace_leftover(tmp_path):
    """The shape the reproduction left: `cv2/` with only contrib's submodules."""
    import subprocess
    import sys

    (tmp_path / "cv2" / "face").mkdir(parents=True)
    proc = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(tmp_path)!r}); "
         + updater._CV2_CHECK],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert proc.returncode != 0
    assert "VideoCapture" in proc.stderr
    bare = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(tmp_path)!r}); import cv2"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert bare.returncode == 0  # which is why a bare import proves nothing


def test_a_camera_feature_is_one_that_imports_cv2(monkeypatch):
    import yazses.system.features as features

    rows = [
        SimpleNamespace(on=True, wired=True, check_modules=("onnx_asr",)),
        SimpleNamespace(on=False, wired=True, check_modules=("cv2", "mediapipe")),
    ]
    monkeypatch.setattr(features, "feature_status", lambda cfg: rows)
    monkeypatch.setattr("yazses.config.load_config", lambda path: object())
    monkeypatch.setattr(
        "yazses.platform.get_platform",
        lambda: SimpleNamespace(paths=SimpleNamespace(config_file=Path("x"))),
    )
    assert updater._camera_feature_enabled() is False
    rows[1].on = True
    assert updater._camera_feature_enabled() is True
