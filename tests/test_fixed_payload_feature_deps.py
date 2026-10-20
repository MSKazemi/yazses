"""A frozen or confined bundle can never pip-install a feature's libraries -- so it says so.

The snap sibling of this bug is pinned in `tests/test_snap_feature_deps.py`. This is the
rest of the packaging matrix (EYE-PERM-001, #414): the macOS ``.app``, the Windows
``.exe`` (and the Chocolatey/Scoop/WinGet channels that install it), the MSIX and the
flatpak all have a fixed payload, and `cameraperm.matrix` already records that as
``can_add_runtime = False``. `install_blocked_reason` did not consult it. Inside a
PyInstaller bundle ``sys.executable`` is the YazSes executable, not a Python, and a
per-user install directory passes the purelib writability check -- so
``yazses features enable gaze --force`` wrote ``[gaze] enabled = true`` and then ran an
install that could never succeed, leaving a camera feature switched on in a package that
cannot run one.

Every assertion here is derived from `PACKAGE_PROFILES`, so a new install format is
covered the moment it gets a row. No bundle is built and no pip runs.
"""

from __future__ import annotations

import sys
import types

import pytest

from yazses.cameraperm import CAMERA_FEATURES, PACKAGE_PROFILES
from yazses.system import deps

FIXED = [p for p in PACKAGE_PROFILES if not p.can_add_runtime]
ADDABLE = [p for p in PACKAGE_PROFILES if p.can_add_runtime]
CAMERA_PKGS = ["mediapipe>=0.10.35", "opencv-python>=5.0"]


def test_the_matrix_has_rows_on_both_sides() -> None:
    """Both parametrisations below iterate; an empty side would be a green no-op."""
    assert FIXED and ADDABLE


@pytest.mark.parametrize("profile", FIXED, ids=lambda p: p.key)
def test_a_fixed_payload_format_refuses_before_pip(profile) -> None:
    reason = deps.install_blocked_reason(
        CAMERA_PKGS, env={"YAZSES_PACKAGE_FORMAT": profile.key}
    )
    assert reason is not None, f"{profile.key} cannot add a runtime but was not refused"
    assert "pipx install yazses" in reason, "the refusal must name the install that works"
    for pkg in CAMERA_PKGS:
        assert pkg in reason


@pytest.mark.parametrize("profile", ADDABLE, ids=lambda p: p.key)
def test_a_format_that_can_add_a_runtime_is_not_refused_on_that_ground(profile) -> None:
    assert deps.fixed_payload_reason(
        CAMERA_PKGS, env={"YAZSES_PACKAGE_FORMAT": profile.key}
    ) is None


@pytest.mark.parametrize(
    ("platform_name", "msix", "expected"),
    [
        ("darwin", False, "macos-app"),
        ("win32", False, "windows-exe"),
        ("win32", True, "windows-msix"),
    ],
)
def test_a_real_frozen_bundle_is_detected_without_the_override(
    monkeypatch, platform_name, msix, expected
) -> None:
    """The override is a maintainer knob; the guard must also fire on the real facts."""
    import yazses.platform.factory as factory

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        factory,
        "describe_host",
        lambda: types.SimpleNamespace(platform_name=platform_name, msix_packaged=msix),
    )
    reason = deps.install_blocked_reason(CAMERA_PKGS, env={})
    label = next(p.label for p in PACKAGE_PROFILES if p.key == expected)
    assert reason is not None and label in reason


def test_an_ordinary_source_install_is_still_allowed() -> None:
    """The test process is a writable venv: the new branch must not refuse it."""
    assert deps.install_blocked_reason(["anything"], env={}) is None


def test_install_packages_never_runs_pip_in_a_fixed_payload(monkeypatch) -> None:
    def boom(*_a, **_k):  # pragma: no cover - must never be reached
        raise AssertionError("pip ran inside a bundle that cannot accept a package")

    monkeypatch.setattr(deps.subprocess, "run", boom)
    monkeypatch.setenv("YAZSES_PACKAGE_FORMAT", "windows-msix")
    msgs: list[str] = []
    assert deps.install_packages(CAMERA_PKGS, echo=msgs.append) is False
    assert len(msgs) == 1 and "MSIX" in msgs[0]


# ---- every enablement surface refuses before writing config -----------------


def _missing_everything(monkeypatch) -> None:
    """The camera runtime is absent, as it is in every fixed-payload bundle."""
    monkeypatch.setattr(deps, "missing_modules", lambda modules: list(modules))


@pytest.mark.parametrize("slug", ["gaze", "facegesture", "headpointer"])
def test_features_enable_refuses_a_camera_feature_in_the_mac_app(monkeypatch, slug) -> None:
    from typer.testing import CliRunner

    from yazses import cli

    _missing_everything(monkeypatch)
    monkeypatch.setenv("YAZSES_PACKAGE_FORMAT", "macos-app")
    written: list[object] = []
    monkeypatch.setattr(cli, "_apply_feature_writes", lambda *a: written.append(a))
    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **k: pytest.fail("pip ran"))

    result = CliRunner().invoke(cli.app, ["features", "enable", slug, "--force"])

    assert result.exit_code == 1, result.output
    assert written == [], "config was written for a camera feature the .app cannot run"
    assert "pipx install yazses" in result.output


def test_the_handsfree_panel_reports_the_bundle_as_the_blocker(monkeypatch) -> None:
    """The tray's Hands-free panel uses the same predicate as the CLI, not a copy."""
    from yazses.config import Config
    from yazses.handsfree.panel_io import _feature_facts

    monkeypatch.setenv("YAZSES_PACKAGE_FORMAT", "windows-exe")
    facts = _feature_facts(
        Config(), {}, deps_probe=lambda modules: list(modules), blocked_probe=None
    )
    camera = [f for f in facts if f.slug in CAMERA_FEATURES and f.missing_packages]
    assert camera, "no camera feature reported missing packages; the check is blind"
    for fact in camera:
        assert "pipx install yazses" in fact.blocked, f"{fact.slug} was not blocked"


@pytest.mark.parametrize("slug", ["gaze", "facegesture", "headpointer"])
def test_the_settings_window_refuses_before_writing_in_the_flatpak(monkeypatch, slug) -> None:
    """The tray's Settings window, with its *default* blocked probe -- not an injected one."""
    from yazses.config import Config
    from yazses.settingsui.controller import SettingsController

    monkeypatch.setenv("YAZSES_PACKAGE_FORMAT", "flatpak")
    written: list[tuple] = []
    controller = SettingsController(
        load_config=Config,
        writer=lambda *a: written.append(a),
        deps_probe=lambda modules: list(modules),
    )

    result = controller.set_enabled(slug, True, confirmed=True)

    assert not result.ok
    assert "pipx install yazses" in (result.error or "")
    assert written == [], f"{slug} was written to config in a flatpak that cannot run it"
