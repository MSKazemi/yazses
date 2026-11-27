"""One settings window: a second launch raises the open one instead of opening another.

The pure half runs everywhere. The Qt half uses a real local socket and real second
processes, with throw-away directories, so nothing here can reach a window you have open.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

import yazses
from yazses.config import Config
from yazses.platform.base import Paths, socket_file_endpoint
from yazses.settingsui import app as settings_app
from yazses.settingsui import overview
from yazses.settingsui import single_window as sw
from yazses.settingsui.single_window import Outcome, ShowRequest
from yazses.system import wincon

# ---- who opens the window ------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _claim(acquired: list[bool], answers: list[bool], **kwargs):
    """Drive `claim` with scripted answers; the last one of each list repeats."""
    clock = _Clock()
    forwarded: list[float] = []

    def _next(script):
        return script.pop(0) if len(script) > 1 else script[0]

    def _forward(seconds):
        forwarded.append(seconds)
        return _next(answers)

    outcome = sw.claim(
        lambda: _next(acquired), _forward, clock=clock, sleep=clock.sleep, **kwargs
    )
    return outcome, forwarded, clock.now


def test_the_first_launch_opens_the_window_and_asks_nobody():
    outcome, forwarded, _ = _claim([True], [False])
    assert outcome is Outcome.OWNER
    assert forwarded == []


def test_a_later_launch_hands_over_and_does_not_open():
    outcome, forwarded, _ = _claim([False], [True], wait_s=5.0)
    assert outcome is Outcome.FORWARDED
    assert forwarded == [5.0]


def test_a_window_still_starting_is_asked_again():
    outcome, forwarded, _ = _claim([False], [False, False, True], wait_s=5.0, retry_s=1.0)
    assert outcome is Outcome.FORWARDED
    assert forwarded == [5.0, 4.0, 3.0]


def test_a_window_that_exits_meanwhile_is_replaced():
    outcome, _, _ = _claim([False, False, True], [False])
    assert outcome is Outcome.OWNER


def test_a_holder_that_never_answers_gets_no_second_window():
    outcome, forwarded, spent = _claim([False], [False], wait_s=2.0, retry_s=0.5)
    assert outcome is Outcome.UNANSWERED
    assert spent == pytest.approx(2.0)
    assert min(forwarded) >= 0.0


# ---- the message ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_", [ShowRequest(), ShowRequest("meetings", "abc-123"), ShowRequest("audio")]
)
def test_a_request_survives_the_wire(request_):
    line = sw.encode_request(request_)
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    assert sw.decode_request(line) == request_


def test_an_unknown_page_still_raises_the_window():
    assert sw.decode_request(b'{"page": "from-a-newer-version"}\n') == ShowRequest()


def test_an_unusable_token_is_dropped_and_the_request_kept():
    line = b'{"page": "audio", "token": "a\\u0000b"}\n'
    assert sw.decode_request(line) == ShowRequest("audio", "")


@pytest.mark.parametrize(
    "line",
    [
        b"",
        b"\n",
        b"show\n",
        b"\xff\xfe\n",
        b"[1]\n",
        b"{}\n",
        b'{"page": 3}\n',
        b'{"page": "audio", "token": 3}\n',
        b'{"page": "' + b"a" * sw.MAX_REQUEST_BYTES + b'"}\n',
    ],
    ids=["empty", "blank", "text", "bytes", "list", "no-page", "page-type", "token-type", "long"],
)
def test_what_is_not_a_request_is_refused(line):
    assert sw.decode_request(line) is None


# ---- names ------------------------------------------------------------------------------------


def test_the_name_is_per_user_and_per_config_file(tmp_path):
    here = sw.instance_tag(tmp_path / "config.toml", "ada")
    assert here == sw.instance_tag(tmp_path / "config.toml", "ada")
    assert here != sw.instance_tag(tmp_path / "config.toml", "grace")
    assert here != sw.instance_tag(tmp_path / "other" / "config.toml", "ada")
    assert len(here) == 12 and here.isalnum()
    assert sw.lock_file(tmp_path, here).parent == tmp_path


def test_the_default_endpoint_is_a_short_socket_file_in_the_runtime_directory():
    # The longest realistic case: macOS keeps it under Application Support, and a Unix
    # socket path is limited to 104 bytes there.
    state = PurePosixPath("/Users") / ("u" * 24) / "Library/Application Support/yazses"
    endpoint = socket_file_endpoint(SimpleNamespace(state_dir=state), "0123456789ab")
    assert endpoint.endswith("ui-0123456789ab.sock")
    assert len(endpoint.replace("\\", "/").encode()) < 104


def test_windows_names_a_pipe_not_a_file():
    import inspect

    from yazses.platform import windows
    from yazses.platform.windows.ipc import window_endpoint_name

    name = window_endpoint_name(None, "0123456789ab")  # type: ignore[arg-type]
    assert name == "yazses-ui-0123456789ab"
    assert not os.path.isabs(name)
    assert "local_endpoint=window_endpoint_name" in inspect.getsource(windows.build_platform)


def test_the_unanswered_message_names_the_process_only_when_known():
    assert "process 41" in sw.unanswered_message(41)
    for unknown in (None, -1):
        assert "process" not in sw.unanswered_message(unknown)


# ---- Windows foreground permission -----------------------------------------------------------


def test_allowing_the_foreground_does_nothing_off_windows(monkeypatch):
    monkeypatch.setattr(wincon.sys, "platform", "linux")
    assert wincon.allow_foreground(1234) is False


def test_on_windows_the_open_window_is_allowed_the_foreground(monkeypatch):
    import ctypes

    allowed: list[int] = []

    def _allow(pid):
        allowed.append(pid)
        return 1

    windll = SimpleNamespace(user32=SimpleNamespace(AllowSetForegroundWindow=_allow))
    monkeypatch.setattr(wincon.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", windll, raising=False)
    assert wincon.allow_foreground(1234) is True
    assert allowed == [1234]


# ---- the recalibration wording ----------------------------------------------------------------


def test_the_recalibration_text_matches_what_the_daemon_records():
    from yazses.core import daemon

    quiet = daemon._RECAL_LEAD_S + daemon._RECAL_ROOM_S + daemon._RECAL_LEAD_S
    assert f"stay quiet for about {quiet:.0f} seconds" in overview.RECALIBRATING
    assert f"for about {daemon._RECAL_SPEECH_S:.0f} seconds" in overview.RECALIBRATING
    assert round(quiet + daemon._RECAL_SPEECH_S) in range(8, 13)  # "about ten seconds"
    detail = overview.health({"silent_streak": 3}).detail
    assert "about ten seconds" in detail
    assert "three seconds" not in detail


# ---- the entry point --------------------------------------------------------------------------


def _run_against(monkeypatch, outcome, argv=(), holder=None):
    """Drive the real `run()` when the claim says another window exists."""
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from yazses.settingsui.single_window_qt import Claim, SingleWindow

    asked: list[ShowRequest] = []
    warned: list[str] = []

    def _claim_window(platform, config_file, request, **_kwargs):
        asked.append(request)
        return Claim(outcome, SingleWindow(), holder)

    def _must_not_open(*_args):
        raise AssertionError("a second settings window was built")

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_app, "claim_window", _claim_window)
    monkeypatch.setattr(settings_app, "SettingsWindow", _must_not_open)
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text, *a: warned.append(text))
    monkeypatch.setattr("yazses.config.load_config", lambda *a, **k: Config())
    monkeypatch.setattr("sys.argv", ["yazses-settings", *argv])
    with pytest.raises(SystemExit) as exit_:
        settings_app.run()
    return exit_.value.code, asked, warned


def test_a_second_launch_forwards_its_page_and_token_and_exits(monkeypatch, capsys):
    monkeypatch.setenv(sw.ACTIVATION_ENV, "tok-1")
    code, asked, warned = _run_against(monkeypatch, Outcome.FORWARDED, ["--page", "Files"])
    assert code == 0
    assert asked == [ShowRequest("files", "tok-1")]
    assert warned == []
    assert sw.ALREADY_OPEN in capsys.readouterr().out


@pytest.mark.parametrize("argv", [[], ["--page", "nonsense"]], ids=["none", "unknown"])
def test_a_launch_without_a_usable_page_only_asks_to_raise(monkeypatch, argv):
    monkeypatch.delenv(sw.ACTIVATION_ENV, raising=False)
    _, asked, _ = _run_against(monkeypatch, Outcome.FORWARDED, argv)
    assert asked == [ShowRequest()]


def test_an_unanswering_window_is_reported_and_nothing_else_opens(monkeypatch, capsys):
    code, _, warned = _run_against(monkeypatch, Outcome.UNANSWERED, holder=41)
    assert code == 1
    assert warned == [sw.unanswered_message(41)]
    assert "process 41" in capsys.readouterr().err


# ---- the real socket, with real second processes ----------------------------------------------


#: A second launch: argv is the directory, the page and the seconds to keep trying.
_LATER_LAUNCH = """
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from tests.test_settingsui_single_window import _platform_in
from yazses.settingsui.single_window import ShowRequest
from yazses.settingsui.single_window_qt import claim_window

