"""Command bodies for ``yazses biosignal ...`` and the daemon's adapter around the runner.

The thin Typer wrappers live in ``cli.py``; everything that does work lives here so it can
be called, and tested, without Typer. Each ``run_*`` function takes the loaded config and
the data directory, prints to stdout/stderr, and returns a process exit code (0 ok,
1 the check or procedure failed, 2 it could not be attempted: bad source, missing file).

Nothing in this module is imported until a ``biosignal`` command runs or the daemon finds
``[biosignal] enabled`` set, and every sibling import is inside the function that needs
it, so a default install pays nothing and a missing optional backend (BrainFlow) is a
printed reason, not a traceback.

What is stored locally, and what is not. A calibration profile holds thresholds derived
from your own signal (``calibration.save_profile``, mode 0600). The activation ledger
holds *aggregate counters only* -- sessions, active seconds, and activations and cancelled
activations per event kind -- never a sample, a timestamp or an event (``fprate``). No raw
signal is written by anything here.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import random
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

OK = 0
FAILED = 1
UNUSABLE = 2

#: File name of the persisted activation counters, inside the platform data directory.
LEDGER_FILENAME = "biosignal_ledger.json"

#: Wall seconds between status lines in ``monitor``.
DEFAULT_MONITOR_INTERVAL_S = 1.0

#: Seconds the synthetic demo in ``monitor`` repeats its scripted gestures over.
_DEMO_HORIZON_S = 300.0
_DEMO_PERIOD_S = 8.0


def _say(text: str = "") -> None:
    print(text, flush=True)


def _warn(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Config -> a pipeline outside the daemon


@dataclass(frozen=True)
class Switches:
    """Which detectors a command runs: ``[biosignal]``, with per-command overrides."""

    emg: bool
    double_blink: bool
    jaw_clench: bool

    def names(self) -> str:
        on = [n for n, v in (("emg", self.emg), ("double_blink", self.double_blink),
                             ("jaw_clench", self.jaw_clench)) if v]
        return ", ".join(on) or "none"


def switches_from(bio: Any, emg: bool | None = None, blink: bool | None = None,
                  clench: bool | None = None) -> Switches:
    """``[biosignal]``'s detector flags, each replaced by an explicit command-line choice."""
    return Switches(
        emg=bool(bio.emg) if emg is None else emg,
        double_blink=bool(bio.double_blink) if blink is None else blink,
        jaw_clench=bool(bio.jaw_clench) if clench is None else clench,
    )


def source_spec(bio: Any, override: str = "") -> str:
    """The source spec to use: the command-line one, else ``[biosignal] source``."""
    return (override or str(bio.source or "")).strip()


def profile_path(bio: Any, data_dir: Path) -> Path:
    """``[biosignal] calibration_file``, else the default profile in ``data_dir``."""
    from yazses.biosignal.calibration import default_profile_path

    named = str(bio.calibration_file or "").strip()
    return Path(named).expanduser() if named else default_profile_path(data_dir)


def _scheme(spec: str) -> str:
    return spec.partition(":")[0].strip().lower()


def squeeze_expected(spec: str) -> bool:
    """Whether the muscle-squeeze switch could apply to this source (so it needs a profile).

    False only for a board known to be EEG-only (a Muse has no muscle channel). A 'mixed'
    board such as ``brainflow:-1``, a board the table does not list, a recording and a
    plain ``emg`` band all return True, so a missing calibration is still reasoned about.
    """
    if _scheme(spec) != "brainflow":
        return True
    try:
        from yazses.biosignal.boards import preset_for

        preset = preset_for(spec)
    except Exception:
        return True
    return preset is None or str(preset.kind_hint).strip().lower() != "eeg"


def _reasons_from(result: Any) -> list[str] | None:
    """Plain-language problems out of whatever ``calibration.check_profile`` returned.

    ``[]`` means "no problem found"; ``None`` means the result could not be understood and
    the caller should use its own checks instead.
    """
    if result is None or result is True:
        return []
    if result is False:
        return ["the saved calibration does not fit this setup"]
    if isinstance(result, str):
        return [result.strip()] if result.strip() else []
    if isinstance(result, dict):
        ok = result.get("ok", result.get("usable"))
        items: Any = result.get("problems") or result.get("reasons") or result.get("issues")
        if items is None:
            text = str(result.get("reason") or result.get("message") or "").strip()
            return [] if ok or not text else [text]
        return _reasons_from(items)
    if isinstance(result, (list, tuple, set, frozenset)):
        out: list[str] = []
        for item in result:
            sub = _reasons_from(item)
            if sub is None:
                return None
            out.extend(sub)
        return out
    for flag in ("ok", "usable", "valid"):
        if getattr(result, flag, None) is True:
            return []
    for name in ("problems", "reasons", "issues"):
        items = getattr(result, name, None)
        if items:
            return _reasons_from(list(items))
    for name in ("reason", "message", "detail"):
        text = str(getattr(result, name, "") or "").strip()
        if text:
            return [text]
    return None


def calibration_problems(profile: Any, spec: str, now: datetime | None = None) -> list[str]:
    """What is wrong with a saved calibration for this source, in plain words (``[]`` if fine).

    Uses ``calibration.check_profile`` when this build has it, and otherwise (or if its
    answer cannot be read) the wrong-board and too-old checks. Never an amplitude.
    """
    from yazses.biosignal import calibration

    when = now or datetime.now(UTC)
    board = ":".join(spec.split(":")[:2]) if _scheme(spec) == "brainflow" else _scheme(spec)
    check = getattr(calibration, "check_profile", None)
    if callable(check):
        try:
            import inspect

            params = inspect.signature(check).parameters
            offered = {"board_id": board, "board": board, "spec": spec, "source": spec,
                       "now": when}
            found = _reasons_from(check(profile, **{k: v for k, v in offered.items()
                                                    if k in params}))
        except Exception:
            log.debug("calibration.check_profile failed", exc_info=True)
            found = None
        if found is not None:
            return found
    if profile.board_id != board:
        return [f"the calibration was made for {profile.board_id!r}, not {board!r}; "
                "amplitudes do not carry over to another board or placement"]
    if calibration.profile_is_stale(profile, when):
        return [f"the calibration is old ({profile.created_at or 'unknown date'}): "
                "skin and electrode contact drift"]
    return []


def _open(spec: str, *, realtime: bool = False) -> Any:
    """``open_source`` with pacing asked of the sources that support it (never BrainFlow)."""
    from yazses.biosignal.sources import open_source

    kw: dict[str, Any] = {"realtime": True} if realtime and _scheme(spec) in (
        "synthetic", "file") else {}
    return open_source(spec, **kw)


def _build_pipeline(
    bio: Any, source: Any, switches: Switches, data_dir: Path,
    clock: Callable[[], float] | None = None,
) -> tuple[Any, Any, Any]:
    """The same pipeline the daemon's runner builds, plus a ledger always attached.

    Returns ``(pipeline, parts, ledger)``. The daemon only keeps a ledger while the
    false-positive governor is on; ``monitor`` and ``replay`` exist to *measure* the rate,
    so they always have one, driven by ``clock`` (data time for a replay, so a recording
    replayed in one second is still measured per hour of recorded signal).
    """
    from yazses.biosignal.fprate import ActivationLedger
    from yazses.biosignal.pipeline import BiosignalPipeline, PartsRequest, build_parts

    mode_map = {str(k).lower(): v for k, v in dict(bio.mode_map or {}).items()}
    graded = not mode_map or "hard" in mode_map     # the runner's own rule
    parts = build_parts(PartsRequest(
        fs=float(source.fs),
        mains_hz=float(bio.mains_hz),
        double_blink=switches.double_blink,
        jaw_clench=switches.jaw_clench,
        emg=switches.emg,
        graded_emg=graded,
        max_cancelled_per_hour=0.0,
        calibration_file=str(profile_path(bio, data_dir)),
        channels=tuple(source.channels),
        source_spec=str(getattr(bio, "source", "") or ""),
        calibration_max_age_days=float(getattr(bio, "calibration_max_age_days", 30.0)),
        min_event_confidence=float(getattr(bio, "min_event_confidence", 0.0)),
    ))
    ledger = ActivationLedger(clock) if clock is not None else ActivationLedger()
    parts.ledger = ledger
    return BiosignalPipeline(parts), parts, ledger


