import time

import numpy as np
import pytest

from yazses.learning.crypto import Cipher, load_or_create_key
from yazses.learning.store import CorpusStore


@pytest.fixture
def store(tmp_path):
    cipher = Cipher(load_or_create_key(tmp_path))
    s = CorpusStore(tmp_path, cipher)
    yield s
    s.close()


def _event(ts):
    return {
        "ts": ts,
        "raw_text": "x",
        "cleaned_text": "x",
        "filtered_text": "x",
        "final_text": "x",
        "injected": True,
    }


def test_prune_by_age(store):
    now = time.time()
    store.add_event(_event(now - 40 * 86400))  # 40 days old
    store.add_event(_event(now - 5 * 86400))   # 5 days old
    removed = store.prune(retention_days=30, max_mb=500)
    assert removed == 1
    assert store.stats().count == 1


def test_prune_age_disabled_when_zero(store):
    now = time.time()
    store.add_event(_event(now - 999 * 86400))
    removed = store.prune(retention_days=0, max_mb=500)
    assert removed == 0
    assert store.stats().count == 1


def test_prune_by_size_drops_oldest_first(store):
    now = time.time()
    # ~0.5 MB of int16 PCM per clip (16000 * 16s = 256k samples * 2 bytes).
    big = np.full(256_000, 0.1, dtype=np.float32)
    first = store.add_event(_event(now - 100), audio=big)
    store.add_event(_event(now - 50), audio=big)
    store.add_event(_event(now), audio=big)
    assert store.stats().count == 3

    # Cap at 1 MB: oldest clips evicted until under the cap.
    store.prune(retention_days=0, max_mb=1)
    remaining = {e.id for e in store.events()}
    assert first not in remaining
    assert store.stats().size_bytes <= 1 * 1024 * 1024


def test_prune_size_disabled_when_zero(store):
    big = np.full(256_000, 0.1, dtype=np.float32)
    store.add_event(_event(time.time()), audio=big)
    removed = store.prune(retention_days=0, max_mb=0)
    assert removed == 0
    assert store.stats().count == 1


# ---- the limits must actually be applied, not merely implemented -------------


def _store_for(tmp_path):
    from yazses.learning.crypto import Cipher, load_or_create_key
    from yazses.learning.store import CorpusStore

    return CorpusStore(tmp_path, Cipher(load_or_create_key(tmp_path)))


def _writer(tmp_path, **kw):
    from yazses.learning.capture import CorpusWriter

    store = _store_for(tmp_path)
    return CorpusWriter(store, (), **kw), store


def _surviving(tmp_path) -> int:
    """Events on disk, read through a fresh store: `stop()` closes the writer's."""
    store = _store_for(tmp_path)
    try:
        return len(store.events())
    finally:
        store.close()


def test_the_writer_prunes_at_start(tmp_path):
    """`CorpusStore.prune` shipped with tests and no caller in `src/`, so
    `retention_days` and `max_corpus_mb` were documented settings that did nothing.

    Measured on a real machine before this was wired: 1292 MB against a 500 MB cap,
    across 38 days against a 30-day retention. Retention is a privacy control
    (ADR-012), so failing to apply it matters more than the disk cost.
    """
    seed = _store_for(tmp_path)
    old = time.time() - 60 * 86400.0
    for i in range(3):
        seed.add_event({"ts": old, "final_text": f"ancient {i}"})
    seed.add_event({"ts": time.time(), "final_text": "fresh"})
    seed.close()
    assert _surviving(tmp_path) == 4

    writer, _ = _writer(tmp_path, retention_days=30, max_corpus_mb=0)
    writer.stop()
    assert _surviving(tmp_path) == 1, "60-day-old events survived a 30-day retention"


def test_zero_means_no_limit_and_prunes_nothing(tmp_path):
    """`0` disables each limit, per the documented config semantics, so a writer
    constructed without them behaves exactly as it did before this change."""
    seed = _store_for(tmp_path)
    seed.add_event({"ts": time.time() - 400 * 86400.0, "final_text": "ancient"})
    seed.close()

    writer, _ = _writer(tmp_path)
    writer.stop()
    assert _surviving(tmp_path) == 1, "an event was evicted although both limits were off"


def test_build_writer_passes_the_configured_limits(tmp_path):
    """The wiring itself: a correct prune reached by nobody is the original bug."""
    from dataclasses import replace

    from yazses.config import LearningConfig
    from yazses.learning.capture import build_writer

    cfg = replace(LearningConfig(), enabled=True, retention_days=7, max_corpus_mb=42)
    writer = build_writer(tmp_path, cfg)
    assert writer is not None
    try:
        assert writer._retention_days == 7
        assert writer._max_corpus_mb == 42
    finally:
        writer.stop()


def test_a_failing_prune_does_not_kill_the_writer_thread(tmp_path, mocker):
    """A dead writer thread stops capture silently, which is far worse than a
    corpus briefly over its cap."""
    writer, store = _writer(tmp_path, retention_days=1, max_corpus_mb=1)
    mocker.patch.object(store, "prune", side_effect=OSError("disk gone"))
    writer._prune()  # must not raise
    writer.write({"final_text": "still working"})
    writer.stop()
    assert _surviving(tmp_path) >= 1, "the writer stopped persisting after a failed prune"
