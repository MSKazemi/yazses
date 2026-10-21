"""The live traceability audit: decision logic and HTTP handling, with NO network.

`scripts/check-traceability-live.py` asks GitHub whether the issues and milestones named by
`design/traceability.yml` still look the way the manifest says. The ordinary suite must stay
offline, so everything here runs against recorded-style payloads and a scripted fake opener;
an autouse fixture makes any real socket connection a test failure rather than a quiet
dependency on GitHub's uptime.

The distinction this file protects: a transient outage (exit 2) must never read as a
traceability violation (exit 1), and a misconfiguration (exit 3) must be neither.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import socket
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-traceability-live.py"
WORKFLOW = ROOT / ".github" / "workflows" / "traceability.yml"
MANIFEST = ROOT / "design" / "traceability.yml"
EXCEPTIONS = ROOT / "design" / "traceability-exceptions.yml"

TOKEN = "ghs_SECRETTOKENVALUE0123456789"


def _load():
    spec = importlib.util.spec_from_file_location("check_traceability_live", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # @dataclass resolves string annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


live = _load()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("test attempted a real network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ---- recorded-style payloads (trimmed to the fields the API really returns) -------------
def api_issue(number, state="open", milestone=None, pr=False, title="t", labels=(), body=None,
              merged=None, parent=None):
    raw = {
        "url": f"https://api.github.com/repos/MSKazemi/yazses/issues/{number}",
        "number": number,
        "title": title,
        "state": state,
        "user": {"login": "MSKazemi"},
        "labels": [{"id": i, "name": name, "color": "ededed"} for i, name in enumerate(labels)],
        "milestone": None,
        "body": body,
    }
    if milestone is not None:
        raw["milestone"] = {"number": milestone, "title": f"M{milestone}", "state": "open"}
    if pr:
        raw["pull_request"] = {"url": raw["url"].replace("/issues/", "/pulls/"),
                               "merged_at": merged}
    if parent is not None:
        # The REST listing names a sub-issue's parent this way (and omits the key otherwise).
        raw["parent_issue_url"] = f"https://api.github.com/repos/MSKazemi/yazses/issues/{parent}"
    return raw


def api_milestone(number, state="open"):
    return {"number": number, "title": f"M{number}", "state": state, "open_issues": 1}


def entry(eid="programme:x", delivery="in-progress", issues=(10,), milestone=9, kind="issue"):
    return {
        "id": eid,
        "kind": "programme",
        "delivery_status": delivery,
        "tracking": {"kind": kind, "issues": list(issues), "task": None, "milestone": milestone},
    }


def world(issues=(), milestones=(9,)):
    return (
        live.parse_issues(list(issues)),
        live.parse_milestones([api_milestone(n) for n in milestones]),
    )


def run_audit(entries, issues=(), milestones=(9,), exceptions=None, today=None):
    iss, ms = world(issues, milestones)
    return live.audit({"version": 1, "entries": entries}, iss, ms, exceptions, today)


def rules(result):
    return sorted((f.rule, f.entry) for f in result.findings)


# ---- parsing ---------------------------------------------------------------------------
def test_parse_issues_keeps_state_milestone_and_pull_request_flag():
    facts = live.parse_issues(
        [api_issue(1, milestone=9), api_issue(2, "closed"), api_issue(3, pr=True)]
    )
    assert facts[1].milestone == 9 and facts[1].state == "open"
    assert facts[2].state == "closed" and facts[2].milestone is None
    assert facts[3].is_pull_request and not facts[1].is_pull_request


@pytest.mark.parametrize(
    "bad",
    [
        ["not-an-object"],
        [{"number": "7", "state": "open"}],
        [{"number": 7, "state": "weird"}],
        [{"number": 7, "state": "open", "milestone": "9"}],
        [{"number": 7, "state": "open", "milestone": {"number": "9"}}],
    ],
)
def test_malformed_issue_payload_is_unavailable_not_a_violation(bad):
    with pytest.raises(live.LiveStateUnavailable):
        live.parse_issues(bad)


def test_malformed_milestone_payload_is_unavailable():
    with pytest.raises(live.LiveStateUnavailable):
        live.parse_milestones([{"number": 1, "state": "???"}])


def test_link_header_next_page():
    header = (
        '<https://api.github.com/repositories/1/issues?page=2>; rel="next", '
        '<https://api.github.com/repositories/1/issues?page=9>; rel="last"'
    )
    assert live.parse_link_next(header) == "https://api.github.com/repositories/1/issues?page=2"
    assert live.parse_link_next('<https://x/?page=1>; rel="prev"') is None
    assert live.parse_link_next(None) is None


def test_locate_entries_finds_every_committed_entry_line():
    text = MANIFEST.read_text(encoding="utf-8")
    ids = [e["id"] for e in yaml.safe_load(text)["entries"]]
    lines = live.locate_entries(text)
    assert set(lines) == set(ids)
    assert text.splitlines()[lines["programme:android"] - 1].strip().startswith("- id:")


# ---- the decision ----------------------------------------------------------------------
def test_a_healthy_world_has_no_findings():
    result = run_audit([entry()], [api_issue(10, milestone=9)])
    assert result.findings == [] and live.exit_code_for(result) == live.EXIT_OK
    assert result.entries_checked == 1 and result.issues_referenced == 1


def test_missing_issue():
    result = run_audit([entry()], [api_issue(11, milestone=9)])
    assert rules(result) == [("ISSUE_MISSING", "programme:x")]
    assert result.findings[0].issue == 10


def test_pull_request_is_not_an_issue():
    result = run_audit([entry()], [api_issue(10, milestone=9, pr=True)])
    assert rules(result) == [("ISSUE_IS_PULL_REQUEST", "programme:x")]


@pytest.mark.parametrize("delivery", ["scheduled", "in-progress", "designed", "blocked", "research"])
def test_closed_sole_tracker_of_active_work(delivery):
    result = run_audit([entry(delivery=delivery, milestone=None)], [api_issue(10, "closed")])
    assert rules(result) == [("NO_OPEN_TRACKER", "programme:x")]


@pytest.mark.parametrize("delivery", ["shipped", "deferred", "not-planned"])
def test_closed_tracker_is_fine_for_terminal_delivery(delivery):
    result = run_audit([entry(delivery=delivery, milestone=None)], [api_issue(10, "closed")])
    assert result.findings == []


def test_one_open_tracker_among_closed_ones_is_enough():
    result = run_audit(
        [entry(issues=(10, 11), milestone=None)], [api_issue(10, "closed"), api_issue(11)]
    )
    assert result.findings == []


def test_missing_milestone():
    result = run_audit([entry(milestone=42)], [api_issue(10, milestone=9)])
    assert rules(result) == [("MILESTONE_MISSING", "programme:x")]
    assert result.findings[0].milestone == 42


def test_milestone_mismatch_names_the_actual_and_declared_milestone():
    result = run_audit([entry()], [api_issue(10, milestone=3)], milestones=(3, 9))
    (finding,) = result.findings
    assert finding.rule == "MILESTONE_MISMATCH" and finding.issue == 10
    assert "milestone 3" in finding.message and "milestone 9" in finding.message


def test_open_issue_with_no_milestone_when_one_is_declared():
    result = run_audit([entry()], [api_issue(10)])
    (finding,) = result.findings
    assert finding.rule == "MILESTONE_MISMATCH" and "no milestone" in finding.message


def test_closed_issue_milestone_is_history_not_a_mismatch():
    result = run_audit(
        [entry(issues=(10, 11))], [api_issue(10, "closed", milestone=3), api_issue(11, milestone=9)],
        milestones=(3, 9),
    )
    assert result.findings == []


def test_no_declared_milestone_means_no_milestone_requirement():
    """Research entries declare none; the audit invents no policy that they need one."""
    result = run_audit([entry(delivery="research", milestone=None)], [api_issue(10)])
    assert result.findings == []


def test_entries_with_nothing_live_to_check_are_skipped():
    bare = entry(delivery="deferred", issues=(), milestone=None, kind="none")
    result = run_audit([bare])
    assert result.findings == [] and result.entries_checked == 0


def test_committed_manifest_against_a_consistent_world_is_clean_and_against_closed_164_is_not():
    """Vacuity anchor: the audit really reads the committed manifest's fields."""
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    declared: dict[int, int | None] = {}
    milestones = set()
    for e in manifest["entries"]:
        t = e["tracking"]
        for n in t["issues"]:
            declared[n] = t["milestone"]
        if t["milestone"] is not None:
            milestones.add(t["milestone"])
    assert declared and milestones
    healthy = [api_issue(n, milestone=m) for n, m in declared.items()]
    iss, ms = world(healthy, milestones)
    assert live.audit(manifest, iss, ms).findings == []

    closed = [api_issue(n, "closed" if n == 164 else "open", milestone=m)
              for n, m in declared.items()]
    iss, _ = world(closed, milestones)
    broken = live.audit(manifest, iss, ms)
    assert broken.findings and {f.rule for f in broken.findings} == {"NO_OPEN_TRACKER"}
    assert all("164" in f.message for f in broken.findings)


