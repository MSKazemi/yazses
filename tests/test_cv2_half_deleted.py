"""A half-deleted OpenCV (``cv2``) is found at start and by doctor, without importing it.

The camera features installed two OpenCV builds up to 2.43.2 (``opencv-python`` and
``opencv-contrib-python``), which write the same ``cv2/`` files. Removing either one --
an older YazSes's ``uv tool upgrade``, ``uv sync``, ``pip uninstall opencv-python`` --
leaves ``cv2/`` as a directory of contrib-only subfolders: ``import cv2`` and
``find_spec("cv2")`` succeed (a namespace package), ``cv2.VideoCapture`` does not exist,
and the camera feature crashes later. ``system/updater.py`` protects upgrades it runs
itself; these pin the backstop for every other route:

* ``system/opencv_health.cv2_half_deleted`` -- the one cheap decision, on real
  directory layouts built in ``tmp_path`` (the namespace husk is the layout the offline
  reproduction left behind: contrib-only subfolders, no ``__init__.py``, no native module);
* ``system/dormant.dormant_features`` -- a camera feature on a husk is NOT ready, with
  the pinned repair as its remedy and no "Install now" (installing changes nothing);
* ``yazses doctor``'s **OpenCV** row.

No OpenCV is installed or imported by any of these.
"""
from __future__ import annotations

import dataclasses
import importlib.machinery
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from yazses.config import Config
from yazses.system import dormant, ondemand, opencv_health
from yazses.system.features import feature_status

SUFFIX = importlib.machinery.EXTENSION_SUFFIXES[0]
CONTRIB = {"opencv-contrib-python": "5.0.0.93"}
REPAIR = [
    "uv", "pip", "install", "--python", "/home/u/.local/share/uv/tools/yazses/bin/python",
    "--reinstall", "--no-deps", "opencv-contrib-python==5.0.0.93",
]


# ---- layouts --------------------------------------------------------------------


def husk(site: Path) -> Path:
    """What `uv tool upgrade` left after removing opencv-python: contrib-only folders."""
    for sub in ("bgsegm", "face", "xfeatures2d", "ximgproc"):
        (site / "cv2" / sub).mkdir(parents=True)
        (site / "cv2" / sub / "__init__.pyi").write_text("", encoding="utf-8")
    return site


def whole(site: Path) -> Path:
    pkg = site / "cv2"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / f"cv2{SUFFIX}").write_bytes(b"\x7fELF")
    (pkg / "face").mkdir()
    return site


def no_native(site: Path) -> Path:
    pkg = site / "cv2"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "config.py").write_text("", encoding="utf-8")
    return site


def dist_info(site: Path, name: str = "opencv_contrib_python", version: str = "5.0.0.93"):
    d = site / f"{name}-{version}.dist-info"
    d.mkdir(parents=True)
    pretty = name.replace("_", "-")
    (d / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {pretty}\nVersion: {version}\n", encoding="utf-8"
    )


def spec_in(site: Path):
    return importlib.machinery.PathFinder.find_spec("cv2", [str(site)])


def _never():
    raise AssertionError("must not be asked")


# ---- the decision ----------------------------------------------------------------


def test_the_husk_really_is_found_by_find_spec_as_a_namespace(tmp_path):
    """The premise: a bare find_spec (what the import probe asks) calls it present."""
    spec = spec_in(husk(tmp_path))
    assert spec is not None
    assert spec.origin is None and spec.submodule_search_locations


def test_a_husk_with_an_opencv_distribution_installed_is_half_deleted(tmp_path):
    spec = spec_in(husk(tmp_path))
    assert opencv_health.cv2_half_deleted(find_spec=lambda: spec, versions=lambda: CONTRIB)


def test_a_package_whose_native_module_is_gone_is_half_deleted(tmp_path):
    spec = spec_in(no_native(tmp_path))
    assert opencv_health.cv2_half_deleted(find_spec=lambda: spec, versions=lambda: CONTRIB)


def test_a_whole_package_is_healthy_and_reads_no_metadata(tmp_path):
    spec = spec_in(whole(tmp_path))
    assert not opencv_health.cv2_half_deleted(find_spec=lambda: spec, versions=_never)


def test_cv2_as_a_single_extension_module_is_whole(tmp_path):
    """Debian's python3-opencv: cv2 is one .so, not a package."""
    (tmp_path / f"cv2{SUFFIX}").write_bytes(b"\x7fELF")
    spec = spec_in(tmp_path)
    assert spec is not None and spec.submodule_search_locations is None
    assert not opencv_health.cv2_half_deleted(find_spec=lambda: spec, versions=_never)


def test_no_cv2_at_all_is_not_half_deleted_and_reads_no_metadata():
    """Not installed is the ordinary missing-library finding, not this one."""
    assert not opencv_health.cv2_half_deleted(find_spec=lambda: None, versions=_never)


