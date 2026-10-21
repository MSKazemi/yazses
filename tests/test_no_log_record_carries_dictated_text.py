"""No log record above DEBUG may carry what the user said (SEC-002, ADR-011).

The rule is written where the daemon logs a burst:

    # INFO: metadata only (length); DEBUG: the actual text.

and the privacy statement, `yazses report` and `test_log_privacy_claims_name_the_condition.py`
all lean on it: at the default `[general] log_level = "INFO"`, `daemon.log` holds lengths,
counts and states, never a transcript. Nothing tested the rule *end to end*.
`test_no_transcript_leaves_the_daemon.py` scans the source for log calls that pass a
transcript-shaped *name*, and the report and docs tests assume the INFO-and-above stream
is clean; none of them can see a transcript carried inside another value.

So each test here drives a real path with a **sentinel transcript** and captures every
record that reaches the root logger, at every level, through a handler attached for the
test. A record at INFO or above whose rendered message, exception text or stack carries
any sentinel word fails the test.

## Why DEBUG is captured and then allowed

`log_level = "DEBUG"` is a documented, supported setting and it *does* write each
transcript (the privacy statement's warning box says so, and `report._log_tail` drops
whole DEBUG records for that reason). Asserting nothing at DEBUG either would fail on the
designed behaviour. But the DEBUG records are still captured, for a different purpose: the
dictation test asserts the sentinel **does** appear there. That is the positive control. A
capture handler that saw nothing -- a logger disabled by an earlier test's `dictConfig`, a
level left at WARNING, a propagate flag turned off -- would make every assertion below
pass on an empty list, and this proves the list is not empty.

## What this found

A failed keystroke backend put the whole transcript into a WARNING. `subprocess.run(...,
check=True)` raises `CalledProcessError`, whose `str()` is the full command line --
`Command '['wtype', '--', '<everything you just said>']' returned non-zero exit status 1`
-- and `run_ydotool` built its own message from the same argv. `LinuxInjector` logs that
exception at WARNING before it falls back to the clipboard, and the daemon logs it again as
`Pipeline error: …` and copies it into `last_error`, which `yazses status` prints and the
`yazses report` bundle carries (`redact_text` scrubs paths, not prose). The backends now
describe their payload by length (`inject/payload.py`); the tests below pin that for every
backend that puts text on a command line, and for the timeout path, which formats the
command the same way.

Everything is offline and mocked: no microphone, no model, no keystroke tool is run.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import replace

import numpy as np
import pytest

#: Three words no log template, key name or diagnosis text contains. Checked one by one and
#: case-insensitively, because the pipeline is allowed to re-case, re-space and re-punctuate
#: a transcript before it is typed -- a leak of the cleaned text is still a leak.
SENTINEL_WORDS = ("quixotrel", "vambrazine", "plinthwort")
SENTINEL = " ".join(SENTINEL_WORDS)


class _RootCapture(logging.Handler):
    """Every record that reaches the root logger, rendered as a sink would write it."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.records: list[tuple[int, str, str]] = []
        self._fmt = logging.Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        parts = [record.getMessage()]
        if record.exc_info:
            parts.append(self._fmt.formatException(record.exc_info))
        if record.exc_text:
            parts.append(record.exc_text)
        if record.stack_info:
            parts.append(self._fmt.formatStack(record.stack_info))
        self.records.append((record.levelno, record.name, "\n".join(parts)))

    def carrying(self, *, at_least: int) -> list[tuple[str, str, str]]:
        """Records at or above *at_least* that mention any sentinel word."""
        hits = []
        for level, name, text in self.records:
            low = text.lower()
            if level >= at_least and any(w in low for w in SENTINEL_WORDS):
                hits.append((logging.getLevelName(level), name, text))
        return hits


@pytest.fixture
def root_capture():
    """Attach at the root, at every level, with every `yazses.*` logger able to reach it.

    An earlier test may have configured logging (`Daemon._configure_logging`, a
    `dictConfig` with `disable_existing_loggers`), so each project logger is forced to
    propagate at NOTSET for the duration and put back afterwards.
    """
    root = logging.getLogger()
    handler = _RootCapture()
    saved_root_level = root.level
    saved: dict[str, tuple[int, bool, bool]] = {}
    for name, obj in list(logging.Logger.manager.loggerDict.items()):
        if name == "yazses" or name.startswith("yazses."):
            if isinstance(obj, logging.Logger):
                saved[name] = (obj.level, obj.propagate, obj.disabled)
                obj.setLevel(logging.NOTSET)
                obj.propagate = True
                obj.disabled = False
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(saved_root_level)
        for name, (level, propagate, disabled) in saved.items():
            lg = logging.getLogger(name)
            lg.setLevel(level)
            lg.propagate = propagate
            lg.disabled = disabled