# ---- exceptions ------------------------------------------------------------------------
def _exc(**over):
    base = {"rule": "MILESTONE_MISMATCH", "entry": "programme:x", "issue": 10,
            "reason": "epic spans milestones", "tracker": 480}
    base.update(over)
    return live.parse_exceptions({"version": 1, "exceptions": [base]})


def test_committed_exceptions_file_is_valid_and_empty_by_default():
    assert live.parse_exceptions(yaml.safe_load(EXCEPTIONS.read_text(encoding="utf-8"))) == []


def test_an_exception_suppresses_exactly_what_it_names_and_stays_visible():
    result = run_audit([entry()], [api_issue(10, milestone=3)], milestones=(3, 9),
                       exceptions=_exc())
    assert result.findings == [] and len(result.suppressed) == 1
    report = live.render_report(result)
    assert "allowed [MILESTONE_MISMATCH]" in report and "#480" in report


def test_an_exception_for_another_rule_entry_or_issue_does_not_apply():
    for exc in (_exc(rule="NO_OPEN_TRACKER"), _exc(entry="programme:y"), _exc(issue=99)):
        result = run_audit([entry()], [api_issue(10, milestone=3)], milestones=(3, 9),
                           exceptions=exc)
        assert rules(result) == [("MILESTONE_MISMATCH", "programme:x")]
        assert result.unused == exc


