"""Which install formats can run a camera feature, and what each must declare.

This is the checked-in permission/packaging matrix EYE-PERM-001 asks for, kept
as data rather than prose so the tests can hold it against the real manifests
instead of against a paragraph somebody has to remember to update. Nothing here
imports anything but the standard library.

The rule the whole table exists to enforce is R-21, and it runs in both
directions:

* a format that **cannot** run a camera feature must **not** declare a camera
  capability. An unused ``webcam`` capability or ``NSCameraUsageDescription`` is
  a consent request no code in that package can honour -- a review question and
  a user prompt with no upside;
* a format that **can** run one must declare it **before** the feature is
  claimed to work there, because macOS and Windows refuse an undeclared service
  *without prompting*, which is indistinguishable from the feature being broken.

Today every frozen or confined format sits on the first side of that rule: none
of the four (macOS ``.app``, Windows ``.exe``, Windows MSIX, snap, flatpak)
carries ``mediapipe``/``opencv-python``, and none of them can install a package
after the fact. Camera features are reachable only from a source/PyPI install,
where there is no manifest to declare anything in and the OS prompt -- on macOS
-- belongs to the Python interpreter's own bundle, not to YazSes.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

__all__ = [
    "PACKAGE_PROFILES",
    "PackageProfile",
    "current_profile",
    "detect_profile_key",
    "profile_for",
    "profile_key_for",
]

#: Import names of the camera runtime every camera feature needs. Kept next to
#: the matrix because "does this package ship a camera runtime" is a question
#: about exactly these two.
CAMERA_MODULES = ("cv2", "mediapipe")

#: The requirements that supply them, spelled as `pyproject.toml` spells them.
CAMERA_PACKAGES = ("mediapipe>=0.10.35", "opencv-python>=5.0")


@dataclass(frozen=True)
class PackageProfile:
    """One row of the matrix: an install format and its camera truth.

    ``declaration`` is the OS-level thing a camera-capable build of this format
    would have to carry, or ``None`` where the format has no manifest at all
    (a plain ``pip install`` declares nothing; the interpreter it runs under is
    what the OS sees). ``declares_camera`` is whether it currently carries it.
    """

    key: str
    label: str
    #: True when a camera feature can actually run from this install format --
    #: either because the runtime is bundled, or because the user can add it.
    can_run_camera: bool
    #: True when the runtime can be installed after the fact (a venv can; a
    #: read-only squashfs, a flatpak and a frozen bundle cannot).
    can_add_runtime: bool
    #: The manifest key / plug / finish-arg a camera-capable build needs.
    declaration: str | None
    #: Whether this format declares it today. Cross-checked against the real
    #: manifest files by ``tests/test_camera_packaging_matrix.py``.
    declares_camera: bool
    #: What a user of this format does to get camera features, if anything.
    remedy: str
    #: Why the row is what it is -- the sentence a reviewer needs.
    why: str


PACKAGE_PROFILES: tuple[PackageProfile, ...] = (
    PackageProfile(
        key="source",
        label="a source / PyPI install (pip, uv, pipx)",
        can_run_camera=True,
        can_add_runtime=True,
        declaration=None,
        declares_camera=False,
        remedy="yazses features enable gaze   # installs mediapipe + opencv-python",
        why=(
            "A virtualenv can install the camera extra on demand, so the runtime is "
            "opt-in rather than absent. There is no application manifest: on macOS the "
            "camera prompt is attributed to the Python interpreter's bundle, and on "
            "Windows to the unpackaged executable, neither of which YazSes owns."
        ),
    ),
    PackageProfile(
        key="distro",
        label="a distribution or third-party channel package "
              "(AUR, Fedora, Nix, Homebrew, Chocolatey, Scoop, WinGet)",
        can_run_camera=True,
        can_add_runtime=True,
        declaration=None,
        declares_camera=False,
        remedy=(
            "install mediapipe and opencv-python with the same tool that installed "
            "YazSes, or use pipx install 'yazses[gaze]'"
        ),
        why=(
            "These wrap the Python package rather than freezing it, so the camera "
            "runtime is installable -- but by the channel's own package manager, which "
            "is why the remedy is not a bare pip command."
        ),
    ),
    PackageProfile(
        key="macos-app",
        label="the macOS .app bundle (.dmg / Homebrew cask)",
        can_run_camera=False,
        can_add_runtime=False,
        declaration="NSCameraUsageDescription",
        declares_camera=False,
        remedy="pipx install 'yazses[gaze]'   # the camera features need a real Python",
        why=(
            "scripts/build-macos.sh syncs only `--extra desktop`, so neither mediapipe "
            "nor opencv-python is inside the bundle, and a frozen .app has no pip to "
            "add them. Declaring NSCameraUsageDescription would put YazSes in the "
            "Camera pane for a capability the bundle cannot use."
        ),
    ),
    PackageProfile(
        key="windows-exe",
        label="the Windows installer (.exe)",
        can_run_camera=False,
        can_add_runtime=False,
        declaration=None,
        declares_camera=False,
        remedy="pipx install 'yazses[gaze]'   # the camera features need a real Python",
        why=(
            "scripts/build-windows.ps1 syncs only `--extra desktop`, so the frozen "
            "bundle carries no camera runtime. An unpackaged Windows app declares no "
            "capabilities: the gate is Settings -> Privacy -> Camera, not a manifest."
        ),
    ),
    PackageProfile(
        key="windows-msix",
        label="the Windows MSIX package",
        can_run_camera=False,
        can_add_runtime=False,
        declaration="DeviceCapability webcam",
        declares_camera=False,
        remedy="pipx install 'yazses[gaze]'   # the camera features need a real Python",
        why=(
            "Same payload as the .exe, and an MSIX has no pip either. The manifest "
            "declares `microphone` and deliberately not `webcam`; the reasoning is "
            "written out in packaging/windows/msix/AppxManifest.xml."
        ),
    ),
    PackageProfile(
        key="snap",
        label="the snap",
        can_run_camera=False,
        can_add_runtime=False,
        declaration="camera plug",
        declares_camera=False,
        remedy="pipx install 'yazses[gaze]'   # a snap cannot add a library at runtime",
        why=(
            "snap/snapcraft.yaml names mediapipe + opencv in the deliberately-NOT-"
            "bundled list (~110 MB for an experimental feature), and the payload is a "
            "read-only squashfs whose staged Debian python is PEP 668 externally "
            "managed -- so nothing can install them later."
        ),
    ),
    PackageProfile(
        key="flatpak",
        label="the flatpak",
        can_run_camera=False,
        can_add_runtime=False,
        declaration="--device=all",
        declares_camera=False,
        remedy="pipx install 'yazses[gaze]'   # a flatpak cannot add a library at runtime",
        why=(
            "packaging/flatpak/python3-yazses.json pins the exact wheel set installed "
            "into the sandbox and neither camera package is in it. finish-args grants "
            "--device=input for the hotkey and no camera device."
        ),
    ),
)

_BY_KEY = {p.key: p for p in PACKAGE_PROFILES}


def profile_for(key: str) -> PackageProfile:
    """The row for *key*, or the conservative one when the key is unknown.

    An unrecognised install format falls back to ``source`` rather than raising:
    this is a diagnostic path, and a traceback out of `yazses doctor` because
    somebody invented a new channel would be a worse failure than a slightly
    generic sentence. The fallback is the permissive-looking row on purpose --
    it is the one that still ends in a real OS permission probe, so nothing is
    waved through; only the packaging *pre*-filter is skipped.
    """
    return _BY_KEY.get(key, _BY_KEY["source"])


def profile_key_for(
    *,
    platform_name: str,
    frozen: bool,
    in_snap: bool,
    in_flatpak: bool,
    appx_manifest_present: bool = False,
) -> str:
    """Pure: which row describes an install with these properties.

    Confinement is checked before freezing because a snap or flatpak is the
    stronger constraint -- neither can install a library at runtime whatever the
    payload looks like -- and `platform_name` is a `sys.platform` string, per the
    note on ``yazses.platform.base``'s name constants.
    """
    if in_snap:
        return "snap"
    if in_flatpak:
        return "flatpak"
    if frozen:
        if platform_name == "darwin":
            return "macos-app"
        if platform_name == "win32":
            return "windows-msix" if appx_manifest_present else "windows-exe"
    return "source"


def detect_profile_key(env: dict[str, str] | None = None) -> str:
    """Gather the facts :func:`profile_key_for` needs from this process.

    The only impure function in the module, and it reads process state rather
    than probing anything. ``YAZSES_PACKAGE_FORMAT`` overrides the detection so
    a maintainer can see what another channel's users would see -- and so the
    tests can exercise a row without building its package.
    """
    environ = os.environ if env is None else env
    override = environ.get("YAZSES_PACKAGE_FORMAT", "").strip()
    if override in _BY_KEY:
        return override

    # `system.snap.in_snap` rather than a second reading of the same two
    # variables: a hand-written copy of an existing predicate is this project's
    # most-repeated defect, and the two would answer differently the first time
    # snapd set only one of them.
    from yazses.system.snap import in_snap

    frozen = bool(getattr(sys, "frozen", False))
    appx = False
    if frozen and sys.platform == "win32":
        from pathlib import Path

        try:
            appx = (Path(sys.executable).resolve().parent / "AppxManifest.xml").is_file()
        except OSError:  # pragma: no cover - defensive
            appx = False
    return profile_key_for(
        platform_name=sys.platform,
        frozen=frozen,
        in_snap=in_snap(environ),
        in_flatpak=bool(environ.get("FLATPAK_ID")) or os.path.isfile("/.flatpak-info"),
        appx_manifest_present=appx,
    )


def current_profile(env: dict[str, str] | None = None) -> PackageProfile:
    """The row describing the install this process is running from."""
    return profile_for(detect_profile_key(env))
