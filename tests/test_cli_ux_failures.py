"""Ordinary failures end in a sentence with a next step, never a traceback.

Covers the root group's handling of daemon and filesystem errors, and the commands
that used to crash, report success, or blame the wrong thing.
"""

from __future__ import annotations

import types

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.ipc.client import IpcCallError, IpcTimeoutError, IpcUnreachableError
from yazses.ipc.protocol import HANDLER_FAILED, METHOD_NOT_FOUND, RpcError

runner = CliRunner()


class _Client:
    def __init__(self, reply=None):
        self.reply = {"ok": True} if reply is None else reply
        self.calls: list[tuple[str, dict]] = []

    def is_reachable(self) -> bool:
        return True

    def call(self, method, **params):
        self.calls.append((method, params))
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


@pytest.fixture
def platform(tmp_path, monkeypatch):
    """Install a fake platform; returns a function that sets what the daemon does."""

    def install(reply=None, *, running: bool = True, injector=None):
        client = _Client(reply)
        paths = types.SimpleNamespace(
            data_dir=tmp_path,
            config_dir=tmp_path,
            log_dir=tmp_path,
            config_file=tmp_path / "config.toml",
            ipc_socket=tmp_path / "daemon.sock",
        )
        plat = types.SimpleNamespace(
            name="linux",
            default_hotkey="right_ctrl",
            paths=paths,
            lifecycle=types.SimpleNamespace(is_running=lambda: running, read_pid=lambda: 42),
            ipc_client_factory=lambda _sock: client,
            injector_factory=lambda: injector,
        )
        monkeypatch.setattr(cli, "get_platform", lambda: plat)
        monkeypatch.setattr(cli, "get_paths", lambda: paths)
        return client

    return install


def _no_traceback(result, code: int = 1) -> None:
    assert result.exit_code == code, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )


def _timeout() -> IpcTimeoutError:
    err = IpcTimeoutError("sock")
    err.timeout_s = 2.0
    return err


# ---- daemon errors, worded once by the root group ------------------------------


@pytest.mark.parametrize(
    "argv",
    [["say", "hi"], ["status"], ["recall"], ["meeting", "start"], ["gesture", "pause"],
     ["staged", "status"], ["remote", "--stop"]],
)
def test_an_older_daemon_is_told_to_restart(platform, argv):
    platform(IpcCallError(RpcError(code=METHOD_NOT_FOUND, message="Unknown method")))
    result = runner.invoke(cli.app, argv)
    _no_traceback(result)
    assert "yazses restart" in result.output


def test_a_failed_handler_reports_the_reason_and_points_at_the_log(platform):
    platform(IpcCallError(RpcError(code=HANDLER_FAILED, message="boom in the daemon")))
    result = runner.invoke(cli.app, ["mark-wrong"])
    _no_traceback(result)
    assert "boom in the daemon" in result.output
    assert "yazses logs" in result.output


@pytest.mark.parametrize("argv", [["say", "hi"], ["scratch"], ["staged", "commit"]])
def test_a_slow_daemon_is_not_reported_as_absent(platform, argv):
    platform(_timeout())
    result = runner.invoke(cli.app, argv)
    _no_traceback(result)
    assert "did not answer within 2 s" in result.output
    assert "not running" not in result.output
    assert "starting up" not in result.output


def test_no_daemon_says_how_to_start_one(platform):
    platform(IpcUnreachableError("sock"), running=False)
    result = runner.invoke(cli.app, ["say", "hi"])
    _no_traceback(result)
    assert "Daemon is not running. Start it with: yazses start" in result.output


def test_a_daemon_still_starting_is_not_told_to_start_again(platform):
    platform(IpcUnreachableError("sock"), running=True)
    result = runner.invoke(cli.app, ["say", "hi"])
    _no_traceback(result)
    assert "still be starting" in result.output
    assert "yazses start" not in result.output


# ---- config file errors ---------------------------------------------------------


def test_a_config_that_cannot_be_written_names_the_file(platform, monkeypatch):
    platform()

    def _denied(*_a, **_k):
        raise PermissionError(13, "Permission denied", "/somewhere/config.toml")

    monkeypatch.setattr("yazses.system.configedit.set_config_key", _denied)
    result = runner.invoke(cli.app, ["hotkey", "set", "right_ctrl"])
    _no_traceback(result)
    assert "Permission denied: /somewhere/config.toml" in result.output


