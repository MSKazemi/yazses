"""The camera packaging matrix and the real manifests must say the same thing.

EYE-PERM-001 (#414) asks for a checked-in permission/packaging matrix. It lives
in `src/yazses/cameraperm/matrix.py` as data rather than in a table somebody has
to remember to update, and this file is what keeps it true: every row is held
against the manifest, plug list or build script it describes.

The rule underneath is R-21, and it cuts both ways:

* an install format that **cannot** run a camera feature must not declare a
  camera capability. `packaging/windows/msix/AppxManifest.xml` already spells
  this out for the MSIX; the same reasoning applies to the .dmg, the snap and
  the flatpak, and none of them had anything checking it.
* an install format that **can** must declare it, because macOS and Windows
  refuse an undeclared service **without prompting** — indistinguishable, from
  the user's chair, from the feature being broken. That is how #182 presented
  for Input Monitoring, and the camera would present identically.

So the interesting assertions are not "webcam is absent". They are the ones that
fail when a build script starts shipping mediapipe: at that moment the matrix,
the manifest and this file all have to move together, and the failure message
says which.

Nothing here needs a webcam, a Mac, a Windows box or a network.
"""

from __future__ import annotations

import ast
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from yazses.cameraperm import CAMERA_MODULES, PACKAGE_PROFILES, profile_for, profile_key_for

ROOT = Path(__file__).resolve().parents[1]
APPX = ROOT / "packaging" / "windows" / "msix" / "AppxManifest.xml"
MACOS_SPEC = ROOT / "packaging" / "macos" / "yazses.spec"
SNAPCRAFT = ROOT / "snap" / "snapcraft.yaml"
FLATPAK = ROOT / "packaging" / "flatpak" / "com.mskazemi.YazSes.yml"
FLATPAK_WHEELS = ROOT / "packaging" / "flatpak" / "python3-yazses.json"
BUILD_MACOS = ROOT / "scripts" / "build-macos.sh"
BUILD_WINDOWS = ROOT / "scripts" / "build-windows.ps1"

#: The pip distribution names behind :data:`CAMERA_MODULES`, as a packaging file
#: would spell them. ``cv2`` is imported but installed as ``opencv-python``, and
#: a scan for the import name alone would miss it in every manifest.
CAMERA_DISTRIBUTIONS = ("mediapipe", "opencv-python", "opencv-contrib-python")


# ---- the guards are not vacuous ------------------------------------------


def test_every_file_this_reads_exists() -> None:
    """A renamed manifest would make most assertions below pass over nothing."""
    for path in (APPX, MACOS_SPEC, SNAPCRAFT, FLATPAK, FLATPAK_WHEELS,
                 BUILD_MACOS, BUILD_WINDOWS):
        assert path.is_file(), f"{path.relative_to(ROOT)} is gone; the matrix is unchecked"


def test_the_matrix_covers_every_channel_this_project_ships() -> None:
    keys = {p.key for p in PACKAGE_PROFILES}
    assert keys == {
        "source", "distro", "macos-app", "windows-exe", "windows-msix", "snap", "flatpak",
    }, f"the matrix no longer describes the channels YazSes ships: {sorted(keys)}"


# ---- the invariant, stated directly --------------------------------------


def test_no_profile_declares_a_camera_capability_it_cannot_use() -> None:
    """R-21. An unused camera capability is a consent request with no upside —
    a review question on the Store, and a scary prompt for the user."""
    wrong = [p.key for p in PACKAGE_PROFILES if p.declares_camera and not p.can_run_camera]
    assert not wrong, (
        f"{wrong} declare a camera capability while no camera code can run there"
    )


def test_a_format_that_cannot_add_a_runtime_cannot_run_a_camera_feature() -> None:
    """The frozen/confined formats carry no camera runtime and have no pip, so
    "can_run_camera" and "can_add_runtime" cannot disagree for them."""
    for profile in PACKAGE_PROFILES:
        if not profile.can_add_runtime:
            assert not profile.can_run_camera, (
                f"{profile.key} claims a camera feature runs there, but also that it "
                "can never install the runtime — one of the two is wrong"
            )


