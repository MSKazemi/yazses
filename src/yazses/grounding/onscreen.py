"""The on-screen reader both consumers share: one accessibility backend, a hard deadline.

Screen-Grounded Dictation (ADR-v2-051) and the Voice Pilot (ADR-v2-007) each own one
:class:`OnScreenReader`. Each reader owns one backend instance built by the platform's
``accessibility_factory`` (``platform/base.py``), so the two never share a handle map: a
snapshot taken for dictation at the start of a hold cannot invalidate the node a pending
"click" confirmation is about to act on.

**Why a wall-clock deadline on top of the walk's own bounds.** ``grounding/treewalk.py``
stops between nodes, but it cannot interrupt one call that blocks: a synchronous D-Bus
request to a hung application waits for the bus timeout, which is tens of seconds. So
each read and each action runs on a short-lived daemon thread and the caller waits at
most ``timeout_s`` for it. A call that overruns is abandoned (its result, if it ever
arrives, is dropped) and **at most one** such call is ever outstanding per reader — a
second read while the first is still stuck returns "unavailable" immediately instead of
piling up threads against the same hung application.

**Probed on first use, never at construction.** A daemon whose user never holds the key
with either feature enabled must not touch the accessibility bus; the factory runs on
the first read, once, and a factory that raises or returns ``None`` leaves the reader
permanently unavailable for this session.

No label, text or node is logged: on-screen text is user content.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from yazses.grounding.contracts import SemanticCandidate

log = logging.getLogger(__name__)

#: How long a caller waits for one read or action before abandoning it. Above the
#: walk's own 0.3 s budget so a healthy tree always finishes; well below the D-Bus
#: default timeout so a hung application costs the user one second, not twenty-five.
DEFAULT_TIMEOUT_S = 1.0


class AccessibilityReader(Protocol):
    """The structural slice of ``platform.base.AccessibilityBackend`` this module uses.

    Restated rather than imported so this module, like the rest of ``grounding``, does
    not depend on the platform layer.
    """

    def snapshot(self, *, window_id: str | None = None,
                 region: Any = None) -> Sequence[SemanticCandidate]: ...

    def perform(self, entity_id: str, action: str) -> bool: ...


class OnScreenReader:
    """Snapshot the focused window, or act on one node of the last snapshot. Never raises."""

    def __init__(
        self,
        factory: Callable[[], AccessibilityReader | None],
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._factory = factory
        self._timeout_s = float(timeout_s)
        self._backend: AccessibilityReader | None = None
        self._probed = False
        self._busy: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- backend ---------------------------------------------------------------
    def _get_backend(self) -> AccessibilityReader | None:
        with self._lock:
            if not self._probed:
                self._probed = True
                try:
                    self._backend = self._factory()
                except Exception:
                    log.debug("accessibility backend factory failed", exc_info=True)
                    self._backend = None
            return self._backend

    def available(self) -> bool:
        """Whether a backend exists (probing it on the first call)."""
        return self._get_backend() is not None

    # -- deadline --------------------------------------------------------------
    def _call(self, fn: Callable[[], Any], name: str) -> tuple[bool, Any]:
        """Run *fn* under the deadline: ``(finished, result)``. Never raises."""
        with self._lock:
            if self._busy is not None and self._busy.is_alive():
                log.debug("accessibility %s skipped: an earlier call has not returned", name)
                return False, None
            box: dict[str, Any] = {}

            def run() -> None:
                try:
                    box["value"] = fn()
                except Exception:
                    log.debug("accessibility %s failed", name, exc_info=True)
                    box["value"] = None

            worker = threading.Thread(target=run, name=f"a11y-{name}", daemon=True)
            self._busy = worker
        worker.start()
        worker.join(self._timeout_s)
        if worker.is_alive():
            log.info("Accessibility %s did not answer within %.1f s; abandoned.",
                     name, self._timeout_s)
            return False, None
        return True, box.get("value")

    # -- public ----------------------------------------------------------------
    def read(self) -> tuple[SemanticCandidate, ...] | None:
        """The focused window's candidates, or ``None`` when nothing could be read.

        ``None`` (no backend, a timeout, a failure) is distinct from ``()`` (the window
        was read and holds nothing with a label), so a caller can tell the user which.
        """
        backend = self._get_backend()
        if backend is None:
            return None
        reader: AccessibilityReader = backend
        finished, value = self._call(lambda: tuple(reader.snapshot()), "snapshot")
        if not finished or value is None:
            return None
        return tuple(c for c in value if isinstance(c, SemanticCandidate))

    def perform(self, entity_id: str, action: str) -> bool:
        """Act on one node of the **last** read. False on any doubt or failure."""
        backend = self._get_backend()
        if backend is None or not entity_id or not action:
            return False
        reader: AccessibilityReader = backend
        finished, value = self._call(lambda: reader.perform(entity_id, action), "action")
        return bool(finished and value)


__all__ = ["DEFAULT_TIMEOUT_S", "AccessibilityReader", "OnScreenReader"]
