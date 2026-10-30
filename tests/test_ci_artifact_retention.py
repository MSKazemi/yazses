"""Every uploaded workflow artifact has an intentional lifetime (CI_POLICY.md §8, #537).

An `actions/upload-artifact` step without `retention-days` silently inherits the
repository's setting, which is GitHub's maximum of 90 days on this repository. That is
per-workflow folklore, not a decision: a failure report kept for three months costs
storage, and a reviewer cannot tell from the YAML whether anyone chose it.

The rule: a new upload states `retention-days`. The steps that inherited the default
before the rule existed are listed in `INHERITS_DEFAULT`. The list is compared both ways
with what the workflows actually contain, so a new silent upload fails here, and so does
an entry whose step has since gained a value (delete it then). The steps are read from the
files, so a new workflow is covered the moment it exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

#: The repository's maximum, as `gh api repos/MSKazemi/yazses/actions/permissions/
#: artifact-and-log-retention` read it on 2026-10-30. A larger value is not an error on
#: GitHub's side; it is clamped, which is the same silent decision this test exists to stop.
MAX_DAYS = 90

#: `workflow:job:artifact name` -> why it still inherits. Shrink this list; do not grow it.
INHERITS_DEFAULT: dict[str, str] = {
    "android-test.yml:build:android-test-reports": "failure report; predates the rule",
    "benchmark.yml:bench:results-${{ matrix.os }}": "benchmark numbers; predates the rule",
    "build-windows.yml:build:unsigned-installer-${{ matrix.arch }}": "build lane; predates the rule",
    "flatpak.yml:generate:python3-yazses-json": "consumed by the build job; predates the rule",
    "fuzz.yml:fuzz:fuzz-${{ matrix.harness }}-findings": "crash inputs; predates the rule",
    "release.yml:build-deb:deb-package-${{ matrix.arch }}": "release lane, kept explicit; predates the rule",
}


def _uploads() -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (data.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                    name = (step.get("with") or {}).get("name", "artifact")
                    found.append((f"{path.name}:{job_name}:{name}", step))
    return found


UPLOADS = _uploads()


def test_the_scan_finds_the_uploads() -> None:
    # A guard that iterates is green on an empty collection, so the collection is checked.
    assert len(UPLOADS) >= 10, f"only {len(UPLOADS)} upload-artifact steps found; the scan is broken"
    labels = [label for label, _ in UPLOADS]
    assert len(labels) == len(set(labels)), "two uploads share a label; the ledger cannot tell them apart"


def test_uploads_without_a_retention_are_exactly_the_listed_ones() -> None:
    silent = {label for label, step in UPLOADS if "retention-days" not in (step.get("with") or {})}
    new = sorted(silent - INHERITS_DEFAULT.keys())
    assert not new, (
        f"{new} upload an artifact without `retention-days`, so it lives for the repository "
        "default (90 days). State the lifetime (CI_POLICY.md §8, 'Artifact retention')."
    )
    fixed = sorted(INHERITS_DEFAULT.keys() - silent)
    assert not fixed, f"{fixed} now state `retention-days` or no longer exist; delete their INHERITS_DEFAULT entries"


@pytest.mark.parametrize(
    ("label", "step"),
    [(label, step) for label, step in UPLOADS if "retention-days" in (step.get("with") or {})],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_stated_retention_is_a_whole_number_of_days_github_will_keep(label: str, step: dict) -> None:
    days = step["with"]["retention-days"]
    assert isinstance(days, int) and not isinstance(days, bool), f"{label}: retention-days {days!r} is not a literal integer, so a reviewer cannot read the lifetime"
    assert 1 <= days <= MAX_DAYS, f"{label}: retention-days {days} is outside 1..{MAX_DAYS}"