def _assert_clean(capture: _RootCapture) -> None:
    leaks = capture.carrying(at_least=logging.INFO)
    assert not leaks, (
        "dictated text reached a log record above DEBUG -- at the default log level it "
        "would be written to daemon.log and carried into `yazses report`:\n"
        + "\n".join(f"  {lvl} {name}: {text}" for lvl, name, text in leaks)
    )


# --- the daemon's dictation pipeline ---------------------------------------------------


class _FakeRecorder:
    def __init__(self) -> None:
        self._audio = np.full(16000, 0.5, dtype="float32")

    def start(self) -> None:
        pass

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, *_a, **_k) -> str:
        return self.text


class _RecordingInjector:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def inject(self, text: str) -> None:
        self.calls.append(text)

    def inject_backspaces(self, n: int) -> None:
        pass

    def inject_key_sequence(self, keys) -> None:
        pass


def _daemon(injector, *, commands: bool = False, disfluency: bool = False):
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    cfg.filters.disfluency.enabled = disfluency
    cfg.commands.enabled = commands
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder()
    d._engine = _FakeEngine(SENTINEL)
    d._padding_buffer = None
    d._injector = injector
    # `_report_failure` runs for real. conftest's autouse fixture makes `notify-send`
    # unavailable, and `system/notify.py` then logs the toast at INFO instead -- so a
    # toast body that quoted the failure would show up in the capture too.
    return d


@pytest.mark.parametrize(
    ("commands", "disfluency"),
    [(False, False), (True, False), (False, True)],
    ids=["plain", "commands-on", "disfluency-filter-on"],
)
def test_a_dictation_burst_logs_no_text_above_debug(root_capture, commands, disfluency):
    injector = _RecordingInjector()
    d = _daemon(injector, commands=commands, disfluency=disfluency)

    d._on_hold_end()

    assert injector.calls, "the burst was not typed, so the path under test did not run"
    assert any(w in injector.calls[0].lower() for w in SENTINEL_WORDS)
    _assert_clean(root_capture)
    # The positive control (see the module docstring): the designed DEBUG record exists,
    # so the capture is live and the assertion above was made over real records.
    assert root_capture.carrying(at_least=logging.DEBUG), (
        "no record carried the sentinel even at DEBUG -- the capture saw nothing, so "
        "the clean result above proves nothing"
    )


def test_a_failed_injection_logs_no_text_and_keeps_it_out_of_status(root_capture, monkeypatch):
    """The daemon's own error path: `Pipeline error: %s` and `last_error`.

    The real `WtypeInjector`, with its tool failing the way `subprocess.run(check=True)`
    reports a non-zero exit, and no clipboard fallback behind it.
    """
    from yazses.inject.wtype import WtypeInjector

    monkeypatch.setattr(subprocess, "run", _failing_run("exit-1"))
    d = _daemon(WtypeInjector())

    d._on_hold_end()

    _assert_clean(root_capture)
    last_error = d._state.last_error or ""
    assert last_error, "the failure was not recorded, so the path under test did not run"
    assert not any(w in last_error.lower() for w in SENTINEL_WORDS), (
        f"last_error carries the transcript: {last_error!r} -- `yazses status` prints it "
        "and `yazses report` bundles it"
    )


# --- the keystroke backends ------------------------------------------------------------


def _failing_run(kind: str):
    """A `subprocess.run` that fails the way the real one does, for *kind*."""

    def run(argv, *_a, check=False, timeout=None, **_k):
        if kind == "timeout":
            raise subprocess.TimeoutExpired(argv, timeout or 10)
        if check:
            raise subprocess.CalledProcessError(1, argv, stderr="compositor refused")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="compositor refused")

    return run


def _backends():
    from yazses.inject.clipboard import ClipboardInjector
    from yazses.inject.wtype import WtypeInjector
    from yazses.inject.xdotool import XdotoolInjector
    from yazses.inject.ydotool import YdotoolInjector

    return {
        "wtype": WtypeInjector,
        "xdotool": XdotoolInjector,
        "ydotool": YdotoolInjector,
        "clipboard-wayland": ClipboardInjector,
    }


@pytest.mark.parametrize("kind", ["exit-1", "timeout"])
@pytest.mark.parametrize("backend", sorted(_backends()))
def test_a_failing_backend_raises_without_the_text(monkeypatch, backend, kind):
    """The exception is what every caller logs, so it must not quote the payload."""
    monkeypatch.setattr(subprocess, "run", _failing_run(kind))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr("yazses.inject.ydotool.ydotool_dialect", lambda: "v1")
    injector = _backends()[backend]()

    with pytest.raises(Exception) as caught:
        injector.inject(SENTINEL)

    rendered = f"{caught.value}\n{caught.value!r}".lower()
    assert not any(w in rendered for w in SENTINEL_WORDS), (
        f"{backend} raised {type(caught.value).__name__} quoting the transcript: "
        f"{caught.value}"
    )
    assert "chars" in rendered or "timed out" in rendered or "exit" in rendered, (
        f"the message lost its diagnosis along with the text: {caught.value}"
    )


