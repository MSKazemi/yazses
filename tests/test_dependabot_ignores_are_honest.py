"""An `ignore` in dependabot.yml is a decision to go without a security fix.

The file used to say the opposite -- that security updates are "NOT limited by this
file" -- and that is wrong. GitHub's reference states Dependabot can be configured to
ignore dependencies "when it opens pull requests for version updates **and security
updates**"; only `update-types` is exempt from that, and `versions:` is not. So an
entry here does not merely quiet the monthly noise, it removes a class of alert.

  https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/controlling-dependencies-updated

These tests hold the two properties that keep that survivable: an ignore must name the
versions it cannot take rather than the whole package, and `onnxruntime` -- the one
dependency whose monthly red job invites a blanket ignore (#322) -- must never acquire a
`versions:` range.

That last distinction is the whole point and it is easy to lose. `onnxruntime` *is*
ignored now, and correctly: an entry naming only `update-types` stops Dependabot
proposing version bumps -- and so stops the resolution that cannot succeed against the
Intel-macOS cap -- while GitHub still opens a security pull request for it, because
`update-types` is the one ignore key exempted from suppressing security updates. Adding
a `versions:` range to that same entry would look like a tightening and would in fact
drop onnxruntime security alerts on Linux, Windows and Apple silicon, where essentially
all users are.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEPENDABOT = ROOT / ".github/dependabot.yml"

#: onnxruntime's Intel-macOS cap makes Dependabot's global `==<version>` pin
#: unsatisfiable, so the monthly `uv` job used to report one handled error every month.
#: The tempting fix is `ignore: onnxruntime >= 1.24`, which would also drop every
#: onnxruntime *security* update on Linux, Windows and Apple silicon -- where the users
#: are. These may be ignored by `update-types` only. See #322 and the comment beside
#: the ignore list.
SECURITY_UPDATES_MUST_SURVIVE = {"onnxruntime"}


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


@pytest.mark.parametrize("name", sorted(SECURITY_UPDATES_MUST_SURVIVE))
def test_a_dependency_that_must_keep_its_security_alerts_is_ignored_by_update_type_only(
    name: str,
) -> None:
    """`update-types` is exempt from suppressing security updates; `versions:` is not.

    So the difference between an ignore that quiets a broken monthly resolution and an
    ignore that hides a CVE is one key -- and the second looks, in a diff, like someone
    being *more* specific.
    """
    entries = [entry for _, entry in _ignores() if entry.get("dependency-name") == name]
    for entry in entries:
        assert not entry.get("versions"), (
            f"{name} is ignored with a `versions:` range. That suppresses its security "
            "pull requests as well as its version updates, on Linux, Windows and Apple "
            "silicon, where essentially all users are. Only `update-types` is exempt "
            "from GitHub's suppression of security updates -- use that alone (#322)."
        )
        assert entry.get("update-types"), (
            f"{name} is ignored with neither `versions:` nor `update-types:`, which "
            "silences it entirely, security advisories included."
        )


def test_ignoring_a_version_update_type_means_ignoring_all_three() -> None:
    """A partial `update-types` list is the failure mode that looks like a fix.

    Every version update is classified as patch, minor or major. An entry naming two of
    the three still lets the third through -- and with it the resolution failure the
    entry was written to stop -- while reading in a diff as though onnxruntime were
    handled.
    """
    levels = {"version-update:semver-patch",
              "version-update:semver-minor",
              "version-update:semver-major"}
    for ecosystem, entry in _ignores():
        declared = set(entry.get("update-types") or [])
        if not declared or entry.get("versions"):
            continue
        assert declared == levels, (
            f"{ecosystem}:{entry['dependency-name']} ignores {sorted(declared)} but not "
            f"{sorted(levels - declared)}. A version bump at the missing level still "
            "opens, so this entry does not do what it looks like it does."
        )


def test_the_file_does_not_repeat_the_claim_that_was_wrong() -> None:
    """The exact sentence that made an ignore look free. Kept as a string so the
    correction cannot be reverted by a copy-paste from an older revision."""
    text = DEPENDABOT.read_text(encoding="utf-8")
    assert "are NOT limited by\n# this file" not in text, (
        "dependabot.yml has regained the claim that security updates are not limited "
        "by this file. They are: an `ignore` entry suppresses security PRs too."
    )