def test_an_exception_without_an_issue_covers_every_issue_of_the_entry():
    result = run_audit([entry(issues=(10, 11))],
                       [api_issue(10, milestone=3), api_issue(11)], milestones=(3, 9),
                       exceptions=_exc(issue=None))
    assert result.findings == [] and len(result.suppressed) == 2


def test_expired_exception_no_longer_applies_and_is_reported():
    exc = _exc(expires=dt.date(2026, 1, 1))
    result = run_audit([entry()], [api_issue(10, milestone=3)], milestones=(3, 9),
                       exceptions=exc, today=dt.date(2026, 6, 1))
    assert rules(result) == [("MILESTONE_MISMATCH", "programme:x")]
    assert result.expired == exc and "expired exception" in live.render_report(result)


def test_unused_exception_is_reported_so_the_allowlist_cannot_rot():
    result = run_audit([entry()], [api_issue(10, milestone=9)], exceptions=_exc())
    assert result.findings == [] and "unused exception" in live.render_report(result)


@pytest.mark.parametrize(
    "bad",
    [
        {"version": 2, "exceptions": []},
        {"version": 1, "exceptions": "nope"},
        {"version": 1, "exceptions": [{"rule": "NOPE", "entry": "a", "reason": "r", "tracker": 1}]},
        {"version": 1, "exceptions": [{"rule": "ISSUE_MISSING", "entry": "a", "tracker": 1}]},
        {"version": 1, "exceptions": [{"rule": "ISSUE_MISSING", "entry": "a", "reason": "r"}]},
        {"version": 1, "exceptions": [{"rule": "ISSUE_MISSING", "entry": "a", "reason": "  ",
                                       "tracker": 1}]},
    ],
)
def test_malformed_exceptions_are_a_config_error(bad):
    with pytest.raises(live.AuditConfigError):
        live.parse_exceptions(bad)


# ---- rendering -------------------------------------------------------------------------
def test_report_names_entry_issue_line_and_points_at_the_manifest():
    result = run_audit([entry()], [api_issue(10, milestone=3)], milestones=(3, 9))
    report = live.render_report(result, {"programme:x": 123})
    assert "programme:x" in report and "#10" in report
    assert "design/traceability.yml:123" in report
    assert "design/traceability-exceptions.yml" in report


def test_unavailable_and_config_messages_say_they_are_not_violations():
    assert "NOT a traceability violation" in live.render_unavailable("HTTP 503")
    assert "not a traceability violation" in live.render_config_error("bad token")


# ---- HTTP layer: scripted opener, no sockets ---------------------------------------------
class FakeResponse:
    def __init__(self, body, headers=None):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def http_error(code, headers=None):
    return urllib.error.HTTPError("https://api.github.com/x", code, "msg", headers or {},
                                  io.BytesIO(b""))


