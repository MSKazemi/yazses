"""Auto-install of a feature's optional deps on `yazses features enable`."""
from __future__ import annotations

import sys

from yazses.system import deps
from yazses.system.features import _registry


def test_missing_modules_detects_absent_import():
    assert deps.missing_modules(["sys", "os"]) == []
    got = deps.missing_modules(["sys", "totally_not_a_real_module_xyz"])
    assert got == ["totally_not_a_real_module_xyz"]


def test_missing_modules_answers_for_a_dotted_name_whose_parent_is_absent():
    """It used to *raise* here, which silently defeated the backend-honesty layer.

    ``find_spec`` returns None for an absent top-level module but raises
    ``ModuleNotFoundError`` for ``a.b`` when ``a`` is missing, because it has to
    import the parent to look inside it. ``pyannote.audio`` is the only backend
    asked about by dotted name, so the exception escaped into
    ``recimport.factory._unavailable_detail`` and its blanket ``except`` reported
    an unrelated error instead of "install the `diarization-pyannote` extra".
    """
    got = deps.missing_modules(["totally_not_a_real_pkg_xyz.submodule"])
    assert got == ["totally_not_a_real_pkg_xyz.submodule"]


def test_missing_modules_reports_a_real_dotted_module_as_present():
    """The dotted-name fix must not degrade into "everything dotted is missing"."""
    assert deps.missing_modules(["os.path", "email.mime"]) == []


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
        "diarize", "gaze", "recimport", "meeting", "stt-parakeet",
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


def test_public_feature_exposes_deps_for_cli():
    """Regression: ``cli._install_feature_deps`` reads ``pip_packages`` /
    ``check_modules`` off the public :class:`Feature` returned by
    ``find_feature`` — not the internal ``_Def``. Those fields must survive the
    ``_Def``→``Feature`` conversion, else `features enable <name>` crashes with
    ``AttributeError: 'Feature' object has no attribute 'pip_packages'``.
    """
    from yazses.config import load_config
    from yazses.system.features import feature_status, find_feature

    cfg = load_config()
    feat = find_feature(cfg, "read-back")
    assert feat is not None
    assert "kokoro_onnx" in feat.check_modules
    assert any("kokoro-onnx" in p for p in feat.pip_packages)
    # every public Feature must carry both fields (CLI touches them unguarded).
    for f in feature_status(cfg):
        assert hasattr(f, "pip_packages") and hasattr(f, "check_modules")
