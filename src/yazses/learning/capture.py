"""Background-thread corpus writer.

The dictation pipeline must never pay for capture: :meth:`CorpusWriter.write`
only enqueues, returning immediately, and a daemon thread does the encryption +
disk I/O. Any failure in capture is swallowed and logged — a broken corpus must
never break dictation. All access to the underlying :class:`CorpusStore` is
serialized through a single lock so the writer thread and the IPC thread
(``mark_last_wrong``) can share one SQLite connection safely.
"""
from __future__ import annotations

import logging
import queue
import re
import threading
from pathlib import Path

import numpy as np

from yazses.config import LearningConfig
from yazses.learning.crypto import Cipher, load_or_create_key
from yazses.learning.store import CorpusStore

log = logging.getLogger(__name__)

_REDACTION = "[REDACTED]"
# Text fields that pass through redaction before storage.
_REDACTABLE = ("raw_text", "cleaned_text", "filtered_text", "final_text")


#: How many captured events between size/retention sweeps. A prune walks the clip
#: directory and deletes rows, so doing it per event would put disk work behind every
#: dictation; doing it only at start would let a daemon left running for weeks grow
#: without limit. 200 events is a few hours of heavy use.
_PRUNE_EVERY_EVENTS = 200


class CorpusWriter:
    """Enqueue dictation events; persist them off the hot path."""

    def __init__(
        self,
        store: CorpusStore,
        redact_patterns: tuple[str, ...] = (),
        anonymize_audio: bool = False,
        anonymize_strength: float = 1.08,
        retention_days: int = 0,
        max_corpus_mb: int = 0,
    ) -> None:
        self._store = store
        self._patterns = [re.compile(p) for p in redact_patterns]
        self._anonymize_audio = anonymize_audio
        self._anonymize_strength = anonymize_strength
        # Both default to 0 (= no limit) so a caller that does not pass them keeps
        # the previous behaviour; `build_writer` passes what the config asks for.
        self._retention_days = retention_days
        self._max_corpus_mb = max_corpus_mb
        self._since_prune = 0
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name="yazses-corpus-writer", daemon=True
        )
        self._thread.start()

    # ---- producer side (hot path) ----------------------------------------

    def write(
        self,
        event: dict,
        audio: np.ndarray | None = None,
        sample_rate: int = 16000,
    ) -> None:
        """Enqueue an event. Never blocks the caller and never raises."""
        try:
            self._queue.put_nowait((self._redact(event), audio, sample_rate))
        except Exception:  # pragma: no cover - defensive
            log.debug("Corpus enqueue failed; dropping event", exc_info=True)

    # ---- consumer side (background thread) --------------------------------

    def _prune(self) -> None:
        """Apply the configured limits. Background thread only; never raises.

        `CorpusStore.prune` has existed, with tests, since the corpus shipped, and
        nothing in `src/` ever called it -- so `[learning] retention_days` and
        `max_corpus_mb` were documented settings that did nothing. Measured on the
        maintainer's own machine: 1292 MB against a 500 MB cap, spanning 38 days
        against a 30-day retention. Retention is a privacy control (ADR-012), not
        housekeeping, so silently not applying it is the more serious half.

        It runs here rather than in `build_writer` because deleting several hundred
        megabytes of clips is not something to do on the way to a working daemon.
        """
        if self._retention_days <= 0 and self._max_corpus_mb <= 0:
            return
        try:
            # The lock lives here, not at the call sites: `threading.Lock` is not
            # reentrant, so a caller that already held it would deadlock the writer
            # thread outright -- and the two call sites had started to disagree.
            with self._lock:
                removed = self._store.prune(self._retention_days, self._max_corpus_mb)
            if removed:
                log.info(
                    "Learning corpus: evicted %d event(s) to honour "
                    "retention_days=%s / max_corpus_mb=%s",
                    removed, self._retention_days, self._max_corpus_mb,
                )
        except Exception:
            # A writer thread that dies takes capture with it, silently. Losing a
            # prune is recoverable; losing the thread is not.
            log.warning("Learning corpus prune failed", exc_info=True)

    def _run(self) -> None:
        # Once at start: a daemon that is restarted often would otherwise only ever
        # grow, and this is the moment the limits are cheapest to apply.
        self._prune()
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                event, audio, sample_rate = item
                if self._anonymize_audio and audio is not None and audio.size:
                    # De-identify the clip before the encrypted write (ADR-v2-048).
                    from yazses.voiceprivacy.anonymize import anonymize_clip

                    audio = anonymize_clip(audio, sample_rate, self._anonymize_strength)
                with self._lock:
                    self._store.add_event(event, audio, sample_rate)
                self._since_prune += 1
                if self._since_prune >= _PRUNE_EVERY_EVENTS:
                    self._since_prune = 0
                    self._prune()
            except Exception:
                log.warning("Corpus write failed", exc_info=True)
            finally:
                self._queue.task_done()

    # ---- control / IPC-facing --------------------------------------------

    def mark_last_wrong(self, correction: str | None = None) -> bool:
        with self._lock:
            return self._store.mark_wrong(None, correction)

    def update_correction_for(self, injected: str, corrected: str, signal: float = 1.0) -> bool:
        """Record a captured in-place edit (from the EditWatcher). Thread-safe."""
        with self._lock:
            return self._store.update_correction_for(injected, corrected, signal)

    def flush(self) -> None:
        """Block until all queued events are persisted (used by tests/shutdown)."""
        self._queue.join()

    def stop(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5.0)
        with self._lock:
            self._store.close()

    # ---- internals --------------------------------------------------------

    def _redact(self, event: dict) -> dict:
        if not self._patterns:
            return event
        out = dict(event)
        for field in _REDACTABLE:
            val = out.get(field)
            if isinstance(val, str) and val:
                for pat in self._patterns:
                    val = pat.sub(_REDACTION, val)
                out[field] = val
        return out


def open_store(data_dir: Path) -> CorpusStore:
    """Open the corpus store directly (for CLI read/maintenance commands)."""
    cipher = Cipher(load_or_create_key(data_dir))
    return CorpusStore(data_dir, cipher)


def build_writer(data_dir: Path, cfg: LearningConfig) -> CorpusWriter | None:
    """Construct a writer when learning is enabled, else ``None`` (dormant)."""
    if not cfg.enabled:
        return None
    cipher = Cipher(load_or_create_key(data_dir))
    store = CorpusStore(data_dir, cipher)
    log.info("Learning corpus enabled at %s (audio=%s)", data_dir, cfg.capture_audio)
    return CorpusWriter(
        store,
        tuple(cfg.redact_patterns),
        anonymize_audio=cfg.anonymize_audio,
        anonymize_strength=cfg.anonymize_strength,
        retention_days=cfg.retention_days,
        max_corpus_mb=cfg.max_corpus_mb,
    )
