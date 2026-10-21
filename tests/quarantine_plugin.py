"""The pytest half of the quarantine policy (#538, CI_POLICY.md §9.3).

`tests/conftest.py` calls `install()`, which registers `QuarantinePlugin`. It does three things
and nothing else:

* registers the `quarantine` marker, so `pytest --markers` documents it;
* **still runs** every quarantined test. When an honoured quarantine's test fails in its call
  phase, the failure is reported as an expected failure (`XFAIL`) carrying the issue, owner and
  expiry, so it does not block; a pass is reported as a pass. Setup and teardown errors are not
  downgraded -- a broken fixture is not the flake that was quarantined;
* prints a "quarantined tests" section at the end of every run that touched one, and appends
  the same table to `$GITHUB_STEP_SUMMARY` when CI provides it. Quarantined coverage stays on
  the page instead of disappearing into a skip count.

A marker that is expired, unregistered, incomplete or disagrees with `tests/quarantine.toml` is
**not honoured**: the test runs as an ordinary blocking test and the section says why.
`tests/test_flake_policy.py` fails on the same conditions statically, so the gate goes red with
an explanation rather than with a mystery.

The rules themselves live in `tests/flake_policy.py`; this file only applies them.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from tests import flake_policy

PLUGIN_NAME = "yazses-quarantine"
_PROPERTY = "quarantine"

Record = tuple[str, str, "flake_policy.Quarantine | None", list[str]]


def install(config: pytest.Config) -> None:
    """Register the marker and the plugin once (idempotent)."""
    if config.pluginmanager.has_plugin(PLUGIN_NAME):
        return
    config.addinivalue_line(
        "markers",
        "quarantine(issue, owner, reason, expires): run the test but do not let its failure "
        "block, while the dated exception in tests/quarantine.toml lasts (CI_POLICY.md §9.3)",
    )
    path = Path(config.rootpath) / flake_policy.REGISTRY_RELPATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    config.pluginmanager.register(
        QuarantinePlugin(flake_policy.parse_registry(text), dt.date.today()), PLUGIN_NAME
    )


#: Lets `pytest -p tests.quarantine_plugin` load it outside this repository's conftest.
pytest_configure = install


class QuarantinePlugin:
    def __init__(self, registry: flake_policy.Registry, today: dt.date) -> None:
        self.registry = registry
        self.today = today
        self.records: dict[str, dict] = {}

    def _resolve(
        self, item: pytest.Item
    ) -> tuple[flake_policy.Quarantine | None, list[str]] | None:
        marker = item.get_closest_marker(flake_policy.MARKER)
        if marker is None:
            return None
        problems = list(self.registry.problems)
        if marker.args:
            problems.append(f"{item.nodeid}: pass issue=, owner=, reason=, expires= as keywords")
        quarantine, more = flake_policy.resolve(
            marker.kwargs, item.nodeid, self.registry, today=self.today
        )
        problems += more
        return (None if problems else quarantine), problems

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo):
        report = yield
        resolved = self._resolve(item)
        if resolved is None:
            return report
        quarantine, problems = resolved
        if report.when == "call" and report.failed and quarantine is not None:
            report.outcome = "skipped"
            report.wasxfail = (
                f"quarantined: #{quarantine.issue}, owner {quarantine.owner}, expires "
                f"{quarantine.expires.isoformat()} -- {quarantine.reason}"
            )
            outcome = "failed"
        elif report.when == "call":
            outcome = "failed" if report.failed else ("skipped" if report.skipped else "passed")
        elif report.when == "setup" and not report.passed:
            outcome = "error" if report.failed else "skipped"
        elif report.when == "teardown" and report.failed:
            outcome = "error"
        else:
            return report
        report.user_properties.append(
            (
                _PROPERTY,
                json.dumps(
                    {
                        "outcome": outcome,
                        "issue": quarantine.issue if quarantine else None,
                        "owner": quarantine.owner if quarantine else None,
                        "reason": quarantine.reason if quarantine else None,
                        "expires": quarantine.expires.isoformat() if quarantine else None,
                        "problems": problems,
                    }
                ),
            )
        )
        return report

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # Read from the report rather than the item, so a distributed run would still gather
        # every worker's results in the controlling process.
        for name, value in report.user_properties:
            if name == _PROPERTY:
                self.records[report.nodeid] = json.loads(value)

    def as_records(self) -> list[Record]:
        records: list[Record] = []
        for nodeid, data in sorted(self.records.items()):
            quarantine = None
            if data["issue"] is not None:
                quarantine = flake_policy.Quarantine(
                    test=nodeid,
                    issue=data["issue"],
                    owner=data["owner"],
                    reason=data["reason"],
                    expires=dt.date.fromisoformat(data["expires"]),
                )
            records.append((nodeid, data["outcome"], quarantine, data["problems"]))
        return records

    def pytest_terminal_summary(self, terminalreporter) -> None:
        records = self.as_records()
        if not records:
            return
        terminalreporter.write_sep(
            "=", f"quarantined tests ({len(records)}; CI_POLICY.md §9.3, tests/quarantine.toml)"
        )
        for line in flake_policy.summary_lines(records):
            terminalreporter.write_line(line)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(flake_policy.summary_markdown(records))