class Script:
    """An opener that plays back a list of responses/exceptions and records requests."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests: list[Any] = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def client(script, token=TOKEN, sleeps=None):
    return live.GitHubClient(
        "MSKazemi/yazses", token, opener=script,
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
    )


def test_pagination_follows_next_links_and_only_issues_get_requests():
    nxt = "https://api.github.com/repositories/1/issues?page=2"
    script = Script(
        FakeResponse([api_issue(1)], {"Link": f'<{nxt}>; rel="next"'}),
        FakeResponse([api_issue(2, "closed")]),
    )
    facts = client(script).issues()
    assert set(facts) == {1, 2}
    assert [r.full_url for r in script.requests][1] == nxt
    assert all(r.get_method() == "GET" for r in script.requests)
    first = script.requests[0].full_url
    assert "state=all" in first and "per_page=100" in first and "direction=asc" in first


def test_one_list_request_per_resource_not_one_per_manifest_entry():
    script = Script(FakeResponse([api_issue(n) for n in range(1, 60)]), FakeResponse([]))
    c = client(script)
    c.issues()
    c.milestones()
    assert len(script.requests) == 2


def test_transient_5xx_is_retried_then_succeeds():
    sleeps: list[float] = []
    script = Script(http_error(503), http_error(502), FakeResponse([api_issue(1)]))
    assert set(client(script, sleeps=sleeps).issues()) == {1}
    assert len(script.requests) == 3 and len(sleeps) == 2


@pytest.mark.parametrize(
    "failure",
    [
        http_error(503),
        http_error(429, {"Retry-After": "1"}),
        http_error(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1"}),
        urllib.error.URLError("connection reset"),
        TimeoutError("timed out"),
    ],
)
def test_persistent_transient_failure_is_unavailable_not_config(failure):
    script = Script(failure, failure, failure)
    with pytest.raises(live.LiveStateUnavailable):
        client(script).issues()


def test_truncated_json_body_is_unavailable():
    script = Script(*[FakeResponse(b'[{"number": 1, ') for _ in range(3)])
    with pytest.raises(live.LiveStateUnavailable):
        client(script).issues()


@pytest.mark.parametrize("code", [401, 403, 404, 301, 422])
def test_fatal_statuses_are_config_errors_and_are_not_retried(code):
    script = Script(http_error(code), FakeResponse([]))
    with pytest.raises(live.AuditConfigError):
        client(script).issues()
    assert len(script.requests) == 1


def test_a_long_rate_limit_wait_gives_up_instead_of_sleeping_for_an_hour():
    sleeps: list[float] = []
    script = Script(http_error(429, {"Retry-After": "3600"}))
    with pytest.raises(live.LiveStateUnavailable):
        client(script, sleeps=sleeps).issues()
    assert sleeps == [] and len(script.requests) == 1


def test_classify_failure_policy():
    assert live.classify_failure(503, {}) == "transient"
    assert live.classify_failure(429, {}) == "transient"
    assert live.classify_failure(403, {"X-RateLimit-Remaining": "0"}) == "transient"
    assert live.classify_failure(403, {}) == "fatal"
    assert live.classify_failure(404, {}) == "fatal"


def test_a_pagination_link_off_the_api_host_is_refused_so_the_token_cannot_leak():
    evil = "https://evil.example/steal?page=2"
    script = Script(FakeResponse([api_issue(1)], {"Link": f'<{evil}>; rel="next"'}))
    with pytest.raises(live.LiveStateUnavailable):
        client(script).issues()
    assert len(script.requests) == 1


def test_runaway_pagination_is_reported_as_truncated_not_complete(monkeypatch):
    monkeypatch.setattr(live, "MAX_PAGES", 3)
    nxt = "https://api.github.com/repositories/1/issues?page=2"
    page = FakeResponse([], {"Link": f'<{nxt}>; rel="next"'})
    with pytest.raises(live.LiveStateUnavailable, match="truncated"):
        client(Script(page, page, page, page)).issues()


def test_client_rejects_non_https_api_and_bad_repo():
    with pytest.raises(live.AuditConfigError):
        live.GitHubClient("MSKazemi/yazses", TOKEN, api_url="http://api.github.com")
    with pytest.raises(live.AuditConfigError):
        live.GitHubClient("not a repo", TOKEN)


def test_token_is_sent_only_as_a_bearer_header_and_never_in_an_error():
    script = Script(http_error(401))
    with pytest.raises(live.AuditConfigError) as info:
        client(script).issues()
    assert TOKEN not in str(info.value)
    assert script.requests[0].get_header("Authorization") == f"Bearer {TOKEN}"
    assert TOKEN not in script.requests[0].full_url


def test_default_opener_never_follows_redirects():
    handler = live._NoRedirect()
    assert handler.redirect_request(None, None, 301, "m", {}, "https://evil.example/") is None


# ---- end to end through run(): exit codes and output ------------------------------------
def _factory(script):
    return lambda repo, token, api: live.GitHubClient(
        repo, token, api, opener=script, sleep=lambda _s: None
    )


def _manifest_file(tmp_path, entries):
    path = tmp_path / "traceability.yml"
    path.write_text(yaml.safe_dump({"version": 1, "entries": entries}), encoding="utf-8")
    return path


def _valid_entry(**over):
    base = {
        "id": "programme:x", "kind": "programme", "title": "X", "source": "design/README.md",
        "decision_status": "accepted", "delivery_status": "in-progress",
        "tracking": {"kind": "issue", "issues": [10], "task": None, "milestone": 9},
    }
    base.update(over)
    return base


def _run(tmp_path, steps, capsys, monkeypatch, entries=None, extra=()):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    manifest = _manifest_file(tmp_path, entries or [_valid_entry()])
    code = live.run(
        ["--manifest", str(manifest), "--exceptions", str(tmp_path / "none.yml"), *extra],
        client_factory=_factory(Script(*steps)),
    )
    out = capsys.readouterr()
    return code, out.out + out.err


def test_exit_0_when_everything_matches(tmp_path, capsys, monkeypatch):
    steps = [FakeResponse([api_issue(10, milestone=9)]), FakeResponse([api_milestone(9)])]
    code, text = _run(tmp_path, steps, capsys, monkeypatch)
    assert code == 0 and "OK" in text and TOKEN not in text


def test_exit_1_for_a_real_violation_and_output_names_the_entry(tmp_path, capsys, monkeypatch):
    steps = [FakeResponse([api_issue(10, "closed")]), FakeResponse([api_milestone(9)])]
    code, text = _run(tmp_path, steps, capsys, monkeypatch)
    assert code == 1
    assert "NO_OPEN_TRACKER" in text and "programme:x" in text and "#10" in text
    assert "design/traceability.yml" in text and TOKEN not in text


def test_exit_2_for_an_outage_with_a_message_that_is_not_a_violation(tmp_path, capsys, monkeypatch):
    code, text = _run(tmp_path, [http_error(503)] * 3, capsys, monkeypatch)
    assert code == 2 and "NOT a traceability violation" in text
    assert "NO_OPEN_TRACKER" not in text and TOKEN not in text


def test_exit_3_for_a_bad_token(tmp_path, capsys, monkeypatch):
    code, text = _run(tmp_path, [http_error(401)], capsys, monkeypatch)
    assert code == 3 and "configuration problem" in text and TOKEN not in text


def test_exit_3_when_the_manifest_is_invalid_even_if_github_would_be_fine(
    tmp_path, capsys, monkeypatch
):
    bad = _valid_entry(delivery_status="scheduled",
                       tracking={"kind": "none", "issues": [], "task": None, "milestone": None})
    code, text = _run(tmp_path, [], capsys, monkeypatch, entries=[bad])
    assert code == 3 and "offline check" in text


def test_summary_file_receives_the_report(tmp_path, capsys, monkeypatch):
    summary = tmp_path / "summary.md"
    steps = [FakeResponse([api_issue(10, milestone=9)]), FakeResponse([api_milestone(9)])]
    code, _ = _run(tmp_path, steps, capsys, monkeypatch, extra=("--summary-file", str(summary)))
    assert code == 0 and "OK" in summary.read_text(encoding="utf-8")


# ---- the workflow contract ---------------------------------------------------------------
@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_runs_on_schedule_and_by_hand_only(wf):
    triggers = wf[True]  # YAML 1.1 parses `on:` as boolean True
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] and "cron" in triggers["schedule"][0]


def test_workflow_token_is_read_only_and_uses_no_secrets(wf):
    expected = {"contents": "read", "issues": "read"}
    assert wf["permissions"] == expected
    job = wf["jobs"]["audit"]
    assert job["permissions"] == expected
    assert "secrets." not in WORKFLOW.read_text(encoding="utf-8")


def test_workflow_follows_the_scheduled_assurance_policy(wf):
    job = wf["jobs"]["audit"]
    assert job["timeout-minutes"] <= 15
    assert wf["concurrency"] == {"group": "traceability-live", "cancel-in-progress": False}
    run_steps = [s["run"] for s in job["steps"] if "run" in s]
    audit_step = next(r for r in run_steps if "check-traceability-live.py" in r)
    assert "|" not in audit_step, "a pipe would replace the script's exit code with tee's"
    assert "github.event" not in WORKFLOW.read_text(encoding="utf-8")


def test_script_only_issues_get_requests_and_does_not_touch_the_product():
    text = SCRIPT.read_text(encoding="utf-8")
    for verb in ("POST", "PATCH", "PUT", "DELETE"):
        assert f'method="{verb}"' not in text
    assert "import yazses" not in text and "from yazses" not in text


def test_workflow_uploads_the_json_report_even_on_a_red_night(wf):
    """The artifact is the drift report's second home; a red exit must not skip it."""
    steps = wf["jobs"]["audit"]["steps"]
    audit_step = next(s for s in steps if "check-traceability-live.py" in s.get("run", ""))
    assert "--json-file traceability-live.json" in audit_step["run"]
    assert "--summary-file" in audit_step["run"]
    upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "${{ !cancelled() }}"
    assert upload["with"]["path"] == "traceability-live.json"
    assert upload["with"]["name"] == "traceability-live"
    assert not any(s.get("continue-on-error") for s in steps)