def format_event(event: Any) -> str:
    """One detection as a table row: time, kind, confidence, channel, squeeze level."""
    level = (event.detail or {}).get("level")
    extra = f"  level={getattr(level, 'value', level)}" if level is not None else ""
    channel = f"  ch={event.channel}" if event.channel else ""
    return f"{event.t:9.2f}s  {event.kind.value:<13}  conf={event.confidence:4.2f}{channel}{extra}"


def _pump(
    source: Any, pipeline: Any, on_result: Callable[[Any, Any], None], *,
    sim_clock: list[float] | None = None, max_seconds: float = 0.0,
) -> str:
    """Read a source to its end or the deadline, feeding the pipeline. Returns why it stopped.

    ``sim_clock[0]`` is set to the end of each block's data time before it is processed,
    for a ledger driven by recorded time. A source that cannot deliver (an unplugged
    board) ends the loop with its own reason rather than waiting for ever.
    """
    deadline = time.monotonic() + max_seconds if max_seconds > 0 else None
    source.start()
    try:
        if getattr(source, "available", True) is False:
            return str(getattr(source, "last_error", "") or "the source is not available")
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                return "time limit reached"
            try:
                block = source.read()
            except EOFError:
                return "end of recording"
            if block is None:
                if getattr(source, "available", True) is False:
                    return str(getattr(source, "last_error", "") or "the source went away")
                time.sleep(0.005)
                continue
            if sim_clock is not None:
                sim_clock[0] = float(block.t0) + float(block.duration)
            on_result(block, pipeline.process(block))
    finally:
        source.stop()


def _channel_table(report: Any, source: Any) -> list[str]:
    kinds = {c.name: c.kind.value for c in getattr(source, "channels", ())}
    rows = [f"  {'channel':<10} {'kind':<5} {'quality':<9} {'score':>5}  reasons"]
    for ch in report.channels:
        rows.append(f"  {ch.name:<10} {kinds.get(ch.name, '?'):<5} {ch.status.value:<9} "
                    f"{ch.score:5.2f}  {', '.join(ch.reasons) or '-'}")
    return rows


def _counts_table(counts: dict[Any, int]) -> list[str]:
    if not counts:
        return ["  (no detections)"]
    return [f"  {kind.value:<13} {n:>5}" for kind, n in sorted(
        counts.items(), key=lambda kv: kv[0].value)]


# ---------------------------------------------------------------------------
# doctor


def _brainflow_state() -> tuple[bool, str]:
    import importlib.util
    from importlib import metadata

    if importlib.util.find_spec("brainflow") is None:
        return False, ""
    try:
        return True, metadata.version("brainflow")
    except metadata.PackageNotFoundError:
        return True, "unknown version"


def _serial_ports() -> list[str]:
    """Visible serial ports as ``device (description)``; pyserial when present, else a glob."""
    try:
        import importlib

        list_ports = importlib.import_module("serial.tools.list_ports")
        return [f"{p.device} ({p.description})" for p in list_ports.comports()]
    except Exception:  # no pyserial, or a platform it cannot enumerate: fall back
        import glob

        found: list[str] = []
        for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usbserial*", "/dev/cu.usbmodem*"):
            found.extend(sorted(glob.glob(pattern)))
        return found


def _self_check() -> tuple[bool, list[str]]:
    """Run scripted synthetic gestures through the real pipeline; no hardware, no files.

    Two blinks 0.5 s apart must come out as one double blink, and the signal-quality gate
    must not be BAD at the end. Proves the filters, quality monitor and blink detector
    import and agree with each other on this machine -- not that your electrodes work.
    """
    from yazses.biosignal.sources import SyntheticSource

    lines: list[str] = []
    # The blink pair is placed after the detectors' warm-up (2 s plus the filters' start-up).
    # A pair at 8 s was once missed because the band-pass ringing merged the two blinks into
    # one excursion; BlinkDetector now splits them, and 15 s keeps a wide margin.
    source = SyntheticSource("mixed", seed=1, duration=24.0, mains_hz=50.0)
    source.schedule_blink(15.0).schedule_blink(15.5)
    from types import SimpleNamespace

    bio = SimpleNamespace(mains_hz=50, mode_map={}, calibration_file="")
    pipeline, parts, _ledger = _build_pipeline(
        bio, source, Switches(emg=False, double_blink=True, jaw_clench=False), Path("."))
    kinds: list[str] = []

    def collect(_block: Any, result: Any) -> None:
        kinds.extend(e.kind.value for e in result.events)

    _pump(source, pipeline, collect)
    report = parts.quality.report if parts.quality is not None else None
    ok = True
    if "double_blink" in kinds:
        lines.append("  [OK]   scripted double blink detected")
    else:
        ok = False
        lines.append(f"  [FAIL] scripted double blink not detected (events: {kinds or 'none'})")
    if report is None:
        ok = False
        lines.append("  [FAIL] no signal-quality report")
    elif report.overall.value == "bad":
        ok = False
        lines.append("  [FAIL] clean synthetic signal judged BAD by the quality gate")
    else:
        lines.append(f"  [OK]   quality gate: {report.overall.value}")
    return ok, lines


def run_doctor(cfg: Any, data_dir: Path, *, boards: bool = False, source: str = "") -> int:
    """What this machine can do for a biosignal switch, and whether the code path is sound.

    Ends with one ``Verdict:`` line: ``ready``, or the single most important next step.
    """
    bio = cfg.biosignal
    spec = source_spec(bio, source)
    scheme = _scheme(spec)
    _say("YazSes biosignal doctor")
    _say(f"  [biosignal] enabled = {bio.enabled}   source = {spec or '(none)'}   "
         f"mains = {bio.mains_hz} Hz")
    sw = switches_from(bio)
    _say(f"  detectors: {sw.names()}")
    steps: list[str] = []           # next steps, most important first

    path = profile_path(bio, data_dir)
    from yazses.biosignal.calibration import load_profile, profile_is_stale

    profile = load_profile(path)
    needs_squeeze = sw.emg and scheme not in ("", "synthetic") and squeeze_expected(spec)
    if profile is None:
        _say(f"  calibration: none at {path}  ->  run `yazses biosignal calibrate`"
             + ("  (the muscle-squeeze switch stays off without it)" if sw.emg else ""))
        if needs_squeeze:
            steps.append("run `yazses biosignal calibrate` (the muscle-squeeze switch stays "
                         "off without it)")
    else:
        problems = calibration_problems(profile, spec) if scheme else []
        stale = profile_is_stale(profile, datetime.now(UTC))
        _say(f"  calibration: {profile.summary()}" + ("  [STALE: recalibrate]" if stale else ""))
        for problem in problems:
            _say(f"  [--]   {problem}")
        if problems and scheme not in ("", "synthetic"):
            steps.append("run `yazses biosignal calibrate` again, because " + problems[0])

    _say()
    present, version = _brainflow_state()
    if present:
        _say(f"  [OK]   brainflow {version}")
    else:
        try:
            from yazses.system.remedy import install_hint

            hint = install_hint("emg-band")
        except Exception:
            hint = ""
        _say("  [--]   brainflow is not installed (only `synthetic` and `file:` sources work)"
             + (f". {hint}" if hint else ""))
        if scheme == "brainflow":
            steps.insert(0, "install BrainFlow, which the source needs" + (f": {hint}" if hint else ""))
    ports = _serial_ports()
    _say(f"  serial ports: {', '.join(ports) if ports else 'none visible'}")

    if present:
        from yazses.biosignal.sources import SYNTHETIC_BOARD_ID, describe_board

        ids: list[int] = [SYNTHETIC_BOARD_ID]
        if scheme == "brainflow":
            try:
                ids.append(int(spec.split(":")[1]))
            except (IndexError, ValueError):
                _warn(f"  [FAIL] source {spec!r} needs an integer board id")
                steps.insert(0, "write the source as brainflow:<board id>[:<port>] "
                                "(`yazses biosignal boards` lists the ids)")
        if boards:
            from brainflow.board_shim import BoardIds

            ids = sorted({int(b.value) for b in BoardIds})
        for board_id in dict.fromkeys(ids):
            for line in describe_board(board_id).format().splitlines():
                _say("  " + line)
        if not boards:
            _say("  (`yazses biosignal doctor --boards` lists every board BrainFlow knows)")

    if spec and scheme not in ("synthetic", "file", "brainflow"):
        _warn(f"  [FAIL] unknown source {spec!r}; expected synthetic, file:<path> "
              "or brainflow:<board_id>[:<port>]")
        steps.insert(0, "fix the source: synthetic, file:<path> or brainflow:<board id>[:<port>]")

    _say()
    _say("Self-check (synthetic signal through the real pipeline):")
    try:
        ok, lines = _self_check()
    except Exception as exc:
        _say(f"  [FAIL] {type(exc).__name__}: {exc}")
        _say(_doctor_verdict(bio, spec, ["the built-in self-check could not run on this "
                                         "machine; the error above is what to report"]))
        return FAILED
    for line in lines:
        _say(line)
    if not ok:
        steps.insert(0, "the built-in self-check failed on this machine; the lines above "
                        "say which part, and that is what to report")
    _say()
    _say(_doctor_verdict(bio, spec, steps))
    return OK if ok else FAILED


