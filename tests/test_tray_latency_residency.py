"""The tray shows the latency governor's extra model beside the speech model (ADR-029 step 2).

`[residency] latency_keep_alive_s` makes the daemon send a `latency_residency` block in its
status reply. `yazses status` prints it as one `memory:` line; the tray appends the same
phrase (from `system/residency.py`, so the two cannot disagree) to its one residency line.
At the default of 0 the daemon sends null and the tray is exactly what it was.
"""
from __future__ import annotations

from yazses.platform.base import TrayModel
from yazses.system.residency import describe_pool_residency
from yazses.tray.menu import build_menu_model, icon_spec, residency_line, status_from_model

_STT = {
    "idle_unload_s": 300, "loaded": True, "loading": False, "idle_s": 45.0,
    "unloaded_after_s": None, "unloaded_for_s": None,
}
_POOL = {
    "keep_alive_s": 600.0,
    "loaded": [
        {"model": "base.en", "beam_size": 5, "base": True, "idle_s": None},
        {"model": "tiny.en", "beam_size": 1, "base": False, "idle_s": 42.0},
    ],
    "evicted_total": 0,
}
_POOL_LINE = "latency: tiny.en (beam 1) loaded, idle 42 s; released after 600 s idle"


def test_the_pool_phrase_is_the_one_status_prints() -> None:
    assert describe_pool_residency(_POOL) == _POOL_LINE


def test_nothing_to_say_is_none_so_the_default_tray_is_unchanged() -> None:
    assert residency_line({"state": "idle"}) is None
    assert residency_line({"latency_residency": None}) is None
    only_base = {"keep_alive_s": 600.0, "loaded": [_POOL["loaded"][0]], "evicted_total": 0}
    assert residency_line({"latency_residency": only_base}) is None


def test_the_pool_alone_gives_its_own_line() -> None:
    assert residency_line({"latency_residency": _POOL}) == _POOL_LINE


def test_the_pool_is_appended_to_the_speech_model_line_never_replacing_it() -> None:
    both = residency_line({"stt_residency": _STT, "latency_residency": _POOL})
    stt_only = residency_line({"stt_residency": _STT})
    assert stt_only is not None and both is not None
    assert both.startswith(stt_only)
    assert both == f"{stt_only} · {_POOL_LINE}"


def test_a_malformed_block_is_ignored_not_raised() -> None:
    for bad in ("x", 7, [], {"keep_alive_s": "no"}, {"keep_alive_s": 600, "loaded": "x"}):
        assert residency_line({"latency_residency": bad}) is None


def test_the_menu_model_and_the_tooltip_carry_the_line() -> None:
    status = {"state": "idle", "hotkey": "right_ctrl", "latency_residency": _POOL}
    assert build_menu_model(status, [], "").residency == _POOL_LINE
    assert icon_spec(status)[1].endswith(_POOL_LINE)
    plain = icon_spec({"state": "idle", "hotkey": "right_ctrl"})
    assert icon_spec({"state": "idle", "hotkey": "right_ctrl", "latency_residency": None}) == plain


def test_the_shared_bridge_carries_the_block_and_the_model_stays_hashable() -> None:
    model = TrayModel(latency_residency=dict(_POOL))
    assert status_from_model(model)["latency_residency"] == _POOL
    hash(model)  # a dict field must stay out of the generated hash
    assert status_from_model(TrayModel())["latency_residency"] is None
