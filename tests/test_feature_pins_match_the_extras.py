"""`features enable` must not install a floor below the one pyproject declares.

There are two descriptions of what a capability needs to run. `[project.optional-
dependencies]` is the packaging one — what `pip install yazses[tts]` resolves, what
the lockfile pins, what the docs point at. `system/features.py::_FEATURE_DEPS` is the
operational one: the requirement strings handed to `uv pip install` when a user types
`yazses features enable read-back`. The second is the one that actually runs on a
user's machine, and nothing compared it to the first.

They had drifted on 11 of 17 packages, every one of them downward -- `opencv-python
>=4.10` against the `gaze` extra's `>=5.0`, `mcp>=1.9` against `>=1.28.1`,
`sherpa-onnx>=1.10` for `diarize` while `recimport` and `meeting` (the same package,
three lines apart in the same map) said `>=1.13.4`.

Why a lower floor is not merely untidy: a floor is not a request for a version, it is
a statement about what already counts as satisfied. On a clean machine the resolver
picks the newest either way and the drift is invisible. On a machine that already has
an older copy -- and opencv, onnxruntime and Qt are exactly the packages another
project leaves behind -- `>=4.10` is *satisfied* by 4.10, so nothing upgrades,
`missing_modules` (which asks only whether the name imports) reports the dependency
present, and the capability is switched on over a version the project says is too old.
The failure surfaces later, inside the backend, as something that does not look like a
dependency problem at all.

This property is already enforced one layer over, for one consumer:
`test_install_paths_agree.py::test_the_universal_installer_does_not_pin_below_pyproject`
holds `install.sh` to the `desktop` extra, on the stated grounds that "a comment is not
a mechanism". `features enable` is the same mechanism with far more traffic -- it runs
whenever anyone turns a capability on -- and had a mechanism for exactly one row of the
table (`denoise`, added when that row was found wrong by hand).

So this file is that guard made total. It derives both sides and compares them, rather
than restating any pin a third time.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from yazses.system.features import _registry

ROOT = Path(__file__).resolve().parent.parent
EXTRAS: dict[str, list[str]] = tomllib.loads(
    (ROOT / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["optional-dependencies"]


def _distribution(requirement: str) -> str:
    """`onnx-asr[cpu,hub]>=0.12` -> `onnx-asr`. Normalised per PEP 503."""
    name = re.split(r"[<>=!~\[;]", requirement, maxsplit=1)[0].strip()
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared() -> dict[str, set[str]]:
    """Distribution -> every requirement string an extra states for it."""
    out: dict[str, set[str]] = {}
    for name, requirements in EXTRAS.items():
        # `all` restates pins the owning extras already state, so counting it here
        # would report every dependency as declared twice. That it really is the
        # union -- in both directions, so a bump in one place cannot drift -- is
        # proved by tests/test_the_all_extra_is_the_union_it_claims.py.
        if name == "all":
            continue
        for req in requirements:
            out.setdefault(_distribution(req), set()).add(req)
    return out


def _installed_by_features() -> list[tuple[str, str]]:
    """`(slug, requirement)` for every package `features enable` would install.

    Read off the registry rather than off `_FEATURE_DEPS`, even though the two agree
    today: `pip_packages` is a field on `_Def`, so a future row could state its pins
    inline and never appear in the map. The registry is what `features enable`
    consults, which makes it the region this guard has to cover.
    """
    return [
        (d.slug, req) for d in _registry() for req in (d.pip_packages or ())
    ]


PINS = _installed_by_features()
DECLARED = _declared()


def test_there_are_pins_to_check() -> None:
    """A guard that iterates an empty collection passes on everything."""
    assert len(PINS) >= 20, f"only {len(PINS)} feature pins found"
    slugs = {slug for slug, _ in PINS}
    assert {"gaze", "read-back", "diarize", "stt-moonshine"} <= slugs
    assert len(DECLARED) >= 15, f"only {len(DECLARED)} distributions in the extras"


@pytest.mark.parametrize(("slug", "requirement"), PINS, ids=lambda v: str(v))
def test_every_feature_pin_is_declared_by_an_extra(slug: str, requirement: str) -> None:
    """A package only this map knows about is one no extra, no `all` and no
    dependency-budget rule can see. `useful-moonshine-onnx` was one."""
    dist = _distribution(requirement)
    assert dist in DECLARED, (
        f"`features enable {slug}` installs {requirement!r}, which no extra in "
        f"pyproject.toml declares. Add an extra for it (and register the extra in "
        f"scripts/check_dependency_budget.py::EXTRA_MODULES) so the package is "
        f"visible to packaging, not only to this map."
    )


@pytest.mark.parametrize(("slug", "requirement"), PINS, ids=lambda v: str(v))
def test_no_feature_pin_sits_below_its_extra(slug: str, requirement: str) -> None:
    """The requirement string must be the extra's, character for character.

    Compared as strings rather than parsed as versions on purpose: `>=1.10` vs
    `>=1.13.4` is caught either way, but so are the differences a version compare
    would wave through -- a dropped `[cpu,hub]` marker changes what onnx-asr can do
    while the floor stays equal.
    """
    dist = _distribution(requirement)
    stated = DECLARED.get(dist, set())
    assert requirement in stated, (
        f"`features enable {slug}` installs {requirement!r} but pyproject declares "
        f"{sorted(stated)} for {dist}. `features enable` is the installer users "
        f"actually run; a looser floor here means an older resident version counts "
        f"as satisfied and the capability is switched on over it."
    )


def test_one_package_is_pinned_the_same_way_by_every_feature_that_installs_it() -> None:
    """`diarize` said `sherpa-onnx>=1.10` while `recimport`/`meeting` said `>=1.13.4`
    -- so which floor you got depended on which capability you enabled first."""
    by_dist: dict[str, dict[str, set[str]]] = {}
    for slug, req in PINS:
        by_dist.setdefault(_distribution(req), {}).setdefault(req, set()).add(slug)
    split = {d: v for d, v in by_dist.items() if len(v) > 1}
    assert not split, (
        "the same package is installed at different floors depending on the feature: "
        + "; ".join(
            f"{d}: " + ", ".join(f"{r} ({', '.join(sorted(s))})" for r, s in v.items())
            for d, v in sorted(split.items())
        )
    )


def test_a_looser_floor_really_would_be_accepted_by_the_resolver() -> None:
    """The premise, stated as an executable fact rather than an assumption.

    Nothing is installed here: this asserts the resolver semantics the whole guard
    rests on -- that a floor is a satisfaction test, so an already-present old
    version is left in place by the looser pin and upgraded by the declared one.
    """
    packaging = pytest.importorskip("packaging.specifiers")
    resident = "4.10.0.84"  # what a machine with an older opencv already has
    assert packaging.SpecifierSet(">=4.10").contains(resident)
    assert not packaging.SpecifierSet(">=5.0").contains(resident)
