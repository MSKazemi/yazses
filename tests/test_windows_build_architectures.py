"""The Windows installer builds one artifact per architecture, named consistently.

The target architecture used to be hardcoded in **three** places that had to
agree and were never checked together: the Inno Setup `OutputBaseFilename`, the
`$Out` path `build-windows.ps1` verifies after running ISCC, and the globs in the
workflow that locate, upload and attach the result. A change to any one of them
fails the build at a different, later step than the edit — or worse, publishes a
file under a name nothing downstream looks for.

Same shape as the snap and .deb architecture gaps: a declaration and the thing
that fulfils it living in separate files with nothing comparing them. These tests
are that comparison for the Windows path.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "build-windows.yml"
SCRIPT = ROOT / "scripts" / "build-windows.ps1"
ISS = ROOT / "packaging" / "windows" / "installer.iss"

EXPECTED_RUNNERS = {"x64": "windows-latest", "arm64": "windows-11-arm"}


def _matrix_arches() -> set[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*-\s*arch:\s*([A-Za-z0-9_-]+)\s*$", text, re.M))


def test_both_architectures_are_built() -> None:
    assert _matrix_arches() == {"x64", "arm64"}, (
        "Windows on ARM is a real desktop target; an x64-only matrix means ARM "
        "users never get a native installer"
    )


@pytest.mark.parametrize("arch", sorted(EXPECTED_RUNNERS))
def test_each_arch_uses_a_native_runner(arch: str) -> None:
    """PyInstaller does not cross-compile, so the runner label *is* the target
    architecture. A wrong label silently produces a second x64 installer under an
    arm64 name — worse than not building it."""
    block = re.search(rf"-\s*arch:\s*{arch}\s*\n\s*runner:\s*(\S+)", WORKFLOW.read_text(encoding="utf-8"))
    assert block, f"no matrix entry for {arch}"
    assert block.group(1) == EXPECTED_RUNNERS[arch]


def test_matrix_does_not_fail_fast() -> None:
    """A failing arm64 build must not cancel x64 and lose a release that was
    otherwise fine."""
    assert re.search(r"fail-fast:\s*false", WORKFLOW.read_text(encoding="utf-8"))


def test_nothing_hardcodes_windows_x64_in_the_workflow() -> None:
    """Every glob must follow the matrix. A leftover literal `windows-x64` makes
    the arm64 job build an installer and then fail to find it."""
    stray = [
        line.strip()
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "windows-x64" in line
    ]
    assert not stray, f"hardcoded x64 in the workflow: {stray}"


def test_build_script_derives_arch_from_the_host() -> None:
    """The script must not take the architecture on faith. It also has to consult
    PROCESSOR_ARCHITEW6432: under x86 emulation Windows reports the emulated arch
    in PROCESSOR_ARCHITECTURE, so reading only that mislabels the build."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "PROCESSOR_ARCHITEW6432" in text, "emulated builds would be mislabelled"
    assert "PROCESSOR_ARCHITECTURE" in text
    assert "YAZSES_ARCH" in text, "the arch must reach Inno Setup"
    assert not re.search(r'\$Out\s*=\s*"dist\\YazSes-\$Version-windows-x64\.exe"', text), (
        "the output path still hardcodes x64"
    )


def test_installer_iss_takes_the_arch_from_the_environment() -> None:
    """Same mechanism the version already uses, so the two cannot diverge in
    style, and a hand-run ISCC still defaults to x64."""
    text = ISS.read_text(encoding="utf-8")
    assert "GetEnv('YAZSES_ARCH')" in text
    assert "OutputBaseFilename=YazSes-{#MyAppVersion}-windows-{#MyAppArch}" in text, (
        "the installer filename must follow the arch, or the workflow glob misses it"
    )
    assert re.search(r'#if\s+MyAppArch\s*==\s*""', text), "a bare ISCC run must still default"


def test_arm64_installer_refuses_to_install_on_x64() -> None:
    """The arm64 payload is native ARM64 and would not run on x64. Note the
    converse is deliberate: x64compatible *includes* arm64, so the x64 installer
    stays usable on an ARM machine under emulation as the fallback."""
    text = ISS.read_text(encoding="utf-8")
    assert re.search(r'#if\s+MyAppArch\s*==\s*"arm64"', text)
    assert "ArchitecturesAllowed=arm64" in text
    assert "ArchitecturesAllowed=x64compatible" in text, "the x64 build must keep emulation support"


def test_signing_and_artifact_names_are_arch_qualified() -> None:
    """Two matrix jobs uploading one artifact name collide and the second fails,
    taking its release attachment with it."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for name in re.findall(r"^\s*name:\s*(unsigned-installer.+|yazses-windows.+)$", text, re.M):
        assert "matrix.arch" in name, f"artifact name {name!r} is not arch-qualified"
