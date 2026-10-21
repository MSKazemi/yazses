"""Daemon glue for the Vocal-Strain Guard (ADR-v2-034): measure off the hot path, nudge once.

The daemon calls :meth:`VoiceHealthRuntime.submit` with each burst it decoded into text,
and only while ``[voicehealth] enabled`` is true; nothing here is imported otherwise.
``submit`` never blocks dictation: it hands the clip to one worker thread through a
one-slot queue and returns. When the worker is still measuring the previous burst, the
new one is *dropped* rather than queued — a missed reading costs nothing, a backlog of
audio would cost memory and hold speech in RAM for longer than needed.

The worker runs :class:`~yazses.voicehealth.biomarkers.StrainMonitor` (Praat via the
optional ``prosody`` extra) and feeds :class:`~yazses.voicehealth.biomarkers.StrainHistory`.
When the history says a break is warranted it raises ONE advisory desktop notification.
The history already enforces a session baseline, a minimum rise, a 45-minute cooldown and
a cap of two suggestions per session; this module adds only that a long idle gap
(:data:`SESSION_GAP_S`) starts a new session, so a daemon left running for days does not
spend its whole allowance on the first day and fall silent for ever.

**Privacy.** Audio is never logged or written anywhere: the worker drops its reference
to the clip as soon as the measurement returns. Only three floats per utterance (and the
derived strain level) are kept, in memory, and they are gone when the daemon exits.

**Missing extra.** Without ``parselmouth`` the runtime is built *inert*: no thread starts,
``submit`` is a no-op, and :attr:`VoiceHealthRuntime.inactive_reason` says why. ``yazses
doctor``, ``yazses status`` and the daemon's start-up announcement report the same thing
through the registry-derived dormant-feature check (``system/dormant.py``).

**Tuning (rule 9).** Every threshold in this path is inherited from ``biomarkers.py`` and
``strain.py`` and was chosen on synthetic signals only; none has been validated against
real users. They err toward silence. Advisory only, never diagnostic.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from yazses.voicehealth.biomarkers import (
    BREAK_SUGGESTION_BODY,
    BREAK_SUGGESTION_TITLE,
    BiomarkerBackend,
    ParselmouthBiomarkers,
    StrainHistory,
    StrainMonitor,
)

log = logging.getLogger(__name__)

#: An idle gap this long (seconds) between measured utterances starts a new session.
SESSION_GAP_S = 2 * 60 * 60.0

#: The import name the Praat backend needs (the ``prosody`` extra).
REQUIRED_MODULES: tuple[str, ...] = ("parselmouth",)

Notifier = Callable[[str, str], None]


def _default_notify(title: str, body: str) -> None:
    """Raise one informational toast through the shared notifier. Never raises."""
    try:
        from yazses.system import notify as notify_mod

        urgency, expire_ms = notify_mod.toast_policy(False)
        notify_mod.notify(title, body, urgency=urgency, expire_ms=expire_ms)
    except Exception:  # noqa: BLE001 — a reminder must never break dictation
        log.debug("voicehealth notification failed", exc_info=True)


def _default_missing() -> list[str]:
    from yazses.system.deps import missing_modules

    return missing_modules(REQUIRED_MODULES)


class VoiceHealthRuntime:
    """One session's strain monitor, run on a worker thread. See the module docstring.

    ``start_thread=False`` builds the same object without a worker, for tests: they call
    :meth:`process` directly and get a deterministic answer.
    """

    def __init__(
        self,
        config: Any,
        *,
        backend: BiomarkerBackend | None = None,
        notify: Notifier | None = None,
        clock: Callable[[], float] = time.monotonic,
        missing: Callable[[], list[str]] | None = None,
        start_thread: bool = True,
    ) -> None:
        self._config = config
        self._notify = notify or _default_notify
        self._clock = clock
        self.history = StrainHistory(config)
        absent = list((missing or _default_missing)()) if backend is None else []
        self.inactive_reason: str | None = (
            f"{', '.join(absent)} is not installed (install the `prosody` extra)"
            if absent else None
        )
        self._monitor = (
            None if self.inactive_reason else StrainMonitor(
                backend or ParselmouthBiomarkers(), self.history
            )
        )
        self._last_observed: float | None = None
        self.suggestions_sent = 0
        self._queue: queue.Queue[tuple[Any, int] | None] = queue.Queue(maxsize=1)
        self._thread: threading.Thread | None = None
        if start_thread and self._monitor is not None:
            self._thread = threading.Thread(
                target=self._run, name="voicehealth", daemon=True
            )
            self._thread.start()

    @property
    def active(self) -> bool:
        return self._monitor is not None

    def submit(self, audio: Any, sample_rate: int) -> bool:
        """Hand one decoded burst to the worker. Non-blocking; True when it was queued."""
        if self._monitor is None or self._thread is None:
            return False
        try:
            self._queue.put_nowait((audio, int(sample_rate)))
        except queue.Full:
            return False  # still measuring the last burst: skip this one, never wait
        return True

    def process(self, audio: Any, sample_rate: int) -> bool:
        """Measure one burst now (the worker's body). True when a reminder was raised."""
        if self._monitor is None:
            return False
        now = self._clock()
        if self._last_observed is not None and now - self._last_observed >= SESSION_GAP_S:
            self.history.reset()
        self._last_observed = now
        if not self._monitor.on_utterance(audio, sample_rate, now):
            return False
        self.suggestions_sent += 1
        log.info("Vocal-Strain Guard: suggested a voice break (%d this session).",
                 self.history.suggestions)
        try:
            self._notify(BREAK_SUGGESTION_TITLE, BREAK_SUGGESTION_BODY)
        except Exception:  # noqa: BLE001 — a reminder must never break dictation
            log.debug("voicehealth notifier raised", exc_info=True)
        return True

    def close(self, timeout: float = 1.0) -> None:
        """Stop the worker. Safe to call twice and on an inert runtime."""
        thread, self._thread = self._thread, None
        if thread is None:
            return
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full:
            pass
        thread.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            audio, sample_rate = item
            del item
            try:
                self.process(audio, sample_rate)
            except Exception:  # noqa: BLE001 — the worker must outlive any one burst
                log.debug("voicehealth measurement failed", exc_info=True)
            finally:
                del audio  # the clip is released here; nothing keeps it


def build_runtime(config: Any, **kwargs: Any) -> VoiceHealthRuntime:
    """Build the daemon's runtime for ``[voicehealth]`` (inert when the extra is missing)."""
    return VoiceHealthRuntime(config, **kwargs)
