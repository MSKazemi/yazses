"""`yazses corpus forget` deleted the row and left the transcript in the file.

The command's own help says what it is for — *"Delete recently captured events (e.g. after
dictating something private)"* — and `docs/privacy-statement.md` names it as the answer to
*"if you need something gone now"*. A plain SQLite `DELETE` does not make anything gone: it
marks the page free and the bytes stay in the file until something reuses them.

Measured before the fix, on a corpus built in a temp directory:

    stored blob: 101 bytes
    forget removed 1 event(s)
    the ciphertext is still in corpus.db: True
    carved from the freed page at offset 17514 and decrypted with the key sitting beside
    it:  'my bank password is hunter2 and the account number is 4417 1234 5678 9113'

Encryption is not the answer here, because the key is not elsewhere. `corpus.key` is
machine-bound and lives in the same directory as `corpus.db` (ADR-012) — that is the whole
design, and it is right for a local corpus, but it means residue in a freed page is residue
in plaintext to anyone who has the machine. Which is precisely the person the user was
protecting themselves from when they ran `forget`.

## Why the pragma rather than a vacuum at the call site

`PRAGMA secure_delete = ON` zeroes freed content on **every** delete path — `forget`,
retention eviction, the size trim, and anything added later. A vacuum bolted onto `forget`
would have fixed the one command that had a test written for it and left retention, which
`capture.py` calls *"a privacy control (ADR-012)"*, quietly leaking. `forget` vacuums as
well, because it is the one command whose promise covers the whole file and not just the
row it removed.

## What this does not claim

The database file no longer contains the text. The filesystem may still hold the blocks of
an unlinked audio clip or a deleted rollback journal — that is below SQLite and below this
project, and `docs/privacy-statement.md` now says so rather than implying otherwise.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from yazses.learning.crypto import Cipher, load_or_create_key
from yazses.learning.store import CorpusStore

SECRET = "my bank password is hunter2 and the account number is 4417 1234 5678 9113"


@pytest.fixture
def store(tmp_path):
    s = CorpusStore(tmp_path, Cipher(load_or_create_key(tmp_path)))
    yield s
    s.close()


def _fill_then_secret(store, *, secret_ts: float, filler_ts: float, n: int = 30) -> bytes:
    """Write `n` ordinary events plus one distinctive one; return its stored blob."""
    for i in range(n):
        store.add_event({"ts": filler_ts, "raw_text": f"filler {i}", "final_text": f"filler {i}"})
    store.add_event({"ts": secret_ts, "raw_text": SECRET, "final_text": SECRET})
    row = store._conn.execute(
        "SELECT raw_text_enc FROM events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["raw_text_enc"]


def _file_bytes(tmp_path) -> bytes:
    return (tmp_path / "corpus.db").read_bytes()


# --- the defect ----------------------------------------------------------------

def test_forget_leaves_no_recoverable_ciphertext_in_the_database(store, tmp_path):
    now = time.time()
    blob = _fill_then_secret(store, secret_ts=now, filler_ts=now - 3600)
    assert blob in _file_bytes(tmp_path), "the fixture never stored it"

    assert store.forget(minutes=5) == 1

    assert blob not in _file_bytes(tmp_path), (
        "the deleted event's encrypted transcript is still in corpus.db, and corpus.key "
        "is in the same directory -- `forget` promises the opposite"
    )


def test_retention_eviction_leaves_no_residue_either(store, tmp_path):
    """`capture.py` calls retention "a privacy control (ADR-012)", so it is one."""
    now = time.time()
    blob = _fill_then_secret(store, secret_ts=now - 40 * 86400, filler_ts=now)

    assert store.prune(retention_days=30, max_mb=0) == 1

    assert blob not in _file_bytes(tmp_path)


def test_the_size_trim_leaves_no_residue(store, tmp_path):
    now = time.time()
    blob = _fill_then_secret(store, secret_ts=now - 100, filler_ts=now, n=0)
    for i in range(60):
        body = f"later {i} " + "x" * 40_000
        store.add_event({"ts": now + i, "raw_text": body, "final_text": body})

    store.prune(retention_days=0, max_mb=1)

    assert blob not in _file_bytes(tmp_path)


# --- the guard is not vacuous ---------------------------------------------------

def test_the_same_check_finds_the_residue_when_the_pragma_is_off(tmp_path):
    """Turn the fix off and the carve succeeds — otherwise these assertions prove nothing."""
    cipher = Cipher(load_or_create_key(tmp_path))
    store = CorpusStore(tmp_path, cipher)
    store._conn.execute("PRAGMA secure_delete = OFF")
    try:
        now = time.time()
        blob = _fill_then_secret(store, secret_ts=now, filler_ts=now - 3600)
        store._conn.execute("DELETE FROM events WHERE ts >= ?", (now - 300,))
        store._conn.commit()
    finally:
        store.close()

    raw = _file_bytes(tmp_path)
    assert blob in raw, "no residue even with the pragma off — the probe is measuring nothing"
    offset = raw.find(blob)
    assert cipher.decrypt_str(raw[offset:offset + len(blob)]) == SECRET


def test_forget_also_clears_residue_left_by_an_older_version(tmp_path):
    """The pragma protects deletes from now on; the vacuum covers what is already there.

    A corpus written before this fix carries freed pages full of transcript. Turning on
    `secure_delete` does nothing for those — it zeroes content as it is deleted, not
    content already deleted. `forget` is where that matters, because it is the command
    someone runs *because* they want the old thing gone.
    """
    cipher = Cipher(load_or_create_key(tmp_path))
    old = CorpusStore(tmp_path, cipher)
    old._conn.execute("PRAGMA secure_delete = OFF")
    try:
        now = time.time()
        blob = _fill_then_secret(old, secret_ts=now - 86400, filler_ts=now - 86400)
        old._conn.execute("DELETE FROM events")
        old._conn.commit()
    finally:
        old.close()
    assert blob in _file_bytes(tmp_path), "the fixture did not leave residue to clean up"

    store = CorpusStore(tmp_path, cipher)
    try:
        store.add_event({"ts": time.time(), "raw_text": "fresh", "final_text": "fresh"})
        assert store.forget(minutes=5) == 1
    finally:
        store.close()

    assert blob not in _file_bytes(tmp_path), (
        "forget left an older version's residue in place; the pragma cannot reach it"
    )


# --- and forget still does the rest of its job ----------------------------------

def test_forget_still_deletes_the_audio_clip(store, tmp_path):
    audio = np.full(16_000, 0.1, dtype=np.float32)
    store.add_event({"ts": time.time(), "raw_text": "x", "final_text": "x"}, audio=audio)
    clips = list((tmp_path / "clips").glob("*.wav.enc"))
    assert clips, "no clip was written"

    store.forget(minutes=5)

    assert not list((tmp_path / "clips").glob("*.wav.enc"))


def test_forget_leaves_older_events_alone(store):
    now = time.time()
    store.add_event({"ts": now - 3600, "raw_text": "keep", "final_text": "keep"})
    store.add_event({"ts": now, "raw_text": "drop", "final_text": "drop"})

    assert store.forget(minutes=5) == 1
    assert [e.final_text for e in store.events()] == ["keep"]


def test_forget_with_nothing_to_remove_is_a_no_op(store):
    store.add_event({"ts": time.time() - 3600, "raw_text": "keep", "final_text": "keep"})
    assert store.forget(minutes=5) == 0
    assert store.stats().count == 1
