"""A release workflow that enumerates major versions dies silently at the next one.

Found by audit on 2026-08-24, by asking a question the YAML cannot answer about
itself: *has this workflow ever actually run?*

    Launchpad PPA   active   runs=0    last=never

`ppa.yml` fires on `tags: ["v0.*"]`, with the comment *"Python v0.x only -- v1.x
handled by rust-release.yml"*. `rust-release.yml` was deleted in `61025cc` when the
Rust line was archived, and the project has been on v1+ ever since. So the trigger
was scoped to a version line that ended, its named successor no longer exists, and
nothing anywhere noticed -- the workflow simply never fired, 0 runs in the repo's
lifetime. Nothing failed, which is exactly why it survived.

`release.yml` and `snap.yml` carry the same shape one major ahead of the blade:

    tags:
      - "v1.*"  # Part 1 owns the 1.x line (Rust release workflow archived)
      - "v2.*"  # v2 Python line (cognitive layer)

That is a list somebody has to remember to extend. On the day `v3.0.0` is tagged,
PyPI and the Snap Store would simply not publish, and the tag would look successful
because *no job ran to fail*. A release that silently does nothing is the worst
failure mode this pipeline has -- v2.30.0 at least went red.

So the invariant is not "these files are correct today" but "these files still fire
for the version after this one". A workflow that genuinely should not fire says so
in its own text, so the exemption lives beside the trigger it explains rather than
in a list here that would drift from it.
"""
from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

#: A workflow that cannot fire for the current major must carry this marker and a
#: reason. Declared in the workflow file so it cannot drift from the trigger.
DISABLED = "RELEASE-TRIGGER-DISABLED:"


def _project_major() -> int:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return int(data["project"]["version"].split(".")[0])


def _tag_patterns(path: Path) -> list[str]:
    """The `on.push.tags` globs of one workflow, or []."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return []
    # `on:` is parsed by YAML 1.1 as the boolean True, not the string "on".
    on = doc.get(True, doc.get("on"))
    if not isinstance(on, dict):
        return []
    push = on.get("push")
    if not isinstance(push, dict):
        return []
    tags = push.get("tags") or []
    return [t for t in tags if isinstance(t, str)]


def _tag_triggered() -> dict[Path, list[str]]:
    return {p: pats for p in sorted(WORKFLOWS.glob("*.yml")) if (pats := _tag_patterns(p))}


def test_the_set_of_tag_triggered_workflows_is_derived_and_non_empty():
    """A sweep that finds nothing reports success. Prove the parse works first."""
    found = _tag_triggered()
    assert found, "no workflow appears to trigger on a tag — the YAML parse is broken"
    names = {p.name for p in found}
    assert "release.yml" in names, f"release.yml is not seen as tag-triggered: {names}"


@pytest.mark.parametrize("offset", [0, 1])
def test_every_tag_triggered_workflow_fires_for_this_major_and_the_next(offset: int):
    """`offset=1` is the whole point: it fails *before* the major bump, not after."""
    major = _project_major() + offset
    tag = f"v{major}.0.0"

    stale = []
    for path, patterns in _tag_triggered().items():
        if any(fnmatch.fnmatch(tag, pat) for pat in patterns):
            continue
        if DISABLED in path.read_text(encoding="utf-8"):
            continue
        stale.append(f"  {path.name:22} tags={patterns}")

    assert not stale, (
        f"these workflows would not fire for {tag}, and a tag that starts no job "
        f"looks exactly like a successful one:\n" + "\n".join(stale) + "\n\n"
        f"Use 'v*' rather than a list of majors somebody must remember to extend. "
        f"If a workflow genuinely should not fire, put '{DISABLED} <reason>' in it."
    )


def test_a_disabled_trigger_states_why():
    """`# RELEASE-TRIGGER-DISABLED:` with nothing after it is a silencer, not a reason."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if DISABLED not in text:
            continue
        reason = text.split(DISABLED, 1)[1].splitlines()[0].strip()
        assert len(reason.split()) >= 6, (
            f"{path.name} disables its release trigger without saying why: {reason!r}"
        )


def test_the_marker_is_what_grants_the_exemption(tmp_path):
    """The probe must be shown to distinguish the two cases, not assumed to.

    A marker check that matched everything (or nothing) would make the test above
    either vacuous or unsatisfiable, and both look green from here.
    """
    dead = "on:\n  push:\n    tags:\n      - 'v0.*'\n"
    assert not fnmatch.fnmatch("v9.0.0", "v0.*")
    assert fnmatch.fnmatch("v9.0.0", "v*")
    assert DISABLED not in dead
    assert DISABLED in dead + f"# {DISABLED} superseded, kept for the archived line\n"
