"""`[residency] latency_keep_alive_s` in the daemon: the evictor thread and the status key.

The pool's own rules (what is evicted, the base key kept) are `test_latency_pool*`; this
file pins how the daemon uses it:

* at the default (`0`) no ``latency-pool-evict`` thread starts and the pool keeps every
  model, exactly as before the key existed;
* above 0 the evictor tick calls ``evict_idle`` on the pool, runs one ``gc.collect`` and
  logs ONE info line only when something was evicted, and an exception in the tick never
  stops the thread;
* the ``status`` reply carries ``latency_residency`` -- the pool snapshot, or null when
  there is no pool.

A fake pool stands in for `EnginePool` so no model loads and no clock is read.
"""

from __future__ import annotations

import logging
import threading

import yazses.system.residency as residency
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform

THREAD = "latency-pool-evict"


class _FakePool:
    def __init__(self, evict_batches=(), snapshot=None, raises=False) -> None:
        self._batches = list(evict_batches)
        self.snapshot = snapshot
        self.raises = raises
        self.evict_calls = 0
        self.called = threading.Event()

    def evict_idle(self):
        self.evict_calls += 1
        self.called.set()
        if self.raises:
            raise RuntimeError("boom")
        return self._batches.pop(0) if self._batches else []

    def residency_snapshot(self):
        if self.snapshot == "raise":
            raise RuntimeError("snapshot broke")
        return self.snapshot


def _daemon(keep_alive_s: int = 0, pool=None) -> Daemon:
    cfg = Config()
    cfg.residency.latency_keep_alive_s = keep_alive_s
    d = Daemon(config=cfg, platform=get_platform())
    d._governor = pool
    return d


def _evictor_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == THREAD]


def test_at_the_default_no_evictor_thread_starts() -> None:
    d = _daemon(0, _FakePool(evict_batches=[[("tiny.en", 1)]]))
    before = len(_evictor_threads())
    d._start_latency_pool_evictor()
    assert len(_evictor_threads()) == before


def test_with_no_pool_no_evictor_thread_starts_even_with_a_keep_alive() -> None:
    d = _daemon(600, pool=None)
    before = len(_evictor_threads())
    d._start_latency_pool_evictor()
    assert len(_evictor_threads()) == before


def test_the_tick_at_the_default_evicts_nothing_because_the_pool_keeps_everything() -> None:
    pool = _FakePool(evict_batches=[])
    d = _daemon(0, pool)
    assert d._latency_pool_evict_tick() == []
    assert pool.evict_calls == 1, "the pool itself decides; it is asked, and says nothing"


def test_a_tick_that_evicts_runs_gc_and_logs_one_line(monkeypatch, caplog) -> None:
    import gc

    collected: list[int] = []
    monkeypatch.setattr(gc, "collect", lambda *a, **k: collected.append(1) or 0)
    pool = _FakePool(evict_batches=[[("tiny.en", 1)]])
    d = _daemon(600, pool)
    with caplog.at_level(logging.INFO, logger="yazses"):
        evicted = d._latency_pool_evict_tick()
    assert evicted == [("tiny.en", 1)]
    assert collected == [1]
    lines = [r for r in caplog.records if "Latency governor released" in r.getMessage()]
    assert len(lines) == 1
    assert "tiny.en" in lines[0].getMessage() and "600" in lines[0].getMessage()


def test_a_tick_that_evicts_nothing_neither_collects_nor_logs(monkeypatch, caplog) -> None:
    import gc

    collected: list[int] = []
    monkeypatch.setattr(gc, "collect", lambda *a, **k: collected.append(1) or 0)
    d = _daemon(600, _FakePool(evict_batches=[[]]))
    with caplog.at_level(logging.INFO, logger="yazses"):
        assert d._latency_pool_evict_tick() == []
    assert collected == []
    assert not [r for r in caplog.records if "Latency governor released" in r.getMessage()]


def test_the_evictor_thread_ticks_the_pool_and_stops_with_the_daemon(monkeypatch) -> None:
    monkeypatch.setattr(residency, "unload_tick_s", lambda keep: 0.01)
    pool = _FakePool(evict_batches=[[("tiny.en", 1)]])
    d = _daemon(600, pool)
    d._start_latency_pool_evictor()
    try:
        assert pool.called.wait(5.0), "the tick never reached the pool"
    finally:
        d._stop_event.set()
    for thread in _evictor_threads():
        thread.join(5.0)
        assert not thread.is_alive(), "the evictor must exit when the daemon stops"


def test_an_exception_in_the_tick_does_not_kill_the_thread(monkeypatch) -> None:
    monkeypatch.setattr(residency, "unload_tick_s", lambda keep: 0.01)
    pool = _FakePool(raises=True)
    d = _daemon(600, pool)
    d._start_latency_pool_evictor()
    try:
        assert pool.called.wait(5.0)
        first = pool.evict_calls
        assert _wait_for(lambda: pool.evict_calls > first + 1, 5.0), "the thread died after an error"
    finally:
        d._stop_event.set()


def _wait_for(predicate, timeout: float) -> bool:
    end = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return True
        end.wait(0.01)
    return predicate()


def test_status_carries_the_pool_snapshot_when_there_is_a_pool() -> None:
    snap = {
        "keep_alive_s": 600.0,
        "loaded": [{"model": "tiny.en", "beam_size": 1, "base": False, "idle_s": 42.0}],
        "evicted_total": 0,
    }
    d = _daemon(600, _FakePool(snapshot=snap))
    status = d._handle_status(None)
    assert "latency_residency" in status, "a literal key, so the report guard can classify it"
    assert status["latency_residency"] == snap


def test_status_is_null_when_there_is_no_pool() -> None:
    d = _daemon(0, pool=None)
    assert d._handle_status(None)["latency_residency"] is None


def test_a_failing_snapshot_is_null_and_the_status_reply_still_arrives() -> None:
    d = _daemon(600, _FakePool(snapshot="raise"))
    status = d._handle_status(None)
    assert status["latency_residency"] is None
    assert "uptime_s" in status