# ---- advisory drift: per-issue observations that never change the exit code ---------------
# Synthetic bodies modelled on the live banner shape (no real issue text is copied here).
BANNER = (
    "> **Current status: PLANNED — do not start yet.** #500 and #501 must merge first.\n"
    "> When blockers clear, maintainers may add `help wanted`.\n"
    "\n"
    "## Goal\n\nDo the thing; see also #900 for background.\n"
)


def drift(issues=(), entries=(), policy=None):
    iss, _ = world(issues)
    return live.evaluate_drift({"entries": list(entries)}, iss, policy)


def drift_rules(found):
    return sorted((d.rule, d.issue) for d in found)


def stale_of(found):
    return [d for d in found if d.rule == "STALE_DO_NOT_START"]


def test_parse_issues_keeps_labels_body_and_merge_state():
    facts = live.parse_issues([
        api_issue(1, labels=("research", "epic"), body="hello"),
        api_issue(2, "closed", pr=True, merged="2026-09-25T00:40:00Z"),
        api_issue(3, "closed", pr=True, merged=None),
    ])
    assert facts[1].labels == ("research", "epic") and facts[1].body == "hello"
    assert facts[2].is_pull_request and facts[2].merged
    assert facts[3].is_pull_request and not facts[3].merged


@pytest.mark.parametrize(
    "bad",
    [
        [{"number": 7, "state": "open", "labels": "bug"}],
        [{"number": 7, "state": "open", "labels": [{"name": 3}]}],
        [{"number": 7, "state": "open", "body": 42}],
    ],
)
def test_malformed_labels_or_body_are_unavailable_not_drift(bad):
    with pytest.raises(live.LiveStateUnavailable):
        live.parse_issues(bad)


def test_banner_blockers_reads_the_banner_and_not_the_rest_of_the_body():
    assert live.banner_blockers(BANNER, 456) == [500, 501]


