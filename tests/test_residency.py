"""The runtime-residency policy (ADR-029) as pure rules, tested without a clock or a model.

ADR-016 made a disabled feature cost zero *bytes and imports*. It still costs RAM and
CPU once it has run once: the speech model is never unloaded, the latency governor's
second model stays resident after its first load, and nothing bounds how many heavy
models are in memory at once. ADR-029 turns residency into policy, and this module
pins that policy's rules directly — a keep-alive that fires exactly at its timeout and
never for a pinned feature, an LRU cap that never evicts a pinned feature, the
out-of-process table, and the RSS check the nightly budget job will call.

Everything here is `system/residency.py`'s own arithmetic. No daemon, no engine, no
mock: the clock is a number the test passes in.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from yazses.system import residency
from yazses.system.residency import (
    DEFAULT_POLICY,
    WORKER_UNITS,
    Breach,
    IdleTracker,
    KeepAlive,
    ResidencyBudget,
    ResidencyPolicy,
    check_rss,
    placement,
    unit_for,
    unmeasured,
)

# ---- the policy table ---------------------------------------------------------


def test_core_stt_stays_resident_by_default_and_in_process() -> None:
    """First-word latency is the product: the dictation engine has no timeout."""
    stt = DEFAULT_POLICY.get("stt")
    assert stt.keep_alive_s is None
    assert stt.resident_default is True
    assert stt.worker_required is False


@pytest.mark.parametrize("unit", ["diarize", "gaze", "tts", "llm", "voiceprint", "latency"])
def test_every_heavy_unit_has_a_finite_keep_alive_and_loads_on_first_use(unit: str) -> None:
    entry = DEFAULT_POLICY.get(unit)
    assert entry.keep_alive_s is not None and entry.keep_alive_s > 0
    assert entry.resident_default is False


def test_the_keep_alive_defaults_are_the_ones_the_adr_decided() -> None:
    """The seconds are the ADR's; a drift here is a decision that skipped the record."""
    seconds = {e.feature: e.keep_alive_s for e in DEFAULT_POLICY.entries}
    assert seconds == {
        "stt": None,
        "latency": 600.0,
        "diarize": 300.0,
        "gaze": 120.0,
        "tts": 300.0,
        "llm": 300.0,
        "voiceprint": 600.0,
    }


def test_the_policy_rejects_a_duplicate_unit() -> None:
    a = KeepAlive("x", 1.0, False, False)
    with pytest.raises(ValueError, match="duplicate"):
        ResidencyPolicy(entries=(a, a), max_resident=2)


def test_the_policy_rejects_a_cap_below_one() -> None:
    with pytest.raises(ValueError, match="max_resident"):
        ResidencyPolicy(entries=(KeepAlive("x", 1.0, False, False),), max_resident=0)


@pytest.mark.parametrize("bad", [-1.0, math.nan, math.inf])
def test_a_keep_alive_rejects_negative_nan_and_infinite_seconds(bad: float) -> None:
    with pytest.raises(ValueError):
        KeepAlive("x", bad, False, False)


def test_a_keep_alive_rejects_an_empty_name() -> None:
    with pytest.raises(ValueError, match="feature"):
        KeepAlive("", 1.0, False, False)


def test_an_unknown_unit_is_a_loud_error_not_a_default() -> None:
    """A misspelt unit must never silently become 'stays resident, in process'."""
    with pytest.raises(KeyError):
        DEFAULT_POLICY.get("gazee")


# ---- registry slug -> residency unit ---------------------------------------------


@pytest.mark.parametrize(
    ("slug", "unit"),
    [
        ("gaze", "gaze"), ("facegesture", "gaze"), ("headpointer", "gaze"), ("gesture", "gaze"),
        ("llm-cleanup", "llm"),
        ("cocktail", "voiceprint"), ("voiceguard", "voiceprint"), ("multiprofile", "voiceprint"),
        ("diarize", "diarize"), ("recimport", "diarize"), ("meeting", "diarize"),
        ("read-back", "tts"),
        ("latency", "latency"),
    ],
)
def test_registry_slugs_map_onto_the_adr_units(slug: str, unit: str) -> None:
    assert unit_for(slug) == unit


