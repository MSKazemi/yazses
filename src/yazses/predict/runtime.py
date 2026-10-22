"""Predictive completion — the background worker that ties session and model together.

``predict/session.py`` decides; ``predict/generator.py`` generates; this runs the
generator **off the dictation path**. The daemon calls :meth:`PredictRuntime.submit`
after a burst is typed and returns at once. One worker thread takes the *latest*
request only — a burst typed while the model is still busy replaces the queued one
rather than queueing behind it — checks it is still current, generates, and offers
the result through the session, which drops it if a newer burst has begun meanwhile.

Every session access happens under one lock; the model call happens outside it, so a
slow generation never blocks :meth:`begin_burst` or :meth:`resolve` on the hotkey
thread. No dependency beyond the standard library; the completer is injected.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

from yazses.predict.session import PredictSession, Resolution, Suggestion

log = logging.getLogger(__name__)


class Completer(Protocol):
    def complete(self, context: str) -> str: ...


class PredictRuntime:
    """Owns the session, the worker thread, and the hand-off to the display surface.

    ``on_offer`` is called (on the worker thread) with each new :class:`Suggestion`;
    it must not raise, and any exception it does raise is logged and swallowed.
    ``threaded=False`` never starts a thread — tests drive :meth:`run_pending`.
    """

    def __init__(
        self,
        completer: Completer,
        on_offer: Callable[[Suggestion], None],
        *,
        session: PredictSession | None = None,
        clock: Callable[[], float] = time.monotonic,
        threaded: bool = True,
    ) -> None:
        self._completer = completer
        self._on_offer = on_offer
        self._session = session if session is not None else PredictSession()
        self._clock = clock
        self._threaded = threaded
        self._cond = threading.Condition()
        self._request: tuple[int, str] | None = None
        self._closed = False
        self._thread: threading.Thread | None = None

    # -- hotkey-thread API (all cheap, none blocks on the model) ---------------

    def begin_burst(self) -> None:
        """A hold started: discard any request or result still in flight."""
        with self._cond:
            self._session.begin_burst()
            self._request = None

    def resolve(self, utterance: str) -> Resolution:
        """What this burst's words do to the pending offer (see ``PredictSession``)."""
        with self._cond:
            return self._session.resolve(utterance, self._clock())

    def submit(self, text: str, app: str = "") -> bool:
        """Dictated *text* was typed into *app*; request a completion. True if queued."""
        with self._cond:
            if self._closed:
                return False
            request = self._session.note_injected(text, app)
            if request is None:
                return False
            self._request = request
            self._cond.notify_all()
        if self._threaded:
            self._ensure_thread()
        return True

    def interrupt(self) -> None:
        """The screen changed by something other than dictation; forget everything."""
        with self._cond:
            self._session.interrupt()
            self._request = None

    @property
    def pending(self) -> Suggestion | None:
        with self._cond:
            return self._session.pending

    def close(self) -> None:
        """Stop the worker. Idempotent; never blocks on a generation in progress."""
        with self._cond:
            self._closed = True
            self._request = None
            self._session.interrupt()
            self._cond.notify_all()

    # -- worker ----------------------------------------------------------------

    def run_pending(self) -> Suggestion | None:
        """Serve the latest request, if any and still current. The offer, or ``None``."""
        with self._cond:
            request, self._request = self._request, None
            if request is None or self._closed:
                return None
            epoch, context = request
            if not self._session.is_current(epoch):
                return None
        raw = self._completer.complete(context)  # outside the lock: may take a while
        with self._cond:
            if self._closed:
                return None
            offered = self._session.offer(epoch, raw, self._clock())
        if offered is not None:
            try:
                self._on_offer(offered)
            except Exception:
                log.debug("Predictive completion: showing the suggestion failed",
                          exc_info=True)
        return offered

    def _ensure_thread(self) -> None:
        with self._cond:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._loop, name="predict-worker", daemon=True
            )
            self._thread.start()

    def _loop(self) -> None:
        while True:
            with self._cond:
                while self._request is None and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
            try:
                self.run_pending()
            except Exception:  # the worker must outlive one bad generation
                log.debug("Predictive completion worker error", exc_info=True)
