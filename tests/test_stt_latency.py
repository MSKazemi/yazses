"""Decode-latency percentiles for `yazses status` (#296).

The point of the feature is that a mean lies about how dictation feels, so the
tests are mostly about the tail and about not overclaiming: a p95 nobody should
trust is not printed, and the sample count never gets lost on the way to the
screen.
"""

from __future__ import annotations

import pytest

from yazses.stt.latency import (
    DEFAULT_WINDOW,
    MIN_SAMPLES_FOR_P95,
    LatencyWindow,
    percentile,
    render_status_lines,
    summarise,
)

# ---- the percentile itself -------------------------------------------------


def test_the_percentile_is_a_latency_that_actually_happened():
    """Nearest-rank, not interpolated: p95 names a real wait, not an average."""
    values = [100.0, 200.0, 300.0]
    assert percentile(values, 0.5) in values
    assert percentile(values, 0.95) in values


def test_the_median_of_an_odd_sample_is_the_middle_one():
    assert percentile([10.0, 30.0, 20.0], 0.5) == 20.0


def test_the_tail_is_not_averaged_away():
    """The bug this guards: a mean over a right-skewed sample reads as 'fine'.

    Ten decodes in a hundred taking three seconds is a dictation experience
    people abandon, and the mean of that sample is 390 ms — a number that looks
    perfectly healthy.
    """
    samples = [100.0] * 90 + [3000.0] * 10
    summary = summarise("small.en", samples)
    assert summary is not None
    mean = sum(samples) / len(samples)
    assert summary.p50_ms == 100.0
    assert summary.p95_ms == 3000.0, "the slow decodes are the whole experience"
    assert mean < 400.0, "…and a mean would have hidden them"


def test_a_tail_thinner_than_five_percent_sits_below_the_p95():
    """Not a bug — the definition. One slow decode in twenty is not the p95."""
    summary = summarise("small.en", [100.0] * 19 + [3000.0])
    assert summary is not None
    assert summary.p95_ms == 100.0
    assert summary.max_ms == 3000.0, "which is why max is reported alongside it"


def test_floating_point_does_not_shift_the_rank():
    """0.95 * 20 is 18.999999999999996 in binary floating point."""
    values = [float(i) for i in range(1, 21)]
    assert percentile(values, 0.95) == 19.0


def test_extremes_are_clamped_rather_than_indexing_off_the_end():
    values = [1.0, 2.0, 3.0]
    assert percentile(values, 0.0) == 1.0
    assert percentile(values, 1.0) == 3.0


def test_a_percentile_of_nothing_is_an_error_not_a_zero():
    """Zero would read as "instant", which is the opposite of "unknown"."""
    with pytest.raises(ValueError):
        percentile([], 0.5)


# ---- not overclaiming ------------------------------------------------------


def test_a_p95_over_too_few_samples_is_not_reported():
    summary = summarise("base.en", [100.0] * (MIN_SAMPLES_FOR_P95 - 1))
    assert summary is not None
    assert summary.p95_ms is None
    assert summary.p95_is_reportable is False
    assert summary.count == MIN_SAMPLES_FOR_P95 - 1


def test_the_p95_appears_as_soon_as_there_is_enough_to_support_it():
    summary = summarise("base.en", [100.0] * MIN_SAMPLES_FOR_P95)
    assert summary is not None and summary.p95_ms is not None


def test_the_count_always_travels_with_the_numbers():
    """Printing a percentile without its n invites reading it as one."""
    summary = summarise("tiny.en", [50.0] * 5)
    assert summary is not None
    assert "n=5" in summary.describe()
    assert "too few for p95" in summary.describe()


def test_no_samples_summarises_to_nothing_rather_than_to_zeros():
    assert summarise("tiny.en", []) is None


# ---- the window ------------------------------------------------------------


def test_models_are_kept_apart():
    """Mixing them would answer 'which model should I run' with an average."""
    window = LatencyWindow()
    for _ in range(30):
        window.record("tiny.en", 100.0)
        window.record("small.en", 900.0)
    by_model = {s.model: s for s in window.summaries()}
    assert by_model["tiny.en"].p50_ms == 100.0
    assert by_model["small.en"].p50_ms == 900.0


def test_the_window_is_bounded_so_it_still_moves_after_a_model_change():
    """An unbounded average stops responding exactly when someone looks at it."""
    window = LatencyWindow(window=10)
    for _ in range(10):
        window.record("base.en", 2000.0)
    for _ in range(10):
        window.record("base.en", 100.0)
    summary = window.summaries()[0]
    assert summary.count == 10
    assert summary.p50_ms == 100.0, "the old, slower samples have aged out"


def test_the_default_window_is_large_enough_for_a_p95():
    assert DEFAULT_WINDOW >= MIN_SAMPLES_FOR_P95


def test_a_bad_sample_is_dropped_rather_than_raised_into_dictation():
    """This runs on the hot path; a clock artefact must not break a burst."""
    window = LatencyWindow()
    for bad in (None, "slow", float("nan"), float("inf"), -5.0):
        window.record("base.en", bad)
    assert window.summaries() == []


