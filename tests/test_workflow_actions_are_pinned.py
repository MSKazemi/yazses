"""Every third-party GitHub Action this repository runs must be pinned to a commit.

A `uses: owner/action@v4` reference resolves through a **mutable tag**. The tag owner
can move it at any time, to any commit, and every workflow in every repository that
names it starts executing the new code on its next run with no diff, no review and no
notification. That is the `tj-actions/changed-files` compromise (CVE-2025-30066,
March 2025) in one sentence: tags from v1 through v45 were retargeted at a commit that
dumped runner memory — including secrets — into the public build log, across tens of
thousands of repositories at once. The published remediation was not "upgrade"; it was
"pin every action to a full commit SHA", because a SHA is the one reference an
upstream account cannot repoint.

This project has a sharper reason than most: it publishes signed release artifacts and
build-provenance attestations. A signature over an artifact built by an action that
silently changed underneath the workflow attests to the wrong thing convincingly.

The policy was already followed by hand in thirteen of the fourteen workflows, which is
exactly the problem this file exists to fix — `docker.yml` was written later, used seven
actions by floating tag, and nothing in the suite noticed, because nothing in the suite
had ever looked. A convention held by memory is not held.

Three properties are asserted, and the second and third are not decoration:

1. **Pinned.** Every non-local `uses:` names a 40-character commit SHA.
2. **Labelled.** Each pin carries a trailing `# <version>` comment. A bare SHA is
   unreviewable — nobody can tell `4d10147…` from `4d10148…`, so a stale pin is
   invisible and a *wrong* one is worse. The comment is also what Dependabot rewrites
   when it bumps the pin, so it is load-bearing rather than cosmetic.
3. **Consistent.** The same (action, SHA) carries the same comment everywhere. A bump
   that moves a SHA in one file and forgets the comment beside it in another shows up
   here as a disagreement, which is the cheapest possible signal that one of them is
   lying.

⚠ The limit of (3), stated plainly because it is not obvious and it has already
mattered: a comment that is **uniformly** wrong passes. Six pins in this repository
were labelled `# v2`, `# v4` and `# release/v1` while pointing at v4.2.2, v7 and
v1.14.2 — and `# v2` was `# v2` at all three of its sites, so no disagreement existed
to find. Deciding whether a SHA really *is* the version beside it means asking GitHub
what that tag resolves to, which needs the network and cannot be a unit test; that is
`scripts/check-action-pins.py`, run by hand and after a Dependabot sweep.

Offline and derived: the workflow directory is read from disk and the rules come out
of the files themselves, so this cannot go stale the way a hand-written list of
workflows would.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"

# `uses: <ref>` optionally followed by `# comment`. Deliberately regex over raw text
# rather than a YAML parse: the version comment is a *comment*, which a YAML loader
# discards, and the comment is half of what is being checked here.
_USES = re.compile(
    r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+?)\s*(?:#\s*(?P<comment>.+?))?\s*$"
)
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert files, f"no workflows found under {WORKFLOWS} -- this guard is blind"
    return files


def _uses_lines() -> list[tuple[Path, int, str, str | None]]:
    """(file, line number, ref, trailing comment) for every non-local `uses:`."""
    found: list[tuple[Path, int, str, str | None]] = []
    for path in _workflow_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = _USES.match(line)
            if not match:
                continue
            ref = match.group("ref").strip("'\"")
            # `./.github/actions/x` and `docker://…` are not tag references at all.
            if ref.startswith((".", "/", "docker://")):
                continue
            found.append((path, number, ref, match.group("comment")))
    return found


USES = _uses_lines()


def test_there_are_workflows_using_third_party_actions() -> None:
    """The three guards below iterate `USES`. If it were ever empty -- a renamed
    directory, a changed suffix, a regex that stopped matching -- all three would pass
    while checking nothing, which is the exact failure they exist to catch."""
    assert len(USES) > 20, f"only {len(USES)} `uses:` lines found; the parser is broken"


def test_every_action_is_pinned_to_a_commit_sha() -> None:
    floating = [
        f"{path.name}:{number}: {ref}"
        for path, number, ref, _ in USES
        if "@" not in ref or not _SHA.match(ref.split("@", 1)[1])
    ]
    assert not floating, (
        "these actions are referenced by a mutable tag or branch, so their upstream "
        "can change what runs here without a diff (CVE-2025-30066):\n  "
        + "\n  ".join(floating)
        + "\nPin to the full commit SHA and add a `# <version>` comment."
    )


def test_every_pin_says_which_version_it_is() -> None:
    unlabelled = [
        f"{path.name}:{number}: {ref}"
        for path, number, ref, comment in USES
        if not comment
    ]
    assert not unlabelled, (
        "these pins carry no version comment, so nobody reviewing them can tell a "
        "current pin from a two-year-old one:\n  " + "\n  ".join(unlabelled)
    )


def test_the_same_pin_is_labelled_the_same_way_everywhere() -> None:
    """A bump that moves the SHA in one file and not the comment in another shows up
    here as a disagreement, which is the only cheap way to notice it."""
    labels: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for path, number, ref, comment in USES:
        if "@" not in ref or not comment:
            continue
        labels[ref][comment.strip()].append(f"{path.name}:{number}")

    conflicts = {ref: seen for ref, seen in labels.items() if len(seen) > 1}
    assert not conflicts, (
        "the same action+SHA is labelled with different versions, so at least one "
        "comment is wrong:\n"
        + "\n".join(
            f"  {ref}\n"
            + "\n".join(f"    # {label} at {', '.join(where)}" for label, where in seen.items())
            for ref, seen in conflicts.items()
        )
    )


# --- the container's base image ---------------------------------------------------
#
# Same argument, different mechanism. `FROM python:3.12-slim` is a moving pointer:
# the image behind that tag is replaced on every Debian and CPython patch, so two
# builds of the same commit can produce different images and the build-provenance
# attestation cannot say which one shipped.

DOCKERFILE = REPO / "packaging" / "docker" / "Dockerfile"
_FROM = re.compile(r"^FROM\s+(?P<image>\S+)", re.MULTILINE)


@pytest.mark.skipif(not DOCKERFILE.exists(), reason="no container is built here")
def test_the_container_base_image_is_pinned_by_digest() -> None:
    images = _FROM.findall(DOCKERFILE.read_text(encoding="utf-8"))
    assert images, f"no FROM lines in {DOCKERFILE} -- this guard is blind"
    floating = [image for image in images if "@sha256:" not in image]
    assert not floating, (
        f"these base images resolve through a mutable tag: {floating}. Pin with "
        "`image:tag@sha256:…` so a build is reproducible and the attestation means "
        "something."
    )


@pytest.mark.skipif(not DOCKERFILE.exists(), reason="no container is built here")
def test_the_pinned_base_image_still_gets_security_updates() -> None:
    """A digest pin with no updater behind it is a base image frozen on the day it was
    written, which trades a reproducibility problem for a patching one. The pin is only
    defensible while Dependabot is watching the directory it lives in."""
    import yaml

    config = yaml.safe_load((REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    docker = [u for u in config["updates"] if u["package-ecosystem"] == "docker"]
    assert docker, (
        "packaging/docker/Dockerfile is pinned by digest but .github/dependabot.yml "
        "has no `docker` ecosystem, so the base image will never receive another "
        "Debian or CPython security patch."
    )
    watched = {u["directory"].rstrip("/") or "/" for u in docker}
    wanted = "/" + str(DOCKERFILE.parent.relative_to(REPO))
    assert wanted in watched, (
        f"Dependabot watches {sorted(watched)} but the Dockerfile is in {wanted}"
    )
