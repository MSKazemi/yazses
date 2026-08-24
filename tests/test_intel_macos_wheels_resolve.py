"""Every platform this project claims to support must have an installable wheel.

`onnxruntime` stopped publishing an Intel macOS wheel after **1.23.2** -- 1.24 through
1.28 are `macosx_14_0_arm64` only. Three optional extras (`tts`, `silero`, `all`) pinned
`>=1.27.0`, and `useful-moonshine-onnx`, `onnx-asr` and `kokoro-onnx` all depend on
`onnxruntime` with no marker at all, so a single version was resolved for every platform
and it was the newest one. On an Intel Mac that is not a slower path or an older feature
set -- it is `uv`/`pip` refusing to install with "no source distribution or wheel for the
current platform", which reads like a broken package rather than a dropped platform.

It went unnoticed because nothing installs on that platform in CI except the
`macOS x86_64 (Intel)` leg of `benchmark.yml`, which is `experimental: true` and had
never once produced a number. The failure is not visible from any machine a maintainer
is likely to be sitting at.

These tests read `uv.lock` and PyPI metadata already embedded in it -- no network, no
macOS -- and they check the *lock*, because the lock is what a user resolves against and
what any "always take the latest stable" bump would quietly rewrite.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "uv.lock"
PYPROJECT = ROOT / "pyproject.toml"

#: Distributions that must remain installable on Intel macOS. Everything here is
#: reachable from an extra a user can enable, so an unresolvable one is a dead feature
#: on that platform rather than a maintainer inconvenience.
INTEL_MACOS_CRITICAL = ("onnxruntime",)

INTEL_MARKER = "platform_machine == 'x86_64' and sys_platform == 'darwin'"


def _packages(name: str) -> list[tuple[str, str]]:
    """(version, body) for every locked entry of `name`. More than one means a fork."""
    text = LOCK.read_text(encoding="utf-8")
    pattern = (
        rf'\[\[package\]\]\nname = "{re.escape(name)}"\nversion = "([^"]+)"'
        r"(.*?)(?=\n\[\[package\]\]|\Z)"
    )
    return [(m.group(1), m.group(2)) for m in re.finditer(pattern, text, re.S)]


def _wheel_tags(body: str, name: str) -> set[str]:
    stem = name.replace("-", "_")
    return {w.removesuffix(".whl").split("-")[-1]
            for w in re.findall(rf"{stem}-[^\"/]+\.whl", body)}


def _is_intel_macos(tag: str) -> bool:
    return "macosx" in tag and ("x86_64" in tag or "universal2" in tag or "intel" in tag)


@pytest.mark.parametrize("name", INTEL_MACOS_CRITICAL)
def test_the_lock_forks_for_intel_macos(name: str) -> None:
    """The fork must *exist*. A guard that only checks the forks it finds passes
    trivially the moment the fork disappears -- which is exactly how this regresses."""
    entries = _packages(name)
    assert entries, f"{name} is not in uv.lock at all"
    assert len(entries) > 1, (
        f"{name} is locked at a single version ({entries[0][0]}) for every platform. "
        "Intel macOS needs its own resolution; see [tool.uv] constraint-dependencies."
    )


@pytest.mark.parametrize("name", INTEL_MACOS_CRITICAL)
def test_one_locked_version_has_an_intel_macos_wheel(name: str) -> None:
    ok = {v: sorted(t for t in _wheel_tags(b, name) if _is_intel_macos(t))
          for v, b in _packages(name)}
    have = {v: tags for v, tags in ok.items() if tags}
    assert have, (
        f"no locked version of {name} ships an Intel macOS wheel. Locked versions and "
        f"their macOS tags: "
        + ", ".join(f"{v}={sorted(t for t in _wheel_tags(b, name) if 'macos' in t)}"
                    for v, b in _packages(name))
    )


@pytest.mark.parametrize("name", INTEL_MACOS_CRITICAL)
def test_the_intel_fork_is_the_one_selected_on_intel_macos(name: str) -> None:
    """It is not enough that *some* locked version has the wheel: the marker that
    selects a version on Intel macOS has to select that one."""
    text = LOCK.read_text(encoding="utf-8")
    # Matched line-wise: a dependency entry is one line, and `source = { registry = ... }`
    # sits between the version and the marker, so a `[^}]*` bridge cannot cross it.
    selected = {
        m.group(1)
        for line in text.splitlines()
        if (m := re.search(
            rf'name = "{re.escape(name)}", version = "([^"]+)"', line))
        and INTEL_MARKER in line
    }
    assert selected, (
        f"nothing in uv.lock selects a version of {name} under the Intel macOS marker; "
        "the fork exists but no dependent uses it"
    )
    assert len(selected) == 1, f"Intel macOS selects more than one {name}: {selected}"
    version = selected.pop()
    body = dict(_packages(name))[version]
    tags = sorted(t for t in _wheel_tags(body, name) if _is_intel_macos(t))
    assert tags, (
        f"Intel macOS resolves {name}=={version}, which ships no x86_64 macOS wheel "
        f"(macOS tags: {sorted(t for t in _wheel_tags(body, name) if 'macos' in t)}). "
        "Tighten the [tool.uv] constraint to the last version that has one."
    )


def test_no_extra_floors_onnxruntime_above_the_intel_ceiling() -> None:
    """A `>=` floor in an extra overrides the constraint and makes the extra
    uninstallable on Intel macOS -- the original bug, in three extras at once."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    offenders = []
    for extra, deps in data["project"].get("optional-dependencies", {}).items():
        for dep in deps:
            if not dep.startswith("onnxruntime"):
                continue
            spec, _, marker = dep.partition(";")
            if ">=1.2" in spec and "1.23" not in spec and "x86_64" not in marker:
                offenders.append((extra, dep))
    assert not offenders, (
        "these extras floor onnxruntime above the last Intel macOS release without "
        f"excluding that platform: {offenders}"
    )
