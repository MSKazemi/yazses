"""Send to (ADR-031): the closed target table, the URL, the limits and the trigger.

Everything here is the pure half, `sendto/targets.py`, so nothing is opened and nothing
is mocked. The tests are about the ways the hand-off could stop being a *local, reviewed*
hand-off:

* a destination nobody chose — a target added at runtime, a configurable URL, an
  `https://` fallback that would carry the text to a server before review;
* a different prompt from the one dictated — hostile characters ending the parameter
  early, a fragment swallowing the tail, or a silent truncation;
* a sentence the user meant to *type* being claimed as a trigger.
"""

from __future__ import annotations

import dataclasses
import re
from urllib.parse import parse_qsl, quote, urlsplit

import pytest

from yazses.config import Config, SendtoConfig
from yazses.sendto.targets import (
    CLAUDE_MAX_CHARS,
    FORBIDDEN_SCHEMES,
    MAX_URL_CHARS,
    TARGETS,
    Refusal,
    choose_text,
    parse_send_phrase,
    percent_encode,
    plan_handoff,
    resolve_target,
    target_names,
)

#: Text chosen to break a naive URL builder, one way each.
HOSTILE = [
    "line one\nline two\r\nline three",            # newlines
    "a & b=c&q=evil&prompt=evil",                  # parameter injection
    "see issue #42 # and the rest",                # fragment
    "100% sure, %41 is not A, %%",                 # literal percent signs
    "+plus+ and spaces",                           # '+' must not become a space
    "?q=second&x=y",                               # a second query
    "naïve café — ünïcode ✓ 漢字 🎤",               # non-ASCII, CJK, emoji
    "שלום ‮evil‬ سلام ‏ end",       # RTL text and bidi controls
    "zero​width‍joiner",                 # zero-width characters
    '"double" \'single\' <tag> `tick` {brace}',    # quoting characters
    "back\\slash / slash ; semi : colon",          # path-ish characters
    "javascript:alert(1)",                         # a scheme inside the text
    "-leading dash",                               # webbrowser refuses a URL that starts with '-'
    "a\tb",                                        # an inner tab is kept
]


# ---- the closed table --------------------------------------------------------


def test_the_targets_are_exactly_the_three_the_adr_names():
    assert target_names() == ("claude", "claude-code", "codex")
    assert set(TARGETS) == {"claude", "claude-code", "codex"}


@pytest.mark.parametrize(
    ("slug", "prefix"),
    [
        ("claude", "claude://claude.ai/new?q="),
        ("claude-code", "claude://code/new?q="),
        ("codex", "codex://new?prompt="),
    ],
)
def test_each_target_builds_its_documented_url(slug, prefix):
    plan = plan_handoff(slug, "hello")
    assert plan.ok
    assert plan.url == prefix + "hello"


def test_no_target_uses_a_web_or_file_scheme():
    """No `https://` fallback, ever: a web URL transmits the text before review."""
    for target in TARGETS.values():
        assert target.scheme not in FORBIDDEN_SCHEMES, target
        assert "https" not in target.url_for("x") and "http:" not in target.url_for("x")


def test_the_table_cannot_be_extended_at_runtime():
    with pytest.raises(TypeError):
        TARGETS["evil"] = TARGETS["claude"]  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        TARGETS["claude"].scheme = "https"  # type: ignore[misc]


def test_the_config_section_cannot_name_a_url():
    """A configurable template would be a configurable exfiltration endpoint (§2)."""
    assert [f.name for f in dataclasses.fields(SendtoConfig)] == ["enabled"]


def test_send_to_is_off_by_default():
    assert Config().sendto.enabled is False


@pytest.mark.parametrize("name", ["claude", "Claude", " CLAUDE ", "claude-code", "codex"])
def test_target_names_resolve_case_insensitively(name):
    assert resolve_target(name) is not None


@pytest.mark.parametrize(
    "name", ["", "chatgpt", "gemini", "https", "claude_code", "claude code", "clau", "codex2"]
)
def test_anything_else_is_not_a_target(name):
    assert resolve_target(name) is None
    plan = plan_handoff(name, "hello")
    assert plan.refusal is Refusal.UNKNOWN_TARGET
    assert plan.url == ""


# ---- encoding -----------------------------------------------------------------


@pytest.mark.parametrize("text", HOSTILE)
def test_the_encoding_matches_the_standard_library(text):
    """Hand-rolled to keep `urllib` out of the scanned tree; the stdlib defines correct."""
    assert percent_encode(text) == quote(text, safe="")


@pytest.mark.parametrize("slug", ["claude", "claude-code", "codex"])
@pytest.mark.parametrize("text", HOSTILE)
def test_hostile_text_round_trips_as_exactly_one_parameter(slug, text):
    plan = plan_handoff(slug, text)
    assert plan.ok, plan.detail
    target = TARGETS[slug]
    parts = urlsplit(plan.url)
    assert parts.scheme == target.scheme
    assert parts.fragment == "", "a '#' in the text must not start a fragment"
    assert parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True) == [
        (target.param, text.strip())
    ]


@pytest.mark.parametrize("text", HOSTILE)
def test_the_encoded_value_is_plain_ascii_with_no_separators(text):
    plan = plan_handoff("claude", text)
    value = plan.url.split("?", 1)[1].split("=", 1)[1]
    assert re.fullmatch(r"(?:[A-Za-z0-9\-._~]|%[0-9A-F]{2})*", value), value
    assert plan.url.count("?") == 1 and plan.url.count("=") == 1
    assert not plan.url.startswith("-")


