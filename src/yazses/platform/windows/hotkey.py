"""Windows hotkey backend via WH_KEYBOARD_LL low-level keyboard hook.

The hook runs on the thread that calls ``SetWindowsHookExW``; that thread
must pump messages with ``GetMessageW`` for the callback to fire. ``run()``
installs the hook and enters the message loop; ``stop()`` posts ``WM_QUIT``
to the loop, which is thread-safe.

Right Ctrl vs Left Ctrl: the low-level hook reports distinct virtual keys
(VK_RCONTROL vs VK_LCONTROL), so a simple vk-code comparison suffices —
no need to inspect ``LLKHF_EXTENDED``.

Press semantics mirror :mod:`yazses.hotkeys.evdev_hold` exactly: a modifier
hotkey starts recording on the *initial* key-down, never on an OS auto-repeat.
Windows delivers no repeat-count in ``KBDLLHOOKSTRUCT`` (unlike ``WM_KEYDOWN``'s
lParam), so a repeat is identified by tracking key state across events.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from yazses.hotkeys.hold_detector import HoldDetector
from yazses.platform.windows.injector import INJECTED_TAG

log = logging.getLogger(__name__)


# WinAPI constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

# Virtual key codes (subset; see Microsoft "Virtual-Key Codes" docs).
VK_BACK = 0x08
VK_SPACE = 0x20
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_LWIN = 0x5B
VK_RWIN = 0x5C


_KEY_MAP: dict[str, int] = {
    "space": VK_SPACE,
    "right_ctrl": VK_RCONTROL,
    "left_ctrl": VK_LCONTROL,
    "right_shift": VK_RSHIFT,
    "left_shift": VK_LSHIFT,
    "right_alt": VK_RMENU,
    "left_alt": VK_LMENU,
    "right_meta": VK_RWIN,
    "left_meta": VK_LWIN,
    # macOS naming compatibility.
    "right_option": VK_RMENU,
    "left_option": VK_LMENU,
}

_CHARACTER_KEYS: frozenset[str] = frozenset({"space"})


def resolve_key_id(key_id: str, default: str = "right_ctrl") -> tuple[str, int]:
    """Return (canonical_key_id, vk_code). 'auto' resolves to default."""
    name = key_id.lower()
    if name == "auto":
        name = default
    if name not in _KEY_MAP:
        raise ValueError(
            f"Unknown hotkey {key_id!r}. Supported: {sorted(_KEY_MAP)} or 'auto'."
        )
    return name, _KEY_MAP[name]


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


# CALLBACK prototype: LRESULT __stdcall LowLevelKeyboardProc(int, WPARAM, LPARAM)
_LRESULT = ctypes.c_ssize_t
_LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    _LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
) if hasattr(ctypes, "WINFUNCTYPE") else None

_HHOOK = ctypes.c_void_p


def _win32() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:  # type: ignore[name-defined]
    """user32 + kernel32 with real error reporting and 64-bit-safe signatures.

    ``ctypes.windll`` caches libraries loaded *without* ``use_last_error``, so
    ``ctypes.get_last_error()`` against it returns a meaningless value — every
    "lastError=..." we logged through it was noise. Declaring argtypes/restype
    matters just as much: ctypes defaults a return to ``c_int``, which silently
    truncates the 64-bit ``HHOOK`` from ``SetWindowsHookExW`` on x64, so the
    handle we later hand to ``UnhookWindowsHookEx`` can be a different one.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        _LowLevelKeyboardProc,
        wintypes.HMODULE,
        wintypes.DWORD,
    ]
    user32.SetWindowsHookExW.restype = _HHOOK

    user32.UnhookWindowsHookEx.argtypes = [_HHOOK]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL

    user32.CallNextHookEx.argtypes = [
        _HHOOK,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallNextHookEx.restype = _LRESULT

    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        ctypes.c_uint,
        ctypes.c_uint,
    ]
    user32.GetMessageW.restype = ctypes.c_int

    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        ctypes.c_uint,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostThreadMessageW.restype = wintypes.BOOL

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    return user32, kernel32


