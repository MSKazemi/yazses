"""Windows clipboard injector — copy, then a real Ctrl+V keystroke.

`WindowsInjector` types with ``SendInput`` + ``KEYEVENTF_UNICODE``, which is the
right default: it carries any character without going through a keyboard layout.
But Microsoft documents two ways that path arrives wrong in *some* applications,
and both produce the same user-visible symptom — the correct *number* of
characters, every one of them wrong:

* **An ANSI window.** ``KEYBDINPUT`` Remarks: the Unicode character "will
  automatically be converted to the appropriate ANSI value if it is posted to an
  ANSI window". Whatever the active ANSI codepage cannot represent becomes the
  substitution character, ``?``.
* **A text service that does not unpack VK_PACKET.** ``KEYEVENTF_UNICODE``
  synthesises a *VK_PACKET* keystroke, and Microsoft's IME requirements state
  that "the WPARAM parameter of the ITfKeyEventSink callbacks always contains
  the virtual key VK_PACKET and doesn't identify the character directly" — a TSF
  text service has to call ``ToUnicode(VK_PACKET, 0, state, &wch, 1, 0)`` to
  recover it. One that doesn't runs the keystroke through the current keyboard
  layout instead, so every character of the sentence comes out as the same wrong
  one (rows of ``-``, ``.`` or ``?``).

Chromium special-cases VK_PACKET, which is why the browser is fine on a machine
where a note application is not.

Pasting sidesteps the whole translation layer: the text goes onto the clipboard
as CF_UNICODETEXT and the app reads it with ``GetClipboardData``. The only
keystroke sent is Ctrl+V, as ordinary virtual keys.

The cost is the clipboard, so this is **opt-in** (``[injection] backend =
"clipboard"``) and the previous contents are saved and put back. Terminals where
Ctrl+V is literal, and password fields that refuse paste, are the known
trade-off — the same one ``inject/clipboard.py`` documents for Linux.
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

from yazses.platform.windows.injector import (
    _INPUT,
    _KEYBDINPUT,
    INJECTED_TAG,
    INPUT_KEYBOARD,
    KEYEVENTF_KEYUP,
    WindowsInjector,
    _load_user32,
)

log = logging.getLogger(__name__)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

VK_CONTROL = 0x11
VK_V = 0x56

#: Seconds between setting the clipboard and sending Ctrl+V. The owner-change
#: notification is asynchronous: a paste fired in the same millisecond can read
#: the *previous* contents. `inject/clipboard.py` carries the same constant for
#: the same reason on Wayland.
_SETTLE_S = 0.05

#: Seconds to wait after Ctrl+V before restoring the previous clipboard. The
#: paste is delivered through the target's message queue, so restoring
#: immediately races it and the app pastes the text we just put back.
_PASTE_DRAIN_S = 0.25

#: How long to keep retrying `OpenClipboard`. Another process (a clipboard
#: manager, or the app itself) can hold it open, and a single failed attempt
#: would silently drop the dictation.
_OPEN_TIMEOUT_S = 1.0
_OPEN_RETRY_S = 0.02


def _load_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    return kernel32


def _load_clipboard_user32():
    """user32 with the clipboard entry points typed for 64-bit.

    Without explicit ``restype`` ctypes assumes ``int``, so ``GetClipboardData``
    — which returns a HANDLE — is truncated to 32 bits on x64 and the saved
    clipboard contents are read from a corrupt pointer.
    """
    user32 = _load_user32()
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    return user32


class _Clipboard:
    """``with`` wrapper around OpenClipboard/CloseClipboard, with retries."""

    def __init__(self, user32, timeout_s: float = _OPEN_TIMEOUT_S) -> None:
        self._user32 = user32
        self._timeout_s = timeout_s

    def __enter__(self):
        deadline = time.monotonic() + self._timeout_s
        while True:
            if self._user32.OpenClipboard(None):
                return self._user32
            if time.monotonic() >= deadline:
                err = ctypes.get_last_error()
                raise OSError(
                    f"OpenClipboard failed after {self._timeout_s:.1f}s "
                    f"(lastError={err}). Another application is holding the "
                    "clipboard open -- a clipboard manager is the usual cause."
                )
            time.sleep(_OPEN_RETRY_S)

    def __exit__(self, *exc) -> None:
        self._user32.CloseClipboard()
        return None


def _read_unicode_text(user32, kernel32) -> str | None:
    """Current CF_UNICODETEXT, or None when the clipboard holds something else.

    Returning None is not an error: it is the honest answer for an image or a
    file list, and the caller uses it to decide *not* to pretend it can restore
    what was there.
    """
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    handle = user32.GetClipboardData(CF_UNICODETEXT)
    if not handle:
        return None
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        return None
    try:
        return ctypes.wstring_at(ptr)
    finally:
        kernel32.GlobalUnlock(handle)


def _write_unicode_text(user32, kernel32, text: str) -> None:
    """Put *text* on the clipboard as CF_UNICODETEXT.

    The clipboard takes ownership of the HGLOBAL on a successful
    ``SetClipboardData``, so it must NOT be freed afterwards — freeing it is a
    use-after-free the next reader pays for. It is only freed on the failure
    path, where ownership never transferred.
    """
    encoded = text.encode("utf-16-le") + b"\x00\x00"
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
    if not handle:
        raise OSError(f"GlobalAlloc({len(encoded)}) failed (lastError={ctypes.get_last_error()})")
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        kernel32.GlobalFree(handle)
        raise OSError(f"GlobalLock failed (lastError={ctypes.get_last_error()})")
    try:
        ctypes.memmove(ptr, encoded, len(encoded))
    finally:
        kernel32.GlobalUnlock(handle)
    user32.EmptyClipboard()
    if not user32.SetClipboardData(CF_UNICODETEXT, handle):
        err = ctypes.get_last_error()
        kernel32.GlobalFree(handle)
        raise OSError(f"SetClipboardData failed (lastError={err})")


def _ctrl_v_events() -> list[tuple[int, int]]:
    """(vk, flags) pairs for Ctrl down, V down, V up, Ctrl up.

    Pure, so the ordering can be asserted without a Windows box. Getting it
    wrong is a stuck Ctrl, which is worse than a failed paste.
    """
    return [
        (VK_CONTROL, 0),
        (VK_V, 0),
        (VK_V, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    ]


class WindowsClipboardInjector:
    """InjectorBackend for Windows that pastes instead of typing.

    Only `inject` differs. Backspaces and key sequences already go out as real
    virtual keys in `WindowsInjector`, so they never met the VK_PACKET problem
    and are delegated rather than reimplemented.
    """

    def __init__(self) -> None:
        self._keys = WindowsInjector()

    # ------------------------------------------------------------------

    def inject(self, text: str) -> None:
        if not text:
            return
        user32 = _load_clipboard_user32()
        kernel32 = _load_kernel32()

        previous: str | None = None
        with _Clipboard(user32):
            previous = _read_unicode_text(user32, kernel32)
            _write_unicode_text(user32, kernel32, text)

        time.sleep(_SETTLE_S)
        self._send_ctrl_v(user32)

        if previous is None:
            # Nothing restorable was there (empty, or a non-text format we must
            # not claim to have preserved). Say so once at debug level rather
            # than silently leaving the dictation on the clipboard.
            log.debug("Clipboard held no text to restore; dictation remains on it.")
            return
        time.sleep(_PASTE_DRAIN_S)
        try:
            with _Clipboard(user32):
                _write_unicode_text(user32, kernel32, previous)
        except OSError:
            log.warning(
                "Could not restore the previous clipboard contents after pasting; "
                "the dictated text is still on the clipboard.", exc_info=True
            )

    def _send_ctrl_v(self, user32) -> None:
        events = _ctrl_v_events()
        inputs = (_INPUT * len(events))()
        for i, (vk, flags) in enumerate(events):
            inputs[i].type = INPUT_KEYBOARD
            inputs[i].ki = _KEYBDINPUT(
                wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=INJECTED_TAG
            )
        sent = user32.SendInput(len(inputs), inputs, ctypes.sizeof(_INPUT))
        if sent != len(inputs):
            err = ctypes.get_last_error()
            log.warning(
                "SendInput sent %d/%d Ctrl+V events (lastError=%d). Error 5 "
                "(ACCESS_DENIED) means the focused window runs elevated and UIPI "
                "blocks input from this process -- run YazSes as administrator.",
                sent, len(inputs), err,
            )

    # ------------------------------------------------------------------

    def inject_backspaces(self, count: int) -> None:
        self._keys.inject_backspaces(count)

    def inject_key_sequence(self, keys: list[str]) -> None:
        self._keys.inject_key_sequence(keys)
