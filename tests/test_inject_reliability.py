"""Lost, doubled or mangled text in the injection and clipboard paths.

Everything here is synthetic: fake `subprocess.run`, fake uinput keyboard, fake
Win32 calls. No display, no ydotoold and no Windows are needed.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yazses.inject import clipboard
from yazses.inject import unicode as unicode_mod
from yazses.inject import ydotool as yd
from yazses.platform.linux.injector import LinuxInjector
from yazses.platform.windows import clipboard as win_clipboard
from yazses.platform.windows import injector as win_injector
from yazses.system.diagnosis import INJECT, diagnose

# ---- ydotool 1.x interprets backslash escapes in `type` arguments -------------

PATH_TEXT = "C:\\Users\\new"


def _ydotool_runs(monkeypatch, answer=lambda argv: (0, "")):
    calls: list[list[str]] = []

    def run(argv, *_a, **_k):
        calls.append(list(argv))
        code, stderr = answer(list(argv))
        return SimpleNamespace(returncode=code, stdout="", stderr=stderr)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


@pytest.fixture
def dialect_v1(monkeypatch):
    monkeypatch.setattr(yd, "_dialect_cache", yd.DIALECT_V1)


def _types(calls):
    return [c for c in calls if c[1] == "type"]


def test_a_backslash_is_typed_literally_on_ydotool_1(monkeypatch, dialect_v1):
    calls = _ydotool_runs(monkeypatch)
    yd.YdotoolInjector().inject(PATH_TEXT)

    (argv,) = _types(calls)
    options = argv[: argv.index("--")]
    assert options[-2:] == ["-e", "0"]
    assert argv[-1] == PATH_TEXT


def test_text_without_a_backslash_keeps_the_old_command_line(monkeypatch, dialect_v1):
    calls = _ydotool_runs(monkeypatch)
    yd.YdotoolInjector().inject("hello")
    assert _types(calls) == [["ydotool", "type", "-d", "6", "-H", "6", "--", "hello"]]


def test_ydotool_0_1_is_not_given_the_escape_flag(monkeypatch):
    monkeypatch.setattr(yd, "_dialect_cache", yd.DIALECT_V0)
    calls = _ydotool_runs(monkeypatch)
    yd.YdotoolInjector().inject(PATH_TEXT)
    assert "-e" not in _types(calls)[0]


def test_a_build_without_the_escape_flag_stays_on_dialect_1(monkeypatch, dialect_v1):
    def answer(argv):
        if "-e" in argv:
            return 1, "ydotool: invalid option -- 'e'\n"
        return 0, ""

    calls = _ydotool_runs(monkeypatch, answer)
    yd.YdotoolInjector().inject(PATH_TEXT)

    assert len(_types(calls)) == 2
    assert _types(calls)[1] == [
        "ydotool", "type", "-d", "6", "-H", "6", "--", PATH_TEXT,
    ]
    assert yd.ydotool_dialect() == yd.DIALECT_V1


def test_a_0_1_ydotool_misprobed_as_1_still_downgrades(monkeypatch, dialect_v1):
    def answer(argv):
        if "-d" in argv:
            return 0, "type: error: unrecognised option '-d'\n"
        return 0, ""

    calls = _ydotool_runs(monkeypatch, answer)
    yd.YdotoolInjector().inject(PATH_TEXT)

    assert _types(calls)[-1] == ["ydotool", "type", "--key-delay", "6", "--", PATH_TEXT]
    assert yd.ydotool_dialect() == yd.DIALECT_V0


# ---- mixed ASCII / non-ASCII text when /dev/uinput cannot be opened -----------


class _Xkb:
    _KEYS = {30: "a", 47: "v", 57: " ", 18: "é", 28: "\r", 101: "\n"}

    def update(self, keycode, direction):
        pass

    def key_text(self, keycode):
        return self._KEYS.get(keycode, "")

    def close(self):
        pass


class _Keyboard:
    def __init__(self):
        self.taps: list[int] = []

    def tap(self, keycode, modifiers=()):
        self.taps.append(keycode)

    def close(self):
        pass


def test_an_unopenable_uinput_types_a_mixed_burst_exactly_once(monkeypatch, dialect_v1):
    """A root-run ydotoold types fine while this process cannot open /dev/uinput."""
    monkeypatch.setattr(unicode_mod._XkbSession, "create", lambda: _Xkb())

    def refuse(path):
        raise unicode_mod.UnicodeInjectorError("cannot open /dev/uinput")

    monkeypatch.setattr(unicode_mod._UinputKeyboard, "create", refuse)
    calls = _ydotool_runs(monkeypatch)
    pasted: list[str] = []

    injector = LinuxInjector.__new__(LinuxInjector)
    injector._primary = yd.YdotoolInjector()
    injector._fallback = SimpleNamespace(inject=pasted.append)
    injector.inject("a vé a")

    assert _types(calls) == [], "an ASCII run was typed before the failure"
    assert pasted == ["a vé a"]


# ---- the unicode backend and line breaks --------------------------------------


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_the_unicode_backend_presses_enter_for_a_line_break(monkeypatch, newline):
    keyboard = _Keyboard()
    monkeypatch.setattr(unicode_mod._XkbSession, "create", lambda: _Xkb())
    monkeypatch.setattr(unicode_mod._UinputKeyboard, "create", lambda path: keyboard)
    monkeypatch.setattr(unicode_mod.time, "sleep", lambda _s: None)

    unicode_mod.UnicodeInjector().inject(f"a{newline}v")

    # KEY_ENTER (28), not KEY_LINEFEED (101), which also "produces" a newline.
    assert keyboard.taps == [30, 28, 47]


# ---- Linux clipboard: copied, but Ctrl+V failed -------------------------------


@pytest.mark.parametrize("session", ["wayland", "x11"])
@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_a_failed_paste_says_the_words_are_on_the_clipboard(monkeypatch, session, failure):
    if session == "wayland":
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setattr(clipboard, "_ydotool_ready", lambda: True)
        monkeypatch.setattr(yd, "_dialect_cache", yd.DIALECT_V1)
    else:
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(clipboard, "_CLIPBOARD_SETTLE_S", 0)

    def run(argv, *_a, check=False, timeout=None, **_k):
        if argv[0] in ("wl-copy", "xclip"):
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, timeout)
        if check:
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no daemon")

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(clipboard.PasteUnavailable) as caught:
        clipboard.ClipboardInjector().inject("hi")

    assert diagnose(caught.value, where=INJECT).slug == "inject-copied-not-pasted"


def test_a_failed_copy_is_not_reported_as_copied(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    def run(argv, *_a, **_k):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(FileNotFoundError):
        clipboard.ClipboardInjector().inject("hi")


# ---- a timed-out key run is not replayed --------------------------------------


@pytest.mark.parametrize(
    ("method", "argument"),
    [("inject_backspaces", 40), ("inject_key_sequence", ["shift+Left"] * 40)],
)
def test_a_timed_out_key_run_is_not_replayed(method, argument):
    replayed: list[object] = []

    def time_out(_argument):
        raise subprocess.TimeoutExpired(["xdotool", "key"], 10)

    injector = LinuxInjector.__new__(LinuxInjector)
    injector._primary = SimpleNamespace(**{method: time_out})
    injector._fallback = SimpleNamespace(**{method: replayed.append})

    with pytest.raises(subprocess.TimeoutExpired):
        getattr(injector, method)(argument)

    assert replayed == []


# ---- Windows: line breaks and tabs are keys -----------------------------------


def test_windows_types_line_breaks_and_tabs_as_keys():
    up = win_injector.KEYEVENTF_KEYUP
    packet = win_injector.KEYEVENTF_UNICODE
    assert win_injector._text_events("a\r\n\tb\n") == [
        (0, ord("a"), packet), (0, ord("a"), packet | up),
        (0x0D, 0, 0), (0x0D, 0, up),
        (0x09, 0, 0), (0x09, 0, up),
        (0, ord("b"), packet), (0, ord("b"), packet | up),
        (0x0D, 0, 0), (0x0D, 0, up),
    ]


def test_windows_still_sends_an_astral_character_as_two_units():
    scans = [scan for _vk, scan, _flags in win_injector._text_events("\U0001f642")]
    assert scans == [0xD83D, 0xD83D, 0xDE42, 0xDE42]


# ---- Windows clipboard backend ------------------------------------------------


def _windows_clipboard(monkeypatch, *, accepted):
    """The paste backend with Win32 replaced; returns (writes, sent event counts)."""
    writes: list[str] = []
    sends: list[int] = []

    class _User32:
        def OpenClipboard(self, _hwnd):
            return True

        def CloseClipboard(self):
            return True

        def SendInput(self, count, _inputs, _size):
            sends.append(count)
            return accepted if len(sends) == 1 else count

    monkeypatch.setattr(win_clipboard, "_load_clipboard_user32", _User32)
    monkeypatch.setattr(win_clipboard, "_load_kernel32", lambda: None)
    monkeypatch.setattr(win_clipboard, "_read_unicode_text", lambda *_a: "before\nit")
    monkeypatch.setattr(
        win_clipboard, "_write_unicode_text", lambda _u, _k, text: writes.append(text)
    )
    monkeypatch.setattr(win_clipboard.ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(win_clipboard.time, "sleep", lambda _s: None)
    return writes, sends


@pytest.mark.parametrize(("accepted", "releases"), [(0, []), (1, [2])])
def test_windows_keeps_the_dictation_when_ctrl_v_is_refused(monkeypatch, accepted, releases):
    writes, sends = _windows_clipboard(monkeypatch, accepted=accepted)

    with pytest.raises(clipboard.PasteUnavailable) as caught:
        win_clipboard.WindowsClipboardInjector().inject("one\ntwo")

    assert writes == ["one\r\ntwo"], "the previous clipboard overwrote the dictation"
    assert sends == [4, *releases]  # a half-sent chord releases its keys
    assert diagnose(caught.value, where=INJECT).slug == "inject-copied-not-pasted"


def test_windows_restores_the_previous_clipboard_untouched(monkeypatch):
    writes, sends = _windows_clipboard(monkeypatch, accepted=4)

    win_clipboard.WindowsClipboardInjector().inject("one\r\ntwo\nthree")

    assert writes == ["one\r\ntwo\r\nthree", "before\nit"]
    assert sends == [4]
