"""No install of YazSes may contain two OpenCV distributions.

OpenCV ships on PyPI as four separate distributions -- `opencv-python`,
`opencv-contrib-python`, and a `-headless` build of each -- and all four install the
same top-level `cv2/` package. pip and uv do not treat them as alternatives: put two in
one closure and both install, each overwriting the other's files, so `cv2` belongs to
whichever happened to install last. Uninstalling either one later deletes files the
other still needs.

That is exactly what the `gaze` extra did until 2.43.x. It declared `opencv-python`,
while `mediapipe` (which the same extra installs) requires `opencv-contrib-python`.
Every eye-control install therefore carried both: about 70 MB twice, and a `cv2`
whose build depended on install order. Nothing noticed, because nothing compared one
dependency's requirement with another's.

So this guard reads `uv.lock` -- what `uv sync` and the packs build actually install --
and walks the resolved closure of every extra and every dependency group, per target
platform, evaluating each lock marker. It names no package YazSes depends on and no
extra: a new extra, or a library that starts requiring a different OpenCV build, is
covered the moment the lock records it.
"""
from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "uv.lock"

#: Every PyPI distribution that installs the top-level `cv2` package. They are
#: mutually exclusive: at most one may be present in any one environment.
OPENCV_DISTRIBUTIONS = frozenset({
    "opencv-python",
    "opencv-contrib-python",
    "opencv-python-headless",
    "opencv-contrib-python-headless",
})

#: The platforms a release targets (see the packaging matrix and the CI legs). The
#: lock's markers fork on these axes, so a closure is only meaningful per platform:
#: a build that appears on Windows and another that appears on Linux never meet.
_PLATFORMS: dict[str, dict[str, str]] = {
    "linux-x86_64": {"sys_platform": "linux", "platform_system": "Linux",
                     "platform_machine": "x86_64", "os_name": "posix"},
    "linux-aarch64": {"sys_platform": "linux", "platform_system": "Linux",
                      "platform_machine": "aarch64", "os_name": "posix"},
    "macos-arm64": {"sys_platform": "darwin", "platform_system": "Darwin",
                    "platform_machine": "arm64", "os_name": "posix"},
    "macos-x86_64": {"sys_platform": "darwin", "platform_system": "Darwin",
                     "platform_machine": "x86_64", "os_name": "posix"},
    "windows-amd64": {"sys_platform": "win32", "platform_system": "Windows",
                      "platform_machine": "AMD64", "os_name": "nt"},
    "windows-arm64": {"sys_platform": "win32", "platform_system": "Windows",
                      "platform_machine": "ARM64", "os_name": "nt"},
}
_PYTHONS = ("3.11.9", "3.12.8", "3.13.1", "3.14.0")


def _environments() -> list[tuple[str, dict[str, str]]]:
    out = []
    for platform, env in _PLATFORMS.items():
        for full in _PYTHONS:
            out.append((f"{platform}-py{full}", {
                **env,
                "python_version": ".".join(full.split(".")[:2]),
                "python_full_version": full,
                "implementation_name": "cpython",
                "platform_python_implementation": "CPython",
                "extra": "",
            }))
    return out


def canonicalize_name(name: str) -> str:
    """PEP 503 normalisation, so `Opencv_Python` and `opencv-python` are one name."""
    return re.sub(r"[-_.]+", "-", name).lower()


@lru_cache(maxsize=None)
def _marker(text: str) -> Any:
    # Imported here, not at module scope: `packaging` reaches the dev environment only
    # through pytest, and the module-scope import guards (FreeBSD set, declared test
    # imports) hold every top-level import to a declared dependency.
    from packaging.markers import Marker  # noqa: PLC0415

    return Marker(text)


def _applies(marker: str | None, env: Mapping[str, str]) -> bool:
    return marker is None or bool(_marker(marker).evaluate(dict(env)))


