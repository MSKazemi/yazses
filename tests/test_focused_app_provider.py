"""Editor command profiles follow the focused app on macOS and Windows too.

`[commands] profile = "auto"` (the default) is documented to pick the focused editor's
keys. Until this change the only thing that could name the focused application was the
text-target guard's detector -- AT-SPI or X11 xdotool, Linux only -- so on macOS and
Windows every command silently got the default keys.

The platform seam now carries an optional `FocusedAppProvider` per OS
(`Platform.focused_app_factory`): the frontmost app's bundle id on macOS, the foreground
window's process image name on Windows. These tests pin each provider against faked OS
calls, the bundles that register them, the privacy line (an identifier, never a title or
a path), and the daemon preferring the provider and degrading when it is missing.

Nothing here has run on a real Mac or a real Windows desktop.
"""
from __future__ import annotations

import dataclasses
import inspect
import logging
import sys
import types

import numpy as np
import pytest

from yazses.commands.profiles import load_profiles
from yazses.config import Config
from yazses.platform.base import (
    PRIMARY_MODIFIER_CMD,
    PRIMARY_MODIFIER_CTRL,
    FocusedAppProvider,
    Platform,
)
from yazses.platform.macos import focused_app as mac
from yazses.platform.windows import focused_app as win

# ---- Windows: the foreground window's process image name -------------------------


def test_windows_reports_the_image_name_of_the_foreground_process():
    seen: list[int] = []

    def _path(pid: int) -> str:
        seen.append(pid)
        return r"C:\Program Files\JetBrains\IntelliJ IDEA 2026.2\bin\idea64.exe"

    provider = win.WindowsFocusedApp(pid_fn=lambda: 4242, path_fn=_path)
    assert provider.app_id() == "idea64.exe"
    assert seen == [4242]


