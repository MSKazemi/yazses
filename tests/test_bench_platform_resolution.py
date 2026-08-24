"""Why an extra will not install, told apart from why it merely did not resolve here.

`benchmark.yml`'s Intel macOS leg had never produced a number, and the cause was not the
benchmark: `uv sync` could not resolve at all. No test can see that class of defect --
every test runs on a machine where the install already worked -- so it is measured
instead, by `bench_platform_resolution.py`.

The measurement is only useful if a failure is classified correctly, and there are three
kinds that look identical in uv's output:

* the architecture was abandoned by the package (nothing to fix),
* wheels exist for the architecture but only *below the floor this repository declares*
  (a defect here, and the one that broke Intel macOS),
* wheels exist and satisfy the floor, but want a newer OS than the probe assumed
  (a statement about the probe, not about the manifest).

Reading the second as the third leaves a real break unfixed; reading the third as the
second gets a correct manifest "fixed" into a wrong one. Both happened while writing the
script, which is why the distinction is pinned here.
"""
from __future__ import annotations

import io
import json

import pytest

from tests.benchmark_deps import load

mod = load("bench_platform_resolution", "bench_platform_resolution.py")


# --- reading uv's failure ------------------------------------------------------------

@pytest.mark.parametrize("stderr,expected", [
    ("And because yazses depends on mediapipe>=0.10.35 has no wheels with a matching",
     ("mediapipe", ">=0.10.35")),
    # uv prints the marker in braces, and wraps it across lines. The braces must not be
    # mistaken for part of the name, and the newline inside them must not stop the match.
    ("onnxruntime{platform_machine != 'x86_64' or sys_platform !=\n'darwin'}>=1.27.0"
     " has no wheels with a matching platform tag", ("onnxruntime", ">=1.27.0")),
    ("pyside6>=6.11.1 has no wheels with a matching platform tag", ("pyside6", ">=6.11.1")),
])
def test_the_blocking_requirement_is_read_whole(stderr: str, expected: tuple) -> None:
    assert mod._blocking_package(stderr) == expected


def test_an_unrecognised_failure_is_not_guessed_at() -> None:
    assert mod._blocking_package("error: Permission denied (os error 13)") is None


def test_the_specifier_is_kept_not_only_the_name() -> None:
    """The whole classification hangs on it; an earlier version dropped it."""
    name, spec = mod._blocking_package("torch>=2.8.0 has no wheels with a matching")
    assert (name, spec) == ("torch", ">=2.8.0")


# --- classifying it ------------------------------------------------------------------

def _pypi(monkeypatch, releases: dict[str, list[str]]) -> None:
    """Stand in for PyPI: version -> wheel filenames."""
    payload = {"releases": {v: [{"filename": f} for f in files] for v, files in releases.items()}}

    class _Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _Resp(json.dumps(payload).encode()),
    )


MEDIAPIPE = {
    "0.10.21": ["mediapipe-0.10.21-cp311-cp311-macosx_11_0_x86_64.whl",
                "mediapipe-0.10.21-cp311-cp311-macosx_11_0_arm64.whl"],
    "1.0.1": ["mediapipe-1.0.1-cp311-cp311-macosx_11_0_arm64.whl"],
}


def test_a_floor_above_the_last_supported_version_is_this_repos_defect(monkeypatch) -> None:
    _pypi(monkeypatch, MEDIAPIPE)
    out = mod._classify("mediapipe", ">=0.10.35", "x86_64-apple-darwin")
    assert out["classification"] == "version_floor"
    assert out["last_version_with_a_wheel"] == "0.10.21"
    assert out["newest_satisfying_the_requirement"] is None


def test_the_same_package_under_a_reachable_floor_is_not_a_defect(monkeypatch) -> None:
    """The negative control. Same package, same platform, lower floor -- and the verdict
    must change, or `version_floor` is just a synonym for the package name."""
    _pypi(monkeypatch, MEDIAPIPE)
    out = mod._classify("mediapipe", ">=0.10.0", "x86_64-apple-darwin")
    assert out["classification"] == "os_floor"
    assert out["newest_satisfying_the_requirement"] == "0.10.21"


