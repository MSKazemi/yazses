#!/usr/bin/env python3
"""Every test must run in at least one of the environments CI provides.

`tests/test_shipped_backends.py` cannot be exercised by a single environment, and
that is by design rather than by accident. Two of its tests are exact opposites:

* ``test_real_resemblyzer_returns_a_unit_vector_at_both_lengths`` skips unless
  ``import resemblyzer`` works, which needs ``setuptools<81`` -- `resemblyzer` imports
  `webrtcvad`, whose first line is ``import pkg_resources``.
* ``test_a_resemblyzer_that_cannot_import_names_the_remedy_and_stays_dormant`` skips
  unless that import *fails*, because it asserts the failure is turned into the
  one-line remedy instead of a `ModuleNotFoundError` raised three layers down.

So `heavy-extras.yml` runs the file twice -- once on the locked setuptools, which is
what a user gets, and once on the documented remedy -- and the property worth checking
is not "nothing was skipped" (unsatisfiable, and it was the gate for three releases)
but "nothing was skipped in *both*".

Reads pytest's ``--junit-xml`` rather than its terminal output, deliberately. The
first version of this check scanned the human-readable report with ``awk '$2 ==
"SKIPPED"'`` and silently dropped four tests, because a parametrized id can contain
spaces::

    tests/...::test_a_raised_access_failure_gets_the_same_remedy[GatedRepoError-403
    Client Error. Access to model is restricted.] PASSED [ 55%]

It found 32 of 36 and reported success. The XML carries the id in an attribute, so
there is nothing to tokenise.

Usage:  check_extras_coverage.py <first.xml> <second.xml>
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: Below this, a report cannot plausibly be a real run of the file, and comparing two
#: near-empty sets would pass while nothing had been tested. Chosen well under the 36
#: that run today so that deleting a test does not turn the build red for no reason.
MIN_TESTS = 20


def read_report(path: Path) -> tuple[set[str], set[str]]:
    """Return ``(every test id, the skipped ones)`` from a pytest JUnit XML report."""
    root = ET.parse(path).getroot()
    every: set[str] = set()
    skipped: set[str] = set()
    for case in root.iter("testcase"):
        test_id = f"{case.get('classname')}::{case.get('name')}"
        every.add(test_id)
        if case.find("skipped") is not None:
            skipped.add(test_id)
    return every, skipped


def check(reports: list[tuple[str, set[str], set[str]]]) -> list[str]:
    """Return the problems found, empty when the pair is sound.

    A list rather than a dict keyed by filename, because two reports can legitimately
    share a name -- and because keying by it made passing the same file twice collapse
    to one entry, which then crashed on an index rather than failing the way it should.
    Found by the control that runs this against a single report twice.
    """
    problems: list[str] = []

    if len(reports) != 2:
        return [f"expected two reports to compare, got {len(reports)}"]

    for name, every, _ in reports:
        if len(every) < MIN_TESTS:
            problems.append(
                f"{name} reported only {len(every)} tests, which cannot be a real run "
                "of this file -- the comparison below would be comparing nothing."
            )
    if problems:
        return problems

    (first_name, first_all, first_skipped), (second_name, second_all, second_skipped) = reports

    if first_all != second_all:
        problems.append(
            "the two runs collected different tests, so 'skipped in both' is not a "
            f"meaningful question.\n  only in {first_name}: {sorted(first_all - second_all)}"
            f"\n  only in {second_name}: {sorted(second_all - first_all)}"
        )
        return problems

    skipped_everywhere = first_skipped & second_skipped
    if skipped_everywhere:
        problems.append(
            "these tests were skipped in every environment, so they guard nothing "
            "here:\n  " + "\n  ".join(sorted(skipped_everywhere))
        )
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    reports = []
    for name in argv:
        every, skipped = read_report(Path(name))
        reports.append((name, every, skipped))
        print(f"{name}: {len(every)} tests, {len(skipped)} skipped")
        for test_id in sorted(skipped):
            print(f"    skipped: {test_id}")

    problems = check(reports)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1

    print("Every test ran in at least one of the two environments.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
