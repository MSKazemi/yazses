"""Voice-to-Tool planning + confirmation guard (ADR-v2-006) — pure planner."""
from __future__ import annotations

from yazses.agent.plan import ToolCall, ToolSpec, needs_confirm, plan_tool

TOOLS = [
    ToolSpec("run_tests", ("run the tests", "run tests"), writes=False),
    ToolSpec("open_file", ("open file", "open"), writes=False),
    ToolSpec("git_commit", ("commit with message", "commit"), writes=True),
]


def test_plan_matches_tool_and_extracts_argument():
    call = plan_tool("open file config dot toml", TOOLS)
    assert call is not None
    assert call.tool == "open_file"
    assert call.argument == "config dot toml"


def test_plan_prefers_longer_more_specific_trigger():
    # "run the tests" (3 words) beats "run tests"/"open" generic matches
    call = plan_tool("run the tests for auth", TOOLS)
    assert call.tool == "run_tests"
    assert call.argument == "for auth"


def test_plan_returns_none_for_no_match():
    assert plan_tool("what is the weather today", TOOLS) is None


def test_plan_returns_none_for_empty():
    assert plan_tool("", TOOLS) is None
    assert plan_tool("   ", TOOLS) is None


def test_plan_respects_allowlist():
    # git_commit excluded → "commit the changes" finds nothing allowed
    call = plan_tool("commit the changes", TOOLS, allowlist=["run_tests", "open_file"])
    assert call is None
    call2 = plan_tool("commit the changes", TOOLS, allowlist=["git_commit"])
    assert call2 is not None and call2.tool == "git_commit"


def test_plan_ignores_punctuation_and_case():
    call = plan_tool("Run The Tests, please!", TOOLS)
    assert call is not None and call.tool == "run_tests"


# ---- needs_confirm ---------------------------------------------------------

def _call(tool):
    return ToolCall(tool=tool, argument="", score=1.0)


def test_confirm_writes_policy_only_for_mutating_tools():
    assert needs_confirm(_call("git_commit"), TOOLS, "writes") is True
    assert needs_confirm(_call("run_tests"), TOOLS, "writes") is False


def test_confirm_all_and_none_policies():
    assert needs_confirm(_call("run_tests"), TOOLS, "all") is True
    assert needs_confirm(_call("git_commit"), TOOLS, "none") is False


def test_confirm_unknown_policy_defaults_to_safe_all():
    assert needs_confirm(_call("run_tests"), TOOLS, "bogus") is True


def test_trigger_that_normalizes_to_empty_is_skipped():
    # A punctuation-only trigger normalizes to "" and must be skipped, not matched.
    tools = [ToolSpec("noop", ("!!!", "shutdown"), writes=True)]
    assert plan_tool("please just talk normally", tools) is None
    # the real trigger still works
    assert plan_tool("shutdown now", tools).tool == "noop"