def _doctor_verdict(bio: Any, spec: str, steps: list[str]) -> str:
    """The last line of ``doctor``: ready, or the one thing to do next."""
    if steps:
        return f"Verdict: not ready yet. Next step: {steps[0]}."
    if not spec:
        return ("Verdict: pick a source first. Try `yazses biosignal monitor --source "
                "synthetic` with no hardware, or see `yazses biosignal boards` for a board.")
    if not bio.enabled:
        return ("Verdict: ready. Nothing is switched on yet; to use it, set "
                "[biosignal] enabled = true and run `yazses restart`.")
    return ("Verdict: ready. To see how often it fires by mistake in your own day, run "
            "`yazses biosignal field-test`.")


# ---------------------------------------------------------------------------
# calibrate


def run_calibrate(
    cfg: Any, data_dir: Path, *, source: str = "", blink: bool | None = None,
    clench: bool | None = None, yes: bool = False,
) -> int:
    """Guided calibration on the configured source; saves the profile on success."""
    from yazses.biosignal.calibration import (
        CalibrationPhase,
        CalibrationSession,
        save_profile,
    )
    from yazses.biosignal.types import SignalKind

    bio = cfg.biosignal
    spec = source_spec(bio, source)
    if not spec:
        _warn("No source. Set [biosignal] source or pass --source (see `yazses biosignal doctor`).")
        return UNUSABLE
    if _scheme(spec) == "synthetic":
        _warn("The synthetic source makes no deliberate gestures, so there is nothing to "
              "calibrate on. Use a board, or `file:<recording>` of a calibration session.")
        return UNUSABLE
    try:
        src = _open(spec)
    except (ValueError, FileNotFoundError) as exc:
        _warn(f"Cannot open source {spec!r}: {exc}")
        return UNUSABLE
    src.start()
    try:
        if getattr(src, "available", True) is False or not src.channels or not src.fs:
            _warn(f"Source {spec!r} is not available: "
                  f"{getattr(src, 'last_error', '') or 'no channels reported'}")
            return UNUSABLE
        kinds = {c.kind for c in src.channels}
        want_blink = bool(bio.double_blink) if blink is None else blink
        want_clench = bool(bio.jaw_clench) if clench is None else clench
        have_blink = bool(kinds & {SignalKind.EOG, SignalKind.EEG})
        have_clench = bool(kinds & {SignalKind.EEG, SignalKind.EMG})
        if want_blink and not have_blink:
            _warn("Skipping the blink step: no EEG/EOG channel on this source.")
        if want_clench and not have_clench:
            _warn("Skipping the jaw-clench step: no EEG/EMG channel on this source.")
        board = ":".join(spec.split(":")[:2]) if _scheme(spec) == "brainflow" else _scheme(spec)
        try:
            session = CalibrationSession(
                board, src.channels, float(src.fs),
                include_squeeze=bool(bio.emg) and SignalKind.EMG in kinds,
                include_blink=want_blink and have_blink,
                include_clench=want_clench and have_clench,
            )
        except ValueError as exc:
            _warn(f"Cannot calibrate this source: {exc}")
            return UNUSABLE

        steps = " -> ".join(p.value for p in session.phases)
        _say(f"Calibrating on {spec}: {steps}. Nothing is typed or sent; only thresholds derived "
             "from your own signal are saved, in a file only you can read.")
        if not yes:
            try:
                input("Electrodes in place and relaxed? Press Enter to start (Ctrl-C cancels): ")
            except (EOFError, KeyboardInterrupt):
                _warn("\nNot started.")
                return UNUSABLE

        shown = ""
        last_pct = -1
        try:
            while not session.finished:
                prompt = session.prompt()
                if prompt != shown:
                    p = session.progress()
                    _say(f"\n[{min(p.phase_index + 1, p.phase_count)}/{p.phase_count}] {prompt}")
                    shown = prompt
                try:
                    block = src.read()
                except EOFError:
                    session.abort()
                    _warn("The recording ended before the calibration was complete.")
                    return FAILED
                issue = session.feed(block)
                if block is None:
                    time.sleep(0.005)
                elif sys.stdout.isatty():          # a redrawn percentage is noise in a log
                    pct = int(session.progress().phase_fraction * 100)
                    if pct != last_pct:
                        last_pct = pct
                        sys.stdout.write(f"\r  {pct:3d}%")
                        sys.stdout.flush()
                if issue is not None:
                    _say(f"\n  ! {issue.message}")
                    shown = ""          # the prompt now leads with the retry reason
        except KeyboardInterrupt:
            session.abort()
            _warn("\nCancelled; nothing was saved.")
            return FAILED
    finally:
        src.stop()

    if session.phase is not CalibrationPhase.DONE:
        issue = session.last_issue
        _warn(f"\nCalibration failed ({session.phase.value})"
              + (f": {issue.message}" if issue is not None else "."))
        return FAILED
    profile = session.result()
    path = profile_path(bio, data_dir)
    try:
        save_profile(profile, path)
    except OSError as exc:
        _warn(f"\nCalibrated, but the profile could not be saved to {path}: {exc}")
        return FAILED
    _say(f"\nDone. {profile.summary()}\nSaved to {path}")
    _say("Restart the daemon to use it (`yazses restart`), and check the rate you actually get "
         "with `yazses biosignal report`.")
    return OK


# ---------------------------------------------------------------------------
# monitor


def _script_demo(source: Any) -> None:
    """Queue a repeating run of scripted gestures on a synthetic source (the demo signal)."""
    t = 4.0
    while t < _DEMO_HORIZON_S:
        source.schedule_blink(t).schedule_blink(t + 0.5)
        source.schedule_clench(t + 3.0, 1.0)
        source.schedule_squeeze(t + 5.0, 1.5)
        t += _DEMO_PERIOD_S


#: How many recent events ``monitor`` lists.
_RECENT_N = 5


def recent_events_of(owner: Any, n: int = _RECENT_N) -> list[Any] | None:
    """``owner.recent_events(n)`` as a list, or ``None`` when it has none (or it fails)."""
    fn = getattr(owner, "recent_events", None)
    if not callable(fn):
        return None
    try:
        return list(fn(n))
    except Exception:
        log.debug("recent_events failed", exc_info=True)
        return None


def describe_recent(entry: Any, now: float | None = None) -> str:
    """One recent event in words: its kind, how long ago, accepted or dropped, and why."""
    def get(*names: str) -> Any:
        for name in names:
            value = entry.get(name) if isinstance(entry, dict) else getattr(entry, name, None)
            if value is not None:
                return value
        return None

    kind = get("kind")
    kind = getattr(kind, "value", kind) or "event"
    age = get("age_s", "age")
    if age is None and get("t") is not None and now is not None:
        age = now - float(get("t"))
    outcome = get("accepted", "outcome", "verdict", "status")
    if isinstance(outcome, str):
        accepted = outcome.strip().lower() in ("accepted", "ok", "passed", "fired")
    else:
        accepted = bool(outcome) if outcome is not None else True
    reason = str(get("reason", "why") or "").strip()
    text = f"{kind}, " + (f"{float(age):.0f} s ago, " if age is not None else "") + (
        "accepted" if accepted else "dropped")
    return text + (f" ({reason})" if reason and not accepted else "")


