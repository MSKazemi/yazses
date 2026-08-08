"""A snap can never pip-install a feature's libraries — so it must say so.

The bug this pins is the snap sibling of issue #44's *impossible advice*. A
snap's payload is a read-only squashfs, and the staged Debian python ships a
PEP 668 ``EXTERNALLY-MANAGED`` marker, so ``yazses features enable read-back``
inside the snap ran pip, waited, and printed Debian's error verbatim:

    error: externally-managed-environment
    ... try apt install python3-xyz ...
    ... create a virtual environment using python3 -m venv ...

None of which a confined user can act on. Worse, the config key had *already*
been written by then, so the capability read as "enabled" while nothing could
ever honour it — exactly the lie `features enable` refuses for unwired features.

The fix is two-sided and both sides are tested here: the snap *bundles* the
libraries that fit (so those capabilities simply work), and refuses — before
writing config — for the ones that provably cannot.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from yazses.system import deps
from yazses.system.snap import dependency_install_advice

SNAP_ENV = {"SNAP_NAME": "yazses", "SNAP": "/snap/yazses/25"}


# ---- the advice ------------------------------------------------------------


def test_advice_names_the_packages_that_are_missing():
    advice = dependency_install_advice(["speechbrain>=1.1"], SNAP_ENV)
    assert "speechbrain>=1.1" in advice


def test_advice_offers_the_only_escape_hatch_and_not_apt():
    advice = dependency_install_advice(["mediapipe>=0.10"], SNAP_ENV)
    assert "pipx install yazses" in advice
    # Debian's own suggestions are meaningless inside confinement; if any of
    # them leaks through we have merely re-worded the bug.
    assert "apt install" not in advice
    assert "python3 -m venv" not in advice


def test_advice_explains_why_rather_than_just_refusing():
    advice = dependency_install_advice(["sherpa-onnx"], SNAP_ENV)
    assert "read-only" in advice


def test_advice_uses_the_instance_name_for_parallel_installs():
    env = dict(SNAP_ENV, SNAP_INSTANCE_NAME="yazses_beta")
    assert "snap remove yazses_beta" in dependency_install_advice(["x"], env)


def test_advice_warns_config_does_not_carry_over():
    # Switching to an unconfined install silently changes the config directory;
    # a user who follows this advice must not be surprised by a reset setup.
    advice = dependency_install_advice(["x"], SNAP_ENV)
    assert "~/snap/yazses/" in advice and "~/.config/yazses" in advice


# ---- the gate --------------------------------------------------------------


def test_install_is_blocked_inside_a_snap():
    reason = deps.install_blocked_reason(["speechbrain>=1.1"], env=SNAP_ENV)
    assert reason is not None
    assert "pipx install yazses" in reason


def test_install_is_allowed_in_an_ordinary_writable_environment():
    # The dev/CI environment running this test is writable, so nothing blocks.
    assert deps.install_blocked_reason(["anything"], env={}) is None


def test_install_is_blocked_when_the_site_directory_is_read_only(monkeypatch, tmp_path):
    """An unwritable ``purelib`` must block the install before pip runs.

    The unwritability is injected rather than made with ``chmod(0o500)``: Windows
    ignores POSIX mode bits on a *directory*, so ``os.access(dir, W_OK)`` stays
    True there and the real check — correctly — found nothing wrong. Patching
    ``os.access`` asserts the branch we care about on every platform instead of
    asserting the host filesystem's permission semantics.
    """
    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.setattr(deps.sysconfig, "get_paths", lambda: {"purelib": str(site)})
    monkeypatch.setattr(
        deps.os, "access", lambda path, mode: not (mode & os.W_OK and Path(path) == site)
    )
    reason = deps.install_blocked_reason(["pkg"], env={})
    assert reason is not None and "not writable" in reason
    assert str(site) in reason


def test_a_not_yet_created_site_directory_is_judged_by_its_parent(monkeypatch, tmp_path):
    """Regression: ``purelib`` often does not exist yet (Debian's
    ``/usr/local/lib/python3.12/dist-packages``). Judging a missing path as
    unwritable would refuse every install on a perfectly good machine."""
    monkeypatch.setattr(
        deps.sysconfig, "get_paths", lambda: {"purelib": str(tmp_path / "a" / "b" / "c")}
    )
    assert deps.install_blocked_reason(["pkg"], env={}) is None


def test_install_packages_refuses_without_running_pip(monkeypatch):
    def boom(*_a, **_k):  # pragma: no cover - must never be reached
        raise AssertionError("pip must not run when the install cannot succeed")

    monkeypatch.setattr(deps.subprocess, "run", boom)
    monkeypatch.setattr(deps, "install_blocked_reason", lambda pkgs: "nope, because")
    msgs: list[str] = []
    assert deps.install_packages(["pkg"], echo=msgs.append) is False
    assert msgs == ["nope, because"]


# ---- `features enable` refuses before writing config -----------------------


class _Feat:
    name = "Cocktail Filter"
    slug = "cocktail"
    pip_packages = ("speechbrain>=1.1",)
    check_modules = ("definitely_not_installed_xyz",)


class _BundledFeat:
    name = "Voice-activity overlay"
    slug = "overlay"
    pip_packages = ("PySide6>=6.8",)
    check_modules = ("sys",)  # stands in for a library the snap does bundle


def test_feature_with_unbuildable_deps_is_blocked(monkeypatch):
    from yazses import cli

    monkeypatch.setattr(deps, "in_snap", lambda env=None: True)
    monkeypatch.setenv("SNAP_NAME", "yazses")
    assert cli._feature_deps_blocked(_Feat()) is not None


def test_feature_whose_deps_are_bundled_is_not_blocked(monkeypatch):
    """The snap bundles sherpa-onnx, kokoro-onnx and PySide6. Those capabilities
    must still enable normally inside a snap — blanket-refusing every
    dependency-bearing feature would break what the snap ships to work."""
    from yazses import cli

    monkeypatch.setattr(deps, "in_snap", lambda env=None: True)
    assert cli._feature_deps_blocked(_BundledFeat()) is None


def test_blocked_feature_does_not_write_config(monkeypatch, tmp_path):
    """The whole point: refuse *before* the config key lands on disk."""
    from typer.testing import CliRunner

    from yazses import cli

    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(cli, "_feature_deps_blocked", lambda feat: "cannot install")
    written: list[object] = []
    monkeypatch.setattr(
        cli, "_apply_feature_writes", lambda *a: written.append(a)  # pragma: no cover
    )

    result = CliRunner().invoke(cli.app, ["features", "enable", "cocktail", "--force"])
    assert result.exit_code == 1
    assert written == [], "config was written for a capability that can never work"
    assert not cfg.exists()


# ---- the snap actually bundles what the registry promises -------------------

_SNAPCRAFT = Path(__file__).resolve().parents[1] / "snap" / "snapcraft.yaml"


@pytest.mark.skipif(not _SNAPCRAFT.exists(), reason="snap packaging not in this tree")
@pytest.mark.parametrize("package", ["sherpa-onnx", "kokoro-onnx", "soundfile"])
def test_snapcraft_bundles_the_installable_extras(package):
    """These are the extras a snap user cannot add later, so the build must ship
    them. Dropping one silently removes Meeting Mode / Read-Back from the snap
    with no error anywhere — it just reports 'unavailable' forever."""
    text = _SNAPCRAFT.read_text(encoding="utf-8")
    assert f"- {package}" in text, f"snap no longer bundles {package}"


@pytest.mark.skipif(not _SNAPCRAFT.exists(), reason="snap packaging not in this tree")
def test_snap_does_not_bundle_the_arch_breaking_or_huge_extras():
    """A guard on the two traps that cost real builds: a dep with no aarch64
    wheel fails the arm64 build outright, and torch would multiply the snap."""
    text = _SNAPCRAFT.read_text(encoding="utf-8")
    for package in ("- praat-parselmouth", "- speechbrain", "- llama-cpp-python"):
        assert package not in text, f"{package} must not be bundled — see the comment"


@pytest.mark.skipif(sys.platform != "linux", reason="snap is Linux-only")
def test_bundled_features_cover_meeting_mode():
    """Meeting Mode is the headline capability; it must not be snap-unreachable."""
    from yazses.system.features import _FEATURE_DEPS

    for slug in ("meeting", "recimport", "diarize"):
        assert any("sherpa-onnx" in p for p in _FEATURE_DEPS[slug][1])
