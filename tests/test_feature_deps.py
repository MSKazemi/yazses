"""Auto-install of a feature's optional deps on `yazses features enable`."""
from __future__ import annotations

import sys

import pytest

from yazses.system import deps
from yazses.system.features import _registry


def test_missing_modules_detects_absent_import():
    assert deps.missing_modules(["sys", "os"]) == []
    got = deps.missing_modules(["sys", "totally_not_a_real_module_xyz"])
    assert got == ["totally_not_a_real_module_xyz"]


def test_install_command_prefers_uv(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv")
    cmd = deps.install_command(["mediapipe>=0.10"])
    assert cmd == ["uv", "pip", "install", "--python", sys.executable, "mediapipe>=0.10"]


def test_install_command_falls_back_to_pip(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    cmd = deps.install_command(["opencv-python>=4.10"])
    assert cmd == [sys.executable, "-m", "pip", "install", "opencv-python>=4.10"]


def test_install_packages_success(monkeypatch):
    calls = []
    monkeypatch.setattr(deps.subprocess, "run", lambda cmd, check: calls.append(cmd))
    assert deps.install_packages(["pkg-a", "pkg-b"], echo=lambda *_: None) is True
    assert calls and calls[0][-2:] == ["pkg-a", "pkg-b"]


def test_install_packages_reports_failure(monkeypatch):
    def boom(cmd, check):
        raise deps.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(deps.subprocess, "run", boom)
    msgs = []
    assert deps.install_packages(["pkg"], echo=msgs.append) is False
    assert any("manually" in m for m in msgs)


def test_install_packages_noop_when_empty():
    assert deps.install_packages([]) is True


def test_gaze_feature_declares_its_deps():
    gaze = next(d for d in _registry() if d.slug == "gaze")
    assert gaze.check_modules == ("cv2", "mediapipe")
    assert "mediapipe>=0.10" in gaze.pip_packages
    assert "opencv-python>=4.10" in gaze.pip_packages


def test_heavy_features_all_declare_deps():
    # Every complex/heavy feature installs its extras on enable (on-demand, not
    # up front). Pure-logic features declare nothing.
    by_slug = {d.slug: d for d in _registry()}
    expected = {
        "overlay", "prosody", "voicehealth", "read-back", "readback_clone",
        "llm-cleanup", "agent", "cocktail", "multiprofile", "voiceguard",
        "diarize", "gaze",
    }
    for slug in expected:
        feat = by_slug[slug]
        assert feat.pip_packages, f"{slug} should declare pip deps"
        assert feat.check_modules, f"{slug} should declare import probes"


def test_deps_map_only_targets_real_features():
    from yazses.system.features import _FEATURE_DEPS

    slugs = {d.slug for d in _registry()}
    assert set(_FEATURE_DEPS).issubset(slugs)  # no typo'd slugs in the map


def test_pure_logic_feature_declares_no_deps():
    # A representative pure-logic feature installs nothing on enable.
    casetransform = next(d for d in _registry() if d.slug == "casetransform")
    assert casetransform.pip_packages == ()