def test_windows_never_hands_out_the_users_profile_path():
    """The full image path carries the user's profile directory; only its last
    component may leave the provider."""
    provider = win.WindowsFocusedApp(
        pid_fn=lambda: 7,
        path_fn=lambda pid: r"C:\Users\someone\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    )
    answer = provider.app_id()
    assert answer == "Code.exe"
    assert "someone" not in answer and "\\" not in answer


@pytest.mark.parametrize("pid", [None, 0])
def test_windows_with_no_foreground_window_answers_nothing(pid):
    def _path(_pid: int) -> str:  # pragma: no cover - must not be reached
        raise AssertionError("no process to ask about")

    assert win.WindowsFocusedApp(pid_fn=lambda: pid, path_fn=_path).app_id() == ""


@pytest.mark.parametrize("path", [None, ""])
def test_windows_with_an_unreadable_image_answers_nothing(path):
    """A protected process refuses even PROCESS_QUERY_LIMITED_INFORMATION."""
    assert win.WindowsFocusedApp(pid_fn=lambda: 9, path_fn=lambda pid: path).app_id() == ""


def test_windows_never_raises():
    def _boom(*_args):
        raise OSError("access denied")

    assert win.WindowsFocusedApp(pid_fn=_boom).app_id() == ""
    assert win.WindowsFocusedApp(pid_fn=lambda: 3, path_fn=_boom).app_id() == ""


@pytest.mark.parametrize("path,expected", [
    (r"C:\Program Files\Sublime Text\sublime_text.exe", "sublime_text.exe"),
    (r"C:\Users\u\AppData\Local\Programs\Microsoft VS Code Insiders\Code - Insiders.exe",
     "Code - Insiders.exe"),
    ("C:/forward/slashes/pycharm64.exe", "pycharm64.exe"),
    (r"\\?\C:\long\path\studio64.exe", "studio64.exe"),
    ("  C:\\x\\rider64.exe  ", "rider64.exe"),
    ("Code.exe", "Code.exe"),
    ("", ""),
    (None, ""),
])
def test_image_name_is_the_windows_file_name_on_every_os(path, expected):
    """`ntpath`, not `os.path`: on Linux `os.path.basename` would keep the backslashes."""
    assert win.image_name(path) == expected


def test_process_image_path_off_windows_answers_none(monkeypatch):
    """No `ctypes.WinDLL` means not Windows: no answer, and no exception."""
    import ctypes

    monkeypatch.delattr(ctypes, "WinDLL", raising=False)
    assert win.process_image_path(1234) is None


def test_the_windows_provider_is_a_focused_app_provider():
    assert isinstance(win.WindowsFocusedApp(), FocusedAppProvider)


# ---- macOS: the frontmost application's bundle identifier ------------------------


class _App:
    """Stands in for an `NSRunningApplication`."""

    def __init__(self, bundle: str | None, name: str | None) -> None:
        self._bundle = bundle
        self._name = name

    def bundleIdentifier(self):  # noqa: N802 - the AppKit selector name
        return self._bundle

    def localizedName(self):  # noqa: N802 - the AppKit selector name
        return self._name


class _Workspace:
    """Stands in for `NSWorkspace.sharedWorkspace()`."""

    def __init__(self, app) -> None:
        self.app = app
        self.asked = 0

    def frontmostApplication(self):  # noqa: N802 - the AppKit selector name
        self.asked += 1
        return self.app


def test_macos_reports_the_bundle_identifier():
    ws = _Workspace(_App("com.microsoft.VSCode", "Code"))
    provider = mac.MacosFocusedApp(lambda: ws)
    assert provider.app_id() == "com.microsoft.VSCode"


def test_macos_reads_the_frontmost_app_on_every_call():
    """Read at dispatch time, never cached: the app in front changes between commands."""
    ws = _Workspace(_App("com.microsoft.VSCode", None))
    provider = mac.MacosFocusedApp(lambda: ws)
    assert provider.app_id() == "com.microsoft.VSCode"
    ws.app = _App("com.jetbrains.pycharm", None)
    assert provider.app_id() == "com.jetbrains.pycharm"
    assert ws.asked == 2


def test_macos_falls_back_to_the_name_for_an_app_without_a_bundle_id():
    ws = _Workspace(_App(None, "Sublime Text"))
    assert mac.MacosFocusedApp(lambda: ws).app_id() == "Sublime Text"


@pytest.mark.parametrize("app", [None, _App(None, None), _App("", "")])
def test_macos_with_nothing_frontmost_answers_nothing(app):
    assert mac.MacosFocusedApp(lambda: _Workspace(app)).app_id() == ""


def test_macos_never_raises():
    def _boom():
        raise RuntimeError("objc.error")

    assert mac.MacosFocusedApp(_boom).app_id() == ""

    class _BadApp:
        def bundleIdentifier(self):  # noqa: N802
            raise RuntimeError("selector failed")

        def localizedName(self):  # noqa: N802
            return "PyCharm"

    assert mac.app_identifier(_BadApp()) == "PyCharm"


def test_macos_answers_a_plain_str():
    """PyObjC hands back NSString proxies; the profile matcher wants a `str`."""

    class _NSString(str):
        pass

    answer = mac.app_identifier(_App(_NSString("com.sublimetext.4"), None))
    assert type(answer) is str and answer == "com.sublimetext.4"


def test_the_macos_factory_uses_the_shared_workspace(monkeypatch):
    ws = _Workspace(_App("com.jetbrains.goland", "GoLand"))
    appkit = types.ModuleType("AppKit")
    appkit.NSWorkspace = types.SimpleNamespace(sharedWorkspace=lambda: ws)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "AppKit", appkit)

    provider = mac.build_macos_focused_app()
    assert isinstance(provider, FocusedAppProvider)
    assert provider.app_id() == "com.jetbrains.goland"


def test_the_macos_factory_without_appkit_raises_the_reason(monkeypatch):
    """`None` in `sys.modules` makes the import fail, as on a stripped install."""
    monkeypatch.setitem(sys.modules, "AppKit", None)
    with pytest.raises(RuntimeError) as err:
        mac.build_macos_focused_app()
    assert str(err.value) == mac.NO_APPKIT_REASON
    assert "pyobjc-framework-Cocoa" in mac.NO_APPKIT_REASON


def test_importing_the_macos_provider_imports_no_framework():
    """The AppKit import sits inside the factory, so this module loads on any OS."""
    source = inspect.getsource(mac)
    module_level = [line for line in source.splitlines()
                    if line.startswith(("import ", "from "))]
    assert not [line for line in module_level if "AppKit" in line or "objc" in line]


# ---- privacy: an identifier, never what is on screen ----------------------------


def test_neither_provider_reads_a_window_title():
    """Same rule as the click observer: say which app, never what it shows."""
    win_source = inspect.getsource(win)
    mac_source = inspect.getsource(mac)
    assert "GetWindowText" not in win_source
    # `winfo.read_focus` reads the title for the user's own diagnostic; not used here.
    imports = [line for line in win_source.splitlines()
               if line.lstrip().startswith(("import ", "from "))]
    assert not [line for line in imports if "winfo" in line], imports
    for forbidden in ("kCGWindowName", "AXTitle", "windowTitle", "CGWindowListCopyWindowInfo"):
        assert forbidden not in mac_source


