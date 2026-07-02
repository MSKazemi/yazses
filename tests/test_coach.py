"""Speaking Coach analytics (ADR-v2-035) — pure metrics."""
from __future__ import annotations

from yazses.coach.analytics import (
    analyze,
    count_fillers,
    filler_rate,
    type_token_ratio,
    words_per_minute,
)


def test_count_fillers_single_and_multi():
    # "um" + "like" + "you know" = 3 fillers
    assert count_fillers("um so like you know this is it") == 3


def test_filler_rate():
    # 1 filler ("um") out of 4 words
    assert filler_rate("um hello there friend") == 0.25


def test_filler_rate_empty():
    assert filler_rate("") == 0.0


def test_words_per_minute():
    assert words_per_minute(150, 60.0) == 150.0
    assert words_per_minute(75, 30.0) == 150.0


def test_words_per_minute_zero_duration():
    assert words_per_minute(100, 0.0) == 0.0


def test_type_token_ratio():
    # 4 unique of 6 words ("the the a a b c" -> unique the,a,b,c=4 / 6)
    assert type_token_ratio("the the a a b c") == 4 / 6


def test_type_token_ratio_empty():
    assert type_token_ratio("") == 0.0


def test_analyze_summary():
    s = analyze("um the report the report is done", duration_s=60.0)
    assert s.words == 7
    assert s.filler_count == 1
    assert round(s.filler_rate, 3) == round(1 / 7, 3)
    assert s.wpm == 7.0
    assert 0.0 < s.type_token_ratio <= 1.0


def test_analyze_empty_is_safe():
    s = analyze("", duration_s=0.0)
    assert s.words == 0 and s.filler_rate == 0.0 and s.wpm == 0.0 and s.type_token_ratio == 0.0


def test_aggregate_stats_sums_texts_and_durations():
    from yazses.coach.analytics import aggregate_stats
    s = aggregate_stats([("um the report", 30.0), ("the report is done", 30.0)])
    # 7 words total over 60s → 7 wpm; one filler ("um")
    assert s.words == 7
    assert s.filler_count == 1
    assert round(s.wpm, 1) == 7.0
    assert 0.0 < s.type_token_ratio <= 1.0


def test_aggregate_stats_ignores_empty_and_bad_duration():
    from yazses.coach.analytics import aggregate_stats
    s = aggregate_stats([("", 0.0), (None, -5.0), ("hello world", 0.0)])
    assert s.words == 2 and s.wpm == 0.0


def test_coach_cli_no_corpus(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import yazses.cli as cli

    class _Paths:
        data_dir = tmp_path

    class _Plat:
        paths = _Paths()

    monkeypatch.setattr(cli, "get_platform", lambda: _Plat())
    r = CliRunner().invoke(cli.app, ["coach"], env={"COLUMNS": "220", "TERM": "dumb"})
    assert r.exit_code == 0
    assert "No corpus yet" in r.output


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "coach" in [f.slug for f in feature_status(Config())]
    assert Config().coach.enabled is False
