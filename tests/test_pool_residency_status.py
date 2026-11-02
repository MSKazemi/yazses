"""`yazses status` says which latency-governor models are loaded (ADR-029 step 2).

With `[residency] latency_keep_alive_s` set, the governor's extra Whisper models are
released after that many idle seconds. The daemon reports them as `latency_residency`
(the pool's `residency_snapshot()`, or null at the default of 0), and `yazses status`
prints one line for them under the speech model's line.

These tests pin:

* the exact line for one model, several models (deterministic order), and the base
  entry being left out;
* `None` for every shape that must print nothing, and never an exception for malformed
  input (a status path must not crash on a half-written reply);
* `with_latency_keep_alive`, mirroring `with_stt_idle_unload`;
* the `yazses status` rendering, including an old daemon that sends no key.

No network, no sleeps, no model, no microphone.
"""

from __future__ import annotations

import math

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.system.residency import (
    DEFAULT_POLICY,
    LATENCY_UNIT,
    describe_pool_residency,
    with_latency_keep_alive,
)

_ONE = {
    "keep_alive_s": 600.0,
    "loaded": [{"model": "tiny.en", "beam_size": 1, "base": False, "idle_s": 42.0}],
    "evicted_total": 0,
}
_BASE = {"model": "base.en", "beam_size": 5, "base": True, "idle_s": None}


def _snap(*rows, keep=600.0):
    return {"keep_alive_s": keep, "loaded": list(rows), "evicted_total": 0}


# ---- the line -------------------------------------------------------------------------


def test_one_extra_model_has_the_exact_line() -> None:
    assert describe_pool_residency(_ONE) == (
        "latency: tiny.en (beam 1) loaded, idle 42 s; released after 600 s idle"
    )


def test_the_base_entry_is_not_described_here() -> None:
    snap = _snap(_BASE, {"model": "tiny.en", "beam_size": 1, "base": False, "idle_s": 3.0})
    assert describe_pool_residency(snap) == (
        "latency: tiny.en (beam 1) loaded, idle 3 s; released after 600 s idle"
    )


def test_only_the_base_loaded_is_nothing_to_say() -> None:
    assert describe_pool_residency(_snap(_BASE)) is None


def test_several_models_are_ordered_least_idle_first_and_joined() -> None:
    snap = _snap(
        {"model": "small.en", "beam_size": 1, "base": False, "idle_s": 300.0},
        {"model": "tiny.en", "beam_size": 1, "base": False, "idle_s": 42.0},
        {"model": "medium.en", "beam_size": 2, "base": False, "idle_s": None},
    )
    assert describe_pool_residency(snap) == (
        "latency: medium.en (beam 2) loaded; tiny.en (beam 1) loaded, idle 42 s; "
        "small.en (beam 1) loaded, idle 300 s; released after 600 s idle"
    )


def test_ties_are_broken_by_model_then_beam_so_the_line_is_stable() -> None:
    a = {"model": "tiny.en", "beam_size": 3, "base": False, "idle_s": 5.0}
    b = {"model": "tiny.en", "beam_size": 1, "base": False, "idle_s": 5.0}
    assert describe_pool_residency(_snap(a, b)) == describe_pool_residency(_snap(b, a))
    assert describe_pool_residency(_snap(a, b)).startswith(
        "latency: tiny.en (beam 1) loaded, idle 5 s; tiny.en (beam 3)"
    )


def test_a_missing_idle_figure_is_left_out_not_invented() -> None:
    row = {"model": "tiny.en", "beam_size": 1, "base": False}
    assert describe_pool_residency(_snap(row)) == (
        "latency: tiny.en (beam 1) loaded; released after 600 s idle"
    )


def test_a_row_without_a_usable_beam_keeps_its_model_name() -> None:
    row = {"model": "tiny.en", "beam_size": True, "base": False, "idle_s": 1.0}
    assert describe_pool_residency(_snap(row)) == (
        "latency: tiny.en loaded, idle 1 s; released after 600 s idle"
    )


def test_the_released_clause_uses_the_keep_alive_as_whole_seconds() -> None:
    assert describe_pool_residency(_snap(*_ONE["loaded"], keep=90.6)).endswith(
        "released after 91 s idle"
    )


# ---- None: print nothing --------------------------------------------------------------