def test_no_banner_means_none_and_a_banner_without_references_means_empty():
    assert live.banner_blockers("## Goal\n\nBlocked by #5.\n") is None
    assert live.banner_blockers("> Do not start this yet.\n") == []
    assert live.banner_blockers("") is None


def test_banner_blockers_adds_the_blocked_by_section_and_ignores_code_and_foreign_refs():
    body = (
        "> **PLANNED — don't start until #10 lands.** See MSKazemi/other#11 and #456.\n\n"
        "## Blocked by\n\n- #12 — schema\n- #10 again\n\n"
        "## Notes\n\n- #13 is unrelated\n\n"
        "```\n> do not start #14\n```\n"
    )
    assert live.banner_blockers(body, 456) == [10, 12]


def test_a_do_not_start_sentence_outside_a_blockquote_is_not_a_banner():
    assert live.banner_blockers("Do not start with a multi-platform backend (#3).\n") is None


def test_stale_banner_fires_only_when_every_blocker_is_closed():
    both_closed = [api_issue(456, body=BANNER, milestone=9),
                   api_issue(500, "closed", pr=True, merged="2026-09-25T00:40:00Z"),
                   api_issue(501, "closed")]
    (stale,) = stale_of(drift(both_closed)[0])
    assert stale.issue == 456
    assert "#500 (PR merged)" in stale.message and "#501 (closed)" in stale.message

    one_open = [api_issue(456, body=BANNER, milestone=9), api_issue(500, "closed"),
                api_issue(501)]
    assert stale_of(drift(one_open)[0]) == []


def test_an_unknown_blocker_keeps_the_banner_quiet():
    found, _, _ = drift([api_issue(456, body=BANNER, milestone=9), api_issue(500, "closed")])
    assert stale_of(found) == []


def test_a_closed_unmerged_pull_request_blocker_is_named_as_abandoned():
    issues = [api_issue(456, body=BANNER, milestone=9),
              api_issue(500, "closed", pr=True, merged=None), api_issue(501, "closed")]
    (stale,) = stale_of(drift(issues)[0])
    assert "#500 (PR closed unmerged)" in stale.message


def test_a_closed_issue_with_a_banner_is_history_not_drift():
    found, _, _ = drift([api_issue(456, "closed", body=BANNER), api_issue(500, "closed"),
                         api_issue(501, "closed")])
    assert found == []


def test_unmilestoned_open_issues_are_listed_and_prs_closed_and_milestoned_ones_are_not():
    found, open_count, _ = drift([
        api_issue(1), api_issue(2, milestone=9), api_issue(3, "closed"), api_issue(4, pr=True),
    ])
    assert drift_rules(found) == [("UNMILESTONED_UNCLASSIFIED", 1)]
    assert open_count == 2


def test_an_exempt_class_label_suppresses_and_an_unused_one_is_reported():
    policy = live.IssuePolicy(frozenset({"research", "evergreen"}))
    found, _, unused = drift([api_issue(1, labels=("research",)), api_issue(2)], policy=policy)
    assert drift_rules(found) == [("UNMILESTONED_UNCLASSIFIED", 2)]
    assert unused == ["evergreen"]


def test_topical_labels_never_exempt_an_unmilestoned_issue():
    """Only `epic` / `evergreen:<class>` exempt (#480); `research` is a topic, not a class."""
    found, _, unused = drift([api_issue(1, labels=("research", "documentation"))])
    assert drift_rules(found) == [("UNMILESTONED_UNCLASSIFIED", 1)] and unused == []


def test_closed_tracker_reference_beside_an_open_one():
    e = entry(issues=(10, 11), milestone=None)
    found, _, _ = drift([api_issue(10, "closed"), api_issue(11, milestone=9)], [e])
    assert drift_rules(found) == [("CLOSED_TRACKER_REFERENCE", 10)]
    assert found[0].entry == "programme:x"


def test_all_closed_is_the_blocking_rule_not_drift_and_terminal_entries_are_skipped():
    all_closed = drift([api_issue(10, "closed")], [entry(issues=(10,), milestone=None)])[0]
    assert [d for d in all_closed if d.rule == "CLOSED_TRACKER_REFERENCE"] == []
    shipped = entry(delivery="shipped", issues=(10, 11), milestone=None)
    found, _, _ = drift([api_issue(10, "closed"), api_issue(11, milestone=9)], [shipped])
    assert found == []


def test_drift_never_changes_the_exit_code():
    result = run_audit(
        [entry()],
        [api_issue(10, milestone=9), api_issue(20), api_issue(456, body=BANNER, milestone=9),
         api_issue(500, "closed"), api_issue(501, "closed")],
    )
    assert result.findings == [] and len(result.drift) == 2
    assert live.exit_code_for(result) == live.EXIT_OK
    report = live.render_report(result)
    assert "Advisory only" in report and "#480" in report
    assert "UNMILESTONED_UNCLASSIFIED (1)" in report and "STALE_DO_NOT_START (1)" in report


def test_an_issue_title_cannot_break_out_of_the_summary_code_fence():
    found, _, _ = drift([api_issue(1, title="```\n# injected\n" + "x" * 200)])
    message = found[0].message
    assert "`" not in message and "\n" not in message and len(message) < 200


