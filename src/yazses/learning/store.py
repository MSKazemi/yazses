"""Encrypted SQLite store for captured dictation events.

Metadata columns (timings, levels, intent labels) are stored in the clear so
``yazses corpus status`` stays cheap; every column holding transcript text is
encrypted with :class:`~yazses.learning.crypto.Cipher`. Source audio, when
captured, is written as an encrypted 16-bit-PCM WAV at ``clips/<id>.wav.enc``.
"""
from __future__ import annotations

import io
import re
import sqlite3
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from yazses.learning.crypto import Cipher

# Text fields encrypted at rest. Order matters only for readability.
_TEXT_FIELDS = (
    "raw_text",
    "cleaned_text",
    "filtered_text",
    "final_text",
    "correction_text",
    "retx_text",
)

_REDACTION = "[REDACTED]"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    audio_secs    REAL,
    decode_ms     REAL,
    model         TEXT,
    level         REAL,
    sample_rate   INTEGER,
    intent_type   TEXT,
    intent_action TEXT,
    injected      INTEGER DEFAULT 0,
    discard_reason TEXT,
    wrong_flag    INTEGER DEFAULT 0,
    edit_signal   REAL,
    retx_distance REAL,
    audio_path    TEXT,
    raw_text_enc        BLOB,
    cleaned_text_enc    BLOB,
    filtered_text_enc   BLOB,
    final_text_enc      BLOB,
    correction_text_enc BLOB,
    retx_text_enc       BLOB
);
"""


@dataclass
class EventRecord:
    """A decrypted corpus row."""

    id: int
    ts: float
    audio_secs: float | None
    decode_ms: float | None
    model: str | None
    level: float | None
    sample_rate: int | None
    intent_type: str | None
    intent_action: str | None
    injected: bool
    discard_reason: str | None
    wrong_flag: bool
    edit_signal: float | None
    retx_distance: float | None
    has_audio: bool
    raw_text: str
    cleaned_text: str
    filtered_text: str
    final_text: str
    correction_text: str
    retx_text: str


@dataclass
class CorpusStats:
    count: int
    discarded: int
    wrong: int
    size_bytes: int
    oldest_ts: float | None
    newest_ts: float | None


def _encode_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    """Serialize float32 [-1, 1] mono audio to 16-bit PCM WAV bytes."""
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as w:
        sample_rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32767.0
    return pcm, sample_rate


#: Fraction of the cap above which `yazses corpus status` calls the corpus full. This is a
#: DISPLAY threshold, not a measurement: `prune()` evicts while `_disk_size() > max_bytes`,
#: so a corpus held at the cap reads a hair under it and "500.0 / 500 MB" would otherwise
#: look like headroom. Nothing in the store consults this.
_NEARLY_FULL = 0.95


def capacity_line(size_bytes: int, max_mb: int, retention_days: int) -> tuple[str, str | None]:
    """``(size text, warning or None)`` for one corpus, against the limits that bind it.

    `yazses corpus status` printed ``size: 500.0 MB`` and nothing else -- a number with
    nothing to compare it to. On a corpus sitting exactly on its cap that is the one fact
    the line fails to convey: `prune()` is evicting the oldest events on every write to
    hold it there, and `yazses tune` learns from what survives.

    Both limits are named because either can be the binding one and they are not
    interchangeable -- age eviction drops what is stale, size eviction drops what is
    oldest regardless of how recent that is.

    Pure: no store, no config object, no filesystem, so both a CLI and a check can call it.
    """
    mb = size_bytes / 1_048_576
    if max_mb <= 0:
        return f"{mb:.1f} MB (no size cap)", None
    text = f"{mb:.1f} MB of {max_mb} MB"
    if mb < max_mb * _NEARLY_FULL:
        return text, None
    keeps = (
        f"{retention_days} days or {max_mb} MB, whichever binds first"
        if retention_days > 0
        else f"{max_mb} MB (no age limit)"
    )
    return text, (
        f"full — the oldest events are evicted on every capture to hold it here. "
        f"Keeps {keeps}; raise `[learning] max_corpus_mb` to keep more."
    )


def corpus_disk_bytes(data_dir) -> int:
    """Bytes the corpus occupies: the database **plus its audio clips**.

    The clips are almost all of it -- measured on a real machine, a 3.0 MB
    database sat beside 1291.9 MB of encrypted audio. Anything reporting or
    capping "the corpus" has to count both, which is why this is a module-level
    function rather than a method: `yazses report` sized `corpus.db` alone and
    said 3.0 MB for a corpus `yazses corpus status` measured at 1294.9 MB, and a
    report that understates the corpus 430x is read by whoever is diagnosing the
    disk it filled.

    Filesystem metadata only. Nothing here opens or decrypts a clip.
    """
    from pathlib import Path

    data_dir = Path(data_dir)
    db = data_dir / "corpus.db"
    total = db.stat().st_size if db.exists() else 0
    for clip in (data_dir / "clips").glob("*.wav.enc"):
        total += clip.stat().st_size
    return total


class CorpusStore:
    """CRUD over the encrypted event corpus."""

    def __init__(
        self, data_dir: Path, cipher: Cipher, redact_patterns: tuple[str, ...] = ()
    ) -> None:
        # Redaction lives here, at `_enc`, rather than in the caller that builds an
        # event. `_enc` is the ONE place text becomes a stored blob, so "encrypted" and
        # "redacted" are the same set by construction and cannot drift apart.
        #
        # They had drifted. `CorpusWriter` redacted a four-field tuple before enqueuing,
        # but `mark_wrong`, `update_correction_for` and `set_retx` write straight to the
        # store -- so `correction_text` and `retx_text` were stored unredacted. The
        # second one matters most: `retx_text` is a re-transcription of the SAME audio,
        # so a pattern the user added to keep a card number or a password out of the
        # corpus scrubbed it from `raw_text` and then `yazses tune` wrote it back in.
        self._redactors = [re.compile(pat) for pat in redact_patterns]
        self._dir = data_dir
        self._clips = data_dir / "clips"
        self._clips.mkdir(parents=True, exist_ok=True)
        self._cipher = cipher
        self._db_path = data_dir / "corpus.db"
        # check_same_thread=False: the daemon's background writer thread and the
        # IPC thread both touch the store; CorpusWriter serializes them with a
        # lock (see learning/capture.py).
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---- writes -----------------------------------------------------------

    def add_event(
        self,
        event: dict,
        audio: np.ndarray | None = None,
        sample_rate: int = 16000,
    ) -> int:
        """Insert one event row and (optionally) its encrypted audio clip."""
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO events (
                ts, audio_secs, decode_ms, model, level, sample_rate,
                intent_type, intent_action, injected, discard_reason,
                edit_signal, retx_distance,
                raw_text_enc, cleaned_text_enc, filtered_text_enc,
                final_text_enc, correction_text_enc, retx_text_enc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event.get("ts", time.time()),
                event.get("audio_secs"),
                event.get("decode_ms"),
                event.get("model"),
                event.get("level"),
                sample_rate,
                event.get("intent_type"),
                event.get("intent_action"),
                1 if event.get("injected") else 0,
                event.get("discard_reason"),
                event.get("edit_signal"),
                event.get("retx_distance"),
                *[self._enc(event.get(f, "")) for f in _TEXT_FIELDS],
            ),
        )
        assert cur.lastrowid is not None
        event_id = int(cur.lastrowid)

        if audio is not None and audio.size:
            clip_path = self._clips / f"{event_id}.wav.enc"
            clip_path.write_bytes(self._cipher.encrypt(_encode_wav(audio, sample_rate)))
            cur.execute(
                "UPDATE events SET audio_path = ? WHERE id = ?",
                (str(clip_path), event_id),
            )
        self._conn.commit()
        return event_id

    def mark_wrong(self, event_id: int | None = None, correction: str | None = None) -> bool:
        """Flag an event as a misrecognition. Defaults to the most recent event."""
        if event_id is None:
            event_id = self.last_event_id()
        if event_id is None:
            return False
        self._conn.execute(
            "UPDATE events SET wrong_flag = 1, correction_text_enc = ? WHERE id = ?",
            (self._enc(correction or ""), event_id),
        )
        self._conn.commit()
        return self._conn.total_changes > 0

    def update_correction_for(
        self, injected_text: str, corrected_text: str, signal: float = 1.0
    ) -> bool:
        """Record a captured in-place edit against the event that injected
        ``injected_text`` (most recent match within the last 50 events)."""
        rows = self._conn.execute(
            "SELECT id, final_text_enc FROM events ORDER BY id DESC LIMIT 50"
        ).fetchall()
        for r in rows:
            if self._dec(r["final_text_enc"]) == injected_text:
                self._conn.execute(
                    "UPDATE events SET correction_text_enc = ?, edit_signal = ? WHERE id = ?",
                    (self._enc(corrected_text), signal, int(r["id"])),
                )
                self._conn.commit()
                return True
        return False

    def set_edit_signal(self, event_id: int, signal: float) -> None:
        """Record the inferred post-dictation edit signal for an event."""
        self._conn.execute(
            "UPDATE events SET edit_signal = ? WHERE id = ?", (signal, event_id)
        )
        self._conn.commit()

    def set_retx(self, event_id: int, text: str, distance: float) -> None:
        """Store re-transcription output and its distance from the live transcript."""
        self._conn.execute(
            "UPDATE events SET retx_text_enc = ?, retx_distance = ? WHERE id = ?",
            (self._enc(text), distance, event_id),
        )
        self._conn.commit()

    # ---- reads ------------------------------------------------------------

    def last_event_id(self) -> int | None:
        row = self._conn.execute("SELECT MAX(id) AS m FROM events").fetchone()
        return int(row["m"]) if row and row["m"] is not None else None

    def events(self) -> list[EventRecord]:
        rows = self._conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        return [self._row_to_record(r) for r in rows]

    def load_audio(self, event_id: int) -> tuple[np.ndarray, int] | None:
        row = self._conn.execute(
            "SELECT audio_path FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None or not row["audio_path"]:
            return None
        path = Path(row["audio_path"])
        if not path.exists():
            return None
        return _decode_wav(self._cipher.decrypt(path.read_bytes()))

    def stats(self) -> CorpusStats:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS n,
                   SUM(CASE WHEN discard_reason IS NOT NULL THEN 1 ELSE 0 END) AS disc,
                   SUM(wrong_flag) AS wrong,
                   MIN(ts) AS oldest, MAX(ts) AS newest
            FROM events
            """
        ).fetchone()
        return CorpusStats(
            count=int(row["n"] or 0),
            discarded=int(row["disc"] or 0),
            wrong=int(row["wrong"] or 0),
            size_bytes=self._disk_size(),
            oldest_ts=row["oldest"],
            newest_ts=row["newest"],
        )

    # ---- maintenance ------------------------------------------------------

    def forget(self, minutes: float) -> int:
        """Delete events captured within the last ``minutes``. Returns count removed."""
        cutoff = time.time() - minutes * 60.0
        return self._delete_where("ts >= ?", (cutoff,))

    def prune(self, retention_days: int, max_mb: int) -> int:
        """Evict events older than ``retention_days``, then trim to ``max_mb``."""
        removed = 0
        if retention_days > 0:
            cutoff = time.time() - retention_days * 86400.0
            removed += self._delete_where("ts < ?", (cutoff,))
        # Size trim: drop the oldest events until under the cap.
        max_bytes = max_mb * 1024 * 1024
        while max_mb > 0 and self._disk_size() > max_bytes:
            row = self._conn.execute("SELECT MIN(id) AS m FROM events").fetchone()
            if row is None or row["m"] is None:
                break
            removed += self._delete_where("id = ?", (int(row["m"]),))
        return removed

    def destroy(self) -> None:
        """Irreversibly remove the database and all audio clips."""
        self._conn.close()
        for clip in self._clips.glob("*.wav.enc"):
            clip.unlink(missing_ok=True)
        self._clips.rmdir() if not any(self._clips.iterdir()) else None
        self._db_path.unlink(missing_ok=True)

    def close(self) -> None:
        self._conn.close()

    # ---- internals --------------------------------------------------------

    def _enc(self, text: str) -> bytes:
        return self._cipher.encrypt_str(self.redact(text))

    def redact(self, text: str) -> str:
        """Apply the configured redaction patterns. Pure w.r.t. the store."""
        out = text or ""
        for pat in self._redactors:
            out = pat.sub(_REDACTION, out)
        return out

    def _dec(self, blob: bytes | None) -> str:
        return self._cipher.decrypt_str(blob) if blob else ""

    def _delete_where(self, clause: str, params: tuple) -> int:
        rows = self._conn.execute(
            f"SELECT id, audio_path FROM events WHERE {clause}", params
        ).fetchall()
        for r in rows:
            if r["audio_path"]:
                Path(r["audio_path"]).unlink(missing_ok=True)
        self._conn.execute(f"DELETE FROM events WHERE {clause}", params)
        self._conn.commit()
        return len(rows)

    def _disk_size(self) -> int:
        return corpus_disk_bytes(self._db_path.parent)

    def _row_to_record(self, r: sqlite3.Row) -> EventRecord:
        return EventRecord(
            id=int(r["id"]),
            ts=float(r["ts"]),
            audio_secs=r["audio_secs"],
            decode_ms=r["decode_ms"],
            model=r["model"],
            level=r["level"],
            sample_rate=r["sample_rate"],
            intent_type=r["intent_type"],
            intent_action=r["intent_action"],
            injected=bool(r["injected"]),
            discard_reason=r["discard_reason"],
            wrong_flag=bool(r["wrong_flag"]),
            edit_signal=r["edit_signal"],
            retx_distance=r["retx_distance"],
            has_audio=bool(r["audio_path"]),
            raw_text=self._dec(r["raw_text_enc"]),
            cleaned_text=self._dec(r["cleaned_text_enc"]),
            filtered_text=self._dec(r["filtered_text_enc"]),
            final_text=self._dec(r["final_text_enc"]),
            correction_text=self._dec(r["correction_text_enc"]),
            retx_text=self._dec(r["retx_text_enc"]),
        )