def test_the_clipboard_fallback_warning_carries_no_text(root_capture, monkeypatch):
    """`LinuxInjector` logs the primary's exception at WARNING, then falls back."""
    from yazses.inject.wtype import WtypeInjector
    from yazses.platform.linux import injector as linux_injector

    calls: list[list[str]] = []

    def run(argv, *_a, check=False, **_k):
        calls.append(list(argv))
        if argv[0] == "wtype" and "--" in argv:
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(linux_injector, "get_injector", WtypeInjector)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr("yazses.inject.clipboard._ydotool_ready", lambda: False)
    monkeypatch.setattr("yazses.inject.clipboard.shutil.which", lambda _n: "/usr/bin/wtype")
    monkeypatch.setattr("yazses.inject.clipboard.time.sleep", lambda _s: None)

    linux_injector.LinuxInjector(fallback_to_clipboard=True).inject(SENTINEL)

    assert any(c[0] == "wl-copy" for c in calls), "the fallback did not run"
    assert any(
        "clipboard fallback" in text for _lvl, _n, text in root_capture.records
    ), "the fallback warning was not emitted, so the path under test did not run"
    _assert_clean(root_capture)


# --- meeting mode ----------------------------------------------------------------------


class _MeetingEngine:
    def transcribe(self, audio, sample_rate=16000) -> str:
        return SENTINEL

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        from yazses.postprocess.prosody import Word

        words = [
            Word(w, 0.4 * i, 0.4 * i + 0.3, 0.9) for i, w in enumerate(SENTINEL_WORDS * 2)
        ]
        return " ".join(w.text for w in words), words


def test_a_meeting_logs_no_text_from_capture_to_finalize(root_capture, tmp_path):
    from yazses.config import MeetingConfig
    from yazses.meeting import store
    from yazses.meeting.controller import MeetingController
    from yazses.meeting.session import read_wav_mono_f32

    sr = 1000
    cfg = replace(MeetingConfig(output_dir=str(tmp_path)), diarize=False)
    ctl = MeetingController(
        cfg, store.new_meeting(cfg, "m1"), "m1", engine=_MeetingEngine(),
        is_silent=lambda chunk: not np.asarray(chunk).any(), sample_rate=sr,
    )
    ctl.start()
    for _ in range(3):
        ctl.feed(np.full(100, 0.3, dtype="float32"))
    for _ in range(8):
        ctl.feed(np.zeros(100, dtype="float32"))
    for _ in range(30):
        ctl.feed(np.full(100, 0.3, dtype="float32"))
    audio = read_wav_mono_f32(ctl.stop_capture())
    info = ctl.finalize(audio)

    assert ctl.status()["line_count"] >= 1, "no live line was decoded"
    assert info["files"], "finalize wrote nothing, so the path under test did not run"
    _assert_clean(root_capture)


# --- file transcription ----------------------------------------------------------------


def test_yazses_transcribe_logs_no_text(root_capture, monkeypatch, tmp_path):
    import sys
    import types

    from typer.testing import CliRunner

    from yazses import cli
    from yazses.config import Config

    class _FileEngine:
        def __init__(self, **_kwargs) -> None:
            pass

        def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
            return SENTINEL, []

    monkeypatch.setitem(
        sys.modules, "yazses.stt.faster_whisper",
        types.SimpleNamespace(FasterWhisperEngine=_FileEngine),
    )
    rng = np.random.default_rng(0)
    signal = (rng.standard_normal(16000) * 1e-2).astype("float32")
    monkeypatch.setattr("yazses.recimport.audio_io.load_audio", lambda *_a, **_k: (signal, 16000))
    monkeypatch.setattr("yazses.recimport.pipeline.build_diarizer", lambda *_a, **_k: None)
    cfg = Config()
    monkeypatch.setattr(cli, "load_config", lambda *_a, **_k: cfg, raising=False)
    monkeypatch.setattr("yazses.config.load_config", lambda *_a, **_k: cfg, raising=False)
    f = tmp_path / "clip.wav"
    f.write_bytes(b"RIFF")

    result = CliRunner().invoke(cli.app, ["transcribe", str(f)], env={"COLUMNS": "200"})

    assert result.exit_code == 0, result.output
    produced = result.output + "".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in tmp_path.iterdir() if p.suffix in {".txt", ".md", ".srt", ".json"}
    )
    assert SENTINEL_WORDS[0] in produced.lower(), (
        "the transcript was not produced, so the path under test did not run"
    )
    _assert_clean(root_capture)
