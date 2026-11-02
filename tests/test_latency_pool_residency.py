"""EnginePool keep-alive: idle eviction, touch on get, base never evicted, snapshot shape.

Pure tests: the clock is a fake the test advances by hand, ``build`` returns a sentinel
object, and ``spawn`` queues the load so the test runs it (or not) on purpose. Nothing
sleeps and no model loads.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from yazses.latency.pool import EnginePool

BASE = ("base.en", 0)


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Harness:
    """A pool wired to a fake clock, a recording build, and a queued spawn."""

    def __init__(self, keep_alive_s: float = 0.0, *, fail: set[str] | None = None) -> None:
        self.clock = FakeClock()
        self.builds: list[tuple[str, int]] = []
        self.queued: list[Callable[[], None]] = []
        self.fail = fail or set()
        self.base_engine = object()
        self.pool = EnginePool(
            self._build,
            BASE,
            self.base_engine,
            spawn=self.queued.append,
            keep_alive_s=keep_alive_s,
            clock=self.clock,
        )

    def _build(self, model: str, beam_size: int) -> object:
        self.builds.append((model, beam_size))
        if model in self.fail:
            raise RuntimeError(f"cannot load {model}")
        return object()

    def run_queued(self) -> None:
        while self.queued:
            self.queued.pop(0)()

    def load(self, model: str, beam_size: int) -> object:
        """Ask for a key, run its background load, and return the resident engine."""
        assert self.pool.get(model, beam_size) is None
        self.run_queued()
        engine = self.pool.get(model, beam_size)
        assert engine is not None
        return engine


def test_default_zero_never_evicts():
    h = Harness(keep_alive_s=0.0)
    h.load("tiny.en", 1)
    h.clock.advance(10**6)
    assert h.pool.evict_idle() == []
    assert ("tiny.en", 1) in h.pool.resident()


def test_negative_keep_alive_behaves_as_never_evict():
    h = Harness(keep_alive_s=-5.0)
    h.load("tiny.en", 1)
    h.clock.advance(10**6)
    assert h.pool.evict_idle() == []
    assert h.pool.residency_snapshot() is None


def test_keep_alive_zero_changes_nothing_on_evict_call():
    h = Harness(keep_alive_s=0.0)
    h.load("tiny.en", 1)
    before = h.pool.resident()
    assert h.pool.evict_idle() == []
    assert h.pool.resident() == before


def test_evicts_at_exactly_keep_alive_s_not_one_tick_earlier():
    h = Harness(keep_alive_s=60.0)
    h.load("tiny.en", 1)  # last use = load completion
    h.clock.advance(59.999)
    assert h.pool.evict_idle() == []
    h.clock.advance(0.001)
    assert h.pool.evict_idle() == [("tiny.en", 1)]
    assert ("tiny.en", 1) not in h.pool.resident()


def test_get_touch_postpones_eviction():
    h = Harness(keep_alive_s=60.0)
    h.load("tiny.en", 1)
    h.clock.advance(50.0)
    assert h.pool.get("tiny.en", 1) is not None  # a use at t+50
    h.clock.advance(50.0)  # 100 s after load, but only 50 s after the use
    assert h.pool.evict_idle() == []
    h.clock.advance(10.0)  # now 60 s after the last use
    assert h.pool.evict_idle() == [("tiny.en", 1)]


def test_base_engine_is_never_evicted_even_if_idle_forever():
    h = Harness(keep_alive_s=1.0)
    h.clock.advance(10**9)
    assert h.pool.evict_idle() == []
    assert h.pool.get("base.en", 0) is h.base_engine
    assert BASE in h.pool.resident()


def test_a_miss_for_another_key_does_not_postpone_eviction():
    h = Harness(keep_alive_s=60.0)
    h.load("tiny.en", 1)
    h.clock.advance(50.0)
    assert h.pool.get("tiny.en", 5) is None  # a miss: starts a load, is not a use
    h.run_queued()
    h.clock.advance(10.0)  # tiny.en/1 is now 60 s idle
    assert h.pool.evict_idle() == [("tiny.en", 1)]


def test_a_load_completion_counts_as_a_use():
    h = Harness(keep_alive_s=60.0)
    assert h.pool.get("tiny.en", 1) is None
    h.clock.advance(50.0)
    h.run_queued()  # the load completes at t+50, which is the last use
    h.clock.advance(50.0)  # 100 s after the request, but only 50 s after completion
    assert h.pool.evict_idle() == []
    h.clock.advance(10.0)
    assert h.pool.evict_idle() == [("tiny.en", 1)]


def test_only_idle_non_base_engines_are_evicted():
    h = Harness(keep_alive_s=60.0)
    h.load("tiny.en", 1)
    h.clock.advance(40.0)
    h.load("tiny.en", 5)  # fresher
    h.clock.advance(20.0)  # tiny.en/1 is 60 s idle, tiny.en/5 is 20 s idle
    assert h.pool.evict_idle() == [("tiny.en", 1)]
    assert set(h.pool.resident()) == {BASE, ("tiny.en", 5)}


def test_evicted_key_reloads_on_next_get():
    h = Harness(keep_alive_s=10.0)
    h.load("tiny.en", 1)
    h.clock.advance(10.0)
    assert h.pool.evict_idle() == [("tiny.en", 1)]
    assert h.pool.get("tiny.en", 1) is None  # not resident: a new background load starts
    assert len(h.queued) == 1
    h.run_queued()
    assert h.builds.count(("tiny.en", 1)) == 2
    assert h.pool.get("tiny.en", 1) is not None


def test_failed_load_is_untouched_by_evict_idle():
    h = Harness(keep_alive_s=10.0, fail={"broken"})
    assert h.pool.get("broken", 1) is None
    h.run_queued()  # the load raised; the key stays in _pending
    h.clock.advance(5.0)
    # Inside the retry backoff a repeat get does not start a second load.
    assert h.pool.get("broken", 1) is None
    assert h.queued == []
    assert h.builds.count(("broken", 1)) == 1
    # Eviction never touches a failed key, however long ago it failed. (With a keep-alive the
    # key may be retried once the backoff has passed -- tests/test_residency_review_fixes.py.)
    h.clock.advance(10**6)
    assert h.pool.evict_idle() == []


def test_snapshot_is_none_without_keep_alive():
    h = Harness(keep_alive_s=0.0)
    h.load("tiny.en", 1)
    assert h.pool.residency_snapshot() is None


def test_snapshot_shape_and_idle_seconds():
    h = Harness(keep_alive_s=600)
    h.load("tiny.en", 1)
    h.clock.advance(42.0)
    snap = h.pool.residency_snapshot()
    assert snap is not None
    assert snap["keep_alive_s"] == 600.0
    assert snap["evicted_total"] == 0
    loaded = {(e["model"], e["beam_size"]): e for e in snap["loaded"]}
    assert set(loaded) == {BASE, ("tiny.en", 1)}
    assert loaded[BASE] == {"model": "base.en", "beam_size": 0, "base": True, "idle_s": None}
    assert loaded[("tiny.en", 1)] == {
        "model": "tiny.en",
        "beam_size": 1,
        "base": False,
        "idle_s": pytest.approx(42.0),
    }


def test_snapshot_is_json_safe():
    import json

    h = Harness(keep_alive_s=5.0)
    h.load("tiny.en", 1)
    json.dumps(h.pool.residency_snapshot())


def test_snapshot_excludes_pending_loads():
    h = Harness(keep_alive_s=5.0)
    h.pool.get("tiny.en", 1)  # load queued, not run
    snap = h.pool.residency_snapshot()
    assert snap is not None
    assert [e["model"] for e in snap["loaded"]] == ["base.en"]


def test_evicted_total_counts_across_evictions():
    h = Harness(keep_alive_s=10.0)
    h.load("tiny.en", 1)
    h.load("tiny.en", 5)
    h.clock.advance(10.0)
    assert len(h.pool.evict_idle()) == 2
    assert h.pool.residency_snapshot()["evicted_total"] == 2  # type: ignore[index]
    h.load("tiny.en", 1)
    h.clock.advance(10.0)
    assert h.pool.evict_idle() == [("tiny.en", 1)]
    assert h.pool.residency_snapshot()["evicted_total"] == 3  # type: ignore[index]
    # A call that evicts nothing does not move the counter.
    assert h.pool.evict_idle() == []
    assert h.pool.residency_snapshot()["evicted_total"] == 3  # type: ignore[index]


def test_concurrent_get_and_evict_do_not_raise():
    h = Harness(keep_alive_s=0.001)
    errors: list[BaseException] = []
    stop = threading.Event()

    def worker_get() -> None:
        try:
            for i in range(200):
                h.pool.get("tiny.en", 1 + (i % 3))
        except BaseException as exc:  # pragma: no cover - recorded for the assertion
            errors.append(exc)

    def worker_evict() -> None:
        try:
            while not stop.is_set():
                h.pool.evict_idle()
                h.pool.residency_snapshot()
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    getters = [threading.Thread(target=worker_get) for _ in range(4)]
    evictor = threading.Thread(target=worker_evict)
    evictor.start()
    for t in getters:
        t.start()
    for t in getters:
        t.join()
    stop.set()
    evictor.join()
    # Loads were queued by the getters; run them now and make sure the pool is consistent.
    h.run_queued()
    assert errors == []
    assert BASE in h.pool.resident()
