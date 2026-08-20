"""The size cap emptied a text-only corpus instead of trimming it.

`[learning] max_corpus_mb` is a disk-space control: *"Auto-expire old events"*, keeping
30 days or 500 MB, whichever binds first. `prune()` implemented it by deleting the oldest
event and re-measuring, in a loop, until the corpus fitted.

`DELETE` does not shrink a SQLite file. The freed pages go on its free list and the file
stays exactly as large. When the events carry audio the clips are unlinked alongside the
rows, the directory does shrink, and the loop converged — which is the only case the
existing test covers, because it is the only case that existed when it was written.

`[learning] capture_audio = false` is the other case. It is documented, and
`docs/privacy-statement.md` offers it in the table of things you stay in control of:
*"Store text but not audio."* With no clips there is nothing to unlink, so every deletion
freed zero bytes and the loop ran until `MIN(id)` was NULL:

    before: 1500 events, 2.95 MB on disk, cap = 1 MB
    ...
    1500 deletions, 0 left, 2.95 MB
    ran out of events -- the corpus is now EMPTY and still over the cap

Every captured event destroyed, no disk reclaimed, and the run took 32.8 s — a SELECT, a
DELETE, a commit and a full directory walk per row. After the fix the same corpus keeps
311 events at 0.62 MB in 0.1 s.

## Two halves, and neither is a refinement

**Vacuum**, so that what the loop measures is the size the file actually is; without it
the trim is steering on a number that cannot move.

**Stop when a round frees nothing**, so the corpus can never be spent on a cap it cannot
reach. Sitting a little over the cap is the right failure here: the limit exists to protect
disk space, and emptying the corpus to satisfy it costs the user everything the limit was
protecting — including, for someone who set `capture_audio = false` on purpose, the only
copy of a learning corpus that took weeks to gather.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from yazses.learning.crypto import Cipher, load_or_create_key
from yazses.learning.store import CorpusStore, corpus_disk_bytes

MB = 1024 * 1024


@pytest.fixture
def store(tmp_path):
    s = CorpusStore(tmp_path, Cipher(load_or_create_key(tmp_path)))
    yield s
    s.close()


#: Each insert commits, so the corpus is taken past 1 MB with few, large events rather
#: than many small ones: 1500 realistic rows cost 33 s to write and proved nothing the
#: 60 do. What the trim reads is bytes on disk, which either way is what it is.
_ROWS = 60
_BODY = 40_000


def _text_event(i: int) -> dict:
    """One event as `capture_audio = false` produces it: text, no clip."""
    body = f"sentence {i} " + "x" * _BODY
    return {"ts": 1_700_000_000 + i, "model": "base.en", "level": 0.01,
            "raw_text": body, "final_text": body}


def _fill(store, n: int = _ROWS) -> None:
    for i in range(n):
        store.add_event(_text_event(i))


# --- the defect ----------------------------------------------------------------

def test_a_text_only_corpus_over_the_cap_is_trimmed_not_emptied(store, tmp_path):
    _fill(store)
    assert corpus_disk_bytes(tmp_path) > 1 * MB, "the corpus must start over the cap"

    removed = store.prune(retention_days=0, max_mb=1)

    assert removed > 0, "nothing was trimmed"
    assert store.stats().count > 0, (
        "the size cap deleted every event in the corpus -- it is a disk limit, not a "
        "licence to destroy the data it is limiting"
    )


def test_the_trim_actually_reclaims_the_disk_it_frees(store, tmp_path):
    _fill(store)
    before = corpus_disk_bytes(tmp_path)

    store.prune(retention_days=0, max_mb=1)

    after = corpus_disk_bytes(tmp_path)
    assert after < before, (
        f"{before} -> {after}: deleting rows without reclaiming the pages leaves the file "
        "exactly as large, so the trim measures a number it cannot move"
    )
    assert after <= 1 * MB


def test_the_oldest_events_are_the_ones_that_go(store):
    _fill(store)
    oldest = min(e.id for e in store.events())

    store.prune(retention_days=0, max_mb=1)

    kept = {e.id for e in store.events()}
    assert kept, "nothing survived"
    assert oldest not in kept
    assert min(kept) > oldest


# --- it can never spend the corpus on a cap it cannot reach --------------------

def test_a_cap_below_what_the_database_can_shrink_to_still_leaves_events(store, caplog):
    """A 1 MB cap on a database whose own floor is larger: trim as far as it goes."""
    _fill(store)
    with caplog.at_level(logging.WARNING):
        store.prune(retention_days=0, max_mb=1)
    assert store.stats().count > 0


def test_a_round_that_frees_nothing_stops_and_says_so(store, caplog, monkeypatch):
    _fill(store)
    monkeypatch.setattr(CorpusStore, "_disk_size", lambda self: 99 * MB)

    with caplog.at_level(logging.WARNING):
        store.prune(retention_days=0, max_mb=1)

    assert store.stats().count > 0, "a trim that frees nothing must not keep deleting"
    assert any("freed nothing" in r.message for r in caplog.records), caplog.text


def test_no_single_round_may_take_the_whole_corpus(store):
    _fill(store)
    assert store._trim_batch(size=100 * MB, max_bytes=1) < store.stats().count


# --- and the case that already worked still does -------------------------------

def test_clips_are_still_evicted_oldest_first(store):
    """The audio path is what the original loop handled; it must not regress."""
    big = np.full(256_000, 0.1, dtype=np.float32)   # ~0.5 MB of int16 PCM
    first = store.add_event({"ts": 1.0, "raw_text": "a", "final_text": "a"}, audio=big)
    store.add_event({"ts": 2.0, "raw_text": "b", "final_text": "b"}, audio=big)
    store.add_event({"ts": 3.0, "raw_text": "c", "final_text": "c"}, audio=big)

    store.prune(retention_days=0, max_mb=1)

    remaining = {e.id for e in store.events()}
    assert first not in remaining
    assert store.stats().size_bytes <= 1 * MB


def test_a_disabled_cap_still_trims_nothing(store):
    _fill(store)
    assert store.prune(retention_days=0, max_mb=0) == 0
    assert store.stats().count == _ROWS


def test_retention_still_runs_before_the_size_trim(store):
    import time as _t
    store.add_event({"ts": _t.time() - 40 * 86400, "raw_text": "old", "final_text": "old"})
    store.add_event({"ts": _t.time(), "raw_text": "new", "final_text": "new"})

    removed = store.prune(retention_days=30, max_mb=500)

    assert removed == 1
    assert store.stats().count == 1