def test_a_slug_with_no_heavy_model_has_no_unit() -> None:
    assert unit_for("vocab") is None


def test_every_mapped_unit_exists_in_the_default_policy() -> None:
    """A slug that names a unit the policy does not know would fall through every rule."""
    known = {e.feature for e in DEFAULT_POLICY.entries}
    assert set(residency.UNIT_OF_SLUG.values()) <= known


# ---- idle unload ---------------------------------------------------------------


def _policy() -> ResidencyPolicy:
    return ResidencyPolicy(
        entries=(
            KeepAlive("stt", None, True, False),
            KeepAlive("tts", 10.0, False, False),
            KeepAlive("llm", 5.0, False, True),
        ),
        max_resident=2,
    )


def test_idle_unload_fires_exactly_at_the_keep_alive_and_not_before() -> None:
    t = IdleTracker(_policy())
    t.mark_loaded("tts", now=100.0)
    assert t.due_for_unload(now=109.999) == []
    assert t.due_for_unload(now=110.0) == ["tts"]


def test_a_touch_restarts_the_keep_alive() -> None:
    t = IdleTracker(_policy())
    t.mark_loaded("tts", now=0.0)
    t.touch("tts", now=8.0)
    assert t.due_for_unload(now=10.0) == []
    assert t.due_for_unload(now=18.0) == ["tts"]


def test_a_unit_with_no_keep_alive_is_never_due() -> None:
    """`None` means 'resident while enabled' — the core engine, by default."""
    t = IdleTracker(_policy())
    t.mark_loaded("stt", now=0.0)
    assert t.due_for_unload(now=1e9) == []


def test_an_unloaded_unit_is_not_due_again() -> None:
    t = IdleTracker(_policy())
    t.mark_loaded("llm", now=0.0)
    assert t.due_for_unload(now=5.0) == ["llm"]
    t.mark_unloaded("llm")
    assert t.due_for_unload(now=50.0) == []
    assert t.is_loaded("llm") is False


def test_due_units_come_longest_idle_first() -> None:
    t = IdleTracker(_policy())
    t.mark_loaded("tts", now=0.0)
    t.mark_loaded("llm", now=3.0)
    # tts idle 20 s (keep-alive 10), llm idle 17 s (keep-alive 5): both due, tts first.
    assert t.due_for_unload(now=20.0) == ["tts", "llm"]


def test_idle_seconds_are_reported_for_a_status_row() -> None:
    t = IdleTracker(_policy())
    t.mark_loaded("tts", now=4.0)
    assert t.idle_s("tts", now=9.5) == 5.5
    assert t.idle_s("llm", now=9.5) is None  # never loaded


def test_the_tracker_uses_the_injected_clock_when_no_time_is_passed() -> None:
    ticks = iter([1.0, 2.0, 13.0])
    t = IdleTracker(_policy(), clock=lambda: next(ticks))
    t.mark_loaded("tts")
    t.touch("tts")
    assert t.due_for_unload() == ["tts"]


def test_the_tracker_refuses_to_guess_the_time() -> None:
    t = IdleTracker(_policy())
    with pytest.raises(ValueError, match="clock"):
        t.mark_loaded("tts")


@pytest.mark.parametrize("bad", [-1.0, math.nan, math.inf])
def test_the_tracker_rejects_a_negative_nan_or_infinite_time(bad: float) -> None:
    t = IdleTracker(_policy())
    with pytest.raises(ValueError):
        t.mark_loaded("tts", now=bad)


def test_the_tracker_rejects_time_running_backwards() -> None:
    """The clock is monotonic by contract; a wall clock handed in by mistake must fail."""
    t = IdleTracker(_policy())
    t.mark_loaded("tts", now=10.0)
    with pytest.raises(ValueError, match="monotonic"):
        t.touch("tts", now=9.0)


