"""Windows add-on pack runtime (ADR-028 §2). Importable on any OS: every Win32 call is
inside a method.

Deliberately light: the PyInstaller runtime hook imports this before ``main`` runs, in
every YazSes process, so it pulls in nothing beyond ``os``, ``sys`` and ``pathlib`` until
a method is called.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from yazses.platform.base import PACK_INDEX_NAME

#: The console binary the spec builds beside ``YazSesApp.exe`` (packaging/windows/yazses.spec).
_CLI_EXE = "yazses-cli.exe"


class WindowsPackRuntime:
    def supported(self) -> bool:
        return True

    def is_elevated(self) -> bool:
        """Token elevation, read by the same probe ``doctor`` uses. ``None`` (could not
        tell) counts as elevated: the safe answer is "do not load user-writable code"."""
        from yazses.platform.windows.permissions import is_elevated

        try:
            answer = is_elevated()
        except Exception:  # noqa: BLE001 - an unanswerable question fails closed
            return True
        return True if answer is None else bool(answer)

    def add_native_dir(self, path: Path) -> object:
        add = getattr(os, "add_dll_directory", None)
        if add is None:
            raise OSError("os.add_dll_directory is not available in this Python")
        return add(str(path))

    def embedded_index_path(self) -> Path | None:
        base = getattr(sys, "_MEIPASS", None)
        if not getattr(sys, "frozen", False) or not base:
            return None
        return Path(base) / PACK_INDEX_NAME

    def probe_command(self, name: str, staged: Path) -> list[str] | None:
        tail = ["--cli", "packs", "probe", name, "--staged", str(staged)]
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable).with_name(_CLI_EXE)
            return [str(exe), *tail]
        return [sys.executable, "-m", "yazses", *tail]

    # -- ADR-028 M1: bind a pack to the base's own copy of a shared DLL ----------------

    def base_native_candidates(self, name: str) -> list[Path]:
        """Every file named ``name`` under the frozen bundle's ``_internal`` folder
        (``sys._MEIPASS``), and nowhere else. Walks the folder: called once, on a binding
        pack's first use, never at start-up."""
        root = getattr(sys, "_MEIPASS", None)
        if not getattr(sys, "frozen", False) or not root:
            return []
        want = name.casefold()
        found: list[Path] = []
        for dirpath, _dirs, files in os.walk(root):
            found.extend(Path(dirpath) / f for f in files if f.casefold() == want)
        return sorted(found)

    def load_base_native(self, path: Path) -> tuple[object, str | None]:
        """``LoadLibraryExW`` on the absolute path (``ctypes.WinDLL``; for a path with a
        separator CPython passes ``LOAD_LIBRARY_SEARCH_DEFAULT_DIRS |
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR``), so the loader opens that file and never
        searches for the name. CPython's ctypes never unloads a library."""
        if not path.is_absolute():
            raise OSError(f"refusing to load {path}: not an absolute path")
        import ctypes

        win_dll = getattr(ctypes, "WinDLL", None)
        if win_dll is None:
            raise OSError("ctypes.WinDLL is not available in this Python")
        lib = win_dll(str(path))
        return lib, ort_version(lib)

    def loaded_native_paths(self, name: str) -> list[Path] | None:
        """Every module of this process whose file is named ``name``, from
        ``K32EnumProcessModules`` + ``GetModuleFileNameW`` (the spike's check (d)).
        ``None`` when the list cannot be read."""
        try:
            return [p for p in _loaded_modules() if p.name.casefold() == name.casefold()]
        except Exception:  # noqa: BLE001 - "cannot tell" is an answer; the caller refuses
            return None


def ort_version(lib: Any) -> str | None:
    """ONNX Runtime's own version string, through its stable C entry point
    ``OrtGetApiBase()->GetVersionString()`` (``onnxruntime_c_api.h``: ``OrtApiBase`` is
    ``{GetApi, GetVersionString}``). ``None`` for a library without that export, or when
    the call fails. x64 only, where there is one calling convention."""
    import ctypes

    try:
        fn: Any = lib.OrtGetApiBase
    except AttributeError:
        return None
    try:
        class _OrtApiBase(ctypes.Structure):
            _fields_ = [
                ("GetApi", ctypes.c_void_p),
                ("GetVersionString", ctypes.CFUNCTYPE(ctypes.c_char_p)),
            ]

        fn.restype = ctypes.POINTER(_OrtApiBase)
        fn.argtypes = []
        base = fn()
        if not base:
            return None
        get_version = base.contents.GetVersionString
        if not get_version:
            return None
        raw = get_version()
        return raw.decode("ascii", "replace") if raw else None
    except Exception:  # noqa: BLE001 - an unreadable version is "unknown", not a crash
        return None


def _loaded_modules() -> list[Path]:
    import ctypes
    from ctypes import wintypes

    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        raise OSError("not Windows")
    k32 = win_dll("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32EnumProcessModules.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    k32.K32EnumProcessModules.restype = wintypes.BOOL
    k32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    k32.GetModuleFileNameW.restype = wintypes.DWORD
    size = 1024
    while True:
        arr = (wintypes.HMODULE * size)()
        needed = wintypes.DWORD()
        if not k32.K32EnumProcessModules(k32.GetCurrentProcess(), arr, ctypes.sizeof(arr),
                                         ctypes.byref(needed)):
            raise OSError("K32EnumProcessModules failed")
        count = needed.value // ctypes.sizeof(wintypes.HMODULE)
        if count <= size:
            break
        size = count + 64  # modules were loaded meanwhile; ask again with room
    buf = ctypes.create_unicode_buffer(32768)
    out: list[Path] = []
    for i in range(count):
        n = k32.GetModuleFileNameW(arr[i], buf, len(buf))
        if n:
            out.append(Path(buf.value))
    return out
