"""Windows click observer for implicit gaze calibration: a `WH_MOUSE_LL` hook (#607).

The Windows producer behind the `ClickObserver` seam in `src/yazses/gaze/clicks.py`. It
turns a mouse-button press anywhere on the desktop into one `ClickEvent` — when, and where
— and nothing else. Which button, which window, what was under the pointer: the value has
no field for any of it, and this module reads none of it beyond the message id it needs to
tell a press from a move.

**Shape.** The same shape as `platform/windows/hotkey.py`, for the same reason: a low-level
hook is called on the thread that installed it, and only while that thread pumps messages
(`LowLevelMouseProc` Remarks). So :meth:`WindowsClickObserver.start` spawns a dedicated
daemon thread that calls `SetWindowsHookExW(WH_MOUSE_LL)` and runs its own `GetMessageW`
loop; :meth:`WindowsClickObserver.stop` posts `WM_QUIT` to that thread with
`PostThreadMessageW` and joins it. The C callback is pinned in ``_hook_proc`` so the
garbage collector cannot free a function Windows still holds a pointer to.

**The hook procedure does almost nothing, on purpose.** Microsoft documents a
``LowLevelHooksTimeout`` (``HKCU\\Control Panel\\Desktop``, 300 ms by default, capped at
1000 ms): a procedure that takes longer is, on Windows 7 and later, *silently removed
without being called*, and "there is no way for the application to know". The same page
says what to do instead — "run the hooks on a dedicated thread that passes the work off to
a worker thread and then immediately returns". That is exactly the split here: the hook
procedure reads the message id and the point, stamps `time.monotonic()`, puts a tuple on a
:class:`queue.SimpleQueue` and returns `CallNextHookEx`. A second thread drains the queue
and calls the user's callback, so a callback that is slow, that blocks, or that raises can
never cost the hook. (`SimpleQueue.put` never blocks and is reentrant.)

**It listens; it never swallows.** The procedure returns whatever `CallNextHookEx` returns
for every message, including the ones it counted. Returning ``1`` would eat the user's
click — the opposite of what a passive observer may do — and for ``nCode < 0`` the
documentation requires passing the message on without looking at it, which is also done.

**Coordinates.** `MSLLHOOKSTRUCT.pt` is documented as "the x- and y-coordinates of the
cursor, in per-monitor-aware screen coordinates"
(https://learn.microsoft.com/windows/win32/api/winuser/ns-winuser-msllhookstruct): the
origin is the primary monitor's top-left and a monitor to its left or above yields
*negative* values, which is the Windows convention `gaze/topology.py` names for the
canonical space of ADR-v2-149. The unit is the physical pixel as a per-monitor-DPI-aware
process would see it, which coincides with the canonical *logical* pixel exactly when every
display is at 100 % scale. :func:`to_canonical` is the single site where that conversion
lives, and today it changes units for no one: Windows has no display-topology provider yet
(the `scale` a conversion needs is a topology fact), and `platform/windows/pointer.py`
already declines to guess a DPI mapping that no Windows machine is available to check — a
wrong one here would quietly teach the refiner a wrong map on a HiDPI desktop. Whoever
writes the Windows topology provider owns filling this function in; until then the
calibration fingerprint, not this backend, is what guards a HiDPI user.

**Never executed on Windows yet.** ctypes packs and reads the real struct on Linux, so the
tests exercise the procedure, the queue, the lifecycle and the sign of a negative
coordinate; whether `SetWindowsHookExW` grants a hook to a Python process on a given
desktop (it does not in services, and not over every remote-desktop configuration) is a
fact only a Windows machine can report.
"""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from typing import Any, Protocol

from yazses.gaze.clicks import ClickEvent, ClickObserverError

log = logging.getLogger(__name__)

__all__ = [
    "CLICK_MESSAGES",
    "WH_MOUSE_LL",
    "WindowsClickObserver",
    "point_of",
    "to_canonical",
]

# WinAPI constants (winuser.h).
WH_MOUSE_LL = 14
WM_QUIT = 0x0012
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B

#: The three messages that are a click to implicit calibration. Button-up is the same
#: place a few milliseconds later; wheel, move and the X buttons are not a fixation target.
CLICK_MESSAGES: frozenset[int] = frozenset({WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN})

#: Thread names, so a test can prove nothing was left running.
THREAD_NAME_PREFIX = "yazses-click-"


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    """https://learn.microsoft.com/windows/win32/api/winuser/ns-winuser-msllhookstruct"""

    _fields_ = [
        ("pt", _POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),  # ULONG_PTR
    ]


# CALLBACK prototype: LRESULT __stdcall LowLevelMouseProc(int, WPARAM, LPARAM).
# Guarded exactly as hotkey.py does so this module imports on Linux, where the tests run.
_LRESULT = ctypes.c_ssize_t
_LowLevelMouseProc = (
    ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    if hasattr(ctypes, "WINFUNCTYPE")
    else None
)


