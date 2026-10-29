"""Daemon-facing runner: pull blocks, drive the pipeline, call back — #103 / ADR-v2-152.

``BrainFlowSource`` established the contract the daemon already understands: a ``run()``
that streams until ``stop()``, ``on_mode_start(mode)`` when a squeeze begins,
``on_mode_end()`` when it relaxes, and *any failure is logged and ends the source while
dictation carries on*. This runner keeps exactly that shape, so ``core/daemon.py`` needs
no new concept to host it — the biosignal stack is one more activation source.

What it adds on top of the BrainFlow source:

* **A stuck-key watchdog.** If the device goes quiet (cable pulled, Bluetooth stall, a
  hung ``read``) while a squeeze is active, nothing would ever send ``SQUEEZE_OFF`` and
  the daemon would dictate forever. A separate thread calls ``on_mode_end`` once no block
  has arrived for ``watchdog_seconds``. It is a thread of its own, not a check in the read
  loop, precisely because the failure it guards against is the read loop being blocked.
* **Intents.** Blink and jaw-clench events become :class:`ActivationIntent` *labels* via
  :func:`events_to_intents` and are handed to ``on_intent``; the daemon routes them through
  ``activation.pipeline.handle_intent`` like any decoded intent, so the same confidence
  and consequence policy applies. Labels only, never text (``activation/intent.py``).
* **A public surface for the daemon**: ``ledger``, ``pipeline``, :meth:`note_cancelled`
  and :meth:`governor_release`, so the daemon never reaches into private attributes.
* **Ledger autosave.** When given a ``ledger_path`` the runner writes the aggregate
  activation counters (``fprate.ActivationLedger.to_dict``: counts and active seconds only,
  no signal, no per-event data) atomically every ``autosave_seconds`` and on stop, so a hard
  kill loses at most one interval. Each save adds only what changed since the previous
  save to whatever the file holds *now*, so it neither double counts nor overwrites the
  totals another process (``yazses biosignal report``) wrote meanwhile.
* **A status snapshot** for IPC and the CLI, including the governor state and the ledger
  summary.

**The stuck-key invariant.** A squeeze the runner forwarded is always released, by one of:
the source's own ``SQUEEZE_OFF``; the pipeline's synthetic OFF (bad signal, suspension, a
dead detector); the watchdog (no block); a stream gap seen by ``step``; ``stop()`` itself
(synchronously, because the run thread may be blocked inside a hung ``read`` and never reach
its ``finally``); or the ``finally`` of ``run``. Squeeze state changes and their callbacks
are serialized by one lock so a late ON can never be overtaken by an OFF that was decided
before it.

Thread model: ``run()`` executes on the caller's thread (the daemon starts it in one);
``stop()`` and ``status()`` may be called from any thread. A lock guards the small piece of
state shared with the watchdog and ``status()``; callbacks always run *outside* the lock so
a slow or re-entrant callback cannot deadlock the runner.

Dormant by default: :func:`build_runner_from_config` returns ``None`` unless
``[biosignal] enabled`` is set.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yazses.activation.intent import ActivationIntent
from yazses.biosignal.pipeline import (
    DEFAULT_INTENT_MAP,
    BiosignalPipeline,
    PartsRequest,
    PipelineStatus,
    build_parts,
    events_to_intents,
    intent_vocabulary,
)
from yazses.biosignal.types import BioEvent, BlockSource, EventKind

if TYPE_CHECKING:
    from yazses.biosignal.fprate import GovernorAction

log = logging.getLogger(__name__)

# Squeeze level → dictation mode. Mirrors the command key and the sotto-voce channel
# (pressure.LEVEL_MODE): light dictates, hard commands. "on" is the fallback for a
# detector that reports a squeeze without a level.
DEFAULT_MODE_MAP: dict[str, str] = {"light": "full_text", "hard": "command", "on": "full_text"}

# No block for this long while a squeeze is held => release it. Design choice: far above
# any block interval (tens of ms) so jitter never trips it, short enough that a dead
# device cannot keep a microphone open for long.
DEFAULT_WATCHDOG_SECONDS = 1.5
_POLL_SECONDS = 0.01         # idle wait when the source has no new block yet

# How often the aggregate counters are written. A design choice: a hard kill (power loss,
# SIGKILL) then costs at most a minute of counts, while a few hundred bytes once a minute
# is no I/O load at all.
DEFAULT_AUTOSAVE_SECONDS = 60.0
_LEDGER_FILENAME = "biosignal_ledger.json"   # must match cli_impl.LEDGER_FILENAME
_MAX_LEDGER_BYTES = 1 << 20
_RELEASE_ATTEMPTS = 2        # a raising on_mode_end is retried once; a stuck key is worse


def _noop(*_args: Any) -> None:
    return None


@dataclass
class RunnerCallbacks:
    """What the daemon injects. Every field defaults to a no-op."""

    on_mode_start: Callable[[str], None] = _noop
    on_mode_end: Callable[[], None] = _noop
    on_intent: Callable[[ActivationIntent], None] = _noop
    # True while the user is speaking; lets the jaw-clench detector ignore the jaw
    # movement of speech and chewing-like articulation. Optional.
    speech_active: Callable[[], bool] | None = None


class BiosignalRunner:
    """Activation source over a :class:`BlockSource`, mirroring ``BrainFlowSource``."""

    def __init__(
        self,
        source_factory: Callable[[], BlockSource],
        pipeline_factory: Callable[[BlockSource], BiosignalPipeline],
        callbacks: RunnerCallbacks | None = None,
        *,
        mode_map: Mapping[str, str] | None = None,
        intent_map: Mapping[Any, str] | None = None,
        watchdog_seconds: float = DEFAULT_WATCHDOG_SECONDS,
        poll_seconds: float = _POLL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        ledger_path: str | Path | None = None,
        autosave_seconds: float = DEFAULT_AUTOSAVE_SECONDS,
    ) -> None:
        cb = callbacks or RunnerCallbacks()
        self._source_factory = source_factory
        self._pipeline_factory = pipeline_factory
        self._on_start, self._on_end, self._on_intent = (
            cb.on_mode_start, cb.on_mode_end, cb.on_intent)
        self._mode_map = {str(k).lower(): str(v) for k, v in
                          (DEFAULT_MODE_MAP if mode_map is None else mode_map).items() if v}
        self._intent_map = DEFAULT_INTENT_MAP if intent_map is None else intent_map
        self.vocabulary: tuple[str, ...] = intent_vocabulary(self._intent_map)
        self._watchdog_s = max(float(watchdog_seconds), 0.0)
        self._poll_s = poll_seconds
        self._clock = clock
        self._ledger_path: Path | None = (
            Path(ledger_path).expanduser() if ledger_path else None)
        self._autosave_s = max(float(autosave_seconds), 0.0)

        self._stop = threading.Event()
        self._lock = threading.Lock()
        # Serializes squeeze state changes *with* their callbacks (RLock: a callback may
        # re-enter, e.g. on_mode_end -> stop()). Lock order: _squeeze_lock -> _lock.
        self._squeeze_lock = threading.RLock()
        self._save_lock = threading.Lock()
        self._saved: dict[str, Any] = {}     # session counters already in the file
        self._next_save = 0.0
        self._save_warned = False
        self._source: BlockSource | None = None
        self._pipeline: BiosignalPipeline | None = None
        # --- guarded by _lock ---
        self._running = False
        self._mode = ""              # active mode, "" when relaxed
        self._last_block = 0.0       # clock() at the last block; 0 = none yet
        self._blocks = 0
        self._events = 0
        self._intents = 0
        self._watchdog_trips = 0
        self._last_error = ""
        self._pipeline_status = PipelineStatus()

    # ---- public surface for the daemon -----------------------------------

    @property
    def pipeline(self) -> BiosignalPipeline | None:
        """The live pipeline (None until ``run()`` has built it). Read-only."""
        return self._pipeline

    @property
    def ledger(self) -> Any:
        """The activation ledger (``fprate.ActivationLedger``), or None when there is none."""
        pipeline = self._pipeline
        return pipeline.ledger if pipeline is not None else None

    @property
    def persists_ledger(self) -> bool:
        """True when the runner itself saves the ledger (autosave and on stop).

        A caller that also persists the session's counters would count them twice.
        """
        return self._ledger_path is not None

    def note_cancelled(self, kind: str | EventKind | None = None) -> bool:
        """The user undid or cancelled the latest switch activation: a false positive.

        ``kind`` narrows it to one switch (``"double_blink"``, ``"jaw_clench"``, ...);
        None means the latest of any kind. Returns True when the ledger matched one inside
        its grace window; False when there is no pipeline, no ledger, or an unknown kind.
        """
        pipeline = self._pipeline
        if pipeline is None:
            return False
        event_kind: EventKind | None = None
        if kind is not None:
            event_kind = _coerce_kind(kind)
            if event_kind is None:
                log.debug("note_cancelled: unknown activation kind %r ignored.", kind)
                return False
        return pipeline.note_cancelled(event_kind)

    def governor_release(self) -> GovernorAction:
        """The user said "carry on": end any desensitization or suspension immediately."""
        pipeline = self._pipeline
        if pipeline is None:
            from yazses.biosignal.fprate import GovernorAction

            return GovernorAction.ok()
        return pipeline.governor_release()

    def save_ledger(self) -> bool:
        """Write the aggregate counters now. True if the file changed; never raises.

        Adds only the change since the previous save to what the file holds at this moment
        (see the module docstring), so repeating it is harmless.
        """
        path, ledger = self._ledger_path, self.ledger
        if path is None or ledger is None:
            return False
        with self._save_lock:
            try:
                session: dict[str, Any] = ledger.to_dict()
                delta = _ledger_delta(session, self._saved)
                if not _ledger_delta_has_data(delta):
                    return False
                merged = _ledger_merge(_read_ledger(path), delta)
                _write_json_atomic(path, merged)
                self._saved = session
                return True
            except Exception:
                level = logging.DEBUG if self._save_warned else logging.WARNING
                self._save_warned = True
                log.log(level, "Could not save the biosignal activation counters.",
                        exc_info=True)
                return False

    # ---- lifecycle -------------------------------------------------------

    def run(self) -> None:
        """Stream until ``stop()`` or the source ends. Any failure is logged and ends it."""
        with self._lock:
            if self._running:
                log.warning("Biosignal runner already running; ignoring second run().")
                return
            self._running = True
        watchdog: threading.Thread | None = None
        source: BlockSource | None = None
        try:
            source = self._open()
            if source is None:
                return
            self._source = source
            self._pipeline = self._pipeline_factory(source)
            with self._lock:
                self._last_block = self._clock()
            if self._watchdog_s > 0:
                watchdog = threading.Thread(target=self._watchdog_loop,
                                            name="biosignal-watchdog", daemon=True)
                watchdog.start()
            self._next_save = self._clock() + self._autosave_s
            while not self._stop.is_set():
                if not self.step():
                    self._stop.wait(self._poll_s)
                self._maybe_autosave()
        except EOFError:
            log.info("Biosignal source ended (finite source reached its end).")
        except Exception as exc:
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
            log.warning("Biosignal runner stopped after an error; "
                        "dictation continues without it.", exc_info=True)
        finally:
            self._stop.set()                 # also releases the watchdog thread
            self._release_squeeze("runner stopped")
            self._finish_ledger()
            self._close(source)
            if watchdog is not None:
                watchdog.join(timeout=1.0)
            with self._lock:
                self._running = False

    def stop(self) -> None:
        """Ask ``run()`` to finish. Safe from any thread, idempotent.

        Also releases a held squeeze and saves the counters *here*, on the caller's thread:
        the run thread may be stuck inside a hung ``source.read()`` and never get to its own
        cleanup, and the watchdog stops with the runner, so without this a stop during a
        device stall would leave the dictation key down.
        """
        self._stop.set()
        self._release_squeeze("stop requested")
        self.save_ledger()

    # ---- one iteration (also the unit-test seam) --------------------------

    def step(self) -> bool:
        """Read and process at most one block. Returns True if a block was handled."""
        source, pipeline = self._source, self._pipeline
        if source is None or pipeline is None:
            return False
        block = source.read()
        if block is None:
            return False
        now = self._clock()
        with self._lock:
            gap = now - self._last_block if self._last_block else 0.0
            self._last_block = now
            self._blocks += 1
        if self._watchdog_s > 0 and gap > self._watchdog_s:
            # Detector and filter state is stale across a gap this long.
            log.info("Biosignal stream resumed after %.1f s; resetting detectors.", gap)
            # Before the reset: resetting makes the pipeline forget a held squeeze, so if
            # the watchdog has not got to it yet nothing would ever send its OFF.
            self._release_squeeze("stream gap")
            pipeline.reset()
        result = pipeline.process(block)
        with self._lock:
            self._pipeline_status = result.status
            self._events += len(result.events)
        self._handle_events(result.events)
        return True

    def check_watchdog(self, now: float | None = None) -> bool:
        """Release a held squeeze if no block has arrived for the watchdog period.

        Returns True if it fired. Public so it can be driven deterministically.
        """
        if self._watchdog_s <= 0:
            return False
        with self._squeeze_lock:
            t = self._clock() if now is None else now
            with self._lock:
                if not self._mode or not self._last_block:
                    return False
                if t - self._last_block <= self._watchdog_s:
                    return False
                self._mode = ""
                self._watchdog_trips += 1
            log.warning("No biosignal block for > %.1f s while a squeeze was held; "
                        "releasing it.", self._watchdog_s)
            self._call_release()
        return True

    def status(self) -> dict[str, Any]:
        """Plain-dict snapshot for IPC / the CLI. Safe from any thread."""
        now = self._clock()
        with self._lock:
            age = (now - self._last_block) if self._last_block else None
            snap = self._pipeline_status
            out: dict[str, Any] = {
                "running": self._running,
                "squeeze_active": bool(self._mode),
                "mode": self._mode,
                "blocks": self._blocks,
                "events": self._events,
                "intents": self._intents,
                "last_block_age_s": None if age is None else round(age, 3),
                "watchdog_trips": self._watchdog_trips,
                "last_error": self._last_error,
                "vocabulary": list(self.vocabulary),
                "pipeline": snap.as_dict(),
            }
        # The governor and ledger have locks of their own; read them outside ours.
        out["governor"] = self._governor_status()
        out["ledger"] = self._ledger_summary()
        out["ledger_persisted"] = self.persists_ledger
        return out

    def _governor_status(self) -> dict[str, str]:
        pipeline = self._pipeline
        governor = pipeline.governor if pipeline is not None else None
        if pipeline is None or governor is None:
            return {"state": "off", "explain": ""}
        explain = ""
        try:
            explain = str(governor.explain())
        except Exception:
            log.debug("governor explain failed", exc_info=True)
        return {"state": pipeline.governor_state or "ok", "explain": explain}

    def _ledger_summary(self) -> str:
        ledger = self.ledger
        if ledger is None:
            return ""
        try:
            from yazses.biosignal.fprate import summary

            return str(summary(ledger))
        except Exception:
            log.debug("ledger summary failed", exc_info=True)
            return ""

    # ---- internals -------------------------------------------------------

    def _open(self) -> BlockSource | None:
        """Create and start the source, or None with the reason logged."""
        source: BlockSource | None = None
        try:
            source = self._source_factory()
            source.start()
            log.info("Biosignal source streaming (fs=%s Hz, %d channels).",
                     getattr(source, "fs", "?"), len(getattr(source, "channels", ())))
            return source
        except ModuleNotFoundError as exc:
            with self._lock:
                self._last_error = f"missing dependency: {exc.name}"
            log.info("Biosignal source needs %s, which is not installed — biosignal "
                     "source disabled.", exc.name)
            self._close(source)
        except Exception as exc:
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
            log.warning("Biosignal source unavailable (%s); continuing without it.", exc)
            self._close(source)       # a half-started device must not stay claimed
        return None

    @staticmethod
    def _close(source: BlockSource | None) -> None:
        if source is None:
            return
        try:
            source.stop()
        except Exception:  # pragma: no cover - teardown is best effort
            log.debug("Biosignal source stop failed", exc_info=True)

    def _handle_events(self, events: tuple[BioEvent, ...]) -> None:
        for event in events:
            if event.kind is EventKind.SQUEEZE_ON:
                self._squeeze_on(event)
            elif event.kind is EventKind.SQUEEZE_OFF:
                self._release_squeeze("squeeze released")
        intents = events_to_intents(events, self._intent_map)
        if intents:
            with self._lock:
                self._intents += len(intents)
            for intent in intents:
                self._call(self._on_intent, intent)

    def _mode_for(self, event: BioEvent) -> str:
        detail = event.detail or {}
        for key in (detail.get("level"), detail.get("mode"), "on"):
            if key is None:
                continue
            mode = self._mode_map.get(str(getattr(key, "value", key)).lower())
            if mode:
                return mode
        return ""

    def _squeeze_on(self, event: BioEvent) -> None:
        mode = self._mode_for(event)
        if not mode:
            log.debug("Squeeze has no mode in the mode map; ignored.")
            return
        with self._squeeze_lock:
            if self._stop.is_set():
                return                       # stopping: never start what stop() just ended
            with self._lock:
                if mode == self._mode:
                    return                   # same level still held
                self._mode = mode
            self._call(self._on_start, mode)

    def _release_squeeze(self, why: str) -> bool:
        """End a held squeeze (idempotent). True if one was held."""
        with self._squeeze_lock:
            with self._lock:
                if not self._mode:
                    return False             # nothing held (also swallows orphan OFFs)
                self._mode = ""
            log.debug("Biosignal squeeze ended: %s", why)
            self._call_release()
        return True

    def _call_release(self) -> None:
        """Run ``on_mode_end``; if it raises, try once more — a key left down is the
        worst failure this runner has, so one transient error must not decide it."""
        for attempt in range(_RELEASE_ATTEMPTS):
            if self._call(self._on_end):
                return
            log.warning("Biosignal on_mode_end failed (attempt %d/%d).",
                        attempt + 1, _RELEASE_ATTEMPTS)

    def _maybe_autosave(self) -> None:
        if self._ledger_path is None or self._autosave_s <= 0:
            return
        now = self._clock()
        if now < self._next_save:
            return
        self._next_save = now + self._autosave_s
        self.save_ledger()

    def _finish_ledger(self) -> None:
        """End of run: stop accruing exposure time, then write the final counters."""
        ledger = self.ledger
        if ledger is not None:
            try:
                ledger.pause()
            except Exception:
                log.debug("ledger pause failed", exc_info=True)
        self.save_ledger()

    def _watchdog_loop(self) -> None:
        interval = max(min(self._watchdog_s / 4.0, 0.25), 0.005)
        while not self._stop.wait(interval):
            try:
                self.check_watchdog()
            except Exception:  # pragma: no cover - never let the watchdog die silently
                log.warning("Biosignal watchdog error", exc_info=True)

    @staticmethod
    def _call(fn: Callable[..., None], *args: Any) -> bool:
        """Invoke a daemon callback; a raising callback must not end the runner."""
        try:
            fn(*args)
            return True
        except Exception:
            log.warning("Biosignal callback %s raised; ignoring.",
                        getattr(fn, "__name__", fn), exc_info=True)
            return False


# ---------------------------------------------------------------------------
# Ledger persistence (aggregate counters only)


def _coerce_kind(kind: str | EventKind) -> EventKind | None:
    if isinstance(kind, EventKind):
        return kind
    text = str(kind).strip()
    try:
        return EventKind(text.lower())
    except ValueError:
        return EventKind.__members__.get(text.upper())


def _as_count(value: Any) -> int:
    """A non-negative int from untrusted JSON, else 0 (bool is not a count)."""
    if isinstance(value, bool):
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {str(k): n for k, v in value.items() if (n := _as_count(v)) > 0}


def _ledger_delta(session: Mapping[str, Any], saved: Mapping[str, Any]) -> dict[str, Any]:
    """What ``session`` gained since ``saved`` (counters only ever grow within a session)."""
    def diff(new: dict[str, int], old: dict[str, int]) -> dict[str, int]:
        return {k: d for k, n in new.items() if (d := n - old.get(k, 0)) > 0}

    return {
        "schema": session.get("schema", 1),
        "sessions": max(_as_count(session.get("sessions")) - _as_count(saved.get("sessions")), 0),
        "active_seconds": max(_as_count(session.get("active_seconds"))
                              - _as_count(saved.get("active_seconds")), 0),
        "activations": diff(_counts(session.get("activations")),
                            _counts(saved.get("activations"))),
        "cancelled": diff(_counts(session.get("cancelled")), _counts(saved.get("cancelled"))),
    }


def _ledger_delta_has_data(delta: Mapping[str, Any]) -> bool:
    """A save is worth a disk write only if it carries something besides a session tick."""
    return bool(delta["activations"] or delta["cancelled"] or delta["active_seconds"])


def _read_ledger(path: Path) -> dict[str, Any]:
    """The stored counters, sanitized; ``{}`` for a missing or corrupt file. Never raises."""
    try:
        if not path.is_file() or path.stat().st_size > _MAX_LEDGER_BYTES:
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(raw, Mapping):
        return {}
    return {
        "schema": raw.get("schema", 1),
        "sessions": _as_count(raw.get("sessions")),
        "active_seconds": _as_count(raw.get("active_seconds")),
        "activations": _counts(raw.get("activations")),
        "cancelled": _counts(raw.get("cancelled")),
    }


def _ledger_merge(stored: Mapping[str, Any], delta: Mapping[str, Any]) -> dict[str, Any]:
    def add(a: Mapping[str, int], b: Mapping[str, int]) -> dict[str, int]:
        out = dict(a)
        for k, n in b.items():
            out[k] = out.get(k, 0) + n
        return out

    acts = add(stored.get("activations") or {}, delta["activations"])
    # A cancellation belongs to an activation: never report more of the first.
    canc = {k: min(n, acts.get(k, 0)) for k, n in
            add(stored.get("cancelled") or {}, delta["cancelled"]).items()}
    return {
        "schema": delta.get("schema", stored.get("schema", 1)),
        "sessions": _as_count(stored.get("sessions")) + delta["sessions"],
        "active_seconds": _as_count(stored.get("active_seconds")) + delta["active_seconds"],
        "activations": acts,
        "cancelled": {k: n for k, n in canc.items() if n > 0},
    }


def _write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    """Temp file in the same directory + ``os.replace``; owner-only (0o600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".biosignal-ledger-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        tmp = ""
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Config -> runner


def _cfg(section: Any, name: str, default: Any) -> Any:
    value = getattr(section, name, default)
    return default if value is None else value


def _default_ledger_path() -> Path | None:
    """``<data_dir>/biosignal_ledger.json`` — the file ``yazses biosignal report`` reads."""
    try:
        from yazses.platform.factory import get_paths

        return Path(get_paths().data_dir) / _LEDGER_FILENAME
    except Exception:
        log.debug("Could not resolve the data directory; ledger will not be saved.",
                  exc_info=True)
        return None


def build_runner_from_config(
    cfg: Any,
    callbacks: RunnerCallbacks | None = None,
    *,
    ledger_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    autosave_seconds: float = DEFAULT_AUTOSAVE_SECONDS,
) -> BiosignalRunner | None:
    """Build a runner from ``cfg.biosignal``, or None when it is off or unusable.

    Reads every field with ``getattr`` and a default, so this works whether or not the
    ``BiosignalConfig`` dataclass has landed in ``config.py`` and for any older config
    object. Nothing is opened here: the source is created inside ``run()``, so a missing
    device or optional dependency is a logged no-op on the runner's thread, never a
    failure while the daemon is starting.

    The runner keeps an activation ledger and saves its aggregate counters (see
    :meth:`BiosignalRunner.save_ledger`). Where: ``ledger_path`` if given, else
    ``<data_dir>/biosignal_ledger.json``, else the platform data directory — the same file
    ``yazses biosignal report`` reads. Pass ``ledger_path=""`` to keep the ledger in memory
    only (nothing is written).
    """
    section = getattr(cfg, "biosignal", None)
    if section is None or not bool(_cfg(section, "enabled", False)):
        return None

    source_spec = str(_cfg(section, "source", "") or "").strip()
    if not source_spec:
        log.warning("[biosignal] enabled but no source configured; biosignal off.")
        return None
    try:
        from yazses.biosignal.sources import open_source
    except Exception:
        log.warning("Biosignal sources unavailable; biosignal off.", exc_info=True)
        return None

    cbs = callbacks or RunnerCallbacks()
    mains_hz = float(_cfg(section, "mains_hz", 50.0))
    double_blink = bool(_cfg(section, "double_blink", False))
    jaw_clench = bool(_cfg(section, "jaw_clench", False))
    emg = bool(_cfg(section, "emg", False))
    max_cancelled = float(_cfg(section, "max_cancelled_per_hour", 0.0))
    calibration_file = str(_cfg(section, "calibration_file", "") or "")
    mode_map = dict(_cfg(section, "mode_map", {}) or {}) or None
    intent_map = dict(_cfg(section, "intent_map", {}) or {})
    # Defaults apply only when the user left the map empty; an explicit map is theirs.
    effective_intents: dict[Any, str] = intent_map or dict(DEFAULT_INTENT_MAP)
    if not double_blink:
        effective_intents.pop("double_blink", None)
    if not jaw_clench:
        effective_intents.pop("jaw_clench", None)

    if ledger_path is None:
        resolved: Path | None = (Path(data_dir) / _LEDGER_FILENAME
                                 if data_dir else _default_ledger_path())
    else:
        resolved = Path(ledger_path) if str(ledger_path) else None

    graded = bool(mode_map) and "hard" in {str(k).lower() for k in (mode_map or {})}

    def make_pipeline(source: BlockSource) -> BiosignalPipeline:
        parts = build_parts(PartsRequest(
            fs=float(source.fs),
            mains_hz=mains_hz,
            double_blink=double_blink,
            jaw_clench=jaw_clench,
            emg=emg,
            graded_emg=graded or mode_map is None,
            max_cancelled_per_hour=max_cancelled,
            calibration_file=calibration_file,
            speech_guard=cbs.speech_active,
            channels=tuple(source.channels),
            with_ledger=True,
        ))
        return BiosignalPipeline(parts)

    return BiosignalRunner(
        source_factory=lambda: open_source(source_spec),
        pipeline_factory=make_pipeline,
        callbacks=cbs,
        mode_map=mode_map,
        intent_map=effective_intents,
        ledger_path=resolved,
        autosave_seconds=autosave_seconds,
    )
