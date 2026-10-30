"""Repository-owned composite actions under `.github/actions/` keep the contract that
makes reusing them safe (CI_POLICY.md §7 and §8, issue #537).

A composite action runs inside the calling job, with that job's token and secrets. It
therefore has to stay boring in three ways, and each is checked here from the files:

1. **Declared as a composite.** `runs.using` must be `composite`. A `node` or `docker`
   action would be a different trust decision, made in a different place.
2. **Pinned and free of secrets.** Each third-party `uses:` is a 40-character commit SHA
   with a version comment, the same convention `test_workflow_actions_are_pinned.py`
   enforces for workflows. The action itself names no secret, no `permissions:` block
   and no `GITHUB_TOKEN`, so reusing it cannot widen what a job can reach.
3. **Wired.** Every action is referenced by a workflow job, so it cannot silently rot,
   and every `uses: ./.github/actions/...` in a workflow resolves to a real action.

It also keeps the reuse rule honest: a job that still calls `astral-sh/setup-uv` directly
must be a listed, justified exception (`DIRECT_SETUP_UV`).

The action directory is read from disk, so a new action is covered the moment it exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
ACTIONS = REPO / ".github" / "actions"

_LOCAL_PREFIX = "./.github/actions/"
_EXTERNAL_USES = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
_SHA_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)\s*#\s*(?P<comment>\S.*?)\s*$", re.M)
_FORBIDDEN = ("secrets.", "permissions:", "GITHUB_TOKEN")


def _action_files() -> list[Path]:
    files = sorted(ACTIONS.glob("*/action.yml")) + sorted(ACTIONS.glob("*/action.yaml"))
    assert files, f"no composite actions under {ACTIONS}; these guards would be inert"
    return files


def _workflow_jobs() -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, job in (data.get("jobs") or {}).items():
            found.append((f"{path.name}:{name}", job))
    return found


def _local_references() -> dict[str, list[str]]:
    """Action directory name -> the workflow jobs that reference it."""
    refs: dict[str, list[str]] = {}
    for label, job in _workflow_jobs():
        for step in job.get("steps") or []:
            uses = str(step.get("uses", ""))
            if uses.startswith(_LOCAL_PREFIX):
                name = uses[len(_LOCAL_PREFIX):].split("@", 1)[0].strip("/")
                refs.setdefault(name, []).append(label)
    return refs


ACTION_FILES = _action_files()
ACTION_IDS = [path.parent.name for path in ACTION_FILES]


def test_the_guards_see_the_actions_and_their_callers() -> None:
    assert len(ACTION_FILES) >= 1
    assert _local_references(), "no workflow references a local action; the wiring guards would be inert"


@pytest.mark.parametrize("action", ACTION_FILES, ids=ACTION_IDS)
def test_every_action_is_a_composite(action: Path) -> None:
    data = yaml.safe_load(action.read_text(encoding="utf-8")) or {}
    assert (data.get("runs") or {}).get("using") == "composite", (
        f"{action.relative_to(REPO)} must declare `runs.using: composite`; a node or docker "
        "action is a different trust decision and does not belong in this directory"
    )


@pytest.mark.parametrize("action", ACTION_FILES, ids=ACTION_IDS)
def test_every_external_uses_is_a_full_commit_sha(action: Path) -> None:
    data = yaml.safe_load(action.read_text(encoding="utf-8")) or {}
    steps = (data.get("runs") or {}).get("steps") or []
    external = [str(s["uses"]) for s in steps if "uses" in s]
    for ref in external:
        assert not ref.startswith("./"), f"{action.relative_to(REPO)} nests a local action {ref!r}"
        assert _EXTERNAL_USES.match(ref), (
            f"{action.relative_to(REPO)}: `uses: {ref}` is not `owner/repo@<40-hex SHA>`. "
            "A tag can be moved by its owner; pin the commit the workflows already use."
        )


@pytest.mark.parametrize("action", ACTION_FILES, ids=ACTION_IDS)
def test_every_pin_carries_a_version_comment(action: Path) -> None:
    text = action.read_text(encoding="utf-8")
    pins = _SHA_LINE.findall(text)
    assert pins, f"{action.relative_to(REPO)} has no pinned `uses:` line with a version comment"
    for ref, comment in pins:
        assert re.match(r"^v\d", comment), (
            f"{action.relative_to(REPO)}: pin {ref} needs a trailing `# vX.Y.Z` comment; "
            "a bare SHA cannot be reviewed"
        )


@pytest.mark.parametrize("action", ACTION_FILES, ids=ACTION_IDS)
def test_the_action_names_no_secret_permission_or_token(action: Path) -> None:
    text = action.read_text(encoding="utf-8")
    hits = [word for word in _FORBIDDEN if word in text]
    assert not hits, (
        f"{action.relative_to(REPO)} mentions {hits}. Repository-owned setup must not read "
        "secrets, grant permissions or touch tokens; put that in the calling job, explicitly "
        "(CI_POLICY.md §7)"
    )


@pytest.mark.parametrize("action", ACTION_FILES, ids=ACTION_IDS)
def test_every_action_is_referenced_by_a_workflow_job(action: Path) -> None:
    refs = _local_references()
    assert refs.get(action.parent.name), (
        f"{action.parent.name} is not used by any workflow job. An unreferenced action "
        "rots silently: delete it or wire it into the job it was written for."
    )


def test_every_local_reference_resolves_to_an_action() -> None:
    for label, job in _workflow_jobs():
        for step in job.get("steps") or []:
            uses = str(step.get("uses", ""))
            if not uses.startswith(_LOCAL_PREFIX):
                continue
            name = uses[len(_LOCAL_PREFIX):].split("@", 1)[0].strip("/")
            target = ACTIONS / name
            assert (target / "action.yml").is_file() or (target / "action.yaml").is_file(), (
                f"{label} uses {uses!r}, but {target.relative_to(REPO)} has no action.yml"
            )


#: Jobs that still call `astral-sh/setup-uv` themselves instead of the composite, each with
#: the reason CI_POLICY.md §8 asks for. The test below derives the real set from the
#: workflows and compares both ways, so a new direct call fails until it is either moved to
#: the composite or justified here, and a migrated job fails until its entry is deleted.
DIRECT_SETUP_UV: dict[str, str] = {
    "benchmark.yml:bench": "its sync is conditional: the macos-15-intel leg resolves unlocked with `uv pip install`",
    "build-macos.yml:build": "build/release lane: produces the shipped macOS bundle (§8 Reuse, §11)",
    "build-windows.yml:build": "build/release lane: produces and signs the shipped Windows installer (§8 Reuse, §11)",
    "packs-spike.yml:spike": "build lane: freezes a `--no-dev` environment held equal to build-windows.ps1's",
    "macos-smoke.yml:smoke": "has no `uv sync` step: scripts/build-macos.sh syncs inside the bundle build",
    "release.yml:test": "release lane: release steps stay explicit (§8 Reuse, §11)",
    "release.yml:publish-pypi": "release lane: publishes to PyPI",
    "release.yml:build-deb": "release lane: builds the released .deb",
    "eye-eval-ci.yml:evaluate": "not migrated yet: tests/test_eye_ci_entry_point.py pins this setup step's shape",
    "eye-eval-ci.yml:matrix": "not migrated yet: tests/test_eye_ci_entry_point.py pins this setup step's shape",
}


def _direct_setup_uv_jobs() -> set[str]:
    return {
        label
        for label, job in _workflow_jobs()
        for step in job.get("steps") or []
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    }


def test_direct_setup_uv_calls_are_exactly_the_justified_exceptions() -> None:
    found = _direct_setup_uv_jobs()
    assert found, "no workflow calls setup-uv directly; the scan is probably broken"
    unjustified = sorted(found - DIRECT_SETUP_UV.keys())
    assert not unjustified, (
        f"{unjustified} install uv with `astral-sh/setup-uv` directly. Use "
        "`./.github/actions/setup-uv-python` (CI_POLICY.md §8), or add the job to "
        "DIRECT_SETUP_UV with the reason it cannot."
    )
    stale = sorted(DIRECT_SETUP_UV.keys() - found)
    assert not stale, f"{stale} no longer call setup-uv directly; delete their DIRECT_SETUP_UV entries"
    assert all(reason.strip() for reason in DIRECT_SETUP_UV.values())


def test_no_test_yml_job_calls_setup_uv_directly() -> None:
    """Every Python job in the PR workflow goes through the composite (#537)."""
    assert not sorted(label for label in _direct_setup_uv_jobs() if label.startswith("test.yml:"))


def test_setup_uv_python_forwards_the_interpreter_to_setup_uv() -> None:
    """`test_macos_uv_jobs_pin_the_interpreter.py` accepts a step whose `uses` contains
    `setup-uv` and whose `with:` has `python-version`. For a job that calls the composite
    that is true of the *caller*, so the guard is only right if the composite hands the
    value on. Without this, deleting the forwarding would leave every macOS leg on
    Homebrew's newest CPython while that guard stayed green."""
    data = yaml.safe_load((ACTIONS / "setup-uv-python" / "action.yml").read_text(encoding="utf-8"))
    setup = [s for s in data["runs"]["steps"] if "astral-sh/setup-uv@" in str(s.get("uses", ""))]
    assert len(setup) == 1, "the composite must install uv through exactly one setup-uv step"
    assert setup[0]["with"]["python-version"] == "${{ inputs.python-version }}"
    assert data["inputs"]["python-version"].get("required") is True


def test_setup_uv_python_leaves_the_uv_cache_key_at_its_default() -> None:
    """CI_POLICY.md §8 "Caches" states what setup-uv's built-in cache key contains: the
    architecture, OS image, interpreter and a hash of the dependency files, matched exactly
    with no restore-key fallback. That holds only while the composite passes nothing that
    changes the key: an empty `cache-dependency-glob` makes it never invalidate, and a
    `cache-suffix` or `enable-cache` change is a cache decision the policy must record.
    Changing the inputs is allowed; doing it without updating §8 is what this stops."""
    data = yaml.safe_load((ACTIONS / "setup-uv-python" / "action.yml").read_text(encoding="utf-8"))
    setup = next(s for s in data["runs"]["steps"] if "astral-sh/setup-uv@" in str(s.get("uses", "")))
    assert set(setup["with"]) == {"version", "python-version"}, (
        f"setup-uv now receives {sorted(setup['with'])}; update CI_POLICY.md §8 'Caches' "
        "with what the uv cache key contains, then this set"
    )
