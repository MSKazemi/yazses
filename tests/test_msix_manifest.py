"""The MSIX package must stay full-trust, and name only logos that exist.

Why these guards exist
----------------------
This package is the Microsoft Store route, and it exists to avoid buying a certificate:
Store policy 10.2.9 demands a Trusted-Root certificate for an EXE/MSI submission, but an
MSIX is signed by Microsoft during certification. That saving is entirely conditional on
the package remaining a *full-trust* app.

If `uap10:TrustLevel` ever becomes `appContainer`, the package still builds, still uploads
and still passes certification -- and then the product silently stops working, because
YazSes needs a global `SetWindowsHookExW` hook, raw microphone capture, and `SendInput`
into other applications' windows. The failure would appear only on a user's machine, as
"the hotkey does nothing". So the trust level is asserted rather than trusted.

The project previously ruled MSIX out on the belief that packaging *forces* AppContainer.
It does not -- AppContainer is opt-in for desktop apps -- and these tests pin the
distinction that the earlier reasoning got wrong.

Deliberately stdlib-only: `xml.etree`, no Pillow, no lxml. The FreeBSD leg installs
neither, and a module-scope import of something absent there is a collection error that
fails the whole run (`tests/test_freebsd_job_can_import_the_suite.py` enforces this).
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MSIX_DIR = ROOT / "packaging" / "windows" / "msix"
MANIFEST = MSIX_DIR / "AppxManifest.xml"
ASSETS = MSIX_DIR / "Assets"
BUILD_SCRIPT = ROOT / "scripts" / "build-msix.ps1"
GEN_ICONS = ROOT / "scripts" / "gen-icons.py"

NS = {
    "d": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
    "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
    "uap10": "http://schemas.microsoft.com/appx/manifest/uap/windows10/10",
    "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities",
}


@pytest.fixture(scope="module")
def manifest() -> ET.Element:
    assert MANIFEST.is_file(), f"{MANIFEST.relative_to(ROOT)} is missing"
    return ET.parse(MANIFEST).getroot()


def test_the_manifest_is_well_formed_xml(manifest: ET.Element) -> None:
    assert manifest.tag.endswith("}Package")


def test_the_app_is_full_trust_and_not_appcontainer(manifest: ET.Element) -> None:
    """The load-bearing assertion. See the module docstring."""
    app = manifest.find("d:Applications/d:Application", NS)
    assert app is not None, "no Application element"
    trust = app.get(f"{{{NS['uap10']}}}TrustLevel")
    assert trust == "mediumIL", (
        f"uap10:TrustLevel is {trust!r}, must be 'mediumIL'. 'appContainer' would build, "
        "upload and certify successfully, then break the global hotkey hook, microphone "
        "capture and keystroke injection on the user's machine."
    )
    behavior = app.get(f"{{{NS['uap10']}}}RuntimeBehavior")
    assert behavior == "packagedClassicApp", f"uap10:RuntimeBehavior is {behavior!r}"


def test_run_full_trust_capability_is_declared(manifest: ET.Element) -> None:
    """mediumIL without runFullTrust is rejected at packaging time, not at runtime."""
    names = [
        c.get("Name")
        for c in manifest.findall(f"d:Capabilities/{{{NS['rescap']}}}Capability", NS)
    ]
    assert "runFullTrust" in names, f"runFullTrust missing; capabilities are {names}"


def test_microphone_is_declared_and_webcam_is_not(manifest: ET.Element) -> None:
    """Microphone is required. Webcam is deliberately absent.

    The gaze and face-gesture features need mediapipe, an optional extra the PyInstaller
    bundle does not ship, so a webcam capability would ask the user and a Store reviewer
    to grant camera access for code that cannot run in this package.
    """
    devices = [c.get("Name") for c in manifest.findall("d:Capabilities/d:DeviceCapability", NS)]
    assert "microphone" in devices, f"microphone capability missing; got {devices}"
    assert "webcam" not in devices, (
        "webcam is declared but the bundle ships no camera-using code; an unused "
        "capability is a certification question with no upside"
    )


def test_the_executable_matches_what_pyinstaller_builds(manifest: ET.Element) -> None:
    """Application/@Executable must be a real name from the PyInstaller spec.

    makeappx does not verify this. A mismatch packages cleanly and fails certification.
    """
    app = manifest.find("d:Applications/d:Application", NS)
    exe = app.get("Executable")
    spec = (ROOT / "packaging" / "windows" / "yazses.spec").read_text(encoding="utf-8")
    stem = exe[:-4] if exe.lower().endswith(".exe") else exe
    assert f'name="{stem}"' in spec, (
        f"manifest runs {exe!r}, which yazses.spec does not build. "
        "The spec's EXE(name=...) values are the only executables in dist/YazSes."
    )


def test_every_logo_the_manifest_names_exists(manifest: ET.Element) -> None:
    raw = MANIFEST.read_text(encoding="utf-8")
    named = sorted(set(re.findall(r"Assets\\([A-Za-z0-9]+\.png)", raw)))
    assert named, "the manifest names no logos at all"
    missing = [n for n in named if not (ASSETS / n).is_file()]
    assert not missing, f"missing from Assets/: {missing}. Run `make icons`."


def test_the_icon_generator_owns_every_logo() -> None:
    """The assets must be generated, not hand-placed.

    `packaging/store/boxart-1080.png` sat on a retired logo for a month precisely because
    it was produced by a pasted command and regenerated by nothing. These tiles are in
    `gen-icons.py` so the next brand change reaches them.
    """
    gen = GEN_ICONS.read_text(encoding="utf-8")
    raw = MANIFEST.read_text(encoding="utf-8")
    for name in sorted(set(re.findall(r"Assets\\([A-Za-z0-9]+\.png)", raw))):
        assert name in gen, (
            f"{name} is named by the manifest but not produced by gen-icons.py, so "
            "nothing redraws it when the brand mark changes"
        )


def test_logos_are_square_and_the_size_their_name_claims() -> None:
    """A Square150x150Logo that is not 150x150 fails certification.

    PNG dimensions are read with stdlib struct so this runs where Pillow is absent.
    """
    for path in sorted(ASSETS.glob("Square*.png")):
        m = re.match(r"Square(\d+)x(\d+)Logo\.png$", path.name)
        assert m, f"unexpected asset name {path.name}"
        head = path.read_bytes()[:24]
        assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
        assert head[12:16] == b"IHDR", f"{path.name}: first chunk is not IHDR"
        width, height = struct.unpack(">II", head[16:24])
        assert (width, height) == (int(m.group(1)), int(m.group(2))), (
            f"{path.name} is {width}x{height}, but its name claims "
            f"{m.group(1)}x{m.group(2)}"
        )


def test_identity_is_a_placeholder_not_an_invented_value(manifest: ET.Element) -> None:
    """Identity comes from Partner Center. A committed guess would be worse than a gap.

    A plausible-looking wrong identity is rejected at submission, after a build that
    looked fine; the placeholder makes the build fail instead.
    """
    identity = manifest.find("d:Identity", NS)
    assert identity is not None
    for attr in ("Name", "Publisher"):
        value = identity.get(attr)
        assert value and value.startswith("__") and value.endswith("__"), (
            f"Identity/@{attr} is {value!r}. It must stay a placeholder: these values "
            "come from Partner Center and are substituted by scripts/build-msix.ps1."
        )


def test_the_build_script_refuses_to_ship_a_placeholder() -> None:
    """The guard that makes the placeholder scheme safe rather than merely tidy."""
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "__[A-Z_]+__" in script, (
        "build-msix.ps1 must scan the substituted manifest for leftover placeholders"
    )
    assert "throw" in script, "the leftover-placeholder check must abort the build"


def test_the_store_revision_field_is_left_to_the_store() -> None:
    """The Store reserves the fourth version component and rejects a package that sets it."""
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert '"$Version.0"' in script, (
        "build-msix.ps1 must append a .0 revision; the Store rejects any other value"
    )


def test_the_package_is_unsigned_on_purpose() -> None:
    """Signing must not creep in.

    A self-signed package installs only where the certificate is already trusted, and the
    Store re-signs during certification, so signing here would add a cost and a false
    sense of completeness. This records the intent next to the code.
    """
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "signtool" not in script.lower(), (
        "build-msix.ps1 signs the package; the Store signs MSIX itself, and avoiding a "
        "purchased certificate is the entire reason this route exists"
    )