def test_a_husk_no_distribution_claims_is_not_this_finding(tmp_path):
    """No OpenCV build installed: there is nothing to repair *in place*."""
    spec = spec_in(husk(tmp_path))
    assert not opencv_health.cv2_half_deleted(find_spec=lambda: spec, versions=lambda: {})


def test_a_probe_that_raises_answers_healthy():
    def boom():
        raise OSError("unreadable")

    assert opencv_health.cv2_half_deleted(find_spec=boom) is False


def test_the_real_probes_never_import_cv2(tmp_path):
    """In a fresh interpreter whose sys.path holds a husk and its dist-info."""
    site = husk(tmp_path)
    dist_info(site)
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(site)!r})
        from yazses.system.opencv_health import cv2_half_deleted, installed_cv2_versions
        print(cv2_half_deleted(), installed_cv2_versions(), "cv2" in sys.modules)
    """)
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == [
        "True", "{'opencv-contrib-python':", "'5.0.0.93'}", "False"
    ]


def test_the_updater_reads_versions_through_the_same_probe():
    """One probe, not two copies: the updater's in-process read is this module's."""
    from yazses.system import updater

    assert updater.CV2_DISTRIBUTIONS is opencv_health.CV2_DISTRIBUTIONS
    assert "installed_cv2_versions()" in inspect.getsource(updater._env_cv2_versions)


# ---- dormant: a camera feature on a husk is not ready ----------------------------


def _camera_rows():
    rows = [f for f in feature_status(Config()) if opencv_health.uses_cv2(f) and f.wired]
    assert rows, "no wired feature checks for cv2; the camera set is empty"
    return [dataclasses.replace(f, on=True) for f in rows]


def test_the_camera_set_is_derived_from_the_registry():
    slugs = {f.slug for f in _camera_rows()}
    assert {"gaze", "facegesture", "headpointer", "gesture", "handsfree"} & slugs
    assert all("cv2" in f.check_modules for f in _camera_rows())


def test_a_camera_feature_on_a_husk_is_dormant_with_the_pinned_repair():
    rows = _camera_rows()
    found = dormant.dormant_features(
        None, features=rows, missing=lambda m: [], blocked=lambda p: None,
        graphical=lambda: True, cv2_broken=lambda: True, cv2_repair=lambda: REPAIR,
    )
    assert {d.slug for d in found} == {f.slug for f in rows}
    item = found[0]
    assert item.installable is False, "installing an installed package fixes nothing"
    assert item.missing == ("cv2",)
    assert "half-deleted" in item.describe()
    assert "not installed" not in item.describe()
    from yazses.system.remedy import render_command

    assert render_command(REPAIR) in item.remedy
    assert item.command == render_command(REPAIR)
    # The start-up announcement: no Install-now button, the repair in the body.
    assert ondemand.toast_actions(item) is None
    assert render_command(REPAIR) in ondemand.toast_body(item)


def test_the_husk_is_probed_once_and_never_without_a_camera_feature_on():
    calls = []

    def probe():
        calls.append(1)
        return False

    rows = _camera_rows()
    dormant.dormant_features(
        None, features=rows, missing=lambda m: [], blocked=lambda p: None,
        graphical=lambda: True, cv2_broken=probe, cv2_repair=_never,
    )
    assert calls == [1]
    off = [dataclasses.replace(f, on=False) for f in rows]
    dormant.dormant_features(
        None, features=off, missing=lambda m: [], blocked=lambda p: None,
        graphical=lambda: True, cv2_broken=_never, cv2_repair=_never,
    )


def test_an_injected_import_probe_does_not_consult_the_real_cv2(monkeypatch):
    monkeypatch.setattr(dormant, "_default_cv2_broken", _never)
    assert dormant.dormant_features(
        None, features=_camera_rows(), missing=lambda m: [], blocked=lambda p: None,
        graphical=lambda: True,
    ) == []


def test_a_genuinely_missing_cv2_keeps_the_install_remedy():
    found = dormant.dormant_features(
        None, features=_camera_rows()[:1], missing=lambda m: list(m),
        blocked=lambda p: None, graphical=lambda: True, cv2_broken=_never,
    )
    assert found and found[0].installable and "features enable" in found[0].remedy


def test_today_a_real_husk_reads_as_healthy_to_the_import_probe(tmp_path, monkeypatch):
    """End to end through the default probes: a husk cv2, a stand-in mediapipe and a
    real contrib dist-info on sys.path. The import probe alone calls gaze ready; the
    change makes dormant say otherwise, with a repair pinned to the installed version."""
    site = husk(tmp_path)
    dist_info(site)
    (site / "mediapipe").mkdir()
    (site / "mediapipe" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(site))
    for name in ("cv2", "mediapipe"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    importlib.invalidate_caches()

    from yazses.system.deps import missing_modules

    gaze = next(f for f in _camera_rows() if f.slug == "gaze")
    assert missing_modules(gaze.check_modules) == [], "premise: find_spec calls it present"

    found = dormant.dormant_features(
        None, features=[gaze], blocked=lambda p: None, graphical=lambda: True
    )
    assert [d.slug for d in found] == ["gaze"]
    assert "opencv-contrib-python==5.0.0.93" in found[0].remedy
    assert "--no-deps" in found[0].remedy


# ---- doctor: one OpenCV row, only when an OpenCV build is installed ---------------


def test_doctor_has_no_opencv_row_without_an_opencv_distribution():
    from yazses.system import doctor

    assert doctor._opencv_check(versions=lambda: {}, broken=_never, repair=_never) is None


def test_doctor_says_ok_for_a_whole_cv2():
    from yazses.system import doctor

    row = doctor._opencv_check(versions=lambda: CONTRIB, broken=lambda: False, repair=_never)
    assert row is not None
    assert row[:2] == ("OpenCV", "OK")
    assert "opencv-contrib-python 5.0.0.93" in row[2]


def test_doctor_fails_a_husk_with_the_pinned_repair():
    from yazses.system import doctor
    from yazses.system.remedy import render_command

    row = doctor._opencv_check(
        versions=lambda: CONTRIB, broken=lambda: True, repair=lambda: REPAIR
    )
    assert row is not None
    label, status, detail = row
    assert (label, status) == ("OpenCV", "FAIL")
    assert "half-deleted" in detail and render_command(REPAIR) in detail


def test_doctor_names_what_to_reinstall_when_no_command_can_be_built():
    from yazses.system import doctor

    row = doctor._opencv_check(versions=lambda: CONTRIB, broken=lambda: True,
                               repair=lambda: None)
    assert row is not None and row[1] == "FAIL"
    assert "opencv-contrib-python" in row[2] and "--no-deps" in row[2]


def test_run_doctor_prints_the_opencv_row(sandbox_paths, monkeypatch, capsys):
    """Wired into the real report, through the default probes."""
    from yazses.system import doctor, updater
    from yazses.system.remedy import render_command

    monkeypatch.setattr(opencv_health, "installed_cv2_versions", lambda: CONTRIB)
    monkeypatch.setattr(opencv_health, "cv2_half_deleted", lambda: True)
    monkeypatch.setattr(updater, "cv2_repair_here", lambda: REPAIR)
    try:
        doctor.run_doctor(check_mic=False)
    except SystemExit:
        pass
    out = capsys.readouterr().out
    line = next((ln for ln in out.splitlines() if "OpenCV" in ln and "half-deleted" in ln),
                None)
    assert line is not None, out
    assert render_command(REPAIR) in out


def test_the_start_up_toast_fits_a_windows_balloon_with_the_command_whole():
    """On Windows the daemon's toast is relayed into a tray balloon, which Windows drops
    over 255 characters, and `fit_balloon` would cut the command. Measured with the
    longest camera feature name and a long Windows profile path."""
    from yazses.system import updater
    from yazses.system.remedy import render_command
    from yazses.tray.about import BALLOON_LIMIT, fit_balloon

    python = (r"C:\Users\Firstname.Lastname-Long\AppData\Roaming\uv\tools\yazses"
              r"\Scripts\python.exe")
    argv = updater.cv2_repair_command("uv", CONTRIB, python=python)
    rows = _camera_rows()
    longest = max(rows, key=lambda f: len(f.name))
    found = dormant.dormant_features(
        None, features=[longest], missing=lambda m: [], blocked=lambda p: None,
        graphical=lambda: True, cv2_broken=lambda: True, cv2_repair=lambda: argv,
    )
    body = ondemand.toast_body(found[0])
    assert len(body) <= BALLOON_LIMIT, (len(body), body)
    assert render_command(argv) in fit_balloon(body)


# ---- the repair for the running environment ----------------------------------------


def test_the_repair_here_is_the_upgrade_s_pinned_repair():
    from yazses.system import updater

    py = "/home/u/.local/share/uv/tools/yazses/bin/python"
    got = updater.cv2_repair_here(method="uv", versions=CONTRIB, python=py)
    assert got == updater.cv2_repair_command("uv", CONTRIB, python=py)
    assert got[-1] == "opencv-contrib-python==5.0.0.93" and "--no-deps" in got


def test_a_pip_less_venv_gets_the_uv_form():
    from yazses.system import updater

    got = updater.cv2_repair_here(
        method="pip", versions=CONTRIB, python="/src/.venv/bin/python",
        has_pip=lambda: False,
    )
    assert got[:3] == ["uv", "pip", "install"] and "/src/.venv/bin/python" in got
    with_pip = updater.cv2_repair_here(
        method="pip", versions=CONTRIB, python="/v/bin/python", has_pip=lambda: True
    )
    assert with_pip[:3] == ["/v/bin/python", "-m", "pip"]


@pytest.mark.parametrize("method", ["snap", "windows-installer", "macos-app", "msix"])
def test_no_repair_command_where_no_python_environment_can_be_repaired(method):
    from yazses.system import updater

    assert updater.cv2_repair_here(method=method, versions=CONTRIB, python="x") is None