def test_an_architecture_with_no_wheel_at_any_version_is_not_fixable_here(monkeypatch) -> None:
    _pypi(monkeypatch, {"1.0.1": ["mediapipe-1.0.1-cp311-cp311-macosx_11_0_arm64.whl"]})
    out = mod._classify("mediapipe", ">=0.1", "x86_64-apple-darwin")
    assert out["classification"] == "no_wheel"
    assert out["last_version_with_a_wheel"] is None


def test_the_architecture_is_matched_not_merely_the_os(monkeypatch) -> None:
    """An arm64 macOS wheel must not satisfy an Intel macOS query, and the reverse.

    Both filenames contain `macosx`, so a check on the OS alone reports every macOS
    package as available on both Macs -- which is exactly the failure being measured.
    """
    _pypi(monkeypatch, MEDIAPIPE)
    intel = mod._classify("mediapipe", ">=1.0", "x86_64-apple-darwin")
    silicon = mod._classify("mediapipe", ">=1.0", "aarch64-apple-darwin")
    assert intel["classification"] == "version_floor"   # 1.0.1 is arm64-only
    assert silicon["classification"] == "os_floor"      # 1.0.1 is reachable there


def test_an_sdist_is_not_counted_as_a_wheel(monkeypatch) -> None:
    """A source distribution does not make a platform installable for this project --
    these are packages nobody is going to compile locally."""
    _pypi(monkeypatch, {"2.0.0": ["mediapipe-2.0.0.tar.gz"]})
    assert mod._classify("mediapipe", ">=1.0", "x86_64-apple-darwin")["classification"] == "no_wheel"


def test_a_network_failure_is_reported_not_swallowed_into_a_verdict(monkeypatch) -> None:
    """An advisory classification must never invent one of the three answers offline."""
    def boom(*a, **k):
        raise OSError("no route to host")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    out = mod._classify("mediapipe", ">=1.0", "x86_64-apple-darwin")
    assert out["classification"].startswith("unknown")
    assert "OSError" in out["classification"]


def test_an_unparseable_version_does_not_abort_the_classification(monkeypatch) -> None:
    """PyPI carries legacy version strings; one must not take the whole run down."""
    _pypi(monkeypatch, dict(MEDIAPIPE, **{
        "0.10.21-beta": ["mediapipe-0.10.21beta-cp311-cp311-macosx_11_0_x86_64.whl"]}))
    assert mod._classify("mediapipe", ">=0.10.35", "x86_64-apple-darwin")["classification"] \
        == "version_floor"


# --- the probe's own footgun ---------------------------------------------------------

def test_the_resolution_output_goes_to_a_real_path() -> None:
    """`-o /dev/null` makes uv fail writing a temporary sibling file, which is reported
    as a resolution failure and is not one. That produced a table in which every row --
    including the base install, which resolves fine -- read FAIL."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(mod._compile).lstrip())
    fn = tree.body[0]
    if ast.get_docstring(fn) is not None:  # the docstring names the footgun on purpose
        fn.body = fn.body[1:]
    body = ast.unparse(fn)
    assert "/dev/null" not in body, "the resolver still writes to a path it cannot write beside"
    assert "TemporaryDirectory" in body


def test_every_platform_declares_the_os_floor_it_assumes() -> None:
    """A resolution result is meaningless without it: the same manifest passes or fails
    depending on the minimum OS the resolver was told to target."""
    assert set(mod.PLATFORMS) == set(mod.ARCH_TAG)
    assert all(v for v in mod.PLATFORMS.values())


def test_the_four_supported_platforms_are_covered() -> None:
    arches = set(mod.PLATFORMS)
    assert {"x86_64-apple-darwin", "aarch64-apple-darwin"} <= arches, "both Macs"
    assert any("linux" in p for p in arches) and any("windows" in p for p in arches)