def test_the_tracker_rejects_a_unit_the_policy_does_not_know() -> None:
    t = IdleTracker(_policy())
    with pytest.raises(KeyError):
        t.mark_loaded("gaze", now=0.0)


# ---- the memory-bounded scheduler -------------------------------------------------


def test_admitting_within_the_cap_evicts_nothing() -> None:
    b = ResidencyBudget(max_resident=2)
    assert b.admit("tts", now=1.0) == []
    assert b.admit("llm", now=2.0) == []
    assert b.resident() == ("tts", "llm")


def test_the_least_recently_used_unit_is_evicted_first() -> None:
    b = ResidencyBudget(max_resident=2)
    b.admit("tts", now=1.0)
    b.admit("llm", now=2.0)
    b.touch("tts", now=3.0)           # llm is now the LRU
    assert b.admit("gaze", now=4.0) == ["llm"]
    assert b.resident() == ("tts", "gaze")


def test_re_admitting_a_resident_unit_only_refreshes_it() -> None:
    b = ResidencyBudget(max_resident=2)
    b.admit("tts", now=1.0)
    b.admit("llm", now=2.0)
    assert b.admit("tts", now=3.0) == []
    assert b.admit("gaze", now=4.0) == ["llm"]


def test_a_pinned_unit_is_never_evicted() -> None:
    b = ResidencyBudget(max_resident=2, pinned=("stt",))
    b.admit("stt", now=1.0)
    b.admit("tts", now=2.0)
    # stt is the LRU but pinned, so tts goes instead.
    assert b.admit("llm", now=3.0) == ["tts"]
    assert b.resident() == ("stt", "llm")


def test_a_cap_of_one_with_a_pin_evicts_everything_else() -> None:
    b = ResidencyBudget(max_resident=1, pinned=("stt",))
    b.admit("stt", now=1.0)
    assert b.admit("tts", now=2.0) == []        # nothing evictable: stt is pinned
    assert b.over_budget() == 1
    assert b.admit("llm", now=3.0) == ["tts"]   # the one evictable unit goes


def test_several_evictions_come_in_lru_order() -> None:
    b = ResidencyBudget(max_resident=3)
    for i, u in enumerate(["a", "b", "c"]):
        b.admit(u, now=float(i))
    b2 = dataclasses.replace(b.policy_view(), max_resident=1)
    assert b2.max_resident == 1
    b.set_cap(1)
    assert b.admit("d", now=10.0) == ["a", "b", "c"]
    assert b.resident() == ("d",)


def test_release_removes_a_unit_without_counting_as_an_eviction() -> None:
    b = ResidencyBudget(max_resident=1)
    b.admit("tts", now=1.0)
    b.release("tts")
    assert b.resident() == ()
    assert b.admit("llm", now=2.0) == []


def test_the_budget_rejects_a_cap_below_one_and_a_bad_time() -> None:
    with pytest.raises(ValueError, match="max_resident"):
        ResidencyBudget(max_resident=0)
    b = ResidencyBudget(max_resident=1)
    with pytest.raises(ValueError):
        b.admit("tts", now=math.nan)
    with pytest.raises(ValueError):
        b.admit("tts", now=-0.5)


def test_the_budget_rejects_time_running_backwards() -> None:
    b = ResidencyBudget(max_resident=2)
    b.admit("tts", now=5.0)
    with pytest.raises(ValueError, match="monotonic"):
        b.admit("llm", now=4.0)


# ---- placement -----------------------------------------------------------------


def test_the_worker_table_is_the_adrs_list() -> None:
    assert WORKER_UNITS == frozenset({"gaze", "llm", "voiceprint", "diarize"})


@pytest.mark.parametrize("unit", sorted(WORKER_UNITS))
def test_worker_units_are_placed_out_of_process(unit: str) -> None:
    assert placement(unit) == "worker"
    assert DEFAULT_POLICY.get(unit).worker_required is True


@pytest.mark.parametrize("unit", ["stt", "latency", "tts"])
def test_the_rest_stay_in_process(unit: str) -> None:
    assert placement(unit) == "in_process"
    assert DEFAULT_POLICY.get(unit).worker_required is False


