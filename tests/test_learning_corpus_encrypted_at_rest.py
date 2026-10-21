"""SEC-003: the learning corpus stays encrypted at rest (ADR-011 privacy boundary).

The corpus holds what the user said, word for word, plus the audio they said it in --
one of the three categories ADR-019 says may never leave the machine. Encryption at rest
is what stops it leaking by the ordinary routes that do not count as "leaving": a backup
tool, a cloud-synced home directory, a `grep -r` over the data dir, a support bundle.

`test_learning_store.py` already checks one field (`raw_text`) in one file (`corpus.db`).
This test is the regression guard for the whole promise, and it is deliberately broader
in three directions, because each is a way the next refactor could break it unnoticed:

* **every text field**, including the two that are written after the insert
  (`correction_text` by `mark_wrong`, `retx_text` by `set_retx`) -- those are the paths
  that once skipped redaction, so they are the ones most likely to skip encryption too;
* **every file under the data dir**, not just `corpus.db` -- a SQLite journal, a WAL, a
  sidecar cache or a debug dump would each be a plaintext copy beside the encrypted one;
* **UTF-8 and both UTF-16 byte orders** -- SQLite can store TEXT as UTF-16, and a
  sentinel search in one encoding is blind to the other.

And it goes through `build_writer`, the constructor the daemon uses, so a change that
gave the daemon a different (unencrypted) store would fail here rather than only in a
store-level unit test the daemon no longer exercises.

A clear-text column allowlist closes the last gap: a new TEXT column added to the schema
is plaintext by default, so it has to be a written-down decision, not an accident.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from yazses.config import LearningConfig
from yazses.learning.capture import build_writer, open_store
from yazses.learning.crypto import Cipher
from yazses.learning.store import CorpusStore

# One distinct sentinel per text field, so a failure names the field that leaked.
_SENTINELS = {
    "raw_text": "ZQXRAW sentinel the user said aloud 4111",
    "cleaned_text": "ZQXCLEAN sentinel after cleanup 4222",
    "filtered_text": "ZQXFILT sentinel after filters 4333",
    "final_text": "ZQXFINAL sentinel that was typed 4444",
}
_CORRECTION = "ZQXCORR sentinel the user corrected to 4555"
_RETX = "ZQXRETX sentinel from re-transcription 4666"

_ALL = {**_SENTINELS, "correction_text": _CORRECTION, "retx_text": _RETX}

# Columns the store keeps in the clear on purpose (cheap `yazses corpus status`).
# Adding a TEXT column to the schema means adding it here, which is the review moment.
_CLEAR_TEXT_COLUMNS = {
    "model",
    "intent_type",
    "intent_action",
    "discard_reason",
    "audio_path",
}


def _encodings(text: str) -> list[bytes]:
    return [text.encode("utf-8"), text.encode("utf-16-le"), text.encode("utf-16-be")]


def _all_bytes_under(root) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _assert_no_plaintext(root) -> None:
    files = _all_bytes_under(root)
    assert "corpus.db" in files, f"no corpus.db under {root}: {sorted(files)}"
    leaks = [
        (field, name)
        for field, text in _ALL.items()
        for name, data in files.items()
        if any(enc in data for enc in _encodings(text))
    ]
    assert not leaks, f"plaintext corpus text found on disk (field, file): {leaks}"


def _tone() -> np.ndarray:
    # A recognisable, non-silent clip: its PCM must not appear verbatim on disk either.
    return (np.sin(np.linspace(0, 400, 16000)) * 0.4).astype(np.float32)


@pytest.fixture
def populated(tmp_path):
    """A corpus written through the daemon's own constructor, every field set."""
    cfg = LearningConfig(enabled=True, retention_days=0, max_corpus_mb=0)
    writer = build_writer(tmp_path, cfg)
    assert writer is not None
    writer.write({**_SENTINELS, "injected": True, "model": "base.en"}, audio=_tone())
    writer.flush()
    assert writer.mark_last_wrong(_CORRECTION) is True
    store = writer._store
    eid = store.last_event_id()
    assert eid is not None
    store.set_retx(eid, _RETX, 0.25)
    yield tmp_path, writer
    writer.stop()


def test_no_text_field_is_plaintext_in_any_file_while_open(populated):
    """Checked with the connection still open: journal/WAL sidecars exist only then."""
    root, _writer = populated
    _assert_no_plaintext(root)


def test_no_text_field_is_plaintext_after_close_and_reads_back(populated):
    root, writer = populated
    writer.stop()
    _assert_no_plaintext(root)

    store = open_store(root)
    try:
        [rec] = store.events()
        got = {f: getattr(rec, f) for f in _ALL}
        assert got == _ALL
        assert rec.wrong_flag is True
        loaded = store.load_audio(rec.id)
        assert loaded is not None
        pcm, sr = loaded
        assert sr == 16000
        assert np.allclose(pcm, _tone(), atol=1e-3)
    finally:
        store.close()


def test_audio_clip_is_not_stored_as_pcm(populated):
    root, writer = populated
    writer.stop()
    clips = list((root / "clips").glob("*.wav.enc"))
    assert len(clips) == 1
    blob = clips[0].read_bytes()
    pcm = (np.clip(_tone(), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    assert b"RIFF" not in blob[:16] and b"WAVE" not in blob
    # Any 64-byte run of the real PCM on disk means the clip is not encrypted.
    assert pcm[3200:3264] not in blob


def test_a_different_key_cannot_read_the_corpus(populated):
    """Proves the bytes are ciphertext, not an encoding that merely hides a sentinel."""
    root, writer = populated
    writer.stop()
    other = CorpusStore(root, Cipher(b"\x01" * 32))
    try:
        with pytest.raises(Exception) as excinfo:
            other.events()
        assert type(excinfo.value).__name__ == "InvalidTag"
    finally:
        other.close()


def test_every_clear_text_column_is_a_written_down_decision(tmp_path):
    """A new TEXT column is plaintext by default; it must be allowlisted to exist."""
    store = open_store(tmp_path)
    store.close()
    conn = sqlite3.connect(str(tmp_path / "corpus.db"))
    try:
        cols = conn.execute("PRAGMA table_info(events)").fetchall()
    finally:
        conn.close()
    text_cols = {name for _cid, name, ctype, *_ in cols if ctype.upper() == "TEXT"}
    assert text_cols, "schema parse found no TEXT columns -- the guard would be vacuous"
    assert text_cols <= _CLEAR_TEXT_COLUMNS, (
        f"unencrypted TEXT column(s) {sorted(text_cols - _CLEAR_TEXT_COLUMNS)}: store "
        "transcript text in a *_enc BLOB, or allowlist the column with a reason"
    )
    blob_cols = {name for _cid, name, ctype, *_ in cols if ctype.upper() == "BLOB"}
    assert {f"{f}_enc" for f in _ALL} <= blob_cols
