"""Echo (ADR-v2-119) + SRPace (ADR-v2-120) — pure cores."""
from __future__ import annotations

from yazses.echo.span import Span, build_span_index, resolve_playback_target
from yazses.srpace.schedule import Chunk, chunk_clauses, plan_injection_schedule


# ---- echo -------------------------------------------------------------------

WORDS = [("hello", 0.0, 0.4), ("there", 0.5, 0.9), ("world", 1.0, 1.5)]


def test_build_span_index_char_and_time():
    spans = build_span_index(WORDS)
    assert spans[0] == Span("hello", 0, 5, 0.0, 0.4)
    assert spans[1] == Span("there", 6, 11, 0.5, 0.9)      # one separating space
    assert spans[2].char_start == 12 and spans[2].char_end == 17
    assert build_span_index([]) == []


def test_resolve_last_first_and_whole():
    spans = build_span_index(WORDS)
    assert resolve_playback_target("play the last word", spans) == (1.0, 1.5)
    assert resolve_playback_target("play the first word", spans) == (0.0, 0.4)
    assert resolve_playback_target("play that back", spans) == (0.0, 1.5)   # whole clip
    assert resolve_playback_target("play that word", spans) == (1.0, 1.5)   # 'that word' → last


def test_resolve_by_token_and_quote():
    spans = build_span_index(WORDS)
    assert resolve_playback_target("repeat 'there'", spans) == (0.5, 0.9)
    assert resolve_playback_target("play world", spans) == (1.0, 1.5)
    assert resolve_playback_target("play nonexistent", spans) == (0.0, 1.5)  # no match → whole


def test_resolve_empty_guards():
    assert resolve_playback_target("play", []) is None
    assert resolve_playback_target("", build_span_index(WORDS)) is None


# ---- srpace -----------------------------------------------------------------

def test_chunk_clauses():
    assert chunk_clauses("Hello, world. Bye!") == ["Hello,", "world.", "Bye!"]
    assert chunk_clauses("   ") == []
    assert chunk_clauses("one clause only") == ["one clause only"]


def test_plan_schedule_cumulative_delays():
    sched = plan_injection_schedule("Hello, world. Bye!", wpm=180, min_chunk_ms=200)
    assert [c.text for c in sched] == ["Hello,", "world.", "Bye!"]
    assert sched[0].delay_ms == 0
    assert sched[1].delay_ms == 333                        # one word at 180 wpm = 333ms
    assert sched[2].delay_ms == 666
    # a 1-word chunk below the floor uses min_chunk_ms
    floored = plan_injection_schedule("a. b.", wpm=600, min_chunk_ms=200)
    assert floored[1].delay_ms == 200
    assert all(isinstance(c, Chunk) for c in sched)


def test_plan_schedule_wpm_scaling_and_disabled():
    fast = plan_injection_schedule("a b c d e f g h i j k l", wpm=600, min_chunk_ms=10)
    slow = plan_injection_schedule("a b c d e f g h i j k l", wpm=60, min_chunk_ms=10)
    assert slow[-1].delay_ms >= fast[-1].delay_ms          # slower reader → later (or equal)
    disabled = plan_injection_schedule("one. two. three.", wpm=0)
    assert len(disabled) == 1 and disabled[0].delay_ms == 0
    assert plan_injection_schedule("", wpm=180) == []


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "echo" in slugs and "srpace" in slugs
    assert Config().echo.enabled is False and Config().srpace.enabled is False
    assert Config().srpace.wpm == 180.0
