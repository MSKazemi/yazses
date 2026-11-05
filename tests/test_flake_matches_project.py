"""`flake.nix` must describe the same package as `pyproject.toml`.

The flake carries a hand-written copy of two facts, the release `version` and the base
dependency list. Nothing compared them: `tests/test_packaging_manifest_versions.py` scans
`packaging/` only, so the flake sat at 2.18.2 while the project moved to 2.48.1, and its
dependency list still named `onnx-asr` (the deliberately optional `parakeet` extra) while
omitting `av` and `jeepney`. The flake's own header records the same drift once before,
at 2.17.0.

Because `src = ./.`, the flake builds the working tree, so the version string needs no
fetch hash and can simply be compared.

This is a text comparison. There is no Nix on the authoring machine, so it does NOT show
that the flake evaluates or builds (its header says it is not yet building); it only keeps
the two copies of the facts from drifting apart.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# PyPI distribution name (normalised) -> nixpkgs python attribute. Explicit on purpose:
# a dependency added to pyproject must be given a Nix name here, so the guard cannot go
# green on a name it does not understand.
PYPI_TO_NIX = {
    "faster-whisper": "faster-whisper",
    "av": "av",
    "sounddevice": "sounddevice",
    "numpy": "numpy",
    "typer": "typer",
    "platformdirs": "platformdirs",
    "cryptography": "cryptography",
    "evdev": "evdev",
    "jeepney": "jeepney",
    "python-xlib": "python-xlib",
}

# Declared in pyproject.toml as extras, never base dependencies.
OPTIONAL_EXTRAS_NEVER_IN_BASE = ("onnx-asr",)

_LINUX_ENV = {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pyproject_version(text: str) -> str:
    return str(tomllib.loads(text)["project"]["version"])


def _applies_on_linux(marker: str) -> bool:
    """Evaluate the only marker shape pyproject uses: `var == "x" or var == "y" ...`.

    Hand-rolled because `packaging` is not a declared test dependency (and
    `tests/test_test_dependencies_are_declared.py` rightly refuses an undeclared import).
    Anything outside that shape raises, so a new marker form cannot pass unread.
    """
    for clause in marker.split(" or "):
        match = re.fullmatch(r'\s*(\w+)\s*==\s*"([^"]+)"\s*', clause)
        if not match or match.group(1) not in _LINUX_ENV:
            raise AssertionError(f"extend _applies_on_linux for the marker clause {clause!r}")
        if _LINUX_ENV[match.group(1)] == match.group(2):
            return True
    return False


def pyproject_linux_base_dependencies(text: str) -> set[str]:
    """Normalised names of base dependencies whose marker holds on Linux."""
    names = set()
    for spec in tomllib.loads(text)["project"]["dependencies"]:
        requirement, _, marker = spec.partition(";")
        if marker and not _applies_on_linux(marker):
            continue
        name = re.match(r"[A-Za-z0-9._-]+", requirement.strip())
        assert name, f"unparseable dependency {spec!r}"
        names.add(_norm(name.group(0)))
    return names


def flake_version(text: str) -> str:
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*;', text, re.M)
    assert match, 'flake.nix no longer declares `version = "...";`'
    return match.group(1)


def _list_items(body: str) -> list[str]:
    """Words of a Nix list body, with `#` comments removed."""
    return [w for line in body.splitlines() for w in line.split("#", 1)[0].split()]


def flake_base_dependencies(text: str) -> set[str]:
    """Names in the `dependencies = with python.pkgs; [...]` list and its Linux tail."""
    head = re.search(r"^\s*dependencies\s*=\s*with python\.pkgs;\s*\[", text, re.M)
    assert head, "flake.nix no longer declares `dependencies = with python.pkgs; [`"
    first_end = text.index("]", head.end())
    names = _list_items(text[head.end():first_end])
    tail = re.match(
        r"\s*\+\+\s*pkgs\.lib\.optionals\s+pkgs\.stdenv\.hostPlatform\.isLinux\s*\[",
        text[first_end + 1:],
    )
    if tail:
        start = first_end + 1 + tail.end()
        names += _list_items(text[start:text.index("]", start)])
    return {_norm(n) for n in names}


def problems(flake_text: str, pyproject_text: str) -> list[str]:
    found = []
    want, have = pyproject_version(pyproject_text), flake_version(flake_text)
    if want != have:
        found.append(f"flake.nix version is {have!r}; pyproject.toml is {want!r}")

    expected = set()
    for pypi in sorted(pyproject_linux_base_dependencies(pyproject_text)):
        if pypi not in PYPI_TO_NIX:
            found.append(f"pyproject dependency {pypi!r} has no entry in PYPI_TO_NIX")
        else:
            expected.add(PYPI_TO_NIX[pypi])
    actual = flake_base_dependencies(flake_text)
    for name in sorted(expected - actual):
        found.append(f"flake.nix dependencies lack {name!r} (a pyproject base dependency)")
    for name in sorted(actual - expected):
        found.append(f"flake.nix dependencies list {name!r}, not a pyproject base dependency")
    for name in OPTIONAL_EXTRAS_NEVER_IN_BASE:
        if name in actual:
            found.append(f"{name} is an optional extra and must not be a flake base dependency")
    return found


@pytest.fixture(scope="module")
def real() -> tuple[str, str]:
    return (
        (ROOT / "flake.nix").read_text(encoding="utf-8"),
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
    )


def test_flake_version_equals_project_version(real: tuple[str, str]) -> None:
    flake, project = real
    assert flake_version(flake) == pyproject_version(project)


def test_flake_dependencies_cover_every_linux_base_dependency(real: tuple[str, str]) -> None:
    flake, project = real
    linux = pyproject_linux_base_dependencies(project)
    unknown = linux - set(PYPI_TO_NIX)
    assert not unknown, f"add a nixpkgs name to PYPI_TO_NIX for: {sorted(unknown)}"
    missing = {PYPI_TO_NIX[n] for n in linux} - flake_base_dependencies(flake)
    assert not missing, f"flake.nix dependencies lack: {sorted(missing)}"


def test_onnx_asr_is_not_a_flake_base_dependency(real: tuple[str, str]) -> None:
    flake, _ = real
    assert not set(OPTIONAL_EXTRAS_NEVER_IN_BASE) & flake_base_dependencies(flake)


def test_the_real_flake_has_no_problems(real: tuple[str, str]) -> None:
    flake, project = real
    assert problems(flake, project) == []


def test_a_stale_flake_is_caught(real: tuple[str, str], tmp_path: Path) -> None:
    """The guard must fail on the exact drift it exists for, not only pass on the real tree."""
    _, project = real
    stale = tmp_path / "flake.nix"
    stale.write_text(
        """{
  outputs = { self }: let
    yazses = python.pkgs.buildPythonApplication rec {
      pname = "yazses";
      version = "2.18.2";
      dependencies = with python.pkgs; [
        faster-whisper
        sounddevice
        numpy
        typer
        platformdirs
        cryptography
        onnx-asr
      ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
        evdev
        python-xlib
      ];
    };
  in { };
}
""",
        encoding="utf-8",
    )
    joined = "\n".join(problems(stale.read_text(encoding="utf-8"), project))
    assert "'2.18.2'" in joined
    assert "lack 'av'" in joined
    assert "lack 'jeepney'" in joined
    assert "onnx-asr" in joined


def test_an_unknown_pypi_dependency_fails_loudly(real: tuple[str, str]) -> None:
    flake, project = real
    extended = project.replace(
        '"platformdirs>=4.10.0",', '"platformdirs>=4.10.0",\n    "brand-new-dep>=1",', 1
    )
    assert any("brand-new-dep" in p for p in problems(flake, extended))
