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


class CorpusWriter:
    """Enqueue dictation events; persist them off the hot path."""

    def __init__(
        self,
        store: CorpusStore,
        redact_patterns: tuple[str, ...] = (),
        anonymize_audio: bool = False,
        anonymize_strength: float = 1.08,
    ) -> None:
        self._store = store
        self._patterns = [re.compile(p) for p in redact_patterns]
        self._anonymize_audio = anonymize_audio
        self._anonymize_strength = anonymize_strength
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

    def _run(self) -> None:
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
    )