class LockGraph:
    """The resolved dependency graph recorded in a `uv.lock` (format version 1)."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        self._by_name: dict[str, list[Mapping[str, Any]]] = {}
        for pkg in data.get("package", []):
            self._by_name.setdefault(canonicalize_name(pkg["name"]), []).append(pkg)
        roots = [p for pkgs in self._by_name.values() for p in pkgs
                 if p.get("source", {}).get("editable") == "."
                 or p.get("source", {}).get("virtual") == "."]
        if len(roots) != 1:
            raise ValueError(f"expected exactly one project root in the lock, found {len(roots)}")
        self.root = roots[0]

    @classmethod
    def load(cls, path: Path) -> LockGraph:
        return cls(tomllib.loads(path.read_text(encoding="utf-8")))

    @property
    def extras(self) -> list[str]:
        return sorted(self.root.get("optional-dependencies", {}))

    @property
    def groups(self) -> list[str]:
        return sorted(self.root.get("dev-dependencies", {}))

    def _resolve(self, dep: Mapping[str, Any]) -> Mapping[str, Any]:
        candidates = self._by_name.get(canonicalize_name(dep["name"]), [])
        if "version" in dep:
            candidates = [p for p in candidates if p.get("version") == dep["version"]]
        if len(candidates) != 1:
            # An unresolvable edge must fail loudly: skipping it would make the walk
            # report a smaller closure than uv installs, and a smaller closure is
            # exactly where a duplicate would go unseen.
            raise ValueError(f"cannot resolve lock edge {dict(dep)}: {len(candidates)} candidates")
        return candidates[0]

    def closure(self, env: Mapping[str, str], *, extras: Iterable[str] = (),
                groups: Iterable[str] = ()) -> set[str]:
        """Distributions installed for the project with `extras` and `groups` on `env`.

        Mirrors `uv sync --extra ... --group ...`: the project's own dependencies,
        plus each requested extra and group, followed transitively, with every
        package's own extras (`dep[extra]`) honoured and each marker evaluated.
        """
        root = self.root
        edges: list[Mapping[str, Any]] = list(root.get("dependencies", []))
        for extra in extras:
            edges += root["optional-dependencies"][extra]
        for group in groups:
            edges += root["dev-dependencies"][group]

        seen: set[tuple[str, str, str]] = set()
        names: set[str] = set()
        stack = [e for e in edges if _applies(e.get("marker"), env)]
        while stack:
            dep = stack.pop()
            pkg = self._resolve(dep)
            requested = [""] + list(dep.get("extra", []))
            for extra in requested:
                key = (pkg["name"], pkg.get("version", ""), extra)
                if key in seen:
                    continue
                seen.add(key)
                names.add(canonicalize_name(pkg["name"]))
                nxt = (pkg.get("dependencies", []) if extra == ""
                       else pkg.get("optional-dependencies", {}).get(extra, []))
                stack += [e for e in nxt if _applies(e.get("marker"), env)]
        return names


def opencv_conflicts(graph: LockGraph) -> list[str]:
    """Every (install set, platform) whose closure holds more than one OpenCV build.

    The install sets are each extra alone, each group alone, and everything at once
    (`uv sync --all-extras --all-groups`). Everything-at-once is a superset of every
    combination a user could ask for, so a clean result there covers them all; the
    per-extra sets only make a failure name its source.
    """
    install_sets: list[tuple[str, list[str], list[str]]] = [
        *((f"extra {e!r}", [e], []) for e in graph.extras),
        *((f"group {g!r}", [], [g]) for g in graph.groups),
        ("all extras and groups", graph.extras, graph.groups),
    ]
    out = []
    for label, extras, groups in install_sets:
        for env_name, env in _environments():
            found = sorted(graph.closure(env, extras=extras, groups=groups) & OPENCV_DISTRIBUTIONS)
            if len(found) > 1:
                out.append(f"{label} on {env_name}: {found}")
    return out


@pytest.fixture(scope="module")
def graph() -> LockGraph:
    return LockGraph.load(LOCK)


def test_no_install_set_holds_two_opencv_distributions(graph: LockGraph) -> None:
    conflicts = opencv_conflicts(graph)
    assert not conflicts, (
        "these install sets contain more than one OpenCV distribution, which all write "
        "the same `cv2/` package -- both install, the last one wins, and removing either "
        "breaks the other. Declare the build the rest of the closure already requires "
        "(mediapipe requires opencv-contrib-python), then `uv lock`:\n  "
        + "\n  ".join(conflicts[:20])
        + (f"\n  ... and {len(conflicts) - 20} more" if len(conflicts) > 20 else "")
    )


def test_the_walk_reaches_opencv_at_all(graph: LockGraph) -> None:
    """Positive control. If the walker silently stopped following edges -- a lock format
    change, a renamed table -- the guard above would pass on empty closures. Some extra
    must still reach an OpenCV build on a mainstream platform, and the full install set
    must be far larger than the base."""
    env = dict(_environments())["linux-x86_64-py3.12.8"]
    everything = graph.closure(env, extras=graph.extras, groups=graph.groups)
    assert everything & OPENCV_DISTRIBUTIONS, "no extra reaches any OpenCV build -- the walk is broken"
    assert len(everything) > 2 * len(graph.closure(env)), "the full closure is implausibly small"


def test_every_declared_extra_is_in_the_lock(graph: LockGraph) -> None:
    """The guard covers the extras the *lock* knows. A pyproject extra missing from it
    means the lock is stale and the guard would be checking yesterday's dependencies."""
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert set(declared["project"]["optional-dependencies"]) == set(graph.extras)


def _synthetic_lock(*, gaze: list[str]) -> dict[str, Any]:
    """The pre-fix shape: an extra naming one OpenCV build beside a library that
    requires another. Built in-test so the checker's own red is permanent."""
    def pkg(name: str, deps: Iterable[str] = ()) -> dict[str, Any]:
        return {"name": name, "version": "1.0", "source": {"registry": "x"},
                "dependencies": [{"name": d} for d in deps]}
    return {"version": 1, "package": [
        {"name": "proj", "version": "0", "source": {"editable": "."},
         "optional-dependencies": {"gaze": [{"name": n} for n in gaze],
                                   "win": [{"name": "opencv-python-headless",
                                            "marker": "sys_platform == 'win32'"}]}},
        pkg("mediapipe", ["opencv-contrib-python"]),
        pkg("opencv-python"), pkg("opencv-contrib-python"), pkg("opencv-python-headless"),
    ]}


def test_the_checker_catches_a_transitive_second_build() -> None:
    bad = LockGraph(_synthetic_lock(gaze=["mediapipe", "opencv-python"]))
    conflicts = opencv_conflicts(bad)
    assert any(c.startswith("extra 'gaze' on linux-x86_64") for c in conflicts), conflicts
    good = LockGraph(_synthetic_lock(gaze=["mediapipe", "opencv-contrib-python"]))
    # `win` adds headless only on Windows, so only the combined set on Windows clashes.
    remaining = opencv_conflicts(good)
    assert remaining and all(c.startswith("all extras and groups on windows-") for c in remaining)