# ---- the platform bundles ---------------------------------------------------------


def test_the_field_defaults_to_none_with_no_reason():
    fields = {f.name: f for f in dataclasses.fields(Platform)}
    assert fields["focused_app_factory"].default is None
    assert fields["focused_app_unavailable_reason"].default is None


def test_macos_and_windows_register_their_provider_and_linux_does_not():
    """Linux and the BSDs read the focused app through the text-target detector, so
    their bundles leave the field at its default."""
    import yazses.platform.bsd as bsd
    import yazses.platform.linux as linux
    import yazses.platform.macos as macos
    import yazses.platform.windows as windows

    assert ("focused_app_factory=build_macos_focused_app"
            in inspect.getsource(macos.build_platform))
    assert "focused_app_factory=WindowsFocusedApp" in inspect.getsource(windows.build_platform)
    for bundle in (linux, bsd):
        assert "focused_app_factory" not in inspect.getsource(bundle.build_platform), bundle


# ---- the daemon -------------------------------------------------------------------


class _Injector:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        self.calls.append(("backspaces", count))

    def inject_key_sequence(self, keys):
        self.calls.append(list(keys))


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text=""):
        self.text = text

    def transcribe(self, *args, **kwargs):
        return self.text


class _FakeProvider:
    def __init__(self, app_id: object) -> None:
        self.answer = app_id
        self.asked = 0

    def app_id(self):
        self.asked += 1
        return self.answer


class _FakeDetector:
    """Stands in for `inject.target.TargetDetector`."""

    def __init__(self, app_class: str) -> None:
        self.app_class = app_class

    def get_app_class(self) -> str:
        return self.app_class


def _daemon(*, factory=None, reason=None, primary=PRIMARY_MODIFIER_CTRL,
            editor_profiles=True, profile="auto"):
    """A daemon on this host's platform bundle with the provider fields swapped in --
    the macOS and Windows bundles themselves cannot be built off their OS."""
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = True
    cfg.commands.editor_profiles = editor_profiles
    cfg.commands.profile = profile
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    platform = dataclasses.replace(get_platform(), focused_app_factory=factory,
                                   focused_app_unavailable_reason=reason,
                                   primary_modifier=primary)
    d = Daemon(config=cfg, platform=platform)
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _Injector()
    d._injector = inj
    d._state.target_ok = True
    return d, inj


def test_the_platform_provider_wins_over_the_text_target_detector():
    provider = _FakeProvider("Code.exe")
    d, _ = _daemon(factory=lambda: provider)
    d._target_detector = _FakeDetector("jetbrains-idea")
    reg = d._build_command_profiles(d._config)
    assert reg is not None and reg.needs_focused_app
    assert d._focused_app_class is not None
    assert d._focused_app_class() == "Code.exe"
    assert d._profile_detector is None, "no detector is built when the platform answers"

    d._command_profiles = reg
    event: dict = {}
    d._command_keymap(event)
    assert event["command_profile"] == "vscode"


def test_the_provider_is_built_once_and_asked_per_command():
    built: list[_FakeProvider] = []

    def _factory():
        built.append(_FakeProvider("sublime_text.exe"))
        return built[-1]

    d, _ = _daemon(factory=_factory)
    d._target_detector = None
    d._command_profiles = d._build_command_profiles(d._config)
    for _ in range(3):
        d._command_keymap({})
    assert len(built) == 1
    assert built[0].asked == 3


def test_a_pinned_profile_never_builds_the_provider():
    def _factory():  # pragma: no cover - must not be reached
        raise AssertionError("a pinned profile needs no focused application")

    d, _ = _daemon(factory=_factory, profile="jetbrains")
    reg = d._build_command_profiles(d._config)
    assert reg is not None and reg.pinned == "jetbrains"
    assert d._focused_app_class is None


def test_profiles_off_never_builds_the_provider():
    def _factory():  # pragma: no cover - must not be reached
        raise AssertionError("editor_profiles is off")

    d, _ = _daemon(factory=_factory, editor_profiles=False)
    assert d._build_command_profiles(d._config) is None
    assert d._focused_app_class is None