def test_outer_whitespace_is_trimmed_and_nothing_else_changes():
    plan = plan_handoff("codex", "  \n  keep  inner   spacing \t\n")
    assert plan.ok
    assert plan.chars == len("keep  inner   spacing")
    assert plan.url == "codex://new?prompt=" + quote("keep  inner   spacing", safe="")


# ---- refusals -----------------------------------------------------------------


@pytest.mark.parametrize("slug", ["claude", "claude-code", "codex"])
def test_text_at_the_limit_is_accepted(slug):
    plan = plan_handoff(slug, "x" * CLAUDE_MAX_CHARS)
    assert plan.ok
    assert plan.chars == CLAUDE_MAX_CHARS


@pytest.mark.parametrize("slug", ["claude", "claude-code", "codex"])
def test_text_over_the_limit_is_refused_never_cut(slug):
    plan = plan_handoff(slug, "x" * (CLAUDE_MAX_CHARS + 1))
    assert plan.refusal is Refusal.TOO_LONG
    assert plan.url == "", "a refusal must not carry a (truncated) URL"
    assert "14,001" in plan.detail and "14,000" in plan.detail
    assert "nothing was cut" in plan.detail


def test_the_limit_counts_the_trimmed_text():
    assert plan_handoff("claude", "   " + "x" * CLAUDE_MAX_CHARS + "\n\n").ok


def test_a_url_that_would_exceed_the_desktop_ceiling_is_refused():
    """One emoji is twelve characters once encoded; the character limit alone is not enough."""
    text = "🎤" * 3000
    assert len(text) < CLAUDE_MAX_CHARS
    plan = plan_handoff("claude", text)
    assert plan.refusal is Refusal.URL_TOO_LONG
    assert plan.url == ""
    assert f"{MAX_URL_CHARS:,}" in plan.detail


def test_cjk_text_under_the_url_ceiling_is_accepted():
    plan = plan_handoff("claude", "漢" * 3000)  # 9 characters each once encoded
    assert plan.ok
    assert len(plan.url) <= MAX_URL_CHARS


@pytest.mark.parametrize("text", ["", "   ", "\n\t\n"])
def test_empty_text_is_refused(text):
    plan = plan_handoff("claude", text)
    assert plan.refusal is Refusal.EMPTY
    assert plan.url == ""


@pytest.mark.parametrize("text", ["a\x00b", "a\x1bb", "a\x07b", "a\x7fb", "a\x0bb"])
def test_control_characters_are_refused_not_stripped(text):
    plan = plan_handoff("claude", text)
    assert plan.refusal is Refusal.INVALID_TEXT
    assert plan.url == ""


def test_tab_newline_and_carriage_return_are_allowed():
    assert plan_handoff("claude", "a\tb\nc\r\nd").ok


def test_a_lone_surrogate_is_refused():
    """What `sys.argv` carries for bytes that are not valid UTF-8."""
    plan = plan_handoff("claude", "abc\udc80def")
    assert plan.refusal is Refusal.INVALID_TEXT
    assert plan.url == ""


def test_no_refusal_detail_quotes_the_text():
    secret = "SECRETPROMPTzebra"
    for plan in (
        plan_handoff("claude", secret * 1000),
        plan_handoff("claude", secret + "\x00"),
        plan_handoff("claude", secret + "\udc80"),
        plan_handoff("claude", secret + "🎤" * 3000),
    ):
        assert not plan.ok
        assert secret not in plan.detail


# ---- the spoken trigger -------------------------------------------------------


@pytest.mark.parametrize(
    ("utterance", "slug"),
    [
        ("send to Claude", "claude"),
        ("Send to Claude.", "claude"),
        ("  send to claude!  ", "claude"),
        ("SEND TO CLAUDE CODE", "claude-code"),
        ("Send to Claude Code.", "claude-code"),
        ("send  to  Claude   Code", "claude-code"),
        ("send to Codex", "codex"),
        ("Send to codex.", "codex"),
    ],
)
def test_each_fixed_phrase_names_its_target(utterance, slug):
    assert parse_send_phrase(utterance) == slug


@pytest.mark.parametrize(
    "utterance",
    [
        "",
        "send to",
        "please send to Claude",
        "send to Claude the draft",
        "send to Claude, please",
        "I will send to Claude tomorrow",
        "send it to Claude",
        "send that to Claude",
        "send to cloud",
        "send to ChatGPT",
        "send to Gemini",
        "send to Claude?",
        "send to Claude Codex",
        "send to claude-code",
    ],
)
def test_nothing_but_the_whole_phrase_is_claimed(utterance):
    """An unanchored match would hand off a sentence the user meant to type."""
    assert parse_send_phrase(utterance) is None


# ---- which text ---------------------------------------------------------------


def test_staged_mode_uses_the_buffer():
    choice = choose_text(staged_enabled=True, staged_text="staged words", last_burst="old")
    assert (choice.text, choice.source) == ("staged words", "staged")


def test_an_empty_buffer_does_not_fall_back_to_an_older_burst():
    choice = choose_text(staged_enabled=True, staged_text="", last_burst="older burst")
    assert (choice.text, choice.source) == ("", "staged")


def test_without_staged_mode_the_last_burst_is_used():
    choice = choose_text(staged_enabled=False, staged_text="ignored", last_burst=" last one")
    assert (choice.text, choice.source) == (" last one", "last_burst")
