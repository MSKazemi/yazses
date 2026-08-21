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
from collections.abc import Callable

log = logging.getLogger(__name__)

Key = tuple[str, int]


def _spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="latency-engine-load", daemon=True).start()


class EnginePool:
    """Memoise one engine per ``(model, beam_size)`` the governor asks for."""

    def __init__(
        self,
        build: Callable[[str, int], object],
        base_key: Key,
        base_engine: object,
        *,
        spawn: Callable[[Callable[[], None]], None] = _spawn,
    ) -> None:
        self._build = build
        self._spawn = spawn
        self._lock = threading.Lock()
        self._engines: dict[Key, object] = {base_key: base_engine}
        #: Keys whose load is in flight or has failed. Both belong here: a second
        #: request must not start a second load, and a model that cannot be loaded
        #: (no disk, no network, a bad name) must not be retried once per burst.
        self._pending: set[Key] = set()

    def get(self, model: str, beam_size: int) -> object | None:
        """The engine for this policy, or ``None`` if it is not resident yet.

        Never blocks and never loads inline. ``None`` means "decode with the engine
        you already have"; a load for this key has been started if one was needed.
        """
        key = (model, int(beam_size or 0))
        with self._lock:
            engine = self._engines.get(key)
            if engine is not None:
                return engine
            if key in self._pending:
                return None
            self._pending.add(key)
        self._spawn(lambda: self._load(key))
        return None

    def _load(self, key: Key) -> None:
        """Build one engine off the hot path. Never raises into the thread."""
        model, beam_size = key
        try:
            engine = self._build(model, beam_size)
        except Exception:
            # Stays in `_pending`, so this is logged once rather than per burst.
            log.exception(
                "Latency governor could not load model %r (beam %d); it will keep "
                "using the engine already loaded", model, beam_size,
            )
            return
        with self._lock:
            self._engines[key] = engine
            self._pending.discard(key)
        log.info("Latency governor loaded model %r (beam %d).", model, beam_size)

    def resident(self) -> tuple[Key, ...]:
        """The keys currently loaded. For `yazses status` and for tests."""
        with self._lock:
            return tuple(sorted(self._engines))