def test_committed_policy_is_valid_and_names_no_class_yet():
    data = yaml.safe_load(EXCEPTIONS.read_text(encoding="utf-8"))
    assert live.parse_issue_policy(data) == live.IssuePolicy()
    assert "issue_policy" in data, "the #480 hook must be visible in the committed file"


@pytest.mark.parametrize(
    "bad",
    [
        {"version": 1, "issue_policy": ["research"]},
        {"version": 1, "issue_policy": {"exempt_labels": "research"}},
        {"version": 1, "issue_policy": {"exempt_labels": ["", "x"]}},
        {"version": 1, "issue_policy": {"exempt_issues": [22]}},
    ],
)
def test_malformed_issue_policy_is_a_config_error(bad):
    with pytest.raises(live.AuditConfigError):
        live.parse_issue_policy(bad)


def test_end_to_end_drift_reaches_summary_and_json_with_exit_0(tmp_path, capsys, monkeypatch):
    summary, report = tmp_path / "summary.md", tmp_path / "report.json"
    steps = [
        FakeResponse([api_issue(10, milestone=9), api_issue(20, title="lonely")]),
        FakeResponse([api_milestone(9)]),
    ]
    code, text = _run(tmp_path, steps, capsys, monkeypatch,
                      extra=("--summary-file", str(summary), "--json-file", str(report)))
    assert code == 0 and "UNMILESTONED_UNCLASSIFIED" in text
    assert "#20" in summary.read_text(encoding="utf-8")
    doc = json.loads(report.read_text(encoding="utf-8"))
    assert doc["status"] == "ok" and doc["exit_code"] == 0
    assert doc["manifest"] == "design/traceability.yml"
    assert [(d["rule"], d["issue"]) for d in doc["drift"]] == [("UNMILESTONED_UNCLASSIFIED", 20)]


@pytest.mark.parametrize(
    ("steps", "code", "status"),
    [
        ([FakeResponse([api_issue(10, "closed")]), FakeResponse([api_milestone(9)])], 1,
         "violations"),
        ([http_error(503)] * 3, 2, "not-checked"),
        ([http_error(401)], 3, "cannot-run"),
    ],
)
def test_json_is_written_for_every_exit_code(tmp_path, capsys, monkeypatch, steps, code, status):
    report = tmp_path / "report.json"
    got, _ = _run(tmp_path, steps, capsys, monkeypatch, extra=("--json-file", str(report)))
    text = report.read_text(encoding="utf-8")
    doc = json.loads(text)
    assert got == code and doc["exit_code"] == code and doc["status"] == status
    assert TOKEN not in text
    if code == 1:
        (violation,) = doc["violations"]
        assert violation["rule"] == "NO_OPEN_TRACKER"
        assert violation["location"].startswith("design/traceability.yml")
    else:
        assert doc["reason"] and doc["violations"] == [] and doc["drift"] == []


# ---- the milestone policy (#480) applied to the live listing: advisory, fixture-based ------
FIXTURES = ROOT / "tests" / "fixtures" / "traceability_live"


def fixture_world():
    """A synthetic REST-shaped listing covering every #480 class (no real issue text)."""
    issues = json.loads((FIXTURES / "policy_issues.json").read_text(encoding="utf-8"))
    milestones = json.loads((FIXTURES / "policy_milestones.json").read_text(encoding="utf-8"))
    return issues, milestones


def fixture_audit():
    issues, milestones = fixture_world()
    return live.audit(
        {"version": 1, "entries": [entry()]},
        live.parse_issues(issues, repo="MSKazemi/yazses"),
        live.parse_milestones(milestones),
    )


def policy_rules(result):
    return sorted((v.rule, v.issue) for v in live.policy_violations(result))


def test_parent_issue_url_names_the_sub_issue_parent_in_the_same_repository():
    issues, _ = fixture_world()
    facts = live.parse_issues(issues, repo="MSKazemi/yazses")
    assert facts[41].parent == 40 and facts[51].parent == 50
    assert facts[40].parent is None and facts[60].parent is None  # key absent: not a sub-issue


def test_a_parent_in_another_repository_is_not_matched_to_a_local_number():
    raw = api_issue(5)
    raw["parent_issue_url"] = "https://api.github.com/repos/someone/else/issues/40"
    assert live.parse_issues([raw], repo="MSKazemi/yazses")[5].parent is None
    assert live.parse_issues([raw])[5].parent == 40  # no repo given: taken as is
    raw["parent_issue_url"] = "https://api.github.com/repos/mskazemi/YAZSES/issues/40"
    assert live.parse_issues([raw], repo="MSKazemi/yazses")[5].parent == 40


@pytest.mark.parametrize("bad", [42, "https://api.github.com/repos/MSKazemi/yazses/pulls/4"])
def test_an_unreadable_parent_link_is_unavailable_not_a_finding(bad):
    raw = api_issue(5)
    raw["parent_issue_url"] = bad
    with pytest.raises(live.LiveStateUnavailable):
        live.parse_issues([raw])