def test_every_frozen_or_confined_format_names_a_way_out() -> None:
    """A row that says "no" without saying what to do instead is the dead end
    this whole contract replaces."""
    for profile in PACKAGE_PROFILES:
        if not profile.can_run_camera:
            assert profile.remedy, f"{profile.key} refuses the camera and offers nothing"
            assert profile.why, f"{profile.key} gives no reason a reviewer could check"


# ---- the detection ---------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (dict(platform_name="linux", frozen=False, in_snap=False, in_flatpak=False), "source"),
        (dict(platform_name="linux", frozen=False, in_snap=True, in_flatpak=False), "snap"),
        (dict(platform_name="linux", frozen=True, in_snap=False, in_flatpak=True), "flatpak"),
        (dict(platform_name="darwin", frozen=True, in_snap=False, in_flatpak=False), "macos-app"),
        (dict(platform_name="darwin", frozen=False, in_snap=False, in_flatpak=False), "source"),
        (dict(platform_name="win32", frozen=True, in_snap=False, in_flatpak=False), "windows-exe"),
        (
            dict(platform_name="win32", frozen=True, in_snap=False, in_flatpak=False,
                 appx_manifest_present=True),
            "windows-msix",
        ),
    ],
)
def test_the_install_format_is_detected_from_facts_not_from_sys_platform(kwargs, expected) -> None:
    """A pure function over stated facts, so every channel is reachable in a test
    without building its package — and so nothing branches on `sys.platform`
    outside the platform seam."""
    assert profile_key_for(**kwargs) == expected


def test_an_unknown_channel_still_ends_at_a_real_permission_check() -> None:
    """`profile_for` falls back rather than raising — a traceback out of `doctor`
    because someone invented a channel would be the worse failure. The fallback
    must be a row that still reaches the OS probe, so nothing is waved through."""
    fallback = profile_for("no-such-channel")
    assert fallback.key == "source"
    assert fallback.can_run_camera is True


# ---- Windows MSIX ----------------------------------------------------------


def _appx() -> ET.Element:
    return ET.parse(APPX).getroot()


def _device_capabilities(root: ET.Element) -> set[str]:
    ns = "{http://schemas.microsoft.com/appx/manifest/foundation/windows10}"
    return {
        el.get("Name", "")
        for el in root.iter(f"{ns}DeviceCapability")
    }


def test_the_msix_manifest_matches_its_matrix_row() -> None:
    devices = _device_capabilities(_appx())
    assert "microphone" in devices, "the manifest parse found nothing; this guard is blind"
    assert ("webcam" in devices) is profile_for("windows-msix").declares_camera, (
        "AppxManifest.xml and cameraperm/matrix.py disagree about the webcam capability"
    )


# ---- macOS .app ------------------------------------------------------------


