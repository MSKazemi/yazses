"""An `ignore` in dependabot.yml is a decision to go without a security fix.

The file used to say the opposite -- that security updates are "NOT limited by this
file" -- and that is wrong. GitHub's reference states Dependabot can be configured to
ignore dependencies "when it opens pull requests for version updates **and security
updates**"; only `update-types` is exempt from that, and `versions:` is not. So an
entry here does not merely quiet the monthly noise, it removes a class of alert.

  https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/controlling-dependencies-updated

These tests hold the two properties that keep that survivable: an ignore must name the
versions it cannot take rather than the whole package, and the one dependency whose red
job invites a blanket ignore (#322) must not have acquired one quietly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEPENDABOT = ROOT / ".github/dependabot.yml"

#: onnxruntime's Intel-macOS cap makes Dependabot's global `==<version>` pin
#: unsatisfiable, so the monthly `uv` job reports one handled error. The tempting fix
#: is `ignore: onnxruntime >= 1.24`, which would also drop every onnxruntime update on
#: Linux, Windows and Apple silicon -- where the users are. See #322 and the comment
#: beside the ignore list.
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
        f"{name} has been added to dependabot.yml's ignore list. That stops the "
        "monthly red, and it also stops every legitimate update on the platforms "
        "essentially all users are on. The red is expected and explained in the file; "
        "the fix is a support decision about Intel macOS, not an ignore rule (#322)."
    )


def test_the_file_does_not_repeat_the_claim_that_was_wrong() -> None:
    """The exact sentence that made an ignore look free. Kept as a string so the
    correction cannot be reverted by a copy-paste from an older revision."""
    text = DEPENDABOT.read_text(encoding="utf-8")
    assert "are NOT limited by\n# this file" not in text, (
        "dependabot.yml has regained the claim that security updates are not limited "
        "by this file. They are: an `ignore` entry suppresses security PRs too."
    )