def point_of(l_param: int) -> tuple[int, int]:
    """The cursor position carried by a `WH_MOUSE_LL` message, as two signed integers."""
    record = ctypes.cast(l_param, ctypes.POINTER(_MSLLHOOKSTRUCT))[0]
    return int(record.pt.x), int(record.pt.y)


def to_canonical(x: int, y: int) -> tuple[float, float]:
    """Hook coordinates -> the canonical desktop space of ADR-v2-149.

    Primary-origin, negative to the left/above: already the Windows convention
    `gaze/topology.py` documents, so the sign and origin are kept. The unit is the hook's
    per-monitor-aware screen pixel, equal to the canonical logical pixel at 100 % scale;
    see the module docstring for why no DPI factor is applied here yet.
    """
    return float(x), float(y)


class MouseHookApi(Protocol):
    """The seven things the observer needs from user32/kernel32, so a test can fake them."""

    def make_proc(self, callback: Callable[[int, int, int], int]) -> Any:
        """Wrap *callback* as the C hook procedure (the caller pins the result)."""
        ...

    def current_thread_id(self) -> int: ...

    def install(self, proc: Any) -> int:
        """`SetWindowsHookExW(WH_MOUSE_LL, ...)`: the hook handle, or 0 on failure."""
        ...

    def last_error(self) -> int: ...

    def call_next_hook(self, hook: int, n_code: int, w_param: int, l_param: int) -> int: ...

    def pump(self) -> None:
        """Run the message loop on the calling thread until `WM_QUIT` arrives."""
        ...

    def post_quit(self, thread_id: int) -> None: ...

    def uninstall(self, hook: int) -> None: ...


def _win32_last_error() -> int:
    """`ctypes.get_last_error()`, which exists only on Windows (as `pointer._last_error`)."""
    getter = getattr(ctypes, "get_last_error", None)
    return int(getter()) if getter is not None else 0


class _Win32MouseHookApi:
    """The real thing. Constructed only inside `start()`, and only on Windows."""

    def __init__(self) -> None:
        if _LowLevelMouseProc is None or not hasattr(ctypes, "WinDLL"):
            raise ClickObserverError(
                "a WH_MOUSE_LL hook needs Windows; this is not a Windows session"
            )
        # `use_last_error=True` is what makes `get_last_error()` report the real code, and
        # the explicit restypes stop 64-bit handles being truncated to a C int — both
        # lessons `platform/windows/hotkey.py` records.
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, _LowLevelMouseProc, wintypes.HINSTANCE, wintypes.DWORD
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
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetCurrentThreadId.argtypes = []
        self._user32 = user32
        self._kernel32 = kernel32

    def make_proc(self, callback: Callable[[int, int, int], int]) -> Any:
        assert _LowLevelMouseProc is not None  # the constructor refused otherwise
        return _LowLevelMouseProc(callback)

    def current_thread_id(self) -> int:
        return int(self._kernel32.GetCurrentThreadId())

    def install(self, proc: Any) -> int:
        h_module = self._kernel32.GetModuleHandleW(None)
        return int(self._user32.SetWindowsHookExW(WH_MOUSE_LL, proc, h_module, 0) or 0)

    def last_error(self) -> int:
        return _win32_last_error()

    def call_next_hook(self, hook: int, n_code: int, w_param: int, l_param: int) -> int:
        return int(self._user32.CallNextHookEx(hook, n_code, w_param, l_param))

    def pump(self) -> None:
        msg = wintypes.MSG()
        while True:
            rv = self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if rv == 0:  # WM_QUIT
                return
            if rv == -1:
                raise OSError(f"GetMessageW failed (lastError={_win32_last_error()})")
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

    def post_quit(self, thread_id: int) -> None:
        if not self._user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0):
            raise OSError(
                f"PostThreadMessageW(WM_QUIT) failed (lastError={_win32_last_error()})"
            )

    def uninstall(self, hook: int) -> None:
        self._user32.UnhookWindowsHookEx(hook)


_STOP = object()


