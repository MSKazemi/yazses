"""The one-release window between a version bump and its published assets.

A packaging manifest that pins a SHA256 cannot be refreshed by the commit that
bumps the version: the checksum is of an artefact built *from* the tag, which does
not exist until the tag is pushed and CI has published the release. So between the
release commit and the post-tag `chore(release): refresh the packaging manifests`
commit, a correct tree legitimately says "project X, manifests X-1".

Every guard that holds a committed artefact to "the current release" has to say
what it measures that against. This module is the one answer, and it is read from
the **tree** — `pyproject.toml` and `CHANGELOG.md` — never from git tags, the
environment, or the network.

Why the tree and not the tags (#602). Tags are repository-global state that moves
independently of the commit under test. The Windows manifest guards used to read
the newest tag, so pushing `v2.43.0` turned every pull request red — and every
commit on `main` — for the hours until the refresh commit landed. On 2026-10-17
the OneVoice PRs (#596, #599) failed four packaging tests for a change none of
them made: their base, `d9576a52`, already contained the `v2.43.0` tag commit and
not yet the refresh. Replaying that rule over 203 first-parent commits on `main`
finds 10 that were red for this reason alone; the rule below is red on none.

A tree-only rule gives one commit one verdict, whenever and wherever it runs.
"""

from __future__ import annotations

import re

_RELEASE_HEADING = re.compile(r"(?m)^## \[(\d+\.\d+\.\d+)\]")


def released_versions(changelog_text: str) -> list[str]:
    """Every version a CHANGELOG records as released, newest first.

    `## [Unreleased]` and pre-release headings do not match: only a stable
    `x.y.z` can have been published to a package channel.
    """
    return _RELEASE_HEADING.findall(changelog_text)


def release_window(project_version: str, changelog_text: str) -> frozenset[str]:
    """The versions a post-tag artefact may describe in a tree at `project_version`.

    The project version itself (its refresh has landed) or the release
    immediately before it (the refresh is still in flight) — the width of one
    publish window and nothing wider. A refresh skipped once is caught by the
    *next* release commit, which moves the window past it; that commit is also
    what `release.yml` tests at the tag, so a release cannot ship on top of a
    manifest two releases stale.
    """
    previous = next(
        (v for v in released_versions(changelog_text) if v != project_version), None
    )
    return frozenset({project_version} | ({previous} if previous else set()))