def run_monitor(
    cfg: Any, data_dir: Path, *, source: str = "", seconds: float = 0.0,
    interval: float = DEFAULT_MONITOR_INTERVAL_S, emg: bool | None = None,
    blink: bool | None = None, clench: bool | None = None,
) -> int:
    """Live signal quality and detections until Ctrl-C (or ``seconds``)."""
    from yazses.biosignal.fprate import summary
    from yazses.biosignal.quality import explain

    bio = cfg.biosignal
    spec = source_spec(bio, source)
    if not spec:
        _warn("No source. Set [biosignal] source, or try `yazses biosignal monitor "
              "--source synthetic`.")
        return UNUSABLE
    try:
        src = _open(spec, realtime=True)
    except (ValueError, FileNotFoundError) as exc:
        _warn(f"Cannot open source {spec!r}: {exc}")
        return UNUSABLE
    demo = _scheme(spec) == "synthetic" and hasattr(src, "schedule_blink")
    if demo:
        _script_demo(src)
    sw = switches_from(bio, emg, blink, clench)

    # Streaming sources only know their channels once started; build after start.
    src.start()
    if getattr(src, "available", True) is False or not src.fs:
        _warn(f"Source {spec!r} is not available: {getattr(src, 'last_error', '') or 'no data'}")
        src.stop()
        return UNUSABLE
    pipeline, parts, ledger = _build_pipeline(bio, src, sw, data_dir)
    _say(f"Monitoring {spec}  (fs {src.fs:g} Hz, {len(src.channels)} channels; detectors: "
         f"{sw.names()}).  Ctrl-C to stop."
         + ("  Demo gestures are scripted every 8 s." if demo else ""))
    if sw.emg and parts.detectors is not None and not any(
            type(d).__name__.startswith(("Emg", "GradedEmg")) for d in parts.detectors):
        _say("  Muscle squeeze: off until you calibrate (`yazses biosignal calibrate`).")

    counts: dict[Any, int] = {}
    started = time.monotonic()
    state: dict[str, Any] = {"next": started + max(interval, 0.1), "overall": "", "blocks": 0,
                             "dropped": 0, "shown": ""}
    # What the pipeline did with each event, newest last. Used unless the pipeline can list
    # its own recent events itself.
    local_recent: list[tuple[float, str, bool, str]] = []

    def recent_lines() -> list[str]:
        own = recent_events_of(pipeline)
        if own is not None:
            return [describe_recent(e, time.monotonic()) for e in own]
        now = time.monotonic()
        return [describe_recent({"kind": k, "age_s": now - t, "accepted": ok, "reason": why_},
                                now) for t, k, ok, why_ in local_recent[-_RECENT_N:]][::-1]

    def on_result(block: Any, result: Any) -> None:
        state["blocks"] += 1
        for event in result.events:
            counts[event.kind] = counts.get(event.kind, 0) + 1
            _say("  " + format_event(event))
            local_recent.append((time.monotonic(), event.kind.value, True, ""))
        dropped = int(getattr(result.status, "dropped", 0) or 0)
        if dropped > state["dropped"]:
            why_ = str(getattr(result.status, "reason", "") or
                       "the signal was not clean enough to trust it")
            local_recent.extend([(time.monotonic(), "an event", False, why_)]
                                * min(dropped - state["dropped"], _RECENT_N))
        state["dropped"] = dropped
        del local_recent[:-50]
        report = parts.quality.report if parts.quality is not None else None
        now = time.monotonic()
        if report is not None and report.overall.value != state["overall"]:
            state["overall"] = report.overall.value
            _say(f"\n  Signal quality: {report.overall.value}")
            for row in _channel_table(report, src):
                _say(row)
            for line in explain(report)[:6]:
                _say(f"  - {line}")
            _say()
        if now >= state["next"]:
            state["next"] = now + max(interval, 0.1)
            st = result.status
            _say(f"{now - started:7.1f}s  quality {st.quality:<8} events {st.accepted:>3} "
                 f"dropped {st.dropped:>3}  rate {st.rate_per_hour:6.1f}/h"
                 + ("  SUSPENDED: " + st.reason if st.suspended else "")
                 + ("  [squeeze held]" if st.squeeze_active else ""))
            lines = recent_lines()
            if lines and "|".join(lines) != state["shown"]:
                state["shown"] = "|".join(lines)
                _say("  recent: " + "; ".join(lines[:_RECENT_N]))

    try:
        why = _pump(src, pipeline, on_result, max_seconds=seconds)
    except KeyboardInterrupt:
        why = "stopped"
    _say(f"\nStopped ({why}) after {time.monotonic() - started:.1f} s, {state['blocks']} blocks.")
    _say("Detections:")
    for row in _counts_table(counts):
        _say(row)
    tail = recent_lines()
    if tail:
        _say("Most recent events (newest first):")
        for line in tail[:_RECENT_N]:
            _say(f"  {line}")
    _say("Measured: " + summary(ledger, with_note=True))
    return FAILED if why not in ("stopped", "time limit reached", "end of recording") else OK


# ---------------------------------------------------------------------------
# replay


def run_replay(
    cfg: Any, data_dir: Path, path: str, *, emg: bool | None = None,
    blink: bool | None = None, clench: bool | None = None, as_json: bool = False,
) -> int:
    """Run a recording through the pipeline; print each detection and the false-positive summary.

    The recording is processed as fast as possible, but the ledger runs on *recording time*,
    so the per-hour rate is per hour of recorded signal. A recording has no "undo", so the
    cancelled count is zero here by construction: judge the activation rate, and treat any
    activation you did not mean to make as a false positive by reading the list.
    """
    from yazses.biosignal.fprate import summary

    bio = cfg.biosignal
    try:
        src = _open(f"file:{path}")
    except (ValueError, FileNotFoundError) as exc:
        _warn(f"Cannot replay {path!r}: {exc}")
        return UNUSABLE
    sw = switches_from(bio, emg, blink, clench)
    sim = [0.0]
    pipeline, parts, ledger = _build_pipeline(bio, src, sw, data_dir, clock=lambda: sim[0])
    rows: list[Any] = []
    counts: dict[Any, int] = {}
    if not as_json:
        _say(f"Replaying {path}  ({src.duration:.1f} s, fs {src.fs:g} Hz, "
             f"{len(src.channels)} channels; detectors: {sw.names()})")
        if sw.jaw_clench:
            _say("  Note: no speech signal in a recording, so the jaw-clench speech guard is "
                 "off; clenches during talking will count.")

    def on_result(block: Any, result: Any) -> None:
        for event in result.events:
            rows.append(event)
            counts[event.kind] = counts.get(event.kind, 0) + 1
            if not as_json:
                _say("  " + format_event(event))

    why = _pump(src, pipeline, on_result, sim_clock=sim)
    ledger.stop()
    stats = ledger.total_stats()
    report = parts.quality.report if parts.quality is not None else None
    if as_json:
        _say(json.dumps({
            "path": path,
            "duration_s": round(float(src.duration), 3),
            "detectors": sw.names(),
            "quality": report.overall.value if report is not None else "unknown",
            "events": [{"t": round(e.t, 3), "kind": e.kind.value,
                        "confidence": round(e.confidence, 3), "channel": e.channel}
                       for e in rows],
            "counts": {k.value: n for k, n in counts.items()},
            "activations": stats.activations,
            "active_seconds": round(stats.active_seconds, 1),
            "activations_per_hour": round(stats.per_hour, 2),
        }, indent=2))
        return OK if why == "end of recording" else FAILED
    _say(f"\nDone ({why}).  Detections:")
    for row in _counts_table(counts):
        _say(row)
    if report is not None:
        _say(f"Signal quality at the end: {report.overall.value}")
    _say("False-positive summary: " + summary(ledger, with_note=True))
    if stats.active_seconds <= 0 and src.duration > 0:
        _say("  (The quality gate kept the detectors closed for the whole recording.)")
    return OK if why == "end of recording" else FAILED


# ---------------------------------------------------------------------------
# the persisted activation counters (aggregate only)


def ledger_path(data_dir: Path) -> Path:
    return Path(data_dir) / LEDGER_FILENAME


def _read_ledger_dict(path: Path) -> dict[str, Any]:
    """The stored counters, or ``{}`` when absent or unreadable. Never raises."""
    try:
        if not path.is_file() or path.stat().st_size > (1 << 20):
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def load_ledger(data_dir: Path) -> Any:
    """The stored counters as an :class:`ActivationLedger` (zero when there is no file)."""
    from yazses.biosignal.fprate import ActivationLedger

    return ActivationLedger.from_dict(_read_ledger_dict(ledger_path(data_dir)))