def test_an_unnamed_model_still_gets_counted():
    window = LatencyWindow()
    window.record("", 120.0)
    assert window.summaries()[0].model == "unknown"


def test_the_busiest_model_is_reported_first():
    window = LatencyWindow()
    window.record("rare.en", 10.0)
    for _ in range(5):
        window.record("usual.en", 10.0)
    assert [s.model for s in window.summaries()] == ["usual.en", "rare.en"]


def test_the_ipc_payload_is_json_safe():
    import json

    window = LatencyWindow()
    for value in range(1, 31):
        window.record("small.en", float(value) * 10)
    payload = window.as_dict()
    json.dumps(payload)  # must not raise
    assert payload[0]["count"] == 30
    assert payload[0]["p95_ms"] is not None


def test_the_payload_carries_a_null_p95_rather_than_omitting_the_model():
    """A model you have only used twice should still appear, with an honest gap."""
    window = LatencyWindow()
    window.record("small.en", 500.0)
    window.record("small.en", 700.0)
    payload = window.as_dict()
    assert payload[0]["p95_ms"] is None
    assert payload[0]["p50_ms"] == 500.0


# ---- what the user reads ---------------------------------------------------


def test_the_status_line_names_the_model_the_numbers_and_the_count():
    window = LatencyWindow()
    for _ in range(MIN_SAMPLES_FOR_P95):
        window.record("small.en", 740.0)
    line = render_status_lines(window.as_dict())[0]
    assert "small.en" in line
    assert "p50 740 ms" in line and "p95 740 ms" in line
    assert f"n={MIN_SAMPLES_FOR_P95}" in line


def test_a_thin_sample_says_so_instead_of_printing_a_p95():
    window = LatencyWindow()
    window.record("base.en", 300.0)
    line = render_status_lines(window.as_dict())[0]
    assert "p95" in line and "need" in line, "must explain the absence, not hide it"
    assert "p95 300" not in line


def test_nothing_decoded_yet_prints_nothing_at_all():
    """Not "0 ms" and not "unknown" — there is simply nothing to say."""
    assert render_status_lines([]) == []
    assert render_status_lines(None) == []


def test_an_older_daemon_without_the_field_does_not_break_status():
    """`yazses status` talks to whatever daemon is running, including a stale one."""
    assert render_status_lines(None) == []


def test_one_line_per_model():
    window = LatencyWindow()
    window.record("tiny.en", 90.0)
    window.record("small.en", 800.0)
    assert len(render_status_lines(window.as_dict())) == 2


# ---- end to end: the daemon reports it, `yazses status` prints it -----------


def _fake_platform(tmp_path, payload):
    import types

    return types.SimpleNamespace(
        name="linux",
        paths=types.SimpleNamespace(
            data_dir=tmp_path,
            config_file=tmp_path / "config.toml",
            ipc_socket=tmp_path / "daemon.sock",
        ),
        lifecycle=types.SimpleNamespace(is_running=lambda: True, read_pid=lambda: 4242),
        ipc_client_factory=lambda _sock: types.SimpleNamespace(
            call=lambda _method, **_kw: payload
        ),
    )


def _run_status(tmp_path, monkeypatch, payload, args=()):
    from typer.testing import CliRunner

    import yazses.cli as cli

    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path, payload))
    result = CliRunner().invoke(cli.app, ["status", *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_status_prints_the_latency_it_was_given(tmp_path, monkeypatch):
    window = LatencyWindow()
    for value in (700.0, 720.0, 740.0):
        window.record("small.en", value)
    output = _run_status(tmp_path, monkeypatch, {
        "state": "idle", "model": "small.en", "decode_latency": window.as_dict(),
    })
    assert "latency:" in output
    assert "small.en" in output and "n=3" in output


def test_status_against_a_daemon_without_the_field_still_works(tmp_path, monkeypatch):
    """An older daemon is exactly when you run `status`; it must not error."""
    output = _run_status(tmp_path, monkeypatch, {"state": "idle", "model": "small.en"})
    assert "YazSes is running" in output
    assert "latency:" not in output


def test_the_json_output_carries_the_raw_numbers_for_scripts(tmp_path, monkeypatch):
    import json

    window = LatencyWindow()
    for _ in range(MIN_SAMPLES_FOR_P95):
        window.record("base.en", 250.0)
    output = _run_status(tmp_path, monkeypatch, {
        "state": "idle", "model": "base.en", "decode_latency": window.as_dict(),
    }, args=("--json",))
    data = json.loads(output)
    assert data["decode_latency"][0]["p95_ms"] == 250.0


def test_the_daemon_status_payload_includes_the_field():
    """The producing half: reading the handler, not just the consuming half."""
    import inspect

    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon._handle_status)
    assert '"decode_latency"' in source


def test_the_decode_path_records_a_sample():
    """Without this call the window stays empty and status shows nothing."""
    import inspect

    from yazses.core import daemon as daemon_module

    source = inspect.getsource(daemon_module)
    assert "self._latency.record(" in source
