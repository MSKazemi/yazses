"""Which of the 22 extras can actually be installed, on which platform.

The `macOS x86_64 (Intel)` leg of `benchmark.yml` had never produced a number, and the
reason turned out not to be the benchmark: `uv sync` could not resolve the dependencies
at all. That is a whole class of defect the test suite structurally cannot see -- every
test runs on a machine where the install already succeeded -- and it is invisible in CI
too, because a leg that dies in `uv sync` looks like an infrastructure flake.

So resolvability is measured, not assumed. For each extra and each platform this runs
`uv pip compile --python-platform <triple>`, which resolves without downloading or
installing anything, and records whether a solution exists.

Reading a failure correctly
---------------------------
`--python-platform` fixes an architecture *and a minimum OS*: `x86_64-unknown-linux-gnu`
assumes `manylinux_2_28`, `aarch64-apple-darwin` assumes `macosx_13_0`. A wheel built for
a newer floor is then reported as "no matching platform tag" -- which reads identically to
a package that abandoned the architecture outright, and means something completely
different. `yazses[all]` "fails" on Linux under this probe only because PySide6 6.11.2
ships `manylinux_2_34`; every distribution anyone runs it on is newer than that.

Each failure is therefore classified against PyPI's own file list for the blocking
package (`--classify`, needs network):

* ``os_floor`` -- a version satisfying the requirement does ship a wheel for this
  architecture, built for a newer OS than the probe assumed. A constraint on the
  *user's OS version*, and nothing this repository states.
* ``version_floor`` -- wheels exist for the architecture, but only at versions below the
  floor declared here. This *is* a defect in this repository, and the one that broke the
  Intel macOS leg: `onnxruntime` was floored at 1.27.0 when 1.23.2 was the last release
  with an x86_64 macOS wheel.
* ``no_wheel`` -- no wheel for this architecture at any version. Nothing to fix; only a
  marker, a fallback, or dropping the platform will do.

The classification hangs on the **specifier**, not the package name. Ignoring it makes
`mediapipe>=0.10.35` on Intel macOS look like an OS-version issue, because mediapipe
0.10.21 does ship an x86_64 macOS wheel -- and it is not reachable from that floor.

    uv run --group benchmark python paper/benchmark/bench_platform_resolution.py
    uv run --group benchmark python paper/benchmark/bench_platform_resolution.py --classify

Writes `platform-resolution.json`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import provenance, write_result  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

#: The four platforms YazSes claims support for. The OS floor each string implies is
#: recorded in the artifact rather than left to the reader to know.
PLATFORMS = {
    "x86_64-unknown-linux-gnu": "manylinux_2_28",
    "aarch64-apple-darwin": "macosx_13_0",
    "x86_64-apple-darwin": "macosx_13_0",
    "x86_64-pc-windows-msvc": "win_amd64",
}

#: The architecture fragment a wheel filename must carry to run on each platform.
ARCH_TAG = {
    "x86_64-unknown-linux-gnu": ("manylinux", "x86_64"),
    "aarch64-apple-darwin": ("macosx", "arm64"),
    "x86_64-apple-darwin": ("macosx", "x86_64"),
    "x86_64-pc-windows-msvc": ("win", "amd64"),
}

_BLOCKER = re.compile(r"([A-Za-z0-9._-]+)(?:\{[^}]*\})?([><=~!]+[0-9a-z.]+) has no wheels")


def _extras() -> list[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return sorted(data["project"].get("optional-dependencies", {}))


def _compile(extra: str | None, platform: str, py: str) -> tuple[bool, str]:
    """Resolve one (extra, platform). Returns (solved, stderr).

    The output goes to a real temporary file: `-o /dev/null` makes uv fail writing its
    temporary sibling, which reports as a resolution failure and is not one. That
    mistake produced a table in which every row, including the base install, was FAIL.
    """
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["uv", "pip", "compile", str(ROOT / "pyproject.toml"),
               "--python-platform", platform, "--python-version", py,
               "-o", str(Path(tmp) / "out.txt")]
        if extra:
            cmd += ["--extra", extra]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        return proc.returncode == 0, proc.stderr


def _blocking_package(stderr: str) -> tuple[str, str] | None:
    """The package uv could not place, and **the specifier it was asked for**.

    The specifier is the half that decides whether a failure is this repository's
    problem. Dropping it -- which the first version of this script did -- makes
    `mediapipe>=0.10.35` on Intel macOS look like an OS-version issue, because
    mediapipe 0.10.21 does ship an x86_64 macOS wheel. It is not reachable from a
    floor of 0.10.35, and that distinction is the entire point of classifying.
    """
    m = _BLOCKER.search(stderr)
    return (m.group(1).lower(), m.group(2)) if m else None


def _classify(package: str, specifier: str, platform: str) -> dict:
    """Why this package could not be placed, in three mutually exclusive kinds."""
    import urllib.request

    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version

    os_tag, arch = ARCH_TAG[platform]
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=60) as fh:
            data = json.load(fh)
    except Exception as exc:  # noqa: BLE001 -- a classification is advisory, never fatal
        return {"classification": f"unknown ({type(exc).__name__})"}

    try:
        spec = SpecifierSet(specifier)
    except Exception:  # noqa: BLE001
        spec = SpecifierSet("")

    supported, satisfying = [], []
    for ver, files in data.get("releases", {}).items():
        if not any(f.get("filename", "").endswith(".whl")
                   and os_tag in f["filename"] and arch in f["filename"] for f in files):
            continue
        supported.append(ver)
        try:
            if Version(ver) in spec:
                satisfying.append(ver)
        except InvalidVersion:
            continue

    def newest(vs: list[str]) -> str | None:
        try:
            return max(vs, key=Version) if vs else None
        except InvalidVersion:
            return sorted(vs)[-1] if vs else None

    if not supported:
        kind = "no_wheel"          # the architecture was abandoned outright
    elif not satisfying:
        kind = "version_floor"     # wheels exist, but only below the declared floor
    else:
        kind = "os_floor"          # reachable, but built for a newer OS than assumed
    return {
        "classification": kind,
        "last_version_with_a_wheel": newest(supported),
        "newest_satisfying_the_requirement": newest(satisfying),
    }


def run(py: str = "3.11", classify: bool = False) -> dict:
    rows = []
    targets = [None, *_extras()]
    for platform in PLATFORMS:
        for extra in targets:
            label = extra or "(base)"
            started = time.time()
            solved, stderr = _compile(extra, platform, py)
            row = {
                "extra": label,
                "platform": platform,
                "assumed_os_floor": PLATFORMS[platform],
                "resolves": solved,
                "seconds": round(time.time() - started, 1),
            }
            if not solved:
                blocker = _blocking_package(stderr)
                row["blocked_by"] = blocker[0] if blocker else None
                row["requirement"] = blocker[1] if blocker else None
                row["classification"] = "unclassified"
                if classify and blocker:
                    row.update(_classify(blocker[0], blocker[1], platform))
            rows.append(row)
            print(f"[resolve] {platform:<26} {label:<24} "
                  f"{'ok' if solved else 'FAIL ' + str(row.get('blocked_by'))}", flush=True)

    failures = [r for r in rows if not r["resolves"]]
    return {
        "config": {"python_version": py, "platforms": PLATFORMS, "classified": classify},
        "rows": rows,
        "summary": {
            "targets_per_platform": len(targets),
            "total": len(rows),
            "resolving": sum(1 for r in rows if r["resolves"]),
            "failing": len(failures),
            # The number that matters: a genuine architecture gap in this repository,
            # as opposed to a wheel that merely wants a newer OS than the probe assumed.
            "no_wheel": sum(1 for r in failures if r.get("classification") == "no_wheel"),
            "version_floor": sum(1 for r in failures if r.get("classification") == "version_floor"),
            "os_floor": sum(1 for r in failures if r.get("classification") == "os_floor"),
        },
    }


def main() -> None:
    classify = "--classify" in sys.argv[1:]
    py = next((a for a in sys.argv[1:] if not a.startswith("-")), "3.11")
    result = run(py, classify)
    result["provenance"] = provenance(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    write_result("platform-resolution", result)
    s = result["summary"]
    print(f"\n{s['resolving']}/{s['total']} resolve; {s['failing']} fail — "
          f"{s['no_wheel']} architecture abandoned, {s['version_floor']} floored above the "
          f"last supported version, {s['os_floor']} want a newer OS than this probe assumed")


if __name__ == "__main__":
    main()
