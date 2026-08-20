"""Live-meeting controller — ties capture, live transcript, and finalize — ADR-v2-127.

One ``MeetingController`` owns a single in-progress meeting. The daemon forwards captured
audio chunks to :meth:`feed` (mic capture stays in the daemon); the controller streams
them to the WAV sink and, when ``live_transcript`` is on, cuts utterances with the
segmenter and transcribes them on a background worker thread so the audio callback never
blocks. At stop it drains the worker and hands the daemon the recording path; the daemon
reads the audio back and calls :meth:`finalize`, which runs the accurate batch diarization
post-pass (reusing ``recimport``) and writes the meeting outputs.

Everything here is injectable (engine, ``is_silent`` predicate, diarizer, embedder,
voiceprint, notes LLM, clock, session) so it is unit-testable with fakes — no mic, no
models. The heavy finalize is synchronous here; the daemon runs it off the IPC thread.
"""
from __future__ import annotations

import logging
import queue
import threading

from yazses.meeting import store
from yazses.meeting.finalize import finalize_meeting
from yazses.meeting.notes import render_minutes_md
from yazses.meeting.segmenter import UtteranceSegmenter
from yazses.meeting.session import MeetingSession

log = logging.getLogger(__name__)


class MeetingController:
    def __init__(
        self,
        config,
        meeting_dir,
        meeting_id: str,
        *,
        engine,
        is_silent,
        embedder=None,
        voiceprint=None,
        diarizer=None,
        llm=None,
        sample_rate: int = 16000,
        started_at: float = 0.0,
        clock=None,
        session=None,
        max_seconds: float = 0.0,
        on_auto_stop=None,
        participants=None,
    ) -> None:
        self._config = config
        self._engine = engine
        self._sr = sample_rate
        self._embedder = embedder
        self._voiceprint = voiceprint
        self._participants = dict(participants or {})
        self._diarizer = diarizer
        self._llm = llm
        self.meeting_id = meeting_id
        # Safety auto-stop: the controller owns the cap (not the recorder), so audio
        # up to the cap is finalized rather than silently dropped. ``on_auto_stop`` is
        # invoked at most once, from the audio-callback thread; the daemon defers the
        # real stop to a worker so the mic stream is never stopped from its own callback.
        self._max_seconds = float(max_seconds or 0.0)
        self._on_auto_stop = on_auto_stop
        self._auto_stop_fired = False
        self._auto_lock = threading.Lock()
        self._session = session or MeetingSession(
            meeting_id, meeting_dir, sample_rate=sample_rate,
            started_at=started_at, clock=clock,
        )
        self._seg = (
            UtteranceSegmenter(is_silent, sample_rate=sample_rate)
            if getattr(config, "live_transcript", True) else None
        )
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._running = False

    @property
    def dir(self):
        return self._session.dir

    def start(self) -> None:
        self._running = True
        if self._seg is not None:
            self._worker = threading.Thread(
                target=self._live_loop, name="meeting-live", daemon=True
            )
            self._worker.start()

    def feed(self, chunk) -> None:
        """Forward one captured audio chunk (called from the mic callback)."""
        if not self._running:
            return
        self._session.append_chunk(chunk)
        if self._seg is not None:
            utt = self._seg.push(chunk)
            if utt is not None:
                self._queue.put(utt)
        self._check_auto_stop()

    def _check_auto_stop(self) -> None:
        """Fire ``on_auto_stop`` once when captured audio reaches ``max_seconds``."""
        if not self._max_seconds or self._on_auto_stop is None:
            return
        if self._session.duration_s() < self._max_seconds:
            return
        with self._auto_lock:
            if self._auto_stop_fired:
                return
            self._auto_stop_fired = True
        log.info("Meeting %s hit the %.0fs cap; auto-stopping.",
                 self.meeting_id, self._max_seconds)
        try:
            self._on_auto_stop()
        except Exception:  # pragma: no cover - defensive; callback owns its errors
            log.exception("Meeting auto-stop callback failed")

    def _live_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            try:
                text = self._engine.transcribe(item, self._sr)
                self._session.add_live_line(text)
            except Exception as exc:  # pragma: no cover - engine-dependent
                log.warning("Live transcription failed (%s).", exc)

    def status(self) -> dict:
        return {
            "id": self.meeting_id,
            "elapsed_s": round(self._session.elapsed_s(), 1),
            "duration_s": round(self._session.duration_s(), 1),
            "live_lines": list(self._session.live_lines[-8:]),
            "line_count": len(self._session.live_lines),
        }

    def stop_capture(self):
        """Stop live processing, drain the worker, and return the recording path."""
        self._running = False
        if self._seg is not None:
            tail = self._seg.flush()
            if tail is not None:
                self._queue.put(tail)
            self._queue.put(None)
            if self._worker is not None:
                self._worker.join(timeout=30.0)
        return self._session.stop()

    def finalize(self, audio) -> dict:
        """Run the batch diarization post-pass + optional notes; write outputs. Heavy."""
        profiles = None
        embedder = None
        if (
            getattr(self._config, "name_from_voiceprints", True)
            and self._embedder is not None
            and (self._voiceprint is not None or self._participants)
        ):
            profiles = {}
            if self._voiceprint is not None:
                profiles["You"] = self._voiceprint
            # Enrolled meeting participants auto-name their clusters in future meetings.
            profiles.update(self._participants)
            embedder = self._embedder

        result = finalize_meeting(
            audio, self._config, sample_rate=self._sr, engine=self._engine,
            diarizer=self._diarizer, embedder=embedder, profiles=profiles, llm=self._llm,
        )
        notes_md = render_minutes_md(result.minutes) if result.minutes else None
        written = store.write_outputs(
            self._session.dir, result.transcript,
            fmt=getattr(self._config, "output_format", "md"), notes_md=notes_md,
        )
        speakers = sorted(set(result.transcript.speaker_names.values()))
        # What the audio turned out to hold. `transcribe_file` has always answered
        # this and only `yazses transcribe` ever read it, so a meeting recorded
        # against a muted microphone finalized as `status: "done"` like any other.
        capture = store.capture_state(
            getattr(result.transcript, "silent_input", False),
            getattr(result.transcript, "no_speech", False),
        )
        store.write_meta(self._session.dir, {
            "id": self.meeting_id,
            "duration_s": round(self._session.duration_s(), 1),
            "diarized": result.transcript.diarized,
            "num_speakers": len(result.transcript.speaker_names),
            "speakers": speakers,
            "has_notes": notes_md is not None,
            "capture": capture,
            "status": "done",
        })
        return {
            "id": self.meeting_id,
            "dir": str(self._session.dir),
            "diarized": result.transcript.diarized,
            "num_speakers": len(result.transcript.speaker_names),
            "speakers": speakers,
            "has_notes": notes_md is not None,
            "capture": capture,
            "files": {k: str(v) for k, v in written.items()},
        }