def test_a_busy_config_asks_to_try_again(platform, monkeypatch):
    from yazses.system.configedit import ConfigEditBusyError

    platform()

    def _busy(*_a, **_k):
        raise ConfigEditBusyError("Config is being changed by another YazSes process")

    monkeypatch.setattr("yazses.system.configedit.set_config_key", _busy)
    result = runner.invoke(cli.app, ["hotkey", "set", "right_ctrl"])
    _no_traceback(result)
    assert "run the command again" in result.output


def test_an_unrelated_runtime_error_is_not_swallowed(platform):
    platform(RuntimeError("a real bug"))
    result = runner.invoke(cli.app, ["say", "hi"])
    assert isinstance(result.exception, RuntimeError)


# ---- punch-in -------------------------------------------------------------------


def test_punch_in_waits_longer_than_the_recording_window(platform, tmp_path):
    client = platform({"ok": True, "old": "brown fox", "new": "brown ox"})
    (tmp_path / "config.toml").write_text(
        "[punch_in]\nenabled = true\nrecord_seconds = 7.0\n", encoding="utf-8"
    )
    result = runner.invoke(cli.app, ["punch-in"])
    assert result.exit_code == 0, result.output
    method, params = client.calls[0]
    assert method == "punch_in"
    assert params["wait_s"] > 7.0
    assert "listening for 7 s" in result.output


def test_punch_in_does_not_ask_to_speak_when_it_is_off(platform):
    platform({"ok": False, "reason": "punch-in is off"})
    result = runner.invoke(cli.app, ["punch-in"])
    assert result.exit_code == 1
    assert "listening" not in result.output


# ---- recording commands ---------------------------------------------------------


def test_enroll_runs_here_even_while_the_daemon_is_up(platform, monkeypatch):
    client = platform()
    ran: list[object] = []
    monkeypatch.setattr(
        "yazses.accessibility.enroll.run_wizard", lambda **kw: ran.append(kw) or {}
    )
    result = runner.invoke(cli.app, ["enroll"])
    assert result.exit_code == 0, result.output
    assert ran and client.calls == []
    assert "yazses restart" in result.output


@pytest.mark.parametrize(
    ("error", "words"),
    [(EOFError(), "terminal"), (OSError("PortAudio library not found"), "yazses doctor")],
)
def test_enroll_failures_are_sentences(platform, monkeypatch, error, words):
    platform(running=False)

    def _fail(**_kw):
        raise error

    monkeypatch.setattr("yazses.accessibility.enroll.run_wizard", _fail)
    result = runner.invoke(cli.app, ["enroll"])
    _no_traceback(result)
    assert words in result.output


def test_mic_level_without_a_microphone(platform, monkeypatch):
    platform(running=False)

    def _fail(*_a, **_k):
        raise OSError("no input device")

    monkeypatch.setattr("yazses.system.miclevel.record", _fail)
    result = runner.invoke(cli.app, ["mic-level"])
    _no_traceback(result)
    assert "no input device" in result.output
    assert "yazses audio devices" in result.output


# ---- injection ------------------------------------------------------------------


class _BrokenInjector:
    backend_name = "Broken"

    def inject(self, _text):
        raise RuntimeError("ydotoold socket is gone")


def test_inject_failure_points_at_doctor(platform):
    platform(injector=_BrokenInjector())
    result = runner.invoke(cli.app, ["inject", "hello"])
    _no_traceback(result)
    assert "ydotoold socket is gone" in result.output
    assert "yazses doctor" in result.output


def test_self_test_fails_when_the_daemon_typed_nothing(platform, monkeypatch):
    platform({"ok": False, "reason": "daemon still loading; try again in a moment"})
    monkeypatch.setattr("time.sleep", lambda _s: None)
    result = runner.invoke(cli.app, ["test"])
    _no_traceback(result)
    assert "Nothing was typed" in result.output


def test_self_test_does_not_type_twice_after_a_timeout(platform, monkeypatch):
    typed: list[str] = []
    injector = types.SimpleNamespace(inject=typed.append, backend_name="Fake")
    platform(_timeout(), injector=injector)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    result = runner.invoke(cli.app, ["test"])
    _no_traceback(result)
    assert typed == []


def test_tray_that_cannot_start_says_why(monkeypatch):
    def _fail():
        raise RuntimeError("The tray needs PySide6, which is not installed.")

    monkeypatch.setattr("yazses.tray.app.run", _fail)
    result = runner.invoke(cli.app, ["tray"])
    _no_traceback(result)
    assert "needs PySide6" in result.output


