"""Every CI cache has a key that names what makes it valid (CI_POLICY.md §8 "Caches", #537).

A cache that restores into the wrong job is not a slow build, it is a wrong one: wheels
built for x86_64 restored on arm64, a virtualenv for CPython 3.11 restored under 3.13, a
lock from last month restored after a dependency bump. The rule is that a key includes
every property that changes compatibility, and that a restore key cannot reach across an
architecture or an interpreter. This file checks it from the workflow files.

Every step that can read or write a cache is found by derivation, never from a list:

* `actions/cache` (and its `restore`/`save` halves): the key must hash its inputs with
  `hashFiles(...)` and name `runner.os` and `runner.arch`, and every restore key must be a
  prefix of the key that keeps each of those compatibility tokens. A cache whose content
  is the same on every OS and architecture may leave them out, but only as a listed
  exception (`PLATFORM_INDEPENDENT`) on a job that runs on one literal runner label.
* `astral-sh/setup-uv`, direct or through `./.github/actions/setup-uv-python`: its
  built-in cache is on by default. Its key at both pinned commits is
  `setup-uv-<n>-<arch>-<platform>-<OS image>-<interpreter>-<dependency hash>` and it is
  restored by exact match (CI_POLICY.md §8). That holds only while no caller passes an
  input that reshapes the key, so the inputs a caller may pass are fixed here.
* Anything else: an action whose cache is on by default, or any step with a truthy
  `with:` key containing `cache`. Those keys are managed by the action, so each is listed
  in `ACTION_MANAGED` with the reason its key is safe. The list is compared both ways.

A privileged trigger (`pull_request_target`, `workflow_run`) runs in the default branch's
context, and a cache saved there is restored by `main` and by tag runs, release jobs
included. No workflow with such a trigger may touch a cache at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
COMPOSITE = "./.github/actions/setup-uv-python"

#: Inputs a setup-uv caller may pass. `version` picks uv and `python-version` the
#: interpreter, which is itself a segment of the key. Every other cache-related input
#: (`enable-cache`, `cache-dependency-glob`, `cache-suffix`, `cache-local-path`,
#: `restore-cache`, `save-cache`, `prune-cache`, `cache-python`, `python-arch`) changes the
#: key or whether it is used, which is a cache decision CI_POLICY.md §8 must record first.
SETUP_UV_INPUTS = frozenset({"version", "python-version"})

#: Inputs a caller of the composite may pass. `uv-version` is forwarded as `version`.
COMPOSITE_INPUTS = frozenset({"python-version", "uv-version", "sync-args"})

#: Actions whose own cache is on unless the step turns it off, and how it is turned off.
DEFAULT_ON: dict[str, tuple[str, object]] = {
    "astral-sh/setup-uv": ("enable-cache", False),
    "gradle/actions/setup-gradle": ("cache-disabled", True),
    "flatpak/flatpak-github-actions/flatpak-builder": ("cache", False),
}

#: Tokens that, when a key carries them, a restore key must keep too.
COMPAT_TOKENS = ("runner.os", "runner.arch", "python-version", "matrix.os", "matrix.arch")

#: `workflow:job:<static key prefix>` -> why the content does not depend on OS or arch.
PLATFORM_INDEPENDENT: dict[str, str] = {
    "docs.yml:build:mkdocs-privacy-": (
        "web fonts mirrored by the MkDocs privacy plugin: woff2 files are the same bytes on "
        "every platform. The key hashes mkdocs.yml, which names the theme and fonts."
    ),
}

#: `workflow:job:action` -> why the key that action computes is safe.
ACTION_MANAGED: dict[str, str] = {
    "android-test.yml:build:gradle/actions/setup-gradle": (
        "setup-gradle keys its caches by OS and job and hashes the Gradle build files; "
        "the job runs on ubuntu-latest only"
    ),
    "docker.yml:build:docker/build-push-action": (
        "BuildKit's `type=gha` cache stores content-addressed layers per platform, so the "
        "amd64 and arm64 halves of one multi-platform build cannot restore each other's"
    ),
}

_PRIVILEGED = ("pull_request_target", "workflow_run")


def _static_prefix(key: str) -> str:
    """The literal start of a key, up to its first `${{ }}` expression."""
    return key.split("${{", 1)[0]


def _workflows() -> list[tuple[Path, dict]]:
    found = [(p, yaml.safe_load(p.read_text(encoding="utf-8")) or {}) for p in sorted(WORKFLOWS.glob("*.y*ml"))]
    assert len(found) >= 20, "almost no workflows parsed; every guard below would be inert"
    return found


def _triggers(doc: dict) -> set[str]:
    on = doc.get("on", doc.get(True))  # PyYAML reads a bare `on:` key as True
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set(on or {})


def _action(step: dict) -> str:
    return str(step.get("uses", "")).split("@", 1)[0]


def _truthy(value: object) -> bool:
    return value not in (None, False, "", "false", "False")


def _steps() -> list[tuple[str, dict, dict, dict]]:
    """(workflow:job, step, job, workflow doc) for every step in every workflow."""
    rows: list[tuple[str, dict, dict, dict]] = []
    for path, doc in _workflows():
        for name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                rows.append((f"{path.name}:{name}", step, job, doc))
    return rows


STEPS = _steps()


def _is_actions_cache(step: dict) -> bool:
    return _action(step) in {"actions/cache", "actions/cache/restore", "actions/cache/save"}


def _caches(step: dict) -> bool:
    """True when the step can read or write a cache."""
    action = _action(step)
    with_ = step.get("with") or {}
    if _is_actions_cache(step) or action == COMPOSITE:
        return True
    if action in DEFAULT_ON:
        switch, off_value = DEFAULT_ON[action]
        return str(with_.get(switch, "")).lower() != str(off_value).lower()
    return any("cache" in str(key).lower() and _truthy(value) for key, value in with_.items())


ACTIONS_CACHE = [(label, step, job) for label, step, job, _ in STEPS if _is_actions_cache(step)]
SETUP_UV = [(label, step) for label, step, _, _ in STEPS if _action(step) == "astral-sh/setup-uv"]
COMPOSITE_CALLS = [(label, step) for label, step, _, _ in STEPS if _action(step) == COMPOSITE]


def _managed() -> set[str]:
    return {
        f"{label}:{_action(step)}"
        for label, step, _, _ in STEPS
        if _caches(step)
        and not _is_actions_cache(step)
        and _action(step) not in {"astral-sh/setup-uv", COMPOSITE}
    }


def test_the_scans_see_the_caches_that_exist() -> None:
    assert len(STEPS) > 200, f"only {len(STEPS)} steps parsed; the scan is broken"
    assert ACTIONS_CACHE, "no actions/cache step found; the key guards below are inert"
    assert len(SETUP_UV) + len(COMPOSITE_CALLS) >= 10, "almost no setup-uv calls found"
    assert _managed(), "no action-managed cache found; the registry comparison is inert"


@pytest.mark.parametrize("row", ACTIONS_CACHE, ids=[r[0] for r in ACTIONS_CACHE])
def test_an_actions_cache_key_hashes_its_inputs(row: tuple[str, dict, dict]) -> None:
    label, step, _ = row
    key = str((step.get("with") or {}).get("key", ""))
    assert "hashFiles(" in key, (
        f"{label}: cache key {key!r} hashes no file, so it never invalidates when the "
        "lockfile or manifest it was built from changes (CI_POLICY.md §8)"
    )


@pytest.mark.parametrize("row", ACTIONS_CACHE, ids=[r[0] for r in ACTIONS_CACHE])
def test_an_actions_cache_key_names_the_os_and_architecture(row: tuple[str, dict, dict]) -> None:
    label, step, job = row
    key = str((step.get("with") or {}).get("key", ""))
    exception = f"{label}:{_static_prefix(key)}"
    if exception in PLATFORM_INDEPENDENT:
        runs_on = job.get("runs-on")
        assert isinstance(runs_on, str) and "${{" not in runs_on, (
            f"{exception} is listed as platform-independent, but its job now runs on "
            f"{runs_on!r}. That exception was granted for one literal runner; re-justify it."
        )
        return
    missing = [token for token in ("runner.os", "runner.arch") if token not in key]
    assert not missing, (
        f"{label}: cache key {key!r} does not name {missing}, so a cache saved on one OS or "
        "architecture can restore on another. Add them, or list the cache in "
        "PLATFORM_INDEPENDENT with the reason its content is the same everywhere."
    )


@pytest.mark.parametrize("row", ACTIONS_CACHE, ids=[r[0] for r in ACTIONS_CACHE])
def test_a_restore_key_cannot_cross_an_architecture_or_interpreter(row: tuple[str, dict, dict]) -> None:
    label, step, _ = row
    with_ = step.get("with") or {}
    key = str(with_.get("key", ""))
    restore = [line.strip() for line in str(with_.get("restore-keys", "")).splitlines() if line.strip()]
    for prefix in restore:
        assert key.startswith(prefix), (
            f"{label}: restore key {prefix!r} is not a prefix of the key {key!r}, so it can "
            "match entries this key would never have written"
        )
        dropped = [token for token in COMPAT_TOKENS if token in key and token not in prefix]
        assert not dropped, (
            f"{label}: restore key {prefix!r} drops {dropped} from the key, so a fallback "
            "can restore a cache built for another OS, architecture or interpreter"
        )


def test_the_platform_independent_exceptions_still_exist() -> None:
    found = {
        f"{label}:{_static_prefix(str((step.get('with') or {}).get('key', '')))}"
        for label, step, _ in ACTIONS_CACHE
    }
    stale = sorted(PLATFORM_INDEPENDENT.keys() - found)
    assert not stale, f"PLATFORM_INDEPENDENT lists caches that no longer exist: {stale}"
    assert all(reason.strip() for reason in PLATFORM_INDEPENDENT.values())


@pytest.mark.parametrize("row", SETUP_UV, ids=[r[0] for r in SETUP_UV])
def test_setup_uv_callers_leave_the_cache_key_at_its_default(row: tuple[str, dict]) -> None:
    label, step = row
    extra = sorted(set(step.get("with") or {}) - SETUP_UV_INPUTS)
    assert not extra, (
        f"{label} passes {extra} to setup-uv. Those reshape or switch its cache key; record "
        "the decision in CI_POLICY.md §8 'Caches' first, then widen SETUP_UV_INPUTS."
    )


@pytest.mark.parametrize("row", COMPOSITE_CALLS, ids=[r[0] for r in COMPOSITE_CALLS])
def test_composite_callers_pass_only_the_inputs_the_cache_policy_covers(row: tuple[str, dict]) -> None:
    label, step = row
    extra = sorted(set(step.get("with") or {}) - COMPOSITE_INPUTS)
    assert not extra, f"{label} passes {extra} to {COMPOSITE}; see CI_POLICY.md §8 'Caches'"


def test_action_managed_caches_are_exactly_the_justified_ones() -> None:
    found = _managed()
    unlisted = sorted(found - ACTION_MANAGED.keys())
    assert not unlisted, (
        f"{unlisted} read or write a cache whose key the action computes. List each in "
        "ACTION_MANAGED with the reason its key cannot cross an OS, architecture or "
        "interpreter, or turn the cache off on that step."
    )
    stale = sorted(ACTION_MANAGED.keys() - found)
    assert not stale, f"ACTION_MANAGED lists caches that no longer exist: {stale}"
    assert all(reason.strip() for reason in ACTION_MANAGED.values())


@pytest.mark.parametrize("trigger", _PRIVILEGED)
def test_a_privileged_trigger_touches_no_cache(trigger: str) -> None:
    """A cache saved from the default branch's context is restored by `main` and by tag
    runs. A workflow that runs there on a contributor's event must not write one, or it
    is a route from that event into a release job's environment."""
    privileged = [(path, doc) for path, doc in _workflows() if trigger in _triggers(doc)]
    if not privileged:
        pytest.skip(f"no workflow runs on {trigger}")
    hits = [
        f"{path.name}:{name}: {_action(step) or step.get('name')}"
        for path, doc in privileged
        for name, job in (doc.get("jobs") or {}).items()
        for step in job.get("steps") or []
        if _caches(step)
    ]
    assert not hits, f"these {trigger} jobs read or write a cache: {hits}"


def test_the_privileged_scan_sees_privileged_workflows() -> None:
    names = {path.name for path, doc in _workflows() if _triggers(doc) & set(_PRIVILEGED)}
    assert len(names) >= 3, f"only {sorted(names)} run on a privileged trigger; the parse is broken"