@pytest.mark.parametrize("snapshot", [
    None,
    {},
    "loaded",
    ["tiny.en"],
    42,
    _snap(),                                             # nothing loaded
    _snap(keep=0.0, *_ONE["loaded"]),                    # keep-alive 0: pool says None
    _snap(keep=-5.0, *_ONE["loaded"]),
    _snap(keep=math.nan, *_ONE["loaded"]),
    _snap(keep=math.inf, *_ONE["loaded"]),
    _snap(keep=True, *_ONE["loaded"]),
    _snap(keep="600", *_ONE["loaded"]),
    {"keep_alive_s": 600.0, "loaded": "tiny.en"},
    {"keep_alive_s": 600.0},
    {"keep_alive_s": 600.0, "loaded": None},
])
def test_nothing_is_said_for_none_an_old_daemon_or_an_unusable_keep_alive(snapshot) -> None:
    assert describe_pool_residency(snapshot) is None


# ---- malformed rows: skipped, never raised --------------------------------------------

_JUNK_ROWS = [
    None,
    "tiny.en",
    42,
    [],
    {},
    {"model": "tiny.en"},                                        # no base flag
    {"model": "tiny.en", "base": "no", "beam_size": 1, "idle_s": 1.0},
    {"model": "tiny.en", "base": 0, "beam_size": 1, "idle_s": 1.0},
    {"model": "", "beam_size": 1, "base": False, "idle_s": 1.0},
    {"model": "   ", "beam_size": 1, "base": False, "idle_s": 1.0},
    {"model": None, "beam_size": 1, "base": False, "idle_s": 1.0},
    {"model": 7, "beam_size": 1, "base": False, "idle_s": 1.0},
    {"model": ["tiny.en"], "beam_size": 1, "base": False, "idle_s": 1.0},
]


@pytest.mark.parametrize("junk", _JUNK_ROWS)
def test_a_junk_row_is_skipped_and_a_good_row_still_prints(junk) -> None:
    good = {"model": "tiny.en", "beam_size": 1, "base": False, "idle_s": 42.0}
    assert describe_pool_residency(_snap(junk, good)) == (
        "latency: tiny.en (beam 1) loaded, idle 42 s; released after 600 s idle"
    )


@pytest.mark.parametrize("junk", _JUNK_ROWS)
def test_a_junk_row_alone_prints_nothing(junk) -> None:
    assert describe_pool_residency(_snap(junk)) is None


@pytest.mark.parametrize("idle", [
    math.nan, math.inf, -math.inf, -3.0, "42", True, [], {},
])
def test_a_bad_idle_figure_is_treated_as_unknown(idle) -> None:
    row = {"model": "tiny.en", "beam_size": 1, "base": False, "idle_s": idle}
    assert describe_pool_residency(_snap(row)) == (
        "latency: tiny.en (beam 1) loaded; released after 600 s idle"
    )


@pytest.mark.parametrize("beam", [0, -1, 1.5, "1", None, False])
def test_a_bad_beam_is_dropped_from_the_line(beam) -> None:
    row = {"model": "tiny.en", "beam_size": beam, "base": False, "idle_s": 2.0}
    assert describe_pool_residency(_snap(row)) == (
        "latency: tiny.en loaded, idle 2 s; released after 600 s idle"
    )


def test_a_very_long_model_name_is_capped_so_the_status_line_stays_short() -> None:
    row = {"model": "x" * 500, "beam_size": 1, "base": False, "idle_s": 1.0}
    line = describe_pool_residency(_snap(row))
    assert line is not None and len(line) < 150


def test_an_absurdly_long_reply_is_bounded() -> None:
    rows = [{"model": f"m{i}", "beam_size": 1, "base": False, "idle_s": float(i)}
            for i in range(200)]
    line = describe_pool_residency(_snap(*rows))
    assert line is not None
    assert line.count(" loaded") == 16


@pytest.mark.parametrize("snapshot", [
    {"keep_alive_s": 600.0, "loaded": [{"base": False}] * 3},
    {"keep_alive_s": 600.0, "loaded": [None, None]},
    {"keep_alive_s": math.nan, "loaded": [{"model": "a", "base": False}]},
    {"keep_alive_s": 600.0, "loaded": [{"model": "a", "base": False, "idle_s": math.inf}]},
    {"keep_alive_s": 1e308, "loaded": [{"model": "a", "base": False, "idle_s": -1e308}]},
    {"keep_alive_s": 600.0, "loaded": (
        {"model": "a", "base": False, "beam_size": 1, "idle_s": 1.0},
    )},
    {"keep_alive_s": 600.0, "loaded": [{"model": "a", "base": False}], "evicted_total": "x"},
])
def test_malformed_snapshots_never_raise(snapshot) -> None:
    line = describe_pool_residency(snapshot)
    assert line is None or line.startswith("latency: ")


# ---- with_latency_keep_alive ----------------------------------------------------------