def test_placement_of_an_unknown_unit_is_an_error() -> None:
    with pytest.raises(KeyError):
        placement("mediapipe")


def test_the_policy_table_and_the_worker_set_agree() -> None:
    """Two spellings of one fact; the test is what keeps them one."""
    flagged = {e.feature for e in DEFAULT_POLICY.entries if e.worker_required}
    assert flagged == WORKER_UNITS


# ---- the nightly RSS budget ------------------------------------------------------


def test_check_rss_reports_each_breach_with_the_amount_over() -> None:
    measured = {"stt": 360.0, "gaze": 200.0, "tts": 90.0}
    budget = {"stt": 343.0, "gaze": 250.0, "tts": 80.0}
    breaches = check_rss(measured, budget)
    assert breaches == [
        Breach(feature="stt", measured_mb=360.0, budget_mb=343.0),
        Breach(feature="tts", measured_mb=90.0, budget_mb=80.0),
    ]
    assert breaches[0].over_mb == 17.0
    assert "stt" in breaches[0].describe() and "17" in breaches[0].describe()


def test_check_rss_is_quiet_within_budget_and_at_the_line() -> None:
    assert check_rss({"stt": 343.0}, {"stt": 343.0}) == []


def test_check_rss_honours_a_tolerance_like_the_import_budget_does() -> None:
    """The import-time gate allows 1.5x before it fails; RSS gets the same shape."""
    assert check_rss({"stt": 400.0}, {"stt": 343.0}, tolerance=1.2) == []
    assert check_rss({"stt": 420.0}, {"stt": 343.0}, tolerance=1.2) != []


def test_check_rss_ignores_a_feature_nobody_budgeted() -> None:
    """Unbudgeted is a separate finding (`unmeasured`'s mirror), not a breach."""
    assert check_rss({"stt": 1.0, "new": 999.0}, {"stt": 343.0}) == []


def test_check_rss_refuses_an_empty_measurement() -> None:
    """A nightly that measured nothing must fail, not pass with zero breaches."""
    with pytest.raises(ValueError, match="measured nothing"):
        check_rss({}, {"stt": 343.0})


@pytest.mark.parametrize("bad", [-1.0, math.nan, math.inf])
def test_check_rss_rejects_a_negative_nan_or_infinite_figure(bad: float) -> None:
    with pytest.raises(ValueError):
        check_rss({"stt": bad}, {"stt": 343.0})
    with pytest.raises(ValueError):
        check_rss({"stt": 1.0}, {"stt": bad})


def test_check_rss_rejects_a_tolerance_below_one() -> None:
    with pytest.raises(ValueError, match="tolerance"):
        check_rss({"stt": 1.0}, {"stt": 343.0}, tolerance=0.5)


def test_unmeasured_names_the_budgeted_features_the_run_skipped() -> None:
    assert unmeasured({"stt": 343.0, "gaze": 250.0}, {"stt": 300.0}) == ["gaze"]
    assert unmeasured({"stt": 343.0}, {"stt": 300.0}) == []


def test_the_measured_baseline_is_the_one_in_the_adr() -> None:
    """[M] on fa058766: base.en 188 MB loaded, 216 MB after the first decode, 343 MB peak;
    the latency governor's tiny.en about 116 MB."""
    assert residency.MEASURED_FA058766_MB["stt.base.en.load_peak"] == 343.0
    assert residency.MEASURED_FA058766_MB["stt.base.en.loaded"] == 188.0
    assert residency.MEASURED_FA058766_MB["stt.base.en.after_first_decode"] == 216.0
    assert residency.MEASURED_FA058766_MB["latency.tiny.en"] == 116.0


def test_the_module_is_stdlib_only() -> None:
    """The policy must be importable on a base install with no model stack present."""
    import ast
    import pathlib

    src = pathlib.Path(residency.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names <= {"__future__", "collections", "dataclasses", "math", "typing"}, names