def test_a_factory_that_raises_falls_back_to_the_detector_and_says_why(caplog):
    """A Mac without the AppKit bridge: the reason is logged, the detector is used
    (which answers "" there, so the default keys and the once-only notice follow)."""

    def _factory():
        raise RuntimeError(mac.NO_APPKIT_REASON)

    d, _ = _daemon(factory=_factory)
    d._target_detector = _FakeDetector("")
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        reg = d._build_command_profiles(d._config)
    assert reg is not None
    assert d._focused_app_class == d._target_detector.get_app_class
    assert any(mac.NO_APPKIT_REASON in r.getMessage() for r in caplog.records)


def test_no_provider_with_a_stated_reason_logs_it_and_uses_the_detector(caplog):
    reason = "this session cannot name the focused application"
    d, _ = _daemon(factory=None, reason=reason)
    d._target_detector = _FakeDetector("jetbrains-pycharm")
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._build_command_profiles(d._config)
    assert d._focused_app_class is not None
    assert d._focused_app_class() == "jetbrains-pycharm"
    assert any(reason in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("answer", [None, 42, object()])
def test_an_answer_that_is_not_a_string_is_no_app(answer):
    d, _ = _daemon()
    d._command_profiles = load_profiles(d._config.commands)
    d._focused_app_class = lambda: answer  # type: ignore[assignment,return-value]
    event: dict = {}
    keymap = d._command_keymap(event)
    assert event["command_profile"] == "default"
    assert keymap is not None and dict(keymap) == {}


@pytest.mark.parametrize("app_id", ["idea64.exe", "pycharm64.exe", "studio64.exe"])
def test_on_windows_a_jetbrains_ide_gets_its_delete_line(app_id):
    """End to end on a Ctrl platform: the provider's image name picks the profile."""
    d, inj = _daemon(factory=lambda: _FakeProvider(app_id))
    d._target_detector = None
    d._command_profiles = d._build_command_profiles(d._config)
    d._command_mode = True
    d._engine.text = "delete the last line"
    d._on_hold_end()
    assert ["ctrl+y"] in inj.calls
    assert ["ctrl+shift+k"] not in inj.calls


def test_on_windows_sublime_refuses_rename():
    d, inj = _daemon(factory=lambda: _FakeProvider("sublime_text.exe"))
    d._target_detector = None
    d._command_profiles = d._build_command_profiles(d._config)
    d._command_mode = True
    d._engine.text = "rename this to user_id"
    d._on_hold_end()
    assert inj.calls == []


@pytest.mark.parametrize("bundle_id", ["com.jetbrains.pycharm", "com.jetbrains.intellij.ce",
                                       "com.google.android.studio"])
def test_on_macos_a_jetbrains_ide_gets_its_macos_delete_line(bundle_id):
    """End to end on a Cmd platform: the bundle id picks the profile, and the profile
    is the editor's *macOS* keymap (`BUILTIN_CMD_PROFILES`), not the Linux one."""
    d, inj = _daemon(factory=lambda: _FakeProvider(bundle_id), primary=PRIMARY_MODIFIER_CMD)
    d._target_detector = None
    d._command_profiles = d._build_command_profiles(d._config)
    d._command_mode = True
    d._engine.text = "delete the last line"
    d._on_hold_end()
    assert ["cmd+BackSpace"] in inj.calls
    assert ["ctrl+y"] not in inj.calls


def test_on_macos_vs_code_keeps_the_macos_default_keys():
    from yazses.commands.dispatch import CMD_DEFAULT_KEYMAP

    d, inj = _daemon(factory=lambda: _FakeProvider("com.microsoft.VSCode"),
                     primary=PRIMARY_MODIFIER_CMD)
    d._target_detector = None
    d._command_profiles = d._build_command_profiles(d._config)
    event: dict = {}
    assert dict(d._command_keymap(event) or {}) == {}
    assert event["command_profile"] == "vscode"

    d._command_mode = True
    d._engine.text = "delete the last line"
    d._on_hold_end()
    assert CMD_DEFAULT_KEYMAP["delete_lines"] in inj.calls


def test_a_stand_in_platform_without_the_field_falls_back_to_the_detector():
    """A test rig's platform built before the field existed has no provider."""
    from yazses.core.daemon import Daemon

    rig = Daemon.__new__(Daemon)
    rig._platform = types.SimpleNamespace()
    assert rig._platform_focused_app_source() is None
    del rig._platform
    assert rig._platform_focused_app_source() is None