def _add_counts(a: Any, b: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for src in (a, b):
        if isinstance(src, dict):
            for key, value in src.items():
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    out[str(key)] = out.get(str(key), 0) + value
    return out


def persist_session_ledger(ledger: Any, data_dir: Path) -> None:
    """Add this session's counters to the stored totals. Atomic, owner-only, never raises.

    ``ledger`` is a session ledger that started empty, so ``to_dict`` is this session's
    counts alone and the merge is a plain sum with whatever the file already holds. Old
    totals are passed through ``from_dict`` first, which drops anything corrupt and clamps
    cancelled counts to the activations they belong to.
    """
    from yazses.biosignal.fprate import ActivationLedger

    path = ledger_path(data_dir)
    tmp = ""
    try:
        ledger.stop()
        new: dict[str, Any] = ledger.to_dict()
        old: dict[str, Any] = ActivationLedger.from_dict(_read_ledger_dict(path)).to_dict()
        merged = {
            "schema": new.get("schema", old.get("schema", 1)),
            "sessions": int(old.get("sessions", 0)) + int(new.get("sessions", 0)),
            "active_seconds": int(old.get("active_seconds", 0)) + int(new.get("active_seconds", 0)),
            "activations": _add_counts(old.get("activations"), new.get("activations")),
            "cancelled": _add_counts(old.get("cancelled"), new.get("cancelled")),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".biosignal-ledger-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        tmp = ""
    except Exception:
        log.warning("Could not save the biosignal activation counters.", exc_info=True)
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# report


def run_report(cfg: Any, data_dir: Path, *, as_json: bool = False) -> int:
    """Your own measured activation and cancel rate, from the local counters."""
    from yazses.biosignal.fprate import PROXY_NOTE, summary

    path = ledger_path(data_dir)
    ledger = load_ledger(data_dir)
    stats = ledger.total_stats()
    budget = float(cfg.biosignal.max_cancelled_per_hour)
    low, high = stats.wilson_interval()
    if as_json:
        by_kind = ledger.counts_by_kind()
        _say(json.dumps({
            "sessions": ledger.sessions,
            "active_seconds": round(stats.active_seconds, 1),
            "activations": stats.activations,
            "cancelled": stats.cancelled,
            "activations_per_hour": round(stats.per_hour, 2),
            "cancelled_per_hour": round(stats.cancelled_per_hour, 2),
            "cancelled_fraction_ci95": [round(low, 3), round(high, 3)] if stats.activations else None,
            "note": PROXY_NOTE,
            "budget_cancelled_per_hour": budget,
            "by_kind": {k.value: {"activations": a, "cancelled": c}
                        for k, (a, c) in by_kind.items()},
        }, indent=2))
        return OK
    if stats.activations == 0 and stats.active_seconds <= 0:
        _say(f"No biosignal activations recorded yet ({path}).")
        _say("Counters are kept by the daemon while `[biosignal] enabled` is on; nothing is "
             "collected otherwise.")
        return OK
    _say("Biosignal switch, measured on you:")
    _say(f"  {summary(ledger, with_note=True)}")
    _say(f"  sessions: {ledger.sessions}")
    if stats.activations:
        _say(f"  cancelled share of activations: {stats.cancelled / stats.activations:.0%} "
             f"(95% Wilson interval {low:.0%}-{high:.0%}, n={stats.activations})"
             + ("  -- few activations, so the interval is wide" if stats.activations < 30 else ""))
    by_kind = ledger.counts_by_kind()
    if by_kind:
        _say(f"  {'event':<13} {'activations':>11} {'cancelled':>9}")
        for kind, (acts, canc) in sorted(by_kind.items(), key=lambda kv: kv[0].value):
            _say(f"  {kind.value:<13} {acts:>11} {canc:>9}")
    if budget > 0:
        verdict = "within" if stats.cancelled_per_hour <= budget else "OVER"
        _say(f"  cancelled per hour: {stats.cancelled_per_hour:.1f} "
             f"({verdict} your budget of {budget:g}; [biosignal] max_cancelled_per_hour)")
    _say("  Here a cancel is a spoken \"undo\" within a few seconds of a switch activation; "
         "a keyboard undo is not seen, so the true rate is at least this high.")
    return OK


# ---------------------------------------------------------------------------
# shared helpers for record / evaluate: a scripted synthetic session and its truth

#: Gestures start after the detectors' baselines settle (see ``_self_check``).
_SESSION_WARMUP_S = 15.0
#: Shortest scripted session: warm-up plus one full gesture cycle.
MIN_SCRIPTED_SECONDS = 30.0
#: A blink pair this close together (seconds) is one double blink in the truth.
_DOUBLE_BLINK_GAP_S = 1.0
_MAX_TRUTH_BYTES = 5 << 20
_SESSION_FILE_SUFFIXES = (".csv", ".npz")


def _synthetic_session(spec: str, seconds: float, seed: int, mains_hz: float) -> Any:
    """A finite synthetic source for ``synthetic[:kind]`` with a seeded, scripted gesture list.

    Each cycle (about 8-10 s, the gap drawn from ``seed``) holds a blink pair, a jaw clench
    and a muscle squeeze, but only the ones the montage can show: a blink needs an EEG/EOG
    channel, a clench an EEG/EMG channel, a squeeze an EMG channel. The scripted events are
    the ground truth (``SyntheticSource.ground_truth``).
    """
    from yazses.biosignal.sources import open_source
    from yazses.biosignal.types import SignalKind

    src: Any = open_source(spec, duration=float(seconds), seed=int(seed), mains_hz=float(mains_hz))
    kinds = {c.kind for c in src.channels}
    eyes = bool(kinds & {SignalKind.EOG, SignalKind.EEG})
    jaw = bool(kinds & {SignalKind.EEG, SignalKind.EMG})
    muscle = SignalKind.EMG in kinds
    rng = random.Random(int(seed))
    t = _SESSION_WARMUP_S
    while t + 7.5 < seconds - 2.0:
        if eyes:
            src.schedule_blink(t).schedule_blink(t + 0.5)
        if jaw:
            src.schedule_clench(t + 3.0, 1.0)
        if muscle:
            src.schedule_squeeze(t + 5.0, 1.5)
        t += 8.0 + rng.uniform(0.0, 2.0)
    return src


def _detector_kinds(parts: Any) -> set[Any]:
    """The event kinds the built detectors can report (a missing calibration drops squeeze)."""
    from yazses.biosignal.types import EventKind

    kinds: set[Any] = set()
    for det in parts.detectors or ():
        name = type(det).__name__
        if name == "BlinkDetector":
            kinds.add(EventKind.DOUBLE_BLINK)
        elif name == "JawClenchDetector":
            kinds.add(EventKind.JAW_CLENCH)
        elif name.startswith(("Emg", "GradedEmg")):
            kinds.update({EventKind.SQUEEZE_ON, EventKind.SQUEEZE_OFF})
    return kinds


def _switch_truth(raw: Any, kinds: set[Any]) -> list[Any]:
    """Generator truth as switch-level events: a blink pair becomes one DOUBLE_BLINK.

    ``SyntheticSource.ground_truth`` lists single blinks; the switch reports a double blink
    at the second one. Lone blinks are not switch events and are dropped. Everything else
    passes through, kept only if its kind is in ``kinds``.
    """
    from yazses.biosignal.types import BioEvent, EventKind

    out: list[Any] = []
    blinks = sorted(e.t for e in raw if e.kind is EventKind.BLINK)
    if EventKind.DOUBLE_BLINK in kinds:
        i = 0
        while i + 1 < len(blinks):
            if blinks[i + 1] - blinks[i] <= _DOUBLE_BLINK_GAP_S:
                out.append(BioEvent(EventKind.DOUBLE_BLINK, blinks[i + 1]))
                i += 2
            else:
                i += 1
    out.extend(e for e in raw if e.kind is not EventKind.BLINK and e.kind in kinds)
    return sorted(out, key=lambda e: e.t)


def _truth_to_json(events: Any) -> str:
    return json.dumps({"events": [{"kind": e.kind.value, "t": round(float(e.t), 4)}
                                  for e in events]}, indent=2)


def load_truth(path: Path) -> list[Any]:
    """Labelled events from a JSON file: ``[{"kind": "double_blink", "t": 12.3}, ...]``.

    Also accepts ``{"events": [...]}`` (what ``record --truth-out`` writes). ``kind`` is an
    ``EventKind`` value (blink, double_blink, jaw_clench, squeeze_on, squeeze_off); ``t`` is
    seconds on the recording's clock. Raises ``ValueError`` naming the first bad entry.
    """
    from yazses.biosignal.types import BioEvent, EventKind

    if path.stat().st_size > _MAX_TRUTH_BYTES:
        raise ValueError(f"{path}: truth file is larger than {_MAX_TRUTH_BYTES >> 20} MB")
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("events") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected a list of events or {{\"events\": [...]}}")
    valid = ", ".join(k.value for k in EventKind)
    out: list[Any] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: event {i} is not an object")
        try:
            kind = EventKind(str(item.get("kind", "")).strip().lower())
        except ValueError:
            raise ValueError(f"{path}: event {i} has unknown kind {item.get('kind')!r} "
                             f"(expected one of: {valid})") from None
        t = item.get("t")
        if isinstance(t, bool) or not isinstance(t, int | float) or t < 0 or t != t:
            raise ValueError(f"{path}: event {i} needs a non-negative number for 't'")
        out.append(BioEvent(kind, float(t)))
    return sorted(out, key=lambda e: e.t)


def _jsonable(obj: Any) -> Any:
    """Plain JSON data from dataclasses, enums, tuples and NaN/inf floats."""
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(getattr(k, "value", k)): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set | frozenset):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return obj if obj == obj and obj not in (float("inf"), float("-inf")) else None
    if isinstance(obj, str | int | bool) or obj is None:
        return obj
    for attr in ("to_dict", "as_dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            return _jsonable(fn())
    return str(obj)


# ---------------------------------------------------------------------------
# record


def run_record(
    cfg: Any, data_dir: Path, *, source: str = "", seconds: float = 30.0, out: str = "",
    force: bool = False, seed: int = 0, truth_out: str = "", as_json: bool = False,
) -> int:
    """Write ``seconds`` of a source to a local CSV/``.npz`` file you can ``replay`` later.

    Recorded in *signal* time, so a synthetic or file source finishes at once and a board
    takes as long as the recording. The file is raw signal -- sensitive, biometric-adjacent
    data -- so it is owner-only (mode 0600), never overwritten without ``force``, and never
    sent anywhere. Ctrl-C stops early and keeps what was captured.
    """
    from yazses.biosignal.sources import RecordingTap

    bio = cfg.biosignal
    spec = source_spec(bio, source)
    if not spec:
        _warn("No source. Set [biosignal] source or pass --source "
              "(try `--source synthetic`; see `yazses biosignal doctor`).")
        return UNUSABLE
    if not out.strip():
        _warn("No output file. Pass --out <file>.csv or --out <file>.npz.")
        return UNUSABLE
    path = Path(out).expanduser()
    if path.suffix.lower() not in _SESSION_FILE_SUFFIXES:
        _warn(f"Use a .csv or .npz file name (got {path.name!r}); `replay` reads those.")
        return UNUSABLE
    truth_path = Path(truth_out).expanduser() if truth_out.strip() else None
    for target in (path, truth_path):
        if target is not None and os.path.lexists(target) and not force:
            _warn(f"{target} already exists; not overwriting. Pass --force to replace it, "
                  "or choose another --out.")
            return UNUSABLE
        if target is not None and os.path.lexists(target) and not target.is_file():
            _warn(f"{target} exists and is not a regular file.")
            return UNUSABLE
    if truth_path is not None and _scheme(spec) != "synthetic":
        _warn("--truth-out only applies to a synthetic source (the generator knows what it "
              "scripted); ignoring it.")
        truth_path = None

    try:
        if _scheme(spec) == "synthetic":
            if seconds < MIN_SCRIPTED_SECONDS:
                _warn(f"Under {MIN_SCRIPTED_SECONDS:g} s a synthetic recording holds no "
                      "scripted gestures (the detectors need a warm-up first).")
            src = _synthetic_session(spec, seconds, seed, float(bio.mains_hz))
        else:
            src = _open(spec)
    except (ValueError, FileNotFoundError) as exc:
        _warn(f"Cannot open source {spec!r}: {exc}")
        return UNUSABLE

    _warn("WARNING: a recording is raw biosignal data -- sensitive, biometric-adjacent "
          "information about you.\n         It is written only to the file below (owner-only, "
          "mode 0600). Keep it local; do not attach it to a public issue.")
    tap = RecordingTap(src, path)
    recorded = 0.0
    blocks = 0
    last_len = 0.0
    why = "time reached"
    wall_deadline = time.monotonic() + seconds * 2.0 + 15.0
    tap.start()
    try:
        if getattr(src, "available", True) is False or not tap.fs:
            _warn(f"Source {spec!r} is not available: "
                  f"{getattr(src, 'last_error', '') or 'no data'}")
            return UNUSABLE
        if not as_json:
            _say(f"Recording {spec} for {seconds:g} s to {path}  (Ctrl-C stops early, keeps the file)")
        # Blocks do not divide the length evenly (and floats add up inexactly), so reaching
        # the end of a source within half a block of the asked length is "time reached".
        slack = 1e-6
        while recorded < seconds - slack:
            if time.monotonic() > wall_deadline:
                why = "the source delivered too little data"
                break
            try:
                block = tap.read()
            except EOFError:
                why = "time reached" if recorded >= seconds - max(slack, last_len / 2) \
                    else "end of source"
                break
            if block is None:
                if getattr(src, "available", True) is False:
                    why = str(getattr(src, "last_error", "") or "the source went away")
                    break
                time.sleep(0.005)
                continue
            blocks += 1
            last_len = float(block.duration)
            recorded += last_len
    except KeyboardInterrupt:
        why = "stopped early"
    finally:
        tap.stop()

    try:
        size = path.stat().st_size
        os.chmod(path, 0o600)
    except OSError:
        size = 0
    if size <= 0:
        _warn(f"Nothing was written to {path} ({why}).")
        return FAILED
    if truth_path is not None:
        from yazses.biosignal.types import EventKind

        truth = _switch_truth(src.ground_truth(), set(EventKind))
        fd = os.open(truth_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_truth_to_json(truth) + "\n")
        os.chmod(truth_path, 0o600)
    result = {
        "path": str(path), "bytes": size, "seconds": round(recorded, 2), "blocks": blocks,
        "fs": float(tap.fs), "channels": [c.name for c in tap.channels],
        "stopped": why, "mode": "0600",
        "truth": str(truth_path) if truth_path is not None else None,
    }
    if as_json:
        _say(json.dumps(result, indent=2))
    else:
        _say(f"Saved {recorded:.1f} s ({size / 1024:.0f} KiB, {len(tap.channels)} channels "
             f"at {tap.fs:g} Hz) to {path}  [mode 0600]  ({why}).")
        if truth_path is not None:
            _say(f"Scripted gestures written to {truth_path}.")
        _say(f"Next: `yazses biosignal replay {path}`")
    return OK


# ---------------------------------------------------------------------------
# evaluate


def run_evaluate(
    cfg: Any, data_dir: Path, *, source: str = "synthetic:mixed", seconds: float = 120.0,
    seed: int = 0, file: str = "", truth: str = "", tolerance: float = 0.3,
    emg: bool | None = None, blink: bool | None = None, clench: bool | None = None,
    as_json: bool = False,
) -> int:
    """Score the detectors against known events: precision, recall, latency, false alarms/hour.

    By default a seeded synthetic recording with scripted gestures (so the answer is the
    same every run and needs no hardware); with ``file`` + ``truth`` a recording you labelled
    yourself. Every detector is on unless you turn it off, because the point is to test
    them, not your config; the muscle-squeeze switch still needs a calibration profile
    and is reported as not evaluated without one. Synthetic numbers show the code works,
    not how well it will work on your skin.
    """
    try:
        from yazses.biosignal import evaluate as ev
    except ImportError:
        _warn("The evaluation module is not available in this build.")
        return UNUSABLE

    bio = cfg.biosignal
    if file:
        try:
            src = _open(f"file:{file}")
        except (ValueError, FileNotFoundError) as exc:
            _warn(f"Cannot read {file!r}: {exc}")
            return UNUSABLE
        if not truth:
            _warn("A recording needs its labels: pass --truth <events.json> "
                  '(e.g. [{"kind": "double_blink", "t": 12.3}]). '
                  "`yazses biosignal record --source synthetic --truth-out` writes an example.")
            return UNUSABLE
        try:
            labelled = load_truth(Path(truth).expanduser())
        except (OSError, ValueError) as exc:
            _warn(f"Cannot read the truth file: {exc}")
            return UNUSABLE
        label = f"file {file}"
        duration = float(src.duration)
    else:
        spec = (source or "synthetic:mixed").strip()
        if _scheme(spec) != "synthetic":
            _warn("`evaluate` scores a synthetic source (it knows what it scripted) or a "
                  "labelled recording: use --source synthetic[:emg|eeg|eog|mixed], or "
                  "--file <recording> --truth <events.json>.")
            return UNUSABLE
        if seconds < MIN_SCRIPTED_SECONDS:
            _warn(f"--seconds must be at least {MIN_SCRIPTED_SECONDS:g} (warm-up plus one "
                  "gesture cycle).")
            return UNUSABLE
        try:
            src = _synthetic_session(spec, seconds, seed, float(bio.mains_hz))
        except ValueError as exc:
            _warn(f"Cannot open source {spec!r}: {exc}")
            return UNUSABLE
        labelled = list(src.ground_truth())
        label = f"{spec} (seed {seed})"
        duration = float(seconds)

    sw = Switches(emg=True if emg is None else emg,
                  double_blink=True if blink is None else blink,
                  jaw_clench=True if clench is None else clench)
    sim = [0.0]
    pipeline, parts, _ledger = _build_pipeline(bio, src, sw, data_dir, clock=lambda: sim[0])
    active = _detector_kinds(parts)
    notes: list[str] = []
    if sw.emg and not any(k.value.startswith("squeeze") for k in active):
        notes.append("muscle squeeze not evaluated: no calibration profile "
                     "(`yazses biosignal calibrate`)")
    if file:
        truth_events = [e for e in labelled if e.kind in active]
        dropped = len(labelled) - len(truth_events)
        if dropped:
            notes.append(f"{dropped} labelled event(s) skipped: no active detector for their kind")
    else:
        truth_events = _switch_truth(labelled, active)
    if not active:
        _warn("No detector is active, nothing to evaluate.")
        return UNUSABLE

    try:
        report = ev.evaluate(src, pipeline, truth_events, tolerance_s=float(tolerance))
    except (ValueError, OSError) as exc:
        _warn(f"Evaluation failed: {exc}")
        return FAILED

    kinds = sorted(k.value for k in active)
    if as_json:
        _say(json.dumps({
            "source": label, "seconds": round(duration, 1), "seed": None if file else seed,
            "detectors": kinds, "tolerance_s": tolerance, "truth_events": len(truth_events),
            "notes": notes, "report": ev.report_to_dict(report),
        }, indent=2))
        return OK
    _say(f"Evaluating {label}: {duration:.0f} s, {len(truth_events)} known events, "
         f"detectors: {', '.join(kinds)}, tolerance {tolerance:g} s")
    for note in notes:
        _say(f"  note: {note}")
    _say()
    _say(ev.format_report(report))
    if not file:
        _say("\nMeasure it on your own signal with `yazses biosignal replay` and `report`.")
    return OK


# ---------------------------------------------------------------------------
# profile / profile-clear


def run_profile_show(cfg: Any, data_dir: Path, *, as_json: bool = False) -> int:
    """The saved calibration profile's identity and age. Never an amplitude or threshold."""
    from yazses.biosignal.calibration import load_profile, profile_is_stale

    path = profile_path(cfg.biosignal, data_dir)
    exists = path.is_file()
    profile = load_profile(path) if exists else None
    stale = profile_is_stale(profile, datetime.now(UTC)) if profile is not None else None
    if as_json:
        _say(json.dumps({
            "path": str(path), "exists": exists, "readable": profile is not None,
            "stale": stale,
            "board_id": profile.board_id if profile else None,
            "channels": list(profile.channels) if profile else None,
            "fs": profile.fs if profile else None,
            "created_at": profile.created_at if profile else None,
            "phases": list(profile.phases) if profile else None,
        }, indent=2))
        return OK
    if not exists:
        _say(f"No calibration profile at {path}.")
        _say("Run `yazses biosignal calibrate`; until you do, the muscle-squeeze switch stays off.")
        return OK
    if profile is None:
        _say(f"A file exists at {path} but it is not a usable profile (damaged, or written by "
             "a different version).")
        _say("Run `yazses biosignal calibrate` to replace it, or `yazses biosignal profile-clear`.")
        return OK
    _say(f"Calibration profile ({path}):")
    _say(f"  {profile.summary()}")
    if stale:
        _say("  STALE: older than the reuse limit; recalibrate with `yazses biosignal calibrate`.")
    _say("  (Amplitudes and thresholds are not printed; they describe your body.)")
    return OK


def run_profile_clear(cfg: Any, data_dir: Path, *, yes: bool = False) -> int:
    """Delete the saved calibration profile after a confirmation (``yes`` skips it)."""
    path = profile_path(cfg.biosignal, data_dir)
    if not path.is_file():
        _say(f"No calibration profile at {path}; nothing to clear.")
        return OK
    if not yes:
        try:
            answer = input(f"Delete the calibration profile at {path}?\n"
                           "The muscle-squeeze switch stays off until you recalibrate. [y/N] ")
        except (EOFError, KeyboardInterrupt):
            _warn("\nNot deleted (no answer; use --yes in a script).")
            return UNUSABLE
        if answer.strip().lower() not in ("y", "yes"):
            _say("Kept.")
            return OK
    try:
        path.unlink()
    except OSError as exc:
        _warn(f"Could not delete {path}: {exc}")
        return FAILED
    _say(f"Deleted {path}. Restart the daemon (`yazses restart`) to drop it from a running session.")
    return OK


# ---------------------------------------------------------------------------
# boards


def run_boards(*, as_json: bool = False) -> int:
    """The boards the switches are known to work with, and the source spec for each."""
    import textwrap

    rows: list[dict[str, Any]] = []
    try:
        from yazses.biosignal.boards import known_boards

        for b in known_boards():
            needs_port = bool(getattr(b, "serial_required", False))
            spec = b.source_spec("<port>" if needs_port else "") if hasattr(b, "source_spec") else ""
            rows.append({
                "name": str(getattr(b, "name", "")),
                "board_id": getattr(b, "board_id", None),
                "source": spec,
                "signals": str(getattr(b, "kind_hint", "") or ""),
                "channels": str(getattr(b, "channels_hint", "") or ""),
                "serial_port_required": needs_port,
                "notes": str(getattr(b, "notes", "") or ""),
            })
        heading = "Boards known to work"
    except ImportError:
        heading = "Boards BrainFlow reports"
        if _brainflow_state()[0]:
            from brainflow.board_shim import BoardIds

            from yazses.biosignal.sources import describe_board

            for board_id in sorted({int(b.value) for b in BoardIds}):
                d = describe_board(board_id)
                if d.available:
                    rows.append({
                        "name": d.name or f"board {board_id}", "board_id": board_id,
                        "source": f"brainflow:{board_id}", "signals": "",
                        "channels": f"{len(d.channels)} ch, {d.fs:g} Hz",
                        "serial_port_required": False, "notes": "",
                    })
    if as_json:
        _say(json.dumps({"boards": rows, "brainflow_installed": _brainflow_state()[0]}, indent=2))
        return OK
    if not rows:
        _say("No board list available: BrainFlow is not installed.")
        try:
            from yazses.system.remedy import install_hint

            hint = install_hint("emg-band")
        except Exception:
            hint = ""
        if hint:
            _say(f"  {hint}")
        _say("`synthetic` and `file:<recording>` sources work without it.")
        return OK
    _say(f"{heading} (BrainFlow id in brackets):\n")
    for r in rows:
        ident = f" [{r['board_id']}]" if r["board_id"] is not None else ""
        _say(f"  {r['name']}{ident}")
        facts = [f"source: {r['source']}" if r["source"] else "source: (not a [biosignal] source)"]
        if r["signals"]:
            facts.append(f"signals: {r['signals']}")
        if r["channels"]:
            facts.append(r["channels"])
        _say("    " + "; ".join(facts))
        if r["notes"]:
            for line in textwrap.wrap(r["notes"], 88):
                _say("    " + line)
        _say()
    _say("A board's channels and rate: `yazses biosignal doctor --source brainflow:<id>`; "
         "everything BrainFlow supports: `yazses biosignal doctor --boards`.")
    return OK


# ---------------------------------------------------------------------------
# field-test


_DURATION_FIELDS = ("duration_s", "seconds", "duration")


def _scaled_protocol(fieldtest: Any, minutes: float,
                     switches: Any = None) -> tuple[Any, float, str]:
    """The default protocol stretched or shrunk to ``minutes`` (0 = as designed).

    Returns ``(protocol or None, total_seconds, note)``. ``None`` means "use the module's
    own default"; ``note`` is non-empty when the length could not be changed.

    ``switches`` limits the deliberate-gesture phases to the detectors that are on: a switch
    that is off can never fire, and cueing it would count misses against a feature the user
    did not enable (dragging the verdict toward "do not enable" for no reason).
    """
    kwargs: dict[str, Any] = {}
    if switches is not None:
        kwargs["switches"] = tuple(
            name for name, on in (("squeeze", switches.emg),
                                  ("double_blink", switches.double_blink),
                                  ("jaw_clench", switches.jaw_clench)) if on)
    try:
        phases = list(fieldtest.default_protocol(**kwargs))
    except TypeError:
        kwargs = {}                       # an older fieldtest without the `switches` argument
        phases = list(fieldtest.default_protocol())
    except Exception:
        return None, 0.0, ""

    def length(phase: Any) -> float:
        for name in _DURATION_FIELDS:
            value = getattr(phase, name, None)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
        return 0.0

    total = sum(length(p) for p in phases)
    if minutes <= 0 or total <= 0:
        # Hand the session the protocol built for these switches, not its own default.
        return (phases if kwargs else None), total, ""
    factor = minutes * 60.0 / total
    try:
        scaled = []
        for phase in phases:
            name = next(n for n in _DURATION_FIELDS if isinstance(getattr(phase, n, None),
                                                                   (int, float)))
            scaled.append(dataclasses.replace(phase, **{name: getattr(phase, name) * factor}))
        return scaled, total * factor, ""
    except Exception:
        return None, total, ("This build cannot change the length of the test; running the "
                             "standard one.")


def run_field_test(
    cfg: Any, data_dir: Path, *, source: str = "", minutes: float = 0.0,
    as_json: bool = False, out: str = "",
) -> int:
    """A guided session of ordinary activity, then the phantom activations per hour for each.

    The prompts tell you what to do (sit still, talk, chew, type, look around). Whatever a
    switch fires on while you do nothing meant for it is a false activation; the report
    gives those as a rate per hour of each activity. Only those counts are reported or
    saved -- never the signal, never an amplitude. Nothing is typed or acted on.
    """
    from yazses.biosignal import fieldtest
    bio = cfg.biosignal
    spec = source_spec(bio, source)
    if not spec:
        _warn("No source. Set [biosignal] source, or try `yazses biosignal field-test "
              "--source synthetic`.")
        return UNUSABLE
    out_path = Path(out).expanduser() if out.strip() else None
    if out_path is not None and os.path.lexists(out_path):
        _warn(f"{out_path} already exists; not overwriting. Choose another --out.")
        return UNUSABLE
    narrate = _warn if as_json else _say          # keep stdout pure JSON when asked
    try:
        src = _open(spec, realtime=True)
    except (ValueError, FileNotFoundError) as exc:
        _warn(f"Cannot open source {spec!r}: {exc}")
        return UNUSABLE
    sw = switches_from(bio)
    src.start()
    try:
        if getattr(src, "available", True) is False or not src.fs:
            _warn(f"Source {spec!r} is not available: "
                  f"{getattr(src, 'last_error', '') or 'no data'}")
            return UNUSABLE

        def make_pipeline(_source: Any = None) -> Any:
            return _build_pipeline(bio, src, sw, data_dir)[0]

        protocol, total, note = _scaled_protocol(fieldtest, minutes, sw)
        session_kwargs: dict[str, Any] = {}
        if protocol is not None:
            session_kwargs["protocol"] = protocol
        budget = float(getattr(bio, "max_cancelled_per_hour", 0.0) or 0.0)
        if budget > 0:
            session_kwargs["max_cancelled_per_hour"] = budget   # judge against YOUR budget
        try:
            session = fieldtest.FieldTestSession(src, make_pipeline, **session_kwargs)
        except (ValueError, TypeError) as exc:
            _warn(f"Cannot start the field test on this source: {exc}")
            return UNUSABLE
        narrate(f"Field test on {spec} (detectors: {sw.names()}). Follow each prompt; keep "
                "the electrodes on the whole time. Nothing is typed or acted on, and no "
                "signal is saved: only counts of false activations are reported.")
        if note:
            narrate(note)
        if total > 0:
            narrate(f"It takes about {total / 60:.0f} min.  Ctrl-C ends it early.")
        deadline = time.monotonic() + max(total, 60.0) * 1.5 + 60.0
        shown = ""
        why = "finished"
        try:
            while not session.finished:
                prompt = str(session.prompt())
                if prompt != shown:
                    shown = prompt
                    narrate(f"\n  >> {prompt}")
                if time.monotonic() > deadline:
                    why = "the source delivered too little data"
                    break
                try:
                    block = src.read()
                except EOFError:
                    why = "the recording ended"
                    break
                if block is None:
                    if getattr(src, "available", True) is False:
                        why = str(getattr(src, "last_error", "") or "the source went away")
                        break
                    time.sleep(0.005)
                    continue
                session.feed(block)
        except KeyboardInterrupt:
            why = "stopped early"
    finally:
        src.stop()

    try:
        report = session.result()
    except Exception as exc:
        _warn(f"No report ({why}): {exc}. Run it to the end for a result.")
        return FAILED
    payload = fieldtest.report_to_dict(report)
    if out_path is not None:
        try:
            fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2) + "\n")
        except OSError as exc:
            _warn(f"Could not write {out_path}: {exc}")
            return FAILED
    if as_json:
        _say(json.dumps(payload, indent=2))
    else:
        _say("")
        _say(str(fieldtest.format_report(report)))
        if why != "finished":
            _say(f"(The test ended early: {why}. Rates from a short test are rough.)")
        if out_path is not None:
            _say(f"Saved the counts to {out_path} [mode 0600].")
    return OK if why in ("finished", "stopped early") else FAILED


# ---------------------------------------------------------------------------
# daemon adapter


class BiosignalActivationSource:
    """A :class:`BiosignalRunner` shaped like the daemon's other activation sources.

    The daemon starts each ``_extra_activations`` entry as ``source.run`` on a thread and
    calls ``source.stop()`` on shutdown (the ``HotkeyBackend`` duck type). This adds the one
    thing the runner does not do: on the way out, the session's activation counters are
    added to ``<data_dir>/biosignal_ledger.json`` so ``yazses biosignal report`` has
    something to read. ``stop`` waits briefly for that save so a daemon exit does not
    kill it half-written.
    """

    def __init__(self, runner: Any, data_dir: Path) -> None:
        self._runner = runner
        self._data_dir = Path(data_dir)
        self._idle = threading.Event()
        self._idle.set()

    @property
    def vocabulary(self) -> tuple[str, ...]:
        return tuple(self._runner.vocabulary)

    def _pipeline(self) -> Any:
        # The runner keeps its pipeline private and offers no public accessor yet.
        return getattr(self._runner, "_pipeline", None)

    def run(self) -> None:
        self._idle.clear()
        try:
            self._runner.run()
        finally:
            try:
                # A runner that autosaves its own counters (persists_ledger) must not be saved
                # again here: both writers add the session, so it would be counted twice.
                if not getattr(self._runner, "persists_ledger", False):
                    ledger = getattr(getattr(self._pipeline(), "_parts", None), "ledger", None)
                    if ledger is not None:
                        persist_session_ledger(ledger, self._data_dir)
            finally:
                self._idle.set()

    def stop(self) -> None:
        self._runner.stop()
        self._idle.wait(timeout=2.0)

    def status(self) -> dict[str, Any]:
        status: dict[str, Any] = dict(self._runner.status())
        return status

    def recent_events(self, n: int = _RECENT_N) -> list[Any]:
        """The runner's last ``n`` events (kind, age, accepted or dropped, why); ``[]`` if it has none."""
        return recent_events_of(self._runner, n) or []

    def note_cancelled(self) -> bool:
        """A non-switch undo just ran: count the latest switch activation as a mistake."""
        pipeline = self._pipeline()
        fn = getattr(pipeline, "note_cancelled", None)
        if not callable(fn):
            return False
        try:
            return bool(fn())
        except Exception:
            log.debug("note_cancelled failed", exc_info=True)
            return False