class WindowsHotkey:
    """HotkeyBackend implementation for Windows."""

    def __init__(
        self,
        key_id: str,
        threshold_ms: int,
        on_hold_start: Callable[[int], None],
        on_hold_end: Callable[[], None],
    ) -> None:
        self._key_id, self._vk = resolve_key_id(key_id)
        self._produces_char = self._key_id in _CHARACTER_KEYS

        self._detector = HoldDetector(threshold_ms=threshold_ms)
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._recording = False
        # The hook gives us no repeat-count, so we derive "is this an OS
        # auto-repeat?" from whether we already saw a down without an up.
        self._key_down = False

        self._hook_handle: int | None = None
        self._hook_thread_id: int | None = None
        self._hook_proc = None  # Strong ref so the C callback isn't GC'd.
        self._user32: ctypes.WinDLL | None = None  # type: ignore[name-defined]
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------

    def run(self) -> None:
        if _LowLevelKeyboardProc is None:
            raise RuntimeError("WINFUNCTYPE unavailable; not running on Windows.")

        user32, kernel32 = _win32()
        self._user32 = user32

        self._hook_thread_id = kernel32.GetCurrentThreadId()

        # Build and pin the callback.
        self._hook_proc = _LowLevelKeyboardProc(self._on_hook)

        # A low-level hook is global and lives in this process, so hMod is
        # ignored; passing NULL avoids a bogus handle under PyInstaller, where
        # the "module" is the bootloader rather than the Python DLL.
        self._hook_handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._hook_proc, None, 0
        )
        if not self._hook_handle:
            err = ctypes.get_last_error()
            raise OSError(
                f"SetWindowsHookExW failed (lastError={err}). The hotkey cannot "
                f"be captured; another app may hold an exclusive hook."
            )

        log.info("WH_KEYBOARD_LL installed for key_id=%s (vk=0x%x)", self._key_id, self._vk)

        try:
            msg = wintypes.MSG()
            while True:
                rv = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if rv == 0:  # WM_QUIT
                    break
                if rv == -1:
                    err = ctypes.get_last_error()
                    raise OSError(f"GetMessageW failed (lastError={err})")
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._teardown()

    def stop(self) -> None:
        self._stop_event.set()
        if self._hook_thread_id is None or self._user32 is None:
            return
        try:
            self._user32.PostThreadMessageW(self._hook_thread_id, WM_QUIT, 0, 0)
        except Exception:
            log.exception("PostThreadMessageW(WM_QUIT) failed")

    @property
    def key_id(self) -> str:
        return self._key_id

    # ------------------------------------------------------------------

    def _on_hook(self, n_code: int, w_param: int, l_param: int) -> int:
        try:
            if n_code >= 0:
                kbd = ctypes.cast(l_param, ctypes.POINTER(_KBDLLHOOKSTRUCT))[0]
                # Ignore our own SendInput traffic. Without this the injector
                # typing a Ctrl-bearing command sequence feeds the hook a
                # modifier press and the daemon triggers itself — the same
                # self-capture the Linux backend avoids by refusing to listen on
                # ydotool/uinput devices.
                if int(kbd.dwExtraInfo or 0) != INJECTED_TAG and int(kbd.vkCode) == self._vk:
                    if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._press()
                    elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                        self._release()
        except Exception:
            log.exception("Hook callback raised")
        # Always pass through; we listen, we never block.
        user32 = self._user32 or ctypes.windll.user32
        return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

    def handle_key_event(self, down: bool, t: float) -> None:
        """Advance the press/hold/release state machine for one hook event.

        Pure with respect to Win32 — ``run()`` feeds it from the hook callback,
        and the tests feed it directly. Semantics match
        :meth:`yazses.hotkeys.evdev_hold.EvdevHoldListener._handle_event`.
        """
        if down:
            is_repeat = self._key_down
            self._key_down = True
            if not is_repeat:
                # Only a real press counts as a leaked character; charging every
                # auto-repeat would make the cleanup eat the user's own text.
                self._detector.on_press(t)
            if self._recording:
                return
            if self._produces_char:
                # A character key types before we can tell a tap from a hold, so
                # it must wait out the threshold and clean up what leaked.
                if self._detector.check(t):
                    self._recording = True
                    self._on_hold_start(self._detector.leaked_count)
            elif not is_repeat:
                # A modifier types nothing, so start the instant it goes down.
                # Waiting for the threshold here would mean waiting for an OS
                # auto-repeat that may never arrive for Ctrl/Shift/Alt — and
                # where it does arrive, it lands after the user's key-repeat
                # delay (250 ms–1 s, their setting), clipping the first words.
                self._recording = True
                self._on_hold_start(0)
        else:
            self._key_down = False
            was_recording = self._recording
            self._recording = False
            self._detector.reset()
            if was_recording:
                self._on_hold_end()

    def _press(self) -> None:
        self.handle_key_event(True, time.monotonic())

    def _release(self) -> None:
        self.handle_key_event(False, time.monotonic())

    def _teardown(self) -> None:
        if self._hook_handle is not None and self._user32 is not None:
            try:
                self._user32.UnhookWindowsHookEx(self._hook_handle)
            except Exception:
                log.exception("UnhookWindowsHookEx failed")
        self._hook_handle = None
        self._hook_thread_id = None
        self._hook_proc = None
        self._user32 = None
