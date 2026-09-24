"""What the focused Windows control is — the evidence a garbled paste needs.

`SendInput` reports success whatever the target does with the keystroke, so when
dictated text arrives as rows of ``?`` or ``-`` there is nothing in a log to
read. Microsoft documents exactly two properties of the receiving window that
decide whether ``KEYEVENTF_UNICODE`` survives the trip, and both are readable
from outside the process:

* ``IsWindowUnicode`` — an ANSI window gets the character converted to the
  active ANSI codepage (``KEYBDINPUT`` Remarks), so anything the codepage cannot
  represent lands as ``?``.
* the thread's keyboard layout / IME — ``KEYEVENTF_UNICODE`` synthesises a
  *VK_PACKET* keystroke, and a text service that does not unpack it with
  ``ToUnicode(VK_PACKET, ...)`` runs it through the layout instead, so every
  character comes out as the same wrong one.

This module reads them and nothing else. It never injects; `cli.inject
--diagnose` prints it immediately before injecting so the report and the result
describe the same window.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

#: Primary language identifiers worth naming. Anything else is reported as the
#: raw hex, which is still actionable -- the point is to show *whether* the
#: layout is what the user thinks it is, not to own a table of every locale.
_LANGS: dict[int, str] = {
    0x0409: "en-US", 0x0809: "en-GB", 0x0410: "it-IT", 0x0407: "de-DE",
    0x040C: "fr-FR", 0x0C0A: "es-ES", 0x0429: "fa-IR (Persian)",
    0x0401: "ar-SA", 0x0419: "ru-RU", 0x0804: "zh-CN", 0x0411: "ja-JP",
    0x0412: "ko-KR", 0x041F: "tr-TR", 0x040D: "he-IL", 0x0439: "hi-IN",
}


@dataclass(frozen=True)
class FocusReport:
    """The foreground window, and the control inside it that gets the keys."""

    hwnd: int
    title: str
    window_class: str
    #: The control with keyboard focus. Equal to `hwnd` for a window that has no
    #: child control (a UWP/WinUI text box typically reports the top-level).
    focus_hwnd: int
    focus_class: str
    #: `IsWindowUnicode` on the focused control. None when it could not be read.
    focus_is_unicode: bool | None
    #: HKL of the foreground thread, and the primary language it encodes.
    keyboard_layout: int
    language: str

    @property
    def ansi_window(self) -> bool:
        return self.focus_is_unicode is False

    def lines(self) -> list[str]:
        """Human-readable report plus the verdict each field supports."""
        out = [
            f"  Foreground window : {self.title!r}  (class {self.window_class})",
            f"  Focused control   : class {self.focus_class} (hwnd 0x{self.focus_hwnd:X})",
            f"  Unicode window    : {_tri(self.focus_is_unicode)}",
            f"  Keyboard layout   : 0x{self.keyboard_layout:08X}  ({self.language})",
        ]
        if self.ansi_window:
            out.append(
                "  -> ANSI window. Windows converts each injected character to the "
                "active ANSI codepage and substitutes '?' for anything it cannot "
                "represent. Set [injection] backend = \"clipboard\"."
            )
        elif self.focus_is_unicode is None:
            out.append("  -> Could not read the focused control; no verdict.")
        else:
            out.append(
                "  -> A Unicode window, so ANSI conversion is not the cause. If the "
                "text still arrives wrong, the app's text service is not unpacking "
                "the VK_PACKET keystroke; set [injection] backend = \"clipboard\"."
            )
        return out


def _tri(value: bool | None) -> str:
    return "unknown" if value is None else ("yes" if value else "no (ANSI)")


def language_name(hkl: int) -> str:
    """Primary language of an HKL. The low word is the language identifier."""
    langid = hkl & 0xFFFF
    return _LANGS.get(langid, f"langid 0x{langid:04X}")


def available() -> bool:
    return sys.platform == "win32"


def read_focus() -> FocusReport | None:
    """Snapshot the focused control, or None when it cannot be determined."""
    if not available():  # pragma: no cover - guarded by `available()` at call sites
        return None

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowUnicode.restype = wintypes.BOOL
    user32.IsWindowUnicode.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetKeyboardLayout.restype = ctypes.c_void_p
    user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]

    class _GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        ]

    user32.GetGUIThreadInfo.restype = wintypes.BOOL
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUITHREADINFO)]

    def _text(fn, hwnd: int, size: int = 512) -> str:
        buf = ctypes.create_unicode_buffer(size)
        fn(hwnd, buf, size)
        return buf.value

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    thread_id = user32.GetWindowThreadProcessId(hwnd, None)

    focus_hwnd = hwnd
    info = _GUITHREADINFO()
    info.cbSize = ctypes.sizeof(_GUITHREADINFO)
    # Best-effort: GetGUIThreadInfo fails across an integrity boundary (an
    # elevated target), and a UWP host legitimately reports no child focus. The
    # top-level window is the right answer in both cases, not an error.
    if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndFocus:
        focus_hwnd = info.hwndFocus

    hkl = int(user32.GetKeyboardLayout(thread_id) or 0)
    return FocusReport(
        hwnd=int(hwnd),
        title=_text(user32.GetWindowTextW, hwnd),
        window_class=_text(user32.GetClassNameW, hwnd, 256),
        focus_hwnd=int(focus_hwnd),
        focus_class=_text(user32.GetClassNameW, focus_hwnd, 256),
        focus_is_unicode=bool(user32.IsWindowUnicode(focus_hwnd)),
        keyboard_layout=hkl,
        language=language_name(hkl),
    )