def _spec_info_plist() -> dict[str, ast.expr]:
    """The spec's ``info_plist=`` dict, read as source — the spec imports
    PyInstaller and cannot be executed here. Same approach as
    `tests/test_macos_usage_descriptions.py`."""
    tree = ast.parse(MACOS_SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "info_plist":
            assert isinstance(node.value, ast.Dict)
            return {
                k.value: v
                for k, v in zip(node.value.keys, node.value.values)
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    raise AssertionError("no info_plist= in the macOS spec")


def test_the_mac_bundle_matches_its_matrix_row() -> None:
    plist = _spec_info_plist()
    assert "NSMicrophoneUsageDescription" in plist, "the plist parse found nothing"
    declared = "NSCameraUsageDescription" in plist
    assert declared is profile_for("macos-app").declares_camera, (
        "packaging/macos/yazses.spec and cameraperm/matrix.py disagree about "
        "NSCameraUsageDescription"
    )


def test_adding_the_camera_string_would_also_have_to_reach_the_dmg_inspector() -> None:
    """If NSCameraUsageDescription is ever declared it must also be inspected, or
    a released .dmg missing the string inspects clean.
    `tests/test_macos_usage_descriptions.py` enforces that in general; this names
    the camera key so the connection is not rediscovered later."""
    inspector = (ROOT / "scripts" / "inspect-dmg.py").read_text(encoding="utf-8")
    declared = "NSCameraUsageDescription" in _spec_info_plist()
    assert declared == ("NSCameraUsageDescription" in inspector), (
        "the camera usage string is declared in exactly one of the spec and "
        "scripts/inspect-dmg.py — both or neither"
    )


# ---- the frozen bundles carry no camera runtime ---------------------------


def _synced_extras(text: str) -> set[str]:
    lines = [
        ln for ln in text.splitlines()
        if "uv sync" in ln and not ln.lstrip().startswith("#")
    ]
    assert lines, "no `uv sync` line found; re-check what the bundle carries"
    return {e for ln in lines for e in re.findall(r"--extra\s+([\w.-]+)", ln)}


@pytest.mark.parametrize(
    ("script", "key"),
    [(BUILD_MACOS, "macos-app"), (BUILD_WINDOWS, "windows-exe")],
)
def test_a_frozen_bundle_that_gained_a_camera_extra_would_fail_here(script: Path, key: str) -> None:
    """The R-21 tripwire, pointing the other way.

    The matrix says these bundles cannot run a camera feature *because of what
    the build script syncs*. Derive it rather than restate it: the day someone
    adds `--extra gaze`, the camera features become reachable inside the bundle
    and the OS declaration becomes mandatory — and that is the day this fails
    and says so, instead of the bundle shipping a silently refused feature.
    """
    extras = _synced_extras(script.read_text(encoding="utf-8"))
    ships_camera = "gaze" in extras or "all" in extras
    assert ships_camera is profile_for(key).can_run_camera, (
        f"{script.name} syncs {sorted(extras)}. If a camera extra is now inside the "
        f"bundle, cameraperm/matrix.py must flip {key}.can_run_camera AND the bundle "
        f"must declare {profile_for(key).declaration or 'its OS camera capability'}, "
        "or the feature will be refused without a prompt."
    )


# ---- snap ------------------------------------------------------------------


def _snapcraft() -> dict:
    import yaml

    return yaml.safe_load(SNAPCRAFT.read_text(encoding="utf-8"))


def test_the_snap_matches_its_matrix_row() -> None:
    snapcraft = _snapcraft()
    plugs = {plug for app in snapcraft["apps"].values() for plug in app.get("plugs", [])}
    assert "audio-record" in plugs, "the plug scan found nothing; this guard is blind"
    assert ("camera" in plugs) is profile_for("snap").declares_camera, (
        "snap/snapcraft.yaml and cameraperm/matrix.py disagree about the camera plug"
    )


def test_the_snap_bundles_no_camera_runtime() -> None:
    """A snap payload is a read-only squashfs and the staged python is PEP 668
    externally managed, so whatever is not bundled is unreachable for the life of
    the revision. If mediapipe ever joins the list, `camera` becomes mandatory."""
    packages = " ".join(_snapcraft()["parts"]["yazses"].get("python-packages", []))
    assert packages, "python-packages is empty; the scan is blind"
    bundled = any(dist in packages for dist in CAMERA_DISTRIBUTIONS)
    assert bundled is profile_for("snap").can_run_camera, (
        "snapcraft.yaml now bundles a camera runtime (or no longer does) and "
        "cameraperm/matrix.py still says otherwise — and the `camera` plug follows"
    )


# ---- flatpak ---------------------------------------------------------------


def _flatpak() -> dict:
    import yaml

    return yaml.safe_load(FLATPAK.read_text(encoding="utf-8"))


def test_the_flatpak_matches_its_matrix_row() -> None:
    args = _flatpak()["finish-args"]
    assert any(a.startswith("--device=") for a in args), "the finish-args scan is blind"
    grants_camera = "--device=all" in args
    assert grants_camera is profile_for("flatpak").declares_camera, (
        "the flatpak finish-args and cameraperm/matrix.py disagree about camera access"
    )


def test_the_flatpak_installs_no_camera_runtime() -> None:
    """`python3-yazses.json` pins the exact wheel set that lands in the sandbox,
    and a flatpak cannot add one afterwards."""
    text = json.dumps(json.loads(FLATPAK_WHEELS.read_text(encoding="utf-8")))
    assert "faster-whisper" in text, "the wheel-set scan found nothing; it is blind"
    bundled = any(dist in text for dist in CAMERA_DISTRIBUTIONS)
    assert bundled is profile_for("flatpak").can_run_camera, (
        "the flatpak wheel set and cameraperm/matrix.py disagree about the camera runtime"
    )


# ---- the runtime the whole table is about ---------------------------------


def test_the_camera_modules_are_the_ones_the_features_import() -> None:
    """`CAMERA_MODULES` is what every "is a camera runtime present" answer is
    computed from. If the backends stop importing these, every row above is
    measuring the wrong thing."""
    backends = (
        ROOT / "src" / "yazses" / "gaze" / "mediapipe_backend.py",
        ROOT / "src" / "yazses" / "facegesture" / "backend.py",
    )
    for path in backends:
        source = path.read_text(encoding="utf-8")
        for module in CAMERA_MODULES:
            assert re.search(rf"\bimport {re.escape(module)}\b", source), (
                f"{path.name} no longer imports {module}; CAMERA_MODULES is stale"
            )


# ---- the page a user reads says the same thing -----------------------------

CAPABILITY_DOC = ROOT / "docs" / "capability-matrix.md"


def _doc_camera_rows() -> dict[str, tuple[str, str, str]]:
    """The camera table out of `docs/capability-matrix.md`, keyed by install format.

    Parsed rather than eyeballed because a published table that has drifted from
    the code is worse than no table: a reader who follows it installs the wrong
    package and concludes the feature is broken.
    """
    text = CAPABILITY_DOC.read_text(encoding="utf-8")
    start = text.index("## Camera permission and packaging")
    section = text[start:]
    rows: dict[str, tuple[str, str, str]] = {}
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 4 or cells[0] == "Install format":
            continue
        rows[cells[0]] = (cells[1], cells[2], cells[3])
    return rows


def test_the_published_table_lists_every_channel() -> None:
    rows = _doc_camera_rows()
    assert len(rows) == len(PACKAGE_PROFILES), (
        f"docs/capability-matrix.md lists {len(rows)} install formats, the matrix has "
        f"{len(PACKAGE_PROFILES)}"
    )


def test_the_published_table_agrees_with_the_matrix() -> None:
    """Three facts per row, each one something a reader would act on."""
    rows = _doc_camera_rows()
    for profile in PACKAGE_PROFILES:
        assert profile.label in rows, f"{profile.key} is missing from the published table"
        runs, declaration, declared = rows[profile.label]
        assert ("✅" in runs) is profile.can_run_camera, (
            f"the docs and the matrix disagree about whether {profile.key} can run a "
            "camera feature"
        )
        assert declaration == (profile.declaration or "—"), (
            f"{profile.key} names {declaration!r} in the docs and "
            f"{profile.declaration!r} in the matrix"
        )
        assert ("✅" in declared) is profile.declares_camera, (
            f"the docs and the matrix disagree about what {profile.key} declares today"
        )


def test_snap_detection_reuses_the_projects_own_predicate() -> None:
    """One reading of SNAP_NAME/SNAP, not two.

    A second hand-written copy of an existing predicate is this project's
    most-repeated defect; here it would have made `doctor` describe the wrong
    install format the first time snapd set only one of the two variables.
    """
    from yazses.cameraperm.matrix import detect_profile_key

    assert detect_profile_key({"SNAP_NAME": "yazses"}) == "snap"
    assert detect_profile_key({"SNAP": "/snap/yazses/42"}) == "snap"
    assert detect_profile_key({"YAZSES_PACKAGE_FORMAT": "flatpak"}) == "flatpak"
    assert detect_profile_key({"YAZSES_PACKAGE_FORMAT": "not-a-channel"}) != "not-a-channel"


def test_the_detector_compares_against_the_real_sys_platform_names() -> None:
    """`profile_key_for` spells "darwin"/"win32" as literals, and must keep to the
    values `platform/base.py` publishes.

    They are literals rather than an import because `platform/base.py` imports
    `cameraperm.contract`, so importing it back here would be a cycle. That is
    exactly the situation in which a friendly-sounding string — `"macos"`,
    `"windows"` — silently matches nothing: it is how the "Elevated windows"
    doctor row came to be unreachable on the only OS it exists for.
    """
    from yazses.platform.base import MACOS_PLATFORM_NAME, WINDOWS_PLATFORM_NAME

    assert profile_key_for(
        platform_name=MACOS_PLATFORM_NAME, frozen=True, in_snap=False, in_flatpak=False
    ) == "macos-app"
    assert profile_key_for(
        platform_name=WINDOWS_PLATFORM_NAME, frozen=True, in_snap=False, in_flatpak=False
    ) == "windows-exe"