def test_every_open_issue_gets_exactly_one_policy_class():
    result = fixture_audit()
    assert result.policy.classes == {
        10: "delivery", 30: "evergreen:field-report", 31: "evergreen:research", 40: "epic",
        41: "delivery", 42: "delivery", 50: "epic", 51: "delivery", 60: "delivery",
        61: "delivery", 70: "epic", 80: "delivery",
    }  # the PR (#90) and the closed issue (#91) are not classified


def test_evergreen_and_epic_issues_are_not_reported_unmilestoned():
    result = fixture_audit()
    unmilestoned = sorted(d.issue for d in result.drift if d.rule == "UNMILESTONED_UNCLASSIFIED")
    assert unmilestoned == [60, 61]  # unlabelled and topic-labelled delivery work only


def test_unlabelled_and_invalid_class_issues_are_still_flagged():
    found, _, _ = drift([
        api_issue(1), api_issue(2, labels=("evergreen:wishlist",)),
        api_issue(3, labels=("epic", "evergreen:community")), api_issue(4, labels=("epic",)),
        api_issue(5, labels=("evergreen:translation",)),
    ])
    assert drift_rules(found) == [
        ("UNMILESTONED_UNCLASSIFIED", 1), ("UNMILESTONED_UNCLASSIFIED", 2),
        ("UNMILESTONED_UNCLASSIFIED", 3),
    ]


def test_policy_violations_are_derived_from_the_listing():
    assert policy_rules(fixture_audit()) == [
        ("EPIC_MILESTONE_MISSING", 50),  # its only open child is in M9, so it owes M9
        ("EVERGREEN_WITH_MILESTONE", 31),
        ("MILESTONE_CLOSED", 80),
    ]  # epic #40 spans M8 and M9 and rightly carries none: no violation


def test_an_epic_carrying_one_milestone_while_a_child_sits_in_another_spans():
    iss, ms = world(
        [api_issue(1, labels=("epic",), milestone=9), api_issue(2, milestone=9, parent=1),
         api_issue(3, milestone=8, parent=1)],
        milestones=(8, 9),
    )
    result = live.audit({"version": 1, "entries": []}, iss, ms)
    assert policy_rules(result) == [("EPIC_SPANS_MILESTONES", 1)]


def test_an_epic_with_no_open_sub_issue_is_unverified_never_passing():
    result = fixture_audit()
    assert result.policy.unverified_epics == [70]
    assert "unverified epic(s) #70" in live.render_report(result)


def test_delivery_without_milestone_is_reported_once_under_the_drift_name():
    result = fixture_audit()
    assert "DELIVERY_WITHOUT_MILESTONE" in {v.rule for v in result.policy.violations}
    assert all(v.rule != "DELIVERY_WITHOUT_MILESTONE" for v in live.policy_violations(result))
    report = live.render_report(result)
    assert "[DELIVERY_WITHOUT_MILESTONE]" not in report
    assert "listed above as UNMILESTONED_UNCLASSIFIED" in report


def test_policy_violations_appear_in_the_summary_and_never_change_the_exit_code():
    result = fixture_audit()
    assert result.findings == [] and live.exit_code_for(result) == live.EXIT_OK
    report = live.render_report(result)
    section = report[report.index("Milestone policy (#480"):]
    assert "Advisory only" in section and "design/milestone-policy.md" in section
    assert "3 violation(s)" in section
    for rule, number in policy_rules(result):
        assert f"[{rule}] #{number}:" in section


def test_end_to_end_policy_reaches_summary_and_json_with_exit_0(tmp_path, capsys, monkeypatch):
    issues, milestones = fixture_world()
    summary, report = tmp_path / "summary.md", tmp_path / "report.json"
    code, text = _run(
        tmp_path, [FakeResponse(issues), FakeResponse(milestones)], capsys, monkeypatch,
        extra=("--summary-file", str(summary), "--json-file", str(report)),
    )
    assert code == 0 and "EPIC_MILESTONE_MISSING" in text
    assert "[EVERGREEN_WITH_MILESTONE] #31" in summary.read_text(encoding="utf-8")
    doc = json.loads(report.read_text(encoding="utf-8"))
    assert doc["status"] == "ok"
    policy = doc["milestone_policy"]
    assert policy["policy"] == "design/milestone-policy.md"
    assert policy["classes"] == {"delivery": 7, "epic": 3, "evergreen:field-report": 1,
                                 "evergreen:research": 1}
    assert [(v["rule"], v["issue"]) for v in policy["violations"]] == [
        ("EVERGREEN_WITH_MILESTONE", 31), ("EPIC_MILESTONE_MISSING", 50),
        ("MILESTONE_CLOSED", 80),
    ]
    assert policy["unverified_epics"] == [70]
    unmilestoned = [d["issue"] for d in doc["drift"] if d["rule"] == "UNMILESTONED_UNCLASSIFIED"]
    assert sorted(unmilestoned) == [60, 61]


def test_the_policy_module_is_the_one_check_traceability_loads():
    """One classifier, not two: the live audit uses scripts/milestone_policy.py itself."""
    module = live._milestone_policy()
    assert module is sys.modules["milestone_policy"]
    assert Path(module.__file__).resolve() == ROOT / "scripts" / "milestone_policy.py"
