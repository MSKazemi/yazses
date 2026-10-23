"""Unload the dictation engine after idle and reload it on the next use (ADR-029 §1).

`[stt] idle_unload_s` is the low-RAM opt-in ADR-029 offers: after that many seconds with
no decode, the speech model is released, and the next hold reloads it. ``0`` (the
default) means the daemon never builds this wrapper at all, so a default install decodes
exactly as before, through the engine itself.

Why a wrapper rather than ``self._engine = None`` in the daemon. Every caller holds the
*engine object*, not the daemon attribute: ``StreamingEngine`` keeps one, the latency
governor's ``EnginePool`` keeps one as its base engine, meeting capture is handed one.
Setting the attribute to ``None`` would free nothing while those references live, and
every ``self._engine is None`` guard in the daemon would read an idle unload as "not
started yet" and drop the burst. A wrapper that stays put while its *inner* engine comes
and goes keeps every one of those references valid, and every caller reloads through it
without knowing.

Thread safety is the point of this module, so it is stated once here:

* Every decode counts itself in (``_inflight``) under one condition variable before it
  touches the inner engine and out after. :meth:`detach_if_idle` releases the engine only
  with that count at zero, so an unload can never pull the model out from under a decode
  in progress — dictation, streaming, a meeting chunk, a spoken answer.
* Decodes do **not** serialise against each other: the lock is held only to count, never
  across a decode, so a file transcription and a dictation still run side by side as
  they do without the wrapper.
* One thread loads; any other that needs the engine meanwhile waits on the condition
  rather than loading a second copy.
* :meth:`detach_if_idle` never blocks: it is called by the daemon's housekeeping tick
  while the daemon holds its own state lock, so it tries the condition without waiting
  and reports "not now" if anyone holds it. The engine lock is never held while calling
  out (the ``on_loaded`` hook, the loader), so the daemon lock → engine lock order is
  the only order there is.

The *decision* — is the engine due? — is :class:`yazses.system.residency.IdleTracker`,
pure and clock-injected; this module only feeds it uses and acts on its answer.

Memory caveat, from ADR-029's context: CTranslate2 does not reliably hand freed pages
back to the OS, so dropping the last reference releases Python's hold on the model but
may leave RSS where it was. How much an unload actually returns is a nightly-job
measurement the ADR schedules; until then this is the mechanism, not a promise of
megabytes.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from yazses.system.residency import STT_UNIT, IdleTracker, with_stt_idle_unload

if TYPE_CHECKING:
    import numpy as np

    from yazses.postprocess.prosody import Word
    from yazses.stt.base import SttEngine

log = logging.getLogger(__name__)


def _spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="stt-reload", daemon=True).start()


class IdleUnloadEngine:
    """An :class:`~yazses.stt.base.SttEngine` whose model may be released when idle.

    ``load`` builds the inner engine (the daemon passes ``build_engine(cfg.stt)``, so a
    reload goes through the same factory, language check and output wrappers as the
    first load). ``engine`` is the one already built at daemon start, so constructing
    the wrapper never loads a second copy.
    """

    def __init__(
        self,
        load: Callable[[], SttEngine],
        idle_unload_s: float,
        *,
        engine: SttEngine | None = None,
        clock: Callable[[], float] = time.monotonic,
        spawn: Callable[[Callable[[], None]], None] = _spawn,
        on_loaded: Callable[[], None] | None = None,
    ) -> None:
        if not idle_unload_s or idle_unload_s <= 0:
            raise ValueError(
                "IdleUnloadEngine needs a positive idle_unload_s; 0 means 'never unload', "
                "which is the plain engine with no wrapper"
            )
        self.idle_unload_s = float(idle_unload_s)
        self._load = load
        self._spawn = spawn
        self._on_loaded = on_loaded
        self._cond = threading.Condition()
        self._inner: SttEngine | None = engine
        self._inflight = 0
        self._loading = False
        self._clock = clock
        self._tracker = IdleTracker(with_stt_idle_unload(self.idle_unload_s), clock=clock)
        #: Counters for status rows and tests: how many loads (after the first) and unloads.
        self.reloads = 0
        self.unloads = 0
        #: When the model was last released (a ``clock`` reading) and how long it had
        #: really been idle then, both ``None`` while it is loaded or was never released.
        #: The idle time is measured, not the keep-alive: the unload tick runs a quarter
        #: of the keep-alive apart and skips a turn while the daemon is busy, so a model
        #: kept for 300 s is released at anything from 300 s to well past it.
        self._released_at: float | None = None
        self._released_after_s: float | None = None
        if engine is not None:
            self._tracker.mark_loaded(STT_UNIT)

    # ---- state ------------------------------------------------------------------

    @property
    def is_resident(self) -> bool:
        """Whether the model is in memory right now (a load in flight is not resident)."""
        with self._cond:
            return self._inner is not None

    @property
    def is_loading(self) -> bool:
        with self._cond:
            return self._loading

    @property
    def released_after_s(self) -> float | None:
        """Seconds the model had been idle when it was last released; ``None`` while loaded.

        One attribute read, no lock: the daemon logs it just after `detach_if_idle`
        returned, from the thread that called it.
        """
        return self._released_after_s

    def idle_s(self) -> float | None:
        """Seconds since the last decode finished, or ``None`` while unloaded."""
        with self._cond:
            return self._tracker.idle_s(STT_UNIT)

    def residency_snapshot(self) -> dict[str, object]:
        """The model's residency for the daemon's ``status`` reply. Never waits on a lock.

        ``{"idle_unload_s": int, "loaded": bool, "loading": bool, "idle_s": float | None,
        "unloaded_after_s": float | None, "unloaded_for_s": float | None}``.
        ``idle_s`` is seconds since the last decode finished, ``0.0`` while one is in
        flight (the model is in use, not idle), and ``None`` while no model is loaded.
        While no model is loaded, ``unloaded_after_s`` is how long it had really been
        idle when it was released and ``unloaded_for_s`` how long ago that was; both are
        ``None`` while it is loaded, and before any release (a wrapper built with no
        engine). They are measured, not the configured keep-alive.

        The daemon builds its status reply under its own state lock, and the tray polls it
        four times a second, so this must not queue behind the engine lock. It *tries*
        the lock, for a consistent read when it is free -- which is nearly always, since
        nobody holds it across a decode or a load -- and otherwise reads the same fields
        without it. Each is one attribute load, and the tracker's :meth:`last_use` reads
        no clock and records nothing, so the unlocked read can at worst be one transition
        stale, never an error. :meth:`idle_s` is not used here for exactly that reason.
        The release stamps are plain attributes read the same way, and the "how long
        ago" reads ``clock`` directly -- not through the tracker -- so it records nothing.
        """
        locked = self._cond.acquire(blocking=False)
        try:
            inner = self._inner
            loading = self._loading
            inflight = self._inflight
            last = self._tracker.last_use(STT_UNIT)
            released_at = self._released_at
            released_after = self._released_after_s
        finally:
            if locked:
                self._cond.release()
        idle: float | None = None
        unloaded_after: float | None = None
        unloaded_for: float | None = None
        if inner is not None:
            if last is not None:
                idle = 0.0 if inflight else round(max(0.0, self._clock() - last), 1)
        else:
            if released_after is not None:
                unloaded_after = round(released_after, 1)
            if released_at is not None:
                unloaded_for = round(max(0.0, self._clock() - released_at), 1)
        return {
            "idle_unload_s": int(round(self.idle_unload_s)),
            "loaded": inner is not None,
            "loading": bool(loading),
            "idle_s": idle,
            "unloaded_after_s": unloaded_after,
            "unloaded_for_s": unloaded_for,
        }

    # ---- use ---------------------------------------------------------------------

    def _acquire(self) -> SttEngine:
        """Count a use in and return the loaded engine, loading it first if needed."""
        with self._cond:
            while True:
                if self._inner is not None:
                    self._inflight += 1
                    self._tracker.touch(STT_UNIT)
                    return self._inner
                if not self._loading:
                    self._loading = True
                    break
                self._cond.wait()
        # This thread is the loader. Outside the lock: a load takes seconds, and the
        # housekeeping tick must be able to see "busy" without waiting for it.
        released_after = self._released_after_s
        if released_after is not None:
            log.info("Reloading the speech model (it was unloaded after %.0f s idle).",
                     released_after)
        else:
            log.info("Loading the speech model.")
        try:
            engine = self._load()
        except BaseException:
            with self._cond:
                self._loading = False
                self._cond.notify_all()
            self._notify_loaded()
            raise
        with self._cond:
            self._inner = engine
            self._loading = False
            self._inflight += 1
            self._tracker.mark_loaded(STT_UNIT)
            self._released_at = None
            self._released_after_s = None
            self.reloads += 1
            self._cond.notify_all()
        self._notify_loaded()
        return engine

    def _release(self) -> None:
        with self._cond:
            self._inflight -= 1
            # The keep-alive counts from the end of the last decode, not its start: a
            # long file decode is use for its whole length.
            self._tracker.touch(STT_UNIT)

    def _notify_loaded(self) -> None:
        # Called with no lock held, success or failure, so a daemon showing a
        # "loading" state always gets the call that ends it.
        if self._on_loaded is None:
            return
        try:
            self._on_loaded()
        except Exception:  # noqa: BLE001 — a status hook must not fail a decode
            log.debug("on_loaded hook raised", exc_info=True)

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> str:
        engine = self._acquire()
        try:
            return engine.transcribe(audio, sample_rate, initial_prompt, task)
        finally:
            self._release()

    def transcribe_words(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> tuple[str, list[Word]]:
        engine = self._acquire()
        try:
            return engine.transcribe_words(audio, sample_rate, initial_prompt, task)
        finally:
            self._release()

    def decode_window(self, audio: np.ndarray) -> str:
        engine = self._acquire()
        try:
            return engine.decode_window(audio)
        finally:
            self._release()

    # ---- residency control -------------------------------------------------------

    def touch(self) -> None:
        """Restart the keep-alive without decoding (a hold began). No-op while unloaded."""
        with self._cond:
            self._tracker.touch(STT_UNIT)

    def prefetch(self) -> bool:
        """Start loading in the background if the model is out; ``True`` if a load began.

        Called when a hold starts, so the reload runs while the user is still speaking
        rather than after they let go. Capture does not wait for it: the recorder never
        touches the engine. When the model is resident this only restarts its
        keep-alive, so a long hold is not unloaded under the speaker.
        """
        with self._cond:
            if self._inner is not None:
                self._tracker.touch(STT_UNIT)
                return False
            if self._loading:
                return False
        self._spawn(self._prefetch_now)
        return True

    def _prefetch_now(self) -> None:
        try:
            self._acquire()
        except Exception:  # noqa: BLE001 — the decode that needs it will report it
            log.warning("Background reload of the speech model failed; the next decode "
                        "will try again and report the error.", exc_info=True)
            return
        self._release()

    def detach_if_idle(self) -> SttEngine | None:
        """Release the model if it is due and unused; return it so the caller can drop it.

        Never blocks. Returns ``None`` — and changes nothing — when the lock is held by
        anyone, a decode is in flight, a load is in flight, the model is already out, or
        the keep-alive has not run out. Otherwise the wrapper forgets the engine and hands
        the last reference back, so the caller can let it go *outside* whatever lock it
        holds: freeing a CTranslate2 model runs its native destructor, which is not free.
        """
        if not self._cond.acquire(blocking=False):
            return None
        try:
            if self._inner is None or self._inflight or self._loading:
                return None
            now = self._clock()
            if STT_UNIT not in self._tracker.due_for_unload(now):
                return None
            last = self._tracker.last_use(STT_UNIT)
            # Stamped before the engine is dropped, so a snapshot read without the lock
            # that already sees "unloaded" also sees when, not a blank.
            self._released_at = now
            self._released_after_s = None if last is None else max(0.0, now - last)
            engine, self._inner = self._inner, None
            self._tracker.mark_unloaded(STT_UNIT)
            self.unloads += 1
            return engine
        finally:
            self._cond.release()

    def __getattr__(self, name: str):
        # Delegate engine-specific attributes like the output wrappers do, but never
        # load a model to answer an attribute probe: `hasattr(engine, "x")` on an idle
        # engine must not cost a reload. `__dict__` is read directly so a lookup during
        # construction cannot recurse.
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)