def _row(policy, unit=LATENCY_UNIT):
    return policy.get(unit)


def test_zero_returns_the_policy_unchanged() -> None:
    assert with_latency_keep_alive(0) is DEFAULT_POLICY
    assert with_latency_keep_alive(0.0, DEFAULT_POLICY) is DEFAULT_POLICY


def test_a_positive_value_replaces_only_the_latency_row() -> None:
    policy = with_latency_keep_alive(90)
    assert _row(policy).keep_alive_s == 90.0
    for unit in DEFAULT_POLICY.units() - {LATENCY_UNIT}:
        assert policy.get(unit) == DEFAULT_POLICY.get(unit)
    assert policy.max_resident == DEFAULT_POLICY.max_resident


def test_the_latency_row_stays_evictable_after_being_given_a_keep_alive() -> None:
    assert LATENCY_UNIT not in with_latency_keep_alive(90).pinned()


@pytest.mark.parametrize("bad", [-1, -0.5, math.nan, math.inf, -math.inf, True, "60", None])
def test_negative_nan_inf_and_non_numbers_raise(bad) -> None:
    with pytest.raises((ValueError, TypeError)):
        with_latency_keep_alive(bad)


# ---- `yazses status` ------------------------------------------------------------------

_REPLY = {
    "state": "idle", "hotkey": "right_ctrl", "model": "base.en",
    "injection_backend": "WtypeInjector", "uptime_s": 5.0, "ready": True,
    "engine": "faster-whisper", "engine_model": "base.en", "engine_fallback": None,
    "stt_residency": None,
}


class _Client:
    def __init__(self, reply):
        self._reply = reply

    def call(self, _method, **_kw):
        return self._reply


class _Platform:
    name = "linux"

    class lifecycle:  # noqa: N801 - a stand-in namespace
        @staticmethod
        def read_pid():
            return 1234

        @staticmethod
        def is_running():
            return True

    class paths:  # noqa: N801
        ipc_socket = "/tmp/nope.sock"
        data_dir = "/tmp"
        config_file = "/tmp/config.toml"

    @staticmethod
    def ipc_client_factory(_s):
        return _Client(_REPLY)


def _status_output(monkeypatch, reply) -> str:
    class _Reply(_Platform):
        @staticmethod
        def ipc_client_factory(_s):
            return _Client(reply)

    monkeypatch.setattr(cli, "get_platform", lambda: _Reply())
    return CliRunner().invoke(cli.app, ["status"]).output


def test_status_prints_the_latency_line_under_the_speech_model(monkeypatch) -> None:
    reply = {**_REPLY, "latency_residency": _ONE}
    out = _status_output(monkeypatch, reply)
    assert ("  memory:   latency: tiny.en (beam 1) loaded, idle 42 s; "
            "released after 600 s idle") in out
    assert out.index("  model:") < out.index("  memory:   latency:") < out.index("  backend:")


def test_status_prints_nothing_for_a_null_key(monkeypatch) -> None:
    out = _status_output(monkeypatch, {**_REPLY, "latency_residency": None})
    assert "latency" not in out


def test_an_old_daemon_without_the_key_still_renders_status(monkeypatch) -> None:
    assert "latency_residency" not in _REPLY
    out = _status_output(monkeypatch, dict(_REPLY))
    assert "  model:" in out and "  backend:" in out
    assert "latency" not in out


def test_status_survives_a_malformed_latency_block(monkeypatch) -> None:
    out = _status_output(monkeypatch, {**_REPLY, "latency_residency": "tiny.en"})
    assert "  backend:" in out and "latency" not in out


def test_a_sub_second_keep_alive_is_not_printed_as_zero() -> None:
    assert describe_pool_residency(_snap(*_ONE["loaded"], keep=0.3)).endswith(
        "released after under 1 s idle"
    )


def test_control_characters_in_a_model_name_cannot_split_the_line() -> None:
    row = {"model": "tiny\n.en\x00\t", "beam_size": 1, "base": False, "idle_s": 1.0}
    line = describe_pool_residency(_snap(row))
    assert line == "latency: tiny.en (beam 1) loaded, idle 1 s; released after 600 s idle"


def test_a_base_row_does_not_use_up_one_of_the_bounded_slots() -> None:
    base = [{"model": "base.en", "beam_size": 5, "base": True, "idle_s": None}] * 20
    extra = [{"model": f"m{i}", "beam_size": 1, "base": False, "idle_s": float(i)}
             for i in range(16)]
    line = describe_pool_residency(_snap(*base, *extra))
    assert line is not None and line.count(" loaded") == 16
