"""Four defects an independent review found in ADR-029 step 2, each pinned here.

1. `float()` of an enormous TOML integer raised ``OverflowError`` at daemon startup, even
   with ``[latency]`` off. The keep-alive is now read through ``keep_alive_seconds``.
2. After an eviction, one failed reload disabled that model until restart. With a
   keep-alive a failed load is retried after ``retry_after_s``; without one it stays
   permanent, as before.
3. The ``latency`` feature text said the light model "stays resident" unconditionally.
4. ``make runtime-budget`` only printed a skeleton but was named like a gate.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.latency.pool import RETRY_AFTER_FAILURE_S, EnginePool
from yazses.platform import get_platform
from yazses.system.features import find_feature
from yazses.system.residency import MAX_KEEP_ALIVE_S, keep_alive_seconds

ROOT = Path(__file__).resolve().parent.parent


# --- 1. a huge integer in the config ------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (0, 0.0), (-1, 0.0), (-(10 ** 400), 0.0), (1, 1.0), (600, 600.0),
    (10 ** 400, MAX_KEEP_ALIVE_S), (int(MAX_KEEP_ALIVE_S), MAX_KEEP_ALIVE_S),
    (int(MAX_KEEP_ALIVE_S) + 1, MAX_KEEP_ALIVE_S),
    (0.0, 0.0), (-2.5, 0.0), (0.5, 0.5), (math.inf, MAX_KEEP_ALIVE_S), (1e300, MAX_KEEP_ALIVE_S),
    (math.nan, 0.0), (-math.inf, 0.0),
    (True, 0.0), (False, 0.0), (None, 0.0), ("600", 0.0), ([], 0.0),
])
def test_keep_alive_seconds_is_total_and_capped(value: object, expected: float) -> None:
    assert keep_alive_seconds(value) == expected


def test_a_400_digit_integer_does_not_stop_the_daemon_starting() -> None:
    with pytest.raises(OverflowError):
        float(10 ** 400)                      # the failure being guarded against
    cfg = Config()
    cfg.residency.latency_keep_alive_s = 10 ** 400
    d = Daemon(config=cfg, platform=get_platform())
    assert d._latency_keep_alive_s() == MAX_KEEP_ALIVE_S
    d._governor = None                        # [latency] off: no pool, so no thread, no error
    d._start_latency_pool_evictor()


def test_a_huge_keep_alive_builds_a_pool_that_still_evicts_nothing_early() -> None:
    pool = EnginePool(lambda m, b: object(), ("base", 5), object(), keep_alive_s=MAX_KEEP_ALIVE_S)
    assert pool.residency_snapshot()["keep_alive_s"] == MAX_KEEP_ALIVE_S      # type: ignore[index]


# --- 2. a failed reload after an eviction ---------------------------------------------------

class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _pool(keep_alive_s: float, build, clock: _Clock) -> tuple[EnginePool, list]:
    spawned: list = []
    pool = EnginePool(
        build, ("base", 5), object(), keep_alive_s=keep_alive_s, clock=clock,
        spawn=spawned.append,
    )
    return pool, spawned


def _run_pending(spawned: list) -> None:
    while spawned:
        spawned.pop(0)()


def test_with_a_keep_alive_a_failed_load_is_retried_after_the_backoff() -> None:
    clock = _Clock()
    calls: list = []

    def build(model: str, beam: int) -> object:
        calls.append((model, beam))
        if len(calls) == 1:
            raise OSError("disk full")
        return object()

    pool, spawned = _pool(600, build, clock)
    assert pool.get("tiny.en", 1) is None
    _run_pending(spawned)                                    # first load fails
    assert len(calls) == 1
    clock.now += RETRY_AFTER_FAILURE_S - 1
    assert pool.get("tiny.en", 1) is None and not spawned    # too soon: no second attempt
    clock.now += 2
    assert pool.get("tiny.en", 1) is None                    # past the backoff: retry starts
    assert len(spawned) == 1
    assert pool.get("tiny.en", 1) is None and len(spawned) == 1   # ...but only one at a time
    _run_pending(spawned)
    assert len(calls) == 2
    assert pool.get("tiny.en", 1) is not None                # the retry succeeded


def test_a_failed_load_is_permanent_without_a_keep_alive_as_before() -> None:
    clock = _Clock()

    def build(model: str, beam: int) -> object:
        raise OSError("no")

    pool, spawned = _pool(0, build, clock)
    pool.get("tiny.en", 1)
    _run_pending(spawned)
    clock.now += 10 ** 6
    assert pool.get("tiny.en", 1) is None and not spawned


def test_a_failing_retry_waits_for_another_backoff_not_every_burst() -> None:
    clock = _Clock()
    pool, spawned = _pool(600, lambda m, b: (_ for _ in ()).throw(OSError("x")), clock)
    pool.get("tiny.en", 1)
    _run_pending(spawned)
    clock.now += RETRY_AFTER_FAILURE_S + 1
    pool.get("tiny.en", 1)
    _run_pending(spawned)                                    # the retry fails too
    clock.now += 5
    assert pool.get("tiny.en", 1) is None and not spawned    # backoff restarts from this failure


def test_eviction_then_a_transient_failure_does_not_disable_the_model() -> None:
    clock = _Clock()
    outcomes = iter([object(), OSError("transient"), object()])

    def build(model: str, beam: int) -> object:
        out = next(outcomes)
        if isinstance(out, Exception):
            raise out
        return out

    pool, spawned = _pool(300, build, clock)
    pool.get("tiny.en", 1)
    _run_pending(spawned)                                    # loads
    clock.now += 301
    assert pool.evict_idle() == [("tiny.en", 1)]             # evicted after idling
    pool.get("tiny.en", 1)
    _run_pending(spawned)                                    # reload fails once
    clock.now += RETRY_AFTER_FAILURE_S + 1
    pool.get("tiny.en", 1)
    _run_pending(spawned)                                    # and works the next time
    assert pool.get("tiny.en", 1) is not None


# --- 3. the feature text ----------------------------------------------------------------------

def test_the_latency_feature_text_mentions_the_release_key() -> None:
    feature = find_feature(Config(), "latency")
    assert feature is not None
    desc = feature.why
    assert "latency_keep_alive_s" in desc
    assert "unless" in desc                                  # "stays resident ... unless"


# --- 4. the Makefile target ------------------------------------------------------------------

def test_the_make_target_is_named_for_what_it_does() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^runtime-budget-template:", text, re.M)
    assert not re.search(r"^runtime-budget:", text, re.M)
    assert "runtime-budget-template" in text.split(".PHONY", 1)[1].split("\n\n", 1)[0]
