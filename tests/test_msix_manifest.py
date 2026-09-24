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

# Store tile names carry the dimensions the tile must have: Square150x150Logo, and the
# one non-square tile, Wide310x150Logo. Derived from the name rather than listed here,
# so a tile added later is covered without anyone remembering to add it.
SIZED_LOGO = re.compile(r"(?:Square|Wide)(\d+)x(\d+)Logo\.png$")


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

    Glance-Type gaze is implemented and works on a normal install when its optional
    dependencies are enabled. Face-Gesture is planned/experimental and does not yet have
    a runtime detector or activation adapter. This frozen package carries no optional gaze
    dependencies, so neither feature provides a reachable camera path here.
    """
    devices = [c.get("Name") for c in manifest.findall("d:Capabilities/d:DeviceCapability", NS)]
    assert "microphone" in devices, f"microphone capability missing; got {devices}"
    assert "webcam" not in devices, (
        "webcam is declared, but this frozen bundle carries no optional gaze dependencies "
        "and Face-Gesture has no reachable runtime implementation, so no camera path is "
        "available here; an unused capability is a certification question with no upside"
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


def test_the_wide_tile_is_declared_whenever_the_large_tile_is(manifest: ET.Element) -> None:
    """makeappx refuses the pair Square310x310Logo-without-Wide310x150Logo.

    Its words: "The DefaultTile element must specify the Wide310x150Logo attribute if
    the Square310x310Logo attribute is specified." Declaring the large tile obliges the
    wide one. That is a packaging-time error, so it cost a Windows CI run to find — but
    it is a relationship between two attributes of this file, and once known it is
    checkable here in milliseconds on any OS. The msix-validate job stays the authority
    on what makeappx accepts; this only stops a rule it already taught us from being
    unlearned off Windows.
    """
    tile = manifest.find(
        "d:Applications/d:Application/uap:VisualElements/uap:DefaultTile", NS
    )
    assert tile is not None, "no uap:DefaultTile element"
    assert tile.get("Square310x310Logo"), (
        "DefaultTile no longer declares Square310x310Logo. Dropping the large tile is a "
        "legitimate choice, but it also makes the rule below unexercised — remove this "
        "test with it rather than leaving a guard that cannot fail."
    )
    assert tile.get("Wide310x150Logo"), (
        "DefaultTile declares Square310x310Logo but not Wide310x150Logo. makeappx "
        "refuses to pack that combination, and only the Windows job would say so."
    )


def test_logos_are_the_size_their_name_claims() -> None:
    """A Square150x150Logo that is not 150x150 fails certification, and so does a
    Wide310x150Logo that is square.

    The names checked are the union of what sits in `Assets/` and what the manifest
    names, so neither a tile the generator has not started drawing nor one the manifest
    has not started naming can slip through the gap between the two.

    Dimensions are read from the IHDR header with stdlib struct — never by comparing
    bytes. Pillow is absent on the FreeBSD leg, and PNG bytes are not reproducible
    across platforms anyway; `scripts/gen-icons.py` learned that when a byte comparison
    turned the Windows and macOS legs red on assets that were pixel-perfect.
    """
    raw = MANIFEST.read_text(encoding="utf-8")
    names = {p.name for p in ASSETS.glob("*.png")}
    names |= set(re.findall(r"Assets\\([A-Za-z0-9]+\.png)", raw))
    sized = [(n, m) for n in sorted(names) if (m := SIZED_LOGO.match(n))]
    assert sized, f"no logo name in {sorted(names)} encodes the size it must be"

    for name, m in sized:
        path = ASSETS / name
        assert path.is_file(), f"{name} is named but missing from Assets/. Run `make icons`."
        head = path.read_bytes()[:24]
        assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG"
        assert head[12:16] == b"IHDR", f"{name}: first chunk is not IHDR"
        width, height = struct.unpack(">II", head[16:24])
        assert (width, height) == (int(m.group(1)), int(m.group(2))), (
            f"{name} is {width}x{height}, but its name claims "
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