class WindowsClickObserver:
    """`ClickObserver` for Windows: a `WH_MOUSE_LL` hook on its own thread, a queue, a worker.

    Constructing it touches nothing: no DLL is loaded until :meth:`start`, which is the
    point at which the daemon has read ``[gaze_refine] enabled = true``. *api* exists for
    the tests; the default is the real user32.
    """

    def __init__(self, api: MouseHookApi | None = None, *, join_timeout_s: float = 2.0) -> None:
        self._api_override = api
        self._api: MouseHookApi | None = None
        self._join_timeout_s = float(join_timeout_s)
        self._lock = threading.RLock()
        self._callback: Callable[[ClickEvent], None] | None = None
        self._queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._hook_thread: threading.Thread | None = None
        self._deliver_thread: threading.Thread | None = None
        self._hook_thread_id: int | None = None
        self._hook_handle: int = 0
        self._hook_proc: Any = None  # strong ref: Windows holds a raw pointer to it
        self._ready = threading.Event()
        self._start_error: str | None = None
        self._hook_proc_failed = False
        self._callback_failed = False
        self._accepting = False

    # ------------------------------------------------------------------ public

    def start(self, on_click: Callable[[ClickEvent], None]) -> None:
        with self._lock:
            if self._hook_thread is not None:
                return  # already started: a no-op, as the Protocol promises
            api = self._api_override or _Win32MouseHookApi()
            self._api = api
            self._callback = on_click
            self._queue = queue.SimpleQueue()
            self._ready.clear()
            self._start_error = None
            self._hook_proc_failed = False
            self._callback_failed = False
            self._hook_proc = api.make_proc(self._on_hook)
            self._accepting = True

            hook_thread = threading.Thread(
                target=self._hook_main, name=THREAD_NAME_PREFIX + "hook", daemon=True
            )
            hook_thread.start()
            if not self._ready.wait(timeout=max(self._join_timeout_s, 5.0)):
                self._start_error = "the hook thread did not report back in time"
            if self._start_error is not None:
                hook_thread.join(timeout=self._join_timeout_s)
                self._forget()
                raise ClickObserverError(self._start_error)

            self._hook_thread = hook_thread
            self._deliver_thread = threading.Thread(
                target=self._deliver_main,
                args=(self._queue, on_click),
                name=THREAD_NAME_PREFIX + "deliver",
                daemon=True,
            )
            self._deliver_thread.start()
            log.info("WH_MOUSE_LL installed: implicit gaze calibration is observing clicks")

    def stop(self) -> None:
        with self._lock:
            hook_thread, self._hook_thread = self._hook_thread, None
            deliver_thread, self._deliver_thread = self._deliver_thread, None
            thread_id = self._hook_thread_id
            api = self._api
            pending = self._queue
            self._callback = None
            self._accepting = False
        if hook_thread is None:
            return
        if api is not None and thread_id is not None:
            try:
                api.post_quit(thread_id)
            except Exception:
                log.exception("PostThreadMessageW(WM_QUIT) to the click hook thread failed")
        if hook_thread is not threading.current_thread():
            hook_thread.join(timeout=self._join_timeout_s)
        pending.put(_STOP)
        if deliver_thread is not None and deliver_thread is not threading.current_thread():
            deliver_thread.join(timeout=self._join_timeout_s)
        with self._lock:
            self._forget()

    # ----------------------------------------------------------------- threads

    def _hook_main(self) -> None:
        """The hook thread: install, pump until WM_QUIT, unhook. Reports back via `_ready`."""
        api = self._api
        assert api is not None
        try:
            self._hook_thread_id = api.current_thread_id()
            self._hook_handle = api.install(self._hook_proc)
            if not self._hook_handle:
                err = api.last_error()
                self._start_error = (
                    f"SetWindowsHookExW(WH_MOUSE_LL) failed (lastError={err}). A low-level "
                    "mouse hook needs an interactive desktop session; it is unavailable in "
                    "services and over some remote-desktop configurations."
                )
                return
        except Exception as exc:
            self._start_error = f"the mouse hook could not be installed ({type(exc).__name__}: {exc})"
            return
        finally:
            self._ready.set()
        try:
            api.pump()
        except Exception:
            log.exception("The click hook's message loop ended with an error")
        finally:
            handle, self._hook_handle = self._hook_handle, 0
            try:
                api.uninstall(handle)
            except Exception:
                log.exception("UnhookWindowsHookEx failed")

    def _on_hook(self, n_code: int, w_param: int, l_param: int) -> int:
        """The C callback. Cheap by construction: read, stamp, enqueue, pass on."""
        api = self._api
        hook = self._hook_handle
        if n_code >= 0 and w_param in CLICK_MESSAGES and self._accepting:
            try:
                x, y = point_of(l_param)
                self._queue.put((time.monotonic(), x, y))
            except Exception:
                if not self._hook_proc_failed:
                    self._hook_proc_failed = True
                    log.exception("The click hook could not read a mouse message")
        if api is None:  # pragma: no cover - the hook cannot fire before start()
            return 0
        return api.call_next_hook(hook, n_code, w_param, l_param)

    def _deliver_main(self, pending: queue.SimpleQueue[Any], on_click: Callable[[ClickEvent], None]) -> None:
        """The worker: the only place the user's callback runs."""
        while True:
            item = pending.get()
            if item is _STOP:
                return
            stamp, x, y = item
            cx, cy = to_canonical(x, y)
            try:
                on_click(ClickEvent(timestamp_s=stamp, x=cx, y=cy))
            except Exception:
                # Logged in full once; the Protocol says the callback must contain its own
                # errors, so a flood here would only hide the first, informative one.
                if not self._callback_failed:
                    self._callback_failed = True
                    log.exception("The click callback raised; later clicks are still delivered")
                else:
                    log.debug("The click callback raised again", exc_info=True)

    def _forget(self) -> None:
        self._hook_thread = None
        self._deliver_thread = None
        self._hook_thread_id = None
        self._hook_handle = 0
        self._hook_proc = None
        self._callback = None
        self._accepting = False
