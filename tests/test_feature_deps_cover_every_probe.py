"""If a backend needs a package, some feature must know how to install it.

`yazses features enable <name>` installs a feature's own optional dependencies
from `_FEATURE_DEPS` — that is the whole point of the map, and a feature absent
from it installs nothing. `denoise` was absent. So enabling noise suppression
wrote `[denoise] enabled = true`, fetched nothing, and the daemon then logged

    Denoise is enabled but the 'spectral' backend needs noisereduce; install the
    `denoise` extra. Audio is passed through unprocessed.

once at startup and passed audio through untouched for the rest of the install.
Found on the maintainer's own machine, at line 2 of a 574 KB `daemon.log` dating
from 2026-08-17: the feature had been on and doing nothing for three days, and
the only notice of it was one line in a file nobody reads.

The warning was not the failure. It was correct, honest and pointed straight at
the fix. The failure was that the command whose job is to *apply* that fix did
not know the package existed.

So the guard is not "denoise has a dep". It is the general property: every
`probe_backend(..., requires=…, extra=…)` in `src/` names a package a user is
expected to install, and some registered feature must be able to install it —
otherwise the advice is the only remedy, and `features enable` cannot deliver it.
A backend deliberately offered *no* remedy (`extra=None`, e.g. deepfilternet,
which caps `numpy<2.0` against this project's `numpy>=2.4.6` and can never be
installed) is exempt, because there is nothing to install.
"""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from yazses.system.features import _FEATURE_DEPS, _registry

ROOT = Path(__file__).resolve().parents[1]


def _tracked_sources() -> list[Path]:
    """Every source file to scan for probes -- from git where there is one.

    The walk is the fallback rather than the default because git knows what is
    actually shipped. But `git` is not guaranteed: on a Windows host without it,
    `subprocess.run` raises `FileNotFoundError: [WinError 2]` *at collection time*,
    which took the entire suite down with "2 errors during collection" -- a
    repository-hygiene guard silencing 13675 unrelated results.

    Falling back to a walk is safe for this guard specifically: it asserts that
    *every* probe has an installable remedy, so a superset of files can only make it
    stricter, never let a probe through unexamined.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "src/*.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return sorted((ROOT / "src").rglob("*.py"))
    return sorted({ROOT / line for line in out.splitlines() if line})


def _literal(node: ast.expr):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _probes() -> list[tuple[str, int, tuple[str, ...], str | None]]:
    """(file, line, required modules, extra) for each probe_backend call."""
    found = []
    for path in _tracked_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "probe_backend":
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            requires = _literal(kwargs["requires"]) if "requires" in kwargs else None
            if requires is None:
                continue  # built from a variable — covered by its own factory's tests
            extra = _literal(kwargs["extra"]) if "extra" in kwargs else None
            found.append((path.relative_to(ROOT).as_posix(), node.lineno, tuple(requires), extra))
    return found


def test_the_scan_finds_probes():
    """Every guard here iterates over this list; an empty one passes vacuously."""
    probes = _probes()
    assert probes, "no literal probe_backend calls found — the AST scan is wrong"
    assert any(extra for *_, extra in probes), probes


@pytest.mark.parametrize("path,lineno,requires,extra", _probes())
def test_a_probe_that_names_an_extra_has_a_feature_that_installs_it(
    path, lineno, requires, extra
):
    if extra is None:
        return  # deliberately no remedy; nothing to install
    installable = {module for modules, _ in _FEATURE_DEPS.values() for module in modules}
    orphan = [m for m in requires if m not in installable]
    assert not orphan, (
        f"{path}:{lineno} tells the user to install the `{extra}` extra for "
        f"{orphan}, but no feature in _FEATURE_DEPS installs it — so "
        "`yazses features enable` writes the config key, fetches nothing, and the "
        "feature is on and dormant. Add the module to that feature's entry."
    )


@pytest.mark.parametrize("slug,dep", sorted(_FEATURE_DEPS.items()))
def test_every_declared_dependency_is_a_real_registered_slug(slug, dep):
    known = {d.slug for d in _registry()}
    assert slug in known, f"_FEATURE_DEPS names {slug!r}, which is not a feature"
    modules, packages = dep
    assert modules and packages, slug


def test_the_deps_map_is_not_empty():
    assert len(_FEATURE_DEPS) > 10


def test_the_denoise_pin_matches_the_extra_it_tells_you_to_install():
    """The row this was written for. The same property over *every* row lives in
    `test_feature_pins_match_the_extras.py` -- 11 of 17 had drifted below their
    extra by the time it was written, so one row is kept here only as the case
    that motivated it, not as the coverage.

    The warning says "install the `denoise` extra"; `features enable denoise`
    installs `_FEATURE_DEPS`. Two routes to the same package — if they drift, one
    of them installs a version the other does not accept.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extra = data["project"]["optional-dependencies"]["denoise"]
    assert list(_FEATURE_DEPS["denoise"][1]) == extra


# ---- and the card must describe the backend that actually runs ----------


def _denoise_description() -> str:
    from yazses.config import Config
    from yazses.system.features import find_feature

    feature = find_feature(Config(), "denoise")
    assert feature is not None
    return feature.why


def test_the_default_denoise_backend_has_an_adapter():
    """A default that names a module nobody shipped is a feature that cannot work."""
    from yazses.config import DenoiseConfig

    default = DenoiseConfig().backend
    assert (ROOT / "src" / "yazses" / "denoise" / f"{default}.py").exists(), default


def test_the_denoise_card_names_the_backend_and_the_package():
    """It named neither: the card described the *other* backend."""
    from yazses.config import DenoiseConfig

    desc = _denoise_description()
    assert DenoiseConfig().backend in desc
    assert "noisereduce" in desc


def test_the_denoise_card_does_not_call_a_working_feature_a_passthrough():
    """The card said the feature "currently passes audio through unchanged" because
    DeepFilterNet is missing. `spectral` shipped and became the default, so that
    sentence stopped being true — and it is the sentence a reader uses to decide
    whether to bother enabling it. A passthrough claim is only allowed where it
    names the backend it is about."""
    desc = _denoise_description()
    # Split on period-then-space, not on any period: a version like `numpy>=2.4.6`
    # otherwise cuts the sentence in half and the guard reports the fragment.
    for sentence in re.split(r"(?<=\.)\s+", desc):
        if "passes audio through" not in sentence:
            continue
        low = sentence.lower()
        assert "deepfilternet" in low, sentence.strip()
        # ...and it must be a claim about that backend, not about enabling the
        # feature. "The deepfilternet backend passes audio through" is true;
        # "enabling this passes audio through" is what the card used to say.
        assert "enabl" not in low, sentence.strip()
