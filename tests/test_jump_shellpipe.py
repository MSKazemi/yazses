"""Voice Jump-to-Symbol (ADR-v2-081) + Spoken Shell Pipeline Builder (ADR-v2-082) — pure cores."""
from __future__ import annotations

from yazses.jump.target import Motion, Target, fuzzy_pick, plan_motion, resolve_target
from yazses.shellpipe.build import dryrun_wrap, parse_stages, render_pipeline

# ---- jump to symbol --------------------------------------------------------

def test_resolve_target_line():
    assert resolve_target("go to line 240") == Target("line", 240)
    assert resolve_target("line three") == Target("line", 3)


def test_resolve_target_symbol_and_search():
    assert resolve_target("jump to function tokenize") == Target("symbol", "tokenize")
    assert resolve_target("go to class Parser".lower()) == Target("symbol", "parser")
    assert resolve_target("find the config loader") == Target("search", "the config loader")
    assert resolve_target("hello there") is None


def test_fuzzy_pick():
    syms = ["tokenize", "normalize", "parse_config"]
    assert fuzzy_pick("tokenise", syms) == "tokenize"
    assert fuzzy_pick("zzzz", syms) is None
    assert fuzzy_pick("x", []) is None


def test_plan_motion():
    assert plan_motion(Target("line", 10)) == Motion("goto_line", 10)
    assert plan_motion(Target("search", "foo")) == Motion("search", "foo")
    assert plan_motion(Target("symbol", "tokenise"), ["tokenize"]) == Motion("goto_symbol", "tokenize")
    # no symbol list → search fallback
    assert plan_motion(Target("symbol", "whatever"), []) == Motion("search", "whatever")
    assert plan_motion(None) is None


# ---- shell pipeline builder ------------------------------------------------

def test_parse_stages():
    assert parse_stages("list files, pipe to grep error, pipe to word count") == [
        "list files", "grep error", "word count"]
    assert parse_stages("list files then sort") == ["list files", "sort"]


def test_render_pipeline():
    stages = parse_stages("list files, pipe to grep error, pipe to word count")
    assert render_pipeline(stages) == "ls | grep error | wc -l"


def test_render_pipeline_quotes_and_unknown():
    assert render_pipeline(["grep foo bar"]) == "grep 'foo bar'"       # shlex-quoted
    assert render_pipeline(["do a barrel roll"]) is None               # unknown stage → abort
    assert render_pipeline([]) is None


def test_dryrun_wrap():
    assert dryrun_wrap("rm -rf build") == "rm -i -rf build"
    assert dryrun_wrap("ls | wc -l") == "ls | wc -l"                   # read-only unchanged
    assert dryrun_wrap("") == ""


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "jump" in slugs and "shellpipe" in slugs
    assert Config().jump.enabled is False and Config().shellpipe.enabled is False
