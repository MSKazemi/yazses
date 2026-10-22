"""The .app's LSMinimumSystemVersion must not promise a macOS its own libraries refuse.

For years the bundle declared macOS 11, and so did the cask and the docs. But the arm64
`.dmg` carried PyAV and onnxruntime built for macOS 14, and `import faster_whisper`
imports PyAV at module load, so on macOS 11-13 the app could not have dictated at all.
Nothing checked it. A Mac on an older release was the only thing that could have
noticed, and none had reported.

This test re-derives the floor from what a build actually installs. The macOS build
runs `uv sync --no-dev` on a macOS 15 runner, for Python 3.12 (build-macos.yml). For
each package on the dictation path, the base dependencies resolved for darwin, uv
picks the most specific compatible wheel: the one with the highest macOS platform tag
the runner accepts. The bundle's floor is the highest of those. If a dependency bump
raises it past MIN_MACOS in packaging/macos/yazses.spec, this fails and names the
package.

A wheel tag is a lower bound, not the whole truth. shiboken6's binaries declare macOS
15.0 in their Mach-O LC_BUILD_VERSION while its wheel is tagged 13.0. Qt is an
optional extra (Settings window, overlay) and is deliberately outside this check;
see the comment beside MIN_MACOS.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

# `packaging` arrives transitively, not as a declared dev dependency, and the FreeBSD
# job does not install it; skip there rather than fail collection.
Marker = pytest.importorskip("packaging.markers").Marker

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "uv.lock"
SPEC = ROOT / "packaging" / "macos" / "yazses.spec"

#: Both build runners (build-macos.yml: macos-latest and macos-15-intel) run macOS 15,
#: so uv accepts wheels tagged up to 15.0.
RUNNER_MACOS = (15, 0)
BUILD_PYTHON = (3, 12)
ARCH_TAGS = {"arm64": ("arm64", "universal2"), "x86_64": ("x86_64", "universal2", "intel")}
_PLAT = re.compile(r"macosx_(\d+)_(\d+)_(\w+)")


def _env(arch: str) -> dict[str, str]:
    return {
        "sys_platform": "darwin",
        "platform_system": "Darwin",
        "os_name": "posix",
        "platform_machine": arch,
        "python_version": f"{BUILD_PYTHON[0]}.{BUILD_PYTHON[1]}",
        "python_full_version": f"{BUILD_PYTHON[0]}.{BUILD_PYTHON[1]}.0",
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
        "extra": "",
    }


def _python_ok(tag: str) -> bool:
    """Whether a wheel's python/abi tag installs on CPython BUILD_PYTHON."""
    py, abi = tag.split("-")[0], tag.split("-")[1]
    major, minor = BUILD_PYTHON
    if py.startswith("py3") or py == "py2.py3":
        return True
    for p in py.split("."):
        m = re.fullmatch(r"cp(\d)(\d+)", p)
        if not m:
            continue
        v = (int(m.group(1)), int(m.group(2)))
        if abi == "abi3" and v <= (major, minor):
            return True
        if v == (major, minor) and abi in (f"cp{major}{minor}", "none"):
            return True
    return False


def _chosen_macos(wheels: list[dict], arch: str) -> tuple[tuple[int, int], str] | None:
    """The macOS tag uv installs for this package on the runner, or None for a pure wheel."""
    best = None
    pure = False
    for w in wheels:
        name = w["url"].rsplit("/", 1)[-1][: -len(".whl")]
        parts = name.split("-")
        py_abi, plat = f"{parts[-3]}-{parts[-2]}", parts[-1]
        if not _python_ok(py_abi):
            continue
        if plat == "any":
            pure = True
            continue
        for p in plat.split("."):
            m = _PLAT.fullmatch(p)
            if not m or m.group(3) not in ARCH_TAGS[arch]:
                continue
            v = (int(m.group(1)), int(m.group(2)))
            if v <= RUNNER_MACOS and (best is None or v > best[0]):
                best = (v, name)
    if best is None and pure:
        return None
    return best if best else ((0, 0), "no compatible wheel")


def _dictation_path(lock: dict, arch: str) -> dict[str, dict]:
    """Packages reachable from yazses's base dependencies (no extras) on darwin/arch."""
    by_name: dict[str, list[dict]] = {}
    for p in lock["package"]:
        by_name.setdefault(p["name"], []).append(p)
    env = _env(arch)
    seen: dict[str, dict] = {}
    stack = [d for d in by_name["yazses"][0].get("dependencies", [])]
    while stack:
        dep = stack.pop()
        if "marker" in dep and not Marker(dep["marker"]).evaluate(env):
            continue
        candidates = by_name[dep["name"]]
        if "version" in dep:
            candidates = [c for c in candidates if c["version"] == dep["version"]]
        if len(candidates) > 1:
            # Several versions in the lock: keep the one whose resolution markers
            # match this environment.
            fitting = [
                c for c in candidates
                if not c.get("resolution-markers")
                or any(Marker(m).evaluate(env) for m in c["resolution-markers"])
            ]
            candidates = fitting or candidates
        pkg = candidates[0]
        key = f"{pkg['name']}=={pkg['version']}"
        if key in seen:
            continue
        seen[key] = pkg
        stack.extend(pkg.get("dependencies", []))
    return seen


def _spec_minimum(arch: str) -> tuple[int, int]:
    text = SPEC.read_text(encoding="utf-8")
    m = re.search(rf'MIN_MACOS\s*=\s*\{{[^}}]*"{arch}":\s*"(\d+)\.(\d+)"', text)
    assert m, f"MIN_MACOS[{arch!r}] not found in {SPEC}"
    return int(m.group(1)), int(m.group(2))


def bundle_floor(arch: str) -> tuple[tuple[int, int], list[str]]:
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    floor, why = (0, 0), []
    for key, pkg in _dictation_path(lock, arch).items():
        chosen = _chosen_macos(pkg.get("wheels", []), arch)
        if chosen is None:
            continue
        version, wheel = chosen
        if version > floor:
            floor, why = version, [f"{key} ({wheel})"]
        elif version == floor:
            why.append(f"{key} ({wheel})")
    return floor, why


def test_the_walk_reaches_the_speech_engine():
    """A graph walk that silently stops early would report a comfortably low floor."""
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    names = {k.split("==")[0] for k in _dictation_path(lock, "arm64")}
    for required in ("faster-whisper", "ctranslate2", "av", "onnxruntime", "numpy"):
        assert required in names, f"{required} missing from the darwin dictation path"
    assert "evdev" not in names, "a linux-only dependency leaked into the darwin walk"


def test_arm64_minimum_covers_the_bundled_wheels():
    floor, why = bundle_floor("arm64")
    declared = _spec_minimum("arm64")
    assert floor <= declared, (
        f"the arm64 bundle installs wheels built for macOS {floor[0]}.{floor[1]} "
        f"but declares {declared[0]}.{declared[1]}: {why}"
    )


def test_x86_64_minimum_covers_the_bundled_wheels():
    floor, why = bundle_floor("x86_64")
    declared = _spec_minimum("x86_64")
    assert floor <= declared, (
        f"the x86_64 bundle installs wheels built for macOS {floor[0]}.{floor[1]} "
        f"but declares {declared[0]}.{declared[1]}: {why}"
    )


def test_the_declared_minimum_is_not_padded():
    """The floor is a promise in both directions: no higher than the wheels need."""
    for arch in ("arm64", "x86_64"):
        floor, why = bundle_floor(arch)
        assert _spec_minimum(arch) == floor, (
            f"{arch}: declares {_spec_minimum(arch)} but the wheels need only {floor} ({why[:3]})"
        )
