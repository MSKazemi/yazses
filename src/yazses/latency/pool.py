"""Hold the engines the Adaptive Latency Governor asks for (ADR-v2-073).

:func:`yazses.latency.governor.pick_policy` names a model and a beam width. Something has
to turn that name into a loaded engine, and the two facts that shape this file are:

**Loading an engine takes seconds.** Doing it on the hot path when load first spikes would
make the *latency* governor's first act the longest pause in the session. So :meth:`get`
never loads: it returns what is already resident, and starts a background load for what is
not. The policy takes effect from the next burst, which is the right trade — the load it is
reacting to is a 1-minute average and will still be there.

**The base policy must not load a second copy of the model already in memory.** The pool is
told which key the daemon's own engine answers to, and hands that engine straight back.

Everything impure is injected: the pool is constructed with a ``build(model, beam_size)``
callable and a ``spawn`` for the background thread, so its behaviour is testable without
loading a model or starting a thread.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

Key = tuple[str, int]

#: With a keep-alive, how long a failed load waits before the next request may try again.
RETRY_AFTER_FAILURE_S = 60.0


def _spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="latency-engine-load", daemon=True).start()


class EnginePool:
    """Memoise one engine per ``(model, beam_size)`` the governor asks for.

    **Keep-alive (ADR-029, opt-in).** With ``keep_alive_s > 0`` a non-base engine whose
    last use is at least ``keep_alive_s`` seconds old is dropped by :meth:`evict_idle`,
    so its memory is returned when the governor has stopped asking for it. A use is a
    successful :meth:`get` or the completion of its load. The base engine is the
    daemon's own dictation model and is never evicted. ``keep_alive_s == 0`` (the
    default) keeps every engine for the life of the pool, exactly as before.

    A load that fails stays pending, so a failure is not retried once per burst. With a
    keep-alive the key may be retried once ``retry_after_s`` has passed, because an
    evicted model will be asked for again and one transient failure should not disable
    it until restart; without a keep-alive a failure is permanent, as it always was.
    """

    def __init__(
        self,
        build: Callable[[str, int], object],
        base_key: Key,
        base_engine: object,
        *,
        spawn: Callable[[Callable[[], None]], None] = _spawn,
        keep_alive_s: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        retry_after_s: float = RETRY_AFTER_FAILURE_S,
    ) -> None:
        self._build = build
        self._spawn = spawn
        self._base_key = base_key
        self._keep_alive_s = float(keep_alive_s)
        self._clock = clock
        self._retry_after_s = float(retry_after_s)
        #: When each failed load failed. Used only with a keep-alive: an eviction means the
        #: model will be asked for again, so one transient failure (a full disk, a busy
        #: network drive) must not switch it off until restart. Without a keep-alive a
        #: failure stays permanent, exactly as before.
        self._failed_at: dict[Key, float] = {}
        self._lock = threading.Lock()
        self._engines: dict[Key, object] = {base_key: base_engine}
        #: Keys whose load is in flight or has failed. Both belong here: a second
        #: request must not start a second load. A key whose load failed stays here for
        #: the life of the pool, so it is never retried (no disk, no network, a bad name)
        #: and :meth:`evict_idle` never touches it.
        self._pending: set[Key] = set()
        #: Clock reading of the last use, per resident key.
        self._last_used: dict[Key, float] = {}
        #: Engines dropped by :meth:`evict_idle` since construction.
        self._evicted_total = 0

    def get(self, model: str, beam_size: int) -> object | None:
        """The engine for this policy, or ``None`` if it is not resident yet.

        Never blocks and never loads inline. ``None`` means "decode with the engine
        you already have"; a load for this key has been started if one was needed.
        A hit records a use, which restarts that key's keep-alive clock; a miss is not
        a use and does not touch any engine.
        """
        key = (model, int(beam_size or 0))
        with self._lock:
            engine = self._engines.get(key)
            if engine is not None:
                self._last_used[key] = self._clock()
                return engine
            if key in self._pending:
                failed = self._failed_at.get(key)
                if (
                    failed is None
                    or self._keep_alive_s <= 0
                    or self._clock() - failed < self._retry_after_s
                ):
                    return None
                # A failed load, long enough ago: try once more. The key stays pending so
                # a second request while this retry runs does not start a third load.
                del self._failed_at[key]
            else:
                self._pending.add(key)
        self._spawn(lambda: self._load(key))
        return None

    def _load(self, key: Key) -> None:
        """Build one engine off the hot path. Never raises into the thread."""
        model, beam_size = key
        try:
            engine = self._build(model, beam_size)
        except Exception:
            # Stays in `_pending`, so a failure is logged once per attempt, never per burst.
            # With a keep-alive it is retried after `retry_after_s`; without one, never.
            with self._lock:
                self._failed_at[key] = self._clock()
            log.exception(
                "Latency governor could not load model %r (beam %d); it will keep "
                "using the engine already loaded", model, beam_size,
            )
            return
        with self._lock:
            self._engines[key] = engine
            self._pending.discard(key)
            self._failed_at.pop(key, None)
            self._last_used[key] = self._clock()
        log.info("Latency governor loaded model %r (beam %d).", model, beam_size)

    def evict_idle(self) -> list[Key]:
        """Drop non-base engines idle for at least ``keep_alive_s``; return their keys.

        A dropped key leaves ``_engines`` and ``_pending``, so the next :meth:`get` for
        it starts a fresh background load. Dropping an engine returns its memory only
        once no caller still holds a reference to it (a decode in progress keeps one).
        Does nothing when ``keep_alive_s <= 0``.
        """
        if self._keep_alive_s <= 0:
            return []
        evicted: list[Key] = []
        with self._lock:
            now = self._clock()
            for key in sorted(self._engines):
                if key == self._base_key:
                    continue
                # Every resident non-base key has a last use: _load sets it in the same
                # locked block that makes the engine resident.
                last = self._last_used.get(key, now)
                if now - last < self._keep_alive_s:
                    continue
                del self._engines[key]
                self._last_used.pop(key, None)
                evicted.append(key)
            self._evicted_total += len(evicted)
        if evicted:
            log.info("Latency governor released %d idle model(s).", len(evicted))
        return evicted

    def residency_snapshot(self) -> dict[str, object] | None:
        """What is loaded and how long it has been idle, or ``None`` with no keep-alive.

        Shape: ``{"keep_alive_s": float, "loaded": [{"model", "beam_size", "base",
        "idle_s"}], "evicted_total": int}``. The base entry has ``idle_s`` ``None``.
        """
        if self._keep_alive_s <= 0:
            return None
        with self._lock:
            now = self._clock()
            loaded: list[dict[str, object]] = []
            for key in sorted(self._engines):
                is_base = key == self._base_key
                idle: float | None = None
                if not is_base:
                    idle = max(0.0, now - self._last_used.get(key, now))
                loaded.append({
                    "model": key[0],
                    "beam_size": key[1],
                    "base": is_base,
                    "idle_s": idle,
                })
            return {
                "keep_alive_s": self._keep_alive_s,
                "loaded": loaded,
                "evicted_total": self._evicted_total,
            }

    def resident(self) -> tuple[Key, ...]:
        """The keys currently loaded. For `yazses status` and for tests."""
        with self._lock:
            return tuple(sorted(self._engines))
