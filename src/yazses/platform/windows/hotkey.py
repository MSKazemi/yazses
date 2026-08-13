"""Windows hotkey backend via WH_KEYBOARD_LL low-level keyboard hook.

The hook runs on the thread that calls ``SetWindowsHookExW``; that thread
must pump messages with ``GetMessageW`` for the callback to fire. ``run()``
installs the hook and enters the message loop; ``stop()`` posts ``WM_QUIT``
to the loop, which is thread-safe.

Right Ctrl vs Left Ctrl: the low-level hook reports distinct virtual keys
(VK_RCONTROL vs VK_LCONTROL), so a simple vk-code comparison suffices —
no need to inspect ``LLKHF_EXTENDED``.

**The hold threshold is driven by a timer, not by key events.** Windows only
delivers repeated ``WM_KEYDOWN`` for typematic keys, and modifier keys — which
is every hotkey we support except ``space`` — do not repeat while held. An
implementation that re-checks the elapsed time only when another key event
arrives therefore never fires for the default ``right_ctrl``: the single
keydown arrives at t=0, when no threshold has elapsed yet, and the next event
is the keyup. Even for ``space``, which does repeat, the first repeat is gated
on the user's typematic *repeat delay* (250–1000 ms, and disableable entirely
via Accessibility → Filter Keys), so the configured threshold would be
silently replaced by an OS setting. Arming a ``threading.Timer`` on the initial
press — the same approach the X11 backend uses in
``platform/linux/hotkey_xgrab.py`` — makes the threshold mean what it says on
every key and every machine.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

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


def _load_user32():
    """Return user32 with `use_last_error` and correct 64-bit prototypes.

    Two things this fixes over a bare ``ctypes.windll.user32``:

    * ``ctypes.get_last_error()`` only ever returns a meaningful value when the
      library was opened with ``use_last_error=True``. Read off ``windll`` it is
      a private ctypes copy that nothing ever wrote to, so every "lastError=..."
      in a failure message was reporting 0 regardless of the real error.
    * Without an explicit ``restype``, ctypes assumes the return value is a C
      ``int``. ``SetWindowsHookExW`` and ``GetModuleHandleW`` return pointers,
      so on 64-bit Windows their handles are silently truncated to 32 bits —
      after which ``UnhookWindowsHookEx`` and ``CallNextHookEx`` are handed a
      corrupt handle.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, _LowLevelKeyboardProc, wintypes.HINSTANCE, wintypes.DWORD
    ]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    user32.CallNextHookEx.restype = _LRESULT
    user32.CallNextHookEx.argtypes = [
        wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    ]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
    ]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    ]
    return user32


def _load_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GetCurrentThreadId.argtypes = []
    return kernel32


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

        self._threshold_ms = threshold_ms
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end

        # Press/hold state. `_press_time` is the "a press is being tracked"
        # flag; `_timer` fires the hold once the threshold elapses.
        self._press_time: float | None = None
        self._leaked_count = 0
        self._recording = False
        self._timer: threading.Timer | None = None
        self._state_lock = threading.Lock()

        self._user32 = None
        self._hook_handle: int | None = None
        self._hook_thread_id: int | None = None
        self._hook_proc = None  # Strong ref so the C callback isn't GC'd.

    # ------------------------------------------------------------------

    def run(self) -> None:
        if _LowLevelKeyboardProc is None:
            raise RuntimeError("WINFUNCTYPE unavailable; not running on Windows.")

        user32 = self._user32 = _load_user32()
        kernel32 = _load_kernel32()

        self._hook_thread_id = kernel32.GetCurrentThreadId()

        # Build and pin the callback.
        self._hook_proc = _LowLevelKeyboardProc(self._on_hook)

        h_module = kernel32.GetModuleHandleW(None)
        self._hook_handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._hook_proc, h_module, 0
        )
        if not self._hook_handle:
            err = ctypes.get_last_error()
            raise OSError(
                f"SetWindowsHookExW failed (lastError={err}). A low-level keyboard "
                "hook needs an interactive desktop session; it is unavailable in "
                "services and over some remote-desktop configurations."
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
        self._cancel_timer()
        if self._hook_thread_id is None:
            return
        try:
            user32 = self._user32 or _load_user32()
            user32.PostThreadMessageW(self._hook_thread_id, WM_QUIT, 0, 0)
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
                if int(kbd.vkCode) == self._vk:
                    if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._press()
                    elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                        self._release()
        except Exception:
            log.exception("Hook callback raised")
        # Always pass through; we listen, we never block.
        user32 = self._user32
        if user32 is None:  # pragma: no cover - hook can't fire before run()
            return 0
        return user32.CallNextHookEx(self._hook_handle or 0, n_code, w_param, l_param)

    # ---- press/hold state machine (pure enough to unit-test) -------------

    def _press(self) -> None:
        """Handle a keydown. Repeats while held must not re-arm the timer."""
        with self._state_lock:
            if self._press_time is not None:
                # Typematic repeat while still held. A character key leaks one
                # more character into the focused app per repeat, so keep
                # counting — that count is what gets backspaced away.
                if self._produces_char:
                    self._leaked_count += 1
                return
            self._press_time = time.monotonic()
            self._leaked_count = 1 if self._produces_char else 0
            timer = threading.Timer(self._threshold_ms / 1000.0, self._fire_hold_start)
            timer.daemon = True
            self._timer = timer
        timer.start()

    def _release(self) -> None:
        self._cancel_timer()
        with self._state_lock:
            was_recording = self._recording
            self._recording = False
            self._press_time = None
            self._leaked_count = 0
        if was_recording:
            self._on_hold_end()

    def _fire_hold_start(self) -> None:
        """Timer callback: the key has now been held for the full threshold."""
        with self._state_lock:
            if self._press_time is None or self._recording:
                return  # released before the threshold, or already recording
            self._recording = True
            leaked = self._leaked_count if self._produces_char else 0
        self._on_hold_start(leaked)

    def _cancel_timer(self) -> None:
        with self._state_lock:
            timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()

    def _teardown(self) -> None:
        self._cancel_timer()
        if self._hook_handle is not None:
            try:
                user32 = self._user32 or _load_user32()
                user32.UnhookWindowsHookEx(self._hook_handle)
            except Exception:
                log.exception("UnhookWindowsHookEx failed")
            self._hook_handle = None
        self._hook_thread_id = None
        self._hook_proc = None
