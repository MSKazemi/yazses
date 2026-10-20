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
def api_issue(number, state="open", milestone=None, pr=False, title="t"):
    raw = {
        "url": f"https://api.github.com/repos/MSKazemi/yazses/issues/{number}",
        "number": number,
        "title": title,
        "state": state,
        "user": {"login": "MSKazemi"},
        "labels": [],
        "milestone": None,
    }
    if milestone is not None:
        raw["milestone"] = {"number": milestone, "title": f"M{milestone}", "state": "open"}
    if pr:
        raw["pull_request"] = {"url": raw["url"].replace("/issues/", "/pulls/")}
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