app = QCoreApplication([])
root = Path(sys.argv[1])
claim = claim_window(
    _platform_in(root), root / "config.toml", ShowRequest(sys.argv[2], "tok"),
    wait_s=float(sys.argv[3]),
)
print(claim.outcome.value, flush=True)
if sys.argv[2] == "crash":
    import os
    os._exit(0)  # no cleanup at all: the lock is freed, a socket file stays behind
claim.window.close()
"""


def _platform_in(root: Path) -> SimpleNamespace:
    """This OS's real endpoint naming, over directories under *root*."""
    from yazses.platform import get_platform

    paths = Paths(
        config_dir=root, state_dir=root / "run", cache_dir=root / "cache",
        log_dir=root / "log", data_dir=root / "data",
    )
    return SimpleNamespace(paths=paths, local_endpoint=get_platform().local_endpoint)


@pytest.fixture
def qapp(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def root():
    # Not `tmp_path`: its length would push a socket path past the operating system's limit.
    path = Path(tempfile.mkdtemp(prefix="yz-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _launch(root: Path, page: str, wait_s: float = 60.0) -> subprocess.Popen:
    repo = Path(__file__).resolve().parents[1]
    source = Path(yazses.__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(source), str(repo), env.get("PYTHONPATH", "")) if p
    )
    return subprocess.Popen(
        [sys.executable, "-c", _LATER_LAUNCH, str(root), page, str(wait_s)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _pump(qapp, until, seconds: float = 90.0) -> None:
    """Run this process's event loop until *until* is true."""
    deadline = time.monotonic() + seconds
    while not until():
        assert time.monotonic() < deadline, "timed out waiting for the second process"
        qapp.processEvents()
        time.sleep(0.01)


def _answer(process: subprocess.Popen) -> str:
    try:
        out, err = process.communicate(timeout=60)
    finally:
        process.kill()
    assert process.returncode == 0, err
    return out.strip()


def _owner(root: Path):
    from yazses.settingsui.single_window_qt import claim_window

    claim = claim_window(_platform_in(root), root / "config.toml", ShowRequest())
    assert claim.outcome is Outcome.OWNER
    return claim


def test_a_second_process_reaches_the_open_window(qapp, root):
    claim = _owner(root)
    shown: list[ShowRequest] = []
    try:
        claim.window.attach(shown.append)
        later = _launch(root, "meetings")
        _pump(qapp, lambda: later.poll() is not None)
        assert _answer(later) == "forwarded"
        assert shown == [ShowRequest("meetings", "tok")]
    finally:
        claim.window.close()


def test_a_request_made_while_the_window_is_being_built_waits_for_it(qapp, root):
    claim = _owner(root)
    shown: list[ShowRequest] = []
    try:
        later = _launch(root, "audio")
        _pump(qapp, lambda: bool(claim.window._waiting))
        assert later.poll() is None, "the second launch left before it was answered"
        claim.window.attach(shown.append)
        _pump(qapp, lambda: later.poll() is not None)
        assert _answer(later) == "forwarded"
        assert shown == [ShowRequest("audio", "tok")]
    finally:
        claim.window.close()


def test_a_window_that_does_not_respond_is_not_doubled(qapp, root):
    claim = _owner(root)
    try:
        # No event loop runs here while the second process waits.
        assert _answer(_launch(root, "audio", wait_s=1.0)) == "unanswered"
    finally:
        claim.window.close()


def test_what_a_crashed_window_leaves_behind_does_not_block_the_next(qapp, root):
    from yazses.settingsui.single_window_qt import _user

    assert _answer(_launch(root, "crash")) == "owner"
    platform = _platform_in(root)
    endpoint = platform.local_endpoint(
        platform.paths, sw.instance_tag(root / "config.toml", _user())
    )
    if os.path.isabs(endpoint):  # a socket file outlives its process; a pipe does not
        assert os.path.exists(endpoint)
    claim = _owner(root)
    shown: list[ShowRequest] = []
    try:
        claim.window.attach(shown.append)
        later = _launch(root, "files")
        _pump(qapp, lambda: later.poll() is not None)
        assert _answer(later) == "forwarded"
        assert shown == [ShowRequest("files", "tok")]
    finally:
        claim.window.close()


def test_a_closed_window_frees_its_place(qapp, root):
    first = _owner(root)
    first.window.close()
    first.window.close()  # twice is fine: `aboutToQuit` and `run` both close it
    assert _answer(_launch(root, "audio")) == "owner"


def test_an_unwritable_data_directory_still_opens_the_window(qapp, root):
    (root / "data").write_text("a file where the directory should be", encoding="utf-8")
    claim = _owner(root)
    claim.window.close()


# ---- raising the window -----------------------------------------------------------------------


def test_the_open_window_turns_to_the_page_and_comes_back(qapp, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent, Qt

    from yazses.settingsui.controller import SettingsController
    from yazses.settingsui.model import build_settings_model

    monkeypatch.delenv(sw.ACTIVATION_ENV, raising=False)
    cfg = Config()
    window = settings_app.SettingsWindow(
        build_settings_model(cfg), SettingsController(lambda: cfg, lambda *a: None, lambda m: [])
    )
    window._daemon_running = lambda: False  # type: ignore[method-assign]
    window._daemon_status = lambda: None  # type: ignore[method-assign]
    # No background poll of a daemon: `show` would start one that outlives the window.
    window._page_context.run = lambda *a: False
    try:
        window.show()
        window._win.setWindowState(
            Qt.WindowState.WindowMinimized | Qt.WindowState.WindowMaximized
        )
        window.bring_to_front("audio", "tok")
        assert window._shell.current_key() == "audio"
        assert window._win.isVisible()
        assert not window._win.windowState() & Qt.WindowState.WindowMinimized
        assert window._win.windowState() & Qt.WindowState.WindowMaximized
        # Processes the window starts afterwards must not inherit a used token.
        assert sw.ACTIVATION_ENV not in os.environ

        window.bring_to_front()  # no page asked for: stay where the user is
        assert window._shell.current_key() == "audio"
    finally:
        window._page_timer.stop()
        window._level_timer.stop()
        window._win.hide()
        window._win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qapp.processEvents()