# ---- files ----------------------------------------------------------------------


def test_relabel_refuses_an_unknown_format_before_writing(platform, tmp_path, monkeypatch):
    platform()
    monkeypatch.setattr(cli, "_meeting_dir", lambda _id: tmp_path)
    (tmp_path / "transcript.json").write_text("untouched", encoding="utf-8")
    result = runner.invoke(cli.app, ["meeting", "relabel", "m1", "--format", "docx"])
    _no_traceback(result, 2)
    assert (tmp_path / "transcript.json").read_text(encoding="utf-8") == "untouched"


@pytest.mark.parametrize("command", ["relabel", "notes"])
def test_a_corrupt_meeting_transcript_is_named(platform, tmp_path, monkeypatch, command):
    platform()
    monkeypatch.setattr(cli, "_meeting_dir", lambda _id: tmp_path)
    (tmp_path / "transcript.json").write_text("{not json", encoding="utf-8")
    result = runner.invoke(cli.app, ["meeting", command, "m1"])
    _no_traceback(result)
    assert "transcript.json" in result.output
    assert "meeting recover m1" in result.output


def test_a_failed_recovery_says_the_recording_is_safe(platform, tmp_path, monkeypatch):
    platform()
    monkeypatch.setattr(cli, "_meeting_dir", lambda _id: tmp_path)
    monkeypatch.setattr("yazses.meeting.recover.recovery_refusal", lambda *_a, **_k: None)

    def _fail(*_a, **_k):
        raise RuntimeError("model could not be loaded")

    monkeypatch.setattr("yazses.meeting.recover.recover_meeting", _fail)
    result = runner.invoke(cli.app, ["meeting", "recover", "m1"])
    _no_traceback(result)
    assert "model could not be loaded" in result.output
    assert "not deleted" in result.output


@pytest.mark.parametrize("target", ["folder", "audio"])
def test_transcribe_rejects_a_bad_output_path_before_any_work(platform, tmp_path, target):
    platform()
    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"RIFF")
    out = tmp_path if target == "folder" else audio
    result = runner.invoke(cli.app, ["transcribe", str(audio), "-o", str(out)])
    _no_traceback(result, 2)
    assert "--out" in result.output
    assert audio.read_bytes() == b"RIFF"


def test_report_to_an_unwritable_path(platform, tmp_path, monkeypatch):
    platform()
    monkeypatch.setattr("yazses.system.report.collect", lambda **_k: {})
    result = runner.invoke(cli.app, ["report", "-o", str(tmp_path)])
    _no_traceback(result)
    assert "--print" in result.output


def test_vocab_export_to_a_folder(platform, tmp_path):
    platform()
    result = runner.invoke(cli.app, ["vocab", "export", "-o", str(tmp_path)])
    _no_traceback(result)
    assert "Could not write" in result.output


# ---- values that used to be ignored or crash ------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["case", "--style", "shouty", "hello"],
        ["outline", "render", "--format", "docx"],
        ["braille", "--grade", "3", "hello"],
        ["scratch", "delete"],
    ],
)
def test_an_unknown_value_is_refused(platform, argv):
    client = platform()
    result = runner.invoke(cli.app, argv)
    _no_traceback(result, 2)
    assert client.calls == []


@pytest.mark.parametrize("content", ['["a", "b"]', '{"word": 3}'])
def test_wordfind_rejects_a_lexicon_of_the_wrong_shape(tmp_path, content):
    lexicon = tmp_path / "lex.json"
    lexicon.write_text(content, encoding="utf-8")
    result = runner.invoke(cli.app, ["wordfind", "a thing", "--lexicon", str(lexicon)])
    _no_traceback(result)
    assert "JSON object" in result.output


# ---- doctor rows that named a problem and no next step --------------------------


def test_doctor_session_and_cache_rows_say_what_to_do(tmp_path):
    from yazses.system.doctor import _model_cache_check, _session_type_check

    assert _session_type_check("X11", True) == ("Session type", "OK", "X11")
    assert "desktop session" in _session_type_check("unknown", False)[2]
    assert _model_cache_check(tmp_path) == ("Model cache", "OK", str(tmp_path))
    status, detail = _model_cache_check(tmp_path / "absent")[1:]
    assert status == "WARN"
    assert "yazses model download" in detail
