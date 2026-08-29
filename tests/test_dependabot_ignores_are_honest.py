"""An `ignore` in dependabot.yml is a decision to go without a security fix.

The file used to say the opposite -- that security updates are "NOT limited by this
file" -- and that is wrong. GitHub's reference states Dependabot can be configured to
ignore dependencies "when it opens pull requests for version updates **and security
updates**"; only `update-types` is exempt from that, and `versions:` is not. So an
entry here does not merely quiet the monthly noise, it removes a class of alert.

  https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/controlling-dependencies-updated

These tests hold the two properties that keep that survivable: an ignore must name the
versions it cannot take rather than the whole package, and the one dependency whose red
job invited a blanket ignore (#322) must not have acquired one quietly.

The last test in the file is the other half of #322. An ignore rule is what you reach
for when an update job fails and you cannot see why; the cheapest way to keep the
ignore list honest is for the job not to fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEPENDABOT = ROOT / ".github/dependabot.yml"

#: onnxruntime's Intel-macOS cap used to make Dependabot's global `==<version>` pin
#: unsatisfiable, failing the monthly `uv` job every run. The tempting fix was
#: `ignore: onnxruntime >= 1.24`, which would also have dropped every onnxruntime
#: update on Linux, Windows and Apple silicon -- where the users are. The failure is
#: fixed properly now (see `test_no_platform_version_range_is_stated_in_both_places`),
#: so an ignore would be buying nothing at all; this stays because the entry is what
#: a future red run will invite again. See #322.
MUST_NOT_BE_IGNORED = {"onnxruntime"}


def _updates() -> list[dict]:
    return yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))["updates"]


def _ignores() -> list[tuple[str, dict]]:
    return [(u["package-ecosystem"], entry)
            for u in _updates() for entry in (u.get("ignore") or [])]


def test_the_config_parses_and_has_ecosystems() -> None:
    """Guards against these tests passing on a file that no longer says anything."""
    assert _updates(), "dependabot.yml declares no updates at all"


@pytest.mark.parametrize(
    "case", _ignores() or [("<none>", {})],
    ids=lambda c: f"{c[0]}:{c[1].get('dependency-name', 'none')}",
)
def test_an_ignore_names_the_versions_it_cannot_take(case: tuple[str, dict]) -> None:
    """A bare `dependency-name` with no `versions` silences that package forever,
    security advisories included. Scope it, so a patch inside the range still lands."""
    _, entry = case
    if not entry:
        pytest.skip("no ignore entries")
    assert entry.get("versions") or entry.get("update-types"), (
        f"{entry['dependency-name']} is ignored with no version range: that suppresses "
        "every future update, including security ones. Name the range that cannot be "
        "taken, and say why beside it."
    )


@pytest.mark.parametrize("name", sorted(MUST_NOT_BE_IGNORED))
def test_the_known_red_dependency_was_not_quietly_silenced(name: str) -> None:
    ignored = {entry["dependency-name"] for _, entry in _ignores() if entry}
    assert name not in ignored, (
        f"{name} has been added to dependabot.yml's ignore list. That would stop "
        "every legitimate update on the platforms essentially all users are on, "
        "security updates included. It would also be buying nothing: the failure it "
        "used to suppress is fixed by keeping the Intel version range out of "
        "`[project]` entirely, so no update run should be red (#322)."
    )


def test_the_file_does_not_repeat_the_claim_that_was_wrong() -> None:
    """The exact sentence that made an ignore look free. Kept as a string so the
    correction cannot be reverted by a copy-paste from an older revision."""
    text = DEPENDABOT.read_text(encoding="utf-8")
    assert "are NOT limited by\n# this file" not in text, (
        "dependabot.yml has regained the claim that security updates are not limited "
        "by this file. They are: an `ignore` entry suppresses security PRs too."
    )


# ── the other half of #322: a range must not be stated in two places ─────────

#: A grid wide enough to decide whether two environment markers can be true at once.
#: Marker overlap is what matters, not marker wording -- `sys_platform == 'darwin' and
#: platform_machine == 'x86_64'` and a differently-phrased equivalent must both be
#: caught, and the non-Intel branch (`!= 'darwin' or != 'x86_64'`) must not be.
_ENVS = [
    {"sys_platform": p, "platform_machine": m, "os_name": "nt" if p == "win32" else "posix",
     "python_version": v, "python_full_version": v + ".0", "platform_system": p,
     "implementation_name": "cpython", "platform_python_implementation": "CPython",
     "extra": ""}
    for p in ("linux", "darwin", "win32", "freebsd14")
    for m in ("x86_64", "arm64", "aarch64")
    for v in ("3.11", "3.14")
]


def _overlap(a, b) -> bool:
    """True if some supported environment satisfies both markers (None = always)."""
    for env in _ENVS:
        if (a is None or a.evaluate(env)) and (b is None or b.evaluate(env)):
            return True
    return False


def _constraints_and_project_reqs(pyproject: dict):
    """`([tool.uv] constraint-dependencies, every [project] requirement)`, parsed."""
    from packaging.requirements import Requirement

    constraints = [
        Requirement(c)
        for c in pyproject.get("tool", {}).get("uv", {}).get("constraint-dependencies", [])
    ]
    reqs = [(Requirement(r), "dependencies") for r in pyproject["project"].get("dependencies", [])]
    for extra, items in pyproject["project"].get("optional-dependencies", {}).items():
        reqs += [(Requirement(r), f"optional-dependencies.{extra}") for r in items]
    return constraints, reqs


def _double_declared(pyproject: dict) -> list[str]:
    """Packages whose version range is stated both in `[project]` and in the constraint
    table, for an overlapping set of platforms. That pair is what breaks Dependabot."""
    constraints, reqs = _constraints_and_project_reqs(pyproject)
    bad = []
    for c in constraints:
        for req, where in reqs:
            if req.name != c.name or not req.specifier:
                continue
            if _overlap(req.marker, c.marker):
                bad.append(f"{where}: {req} (constrained here by `{c}`)")
    return bad


def test_no_platform_version_range_is_stated_in_both_places() -> None:
    """#322, and the reason the monthly `uv` job was red from the day it was written.

    `[tool.uv] constraint-dependencies` capped onnxruntime at `<1.24` on Intel macOS,
    where upstream stopped publishing an x86_64 wheel after 1.23.0 -- and three extras
    *also* declared `onnxruntime>=1.23.2,<1.24` for that same platform. Dependabot
    rewrites every `[project]` requirement for the package it is bumping and does not
    touch `[tool.uv]`, so proposing 1.29.0 produced `>=1.29.0; darwin+x86_64` next to
    `<1.24` and uv answered "unsatisfiable". The job aborts on that, taking the fifteen
    unrelated bumps grouped with it down too.

    The fix is not to delete either bound. It is to state the range once, in the table
    Dependabot cannot rewrite, and leave the `[project]` requirement unconstrained --
    which its uv handler treats as non-updatable and returns unchanged
    (dependabot/dependabot-core#12273). The requirement stays declared, so the extra
    does not quietly start depending on kokoro-onnx to pull the runtime in for it.
    """
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    bad = _double_declared(pyproject)
    assert not bad, (
        "these `[project]` requirements carry a version range for a package that "
        "`[tool.uv] constraint-dependencies` already bounds on the same platform:\n  "
        + "\n  ".join(sorted(bad))
        + "\n\nDependabot will rewrite the `[project]` one and not the constraint, and "
        "the update job dies on the contradiction. Drop the specifier from the "
        "`[project]` requirement and let the table carry the range (#322)."
    )


def test_the_check_would_have_caught_the_shape_that_was_shipped() -> None:
    """A guard for a resolved bug is worth exactly what it catches. Both directions.

    The allowed case is not a weaker version of the bad one: the non-Intel branch
    keeps a real `>=1.27.0` floor, and must keep it -- that is the declaration
    Dependabot is supposed to bump.
    """
    intel = "sys_platform == 'darwin' and platform_machine == 'x86_64'"
    other = "sys_platform != 'darwin' or platform_machine != 'x86_64'"
    table = {"tool": {"uv": {"constraint-dependencies": [f"onnxruntime<1.24; {intel}"]}}}

    shipped = dict(table, project={"optional-dependencies": {"tts": [
        f"onnxruntime>=1.27.0; {other}", f"onnxruntime>=1.23.2,<1.24; {intel}"]}})
    assert _double_declared(shipped), "the guard misses the shape that was shipped"

    fixed = dict(table, project={"optional-dependencies": {"tts": [
        f"onnxruntime>=1.27.0; {other}", f"onnxruntime; {intel}"]}})
    assert not _double_declared(fixed), "the guard rejects the fix"

    unmarked = dict(table, project={"dependencies": ["onnxruntime>=1.27.0"]})
    assert _double_declared(unmarked), (
        "an unmarked requirement overlaps every platform, including the constrained "
        "one, so it must be caught too"
    )
