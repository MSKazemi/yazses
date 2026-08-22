"""The half of the #182 fix that only a real Mac can answer. **Skipped off macOS.**

Everything in `test_macos_input_monitoring.py` substitutes IOKit, so it proves the
mapping and the wiring and says nothing about whether the binding *works*. That is
the assumption most likely to be wrong, and its failure mode is silent: if IOKit
never loads, `check_input_monitoring` answers UNKNOWN forever, `doctor` renders a
WARN with advice attached, and it looks exactly like "the user has not been asked
yet". The fix for #182 would appear to be shipped and do nothing at all.

The specific hazard is that since macOS 11 system frameworks are not files on
disk — they live in the dyld shared cache — so anything that stats a path before
loading it reports IOKit as missing on a Mac that has it.

These tests therefore call the real thing on the real OS. On GitHub's macOS
runners nothing has granted Input Monitoring, so the *value* is expected to be
"not granted"; what is being proved is that we can ask at all and get an answer
inside the documented enum, rather than `None`, an exception, or garbage.

⚠ What this still cannot prove: that granting the permission makes the hotkey
work. That needs a human at a Mac with a GUI session, which is #182.
"""

from __future__ import annotations

import sys

import pytest

from yazses.platform.base import PermissionState
from yazses.platform.macos import permissions as perms_mod
from yazses.platform.macos.permissions import MacosPermissions

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="exercises the real macOS IOKit binding"
)


def test_iokit_actually_loads_on_this_mac() -> None:
    """The load itself, before any call. This is the silent-failure gate."""
    lib = perms_mod._iokit()
    assert lib is not None, (
        "IOKit did not load on a real Mac. Input Monitoring would report UNKNOWN "
        "forever and the #182 fix would be inert. Check `_IOKIT_FRAMEWORK` and the "
        "`find_library` fallback in platform/macos/permissions.py."
    )


def test_the_constant_framework_path_is_the_one_that_works() -> None:
    """Pin *why* it loads.

    If this ever fails while `test_iokit_actually_loads_on_this_mac` passes, the
    constant has gone stale and the code is silently living on the `find_library`
    fallback -- the path that `NotImplementedError` inside `dyld_find` can take
    away without warning.
    """
    import ctypes

    ctypes.CDLL(perms_mod._IOKIT_FRAMEWORK)  # raises OSError if the path is wrong


def test_iohidcheckaccess_is_present_and_callable() -> None:
    """The symbol, not just the framework. `IOHIDCheckAccess` is macOS 10.15+."""
    lib = perms_mod._iokit()
    assert lib is not None
    assert hasattr(lib, "IOHIDCheckAccess"), (
        "IOKit loaded but IOHIDCheckAccess is missing — the whole check degrades "
        "to UNKNOWN"
    )


def test_the_real_call_returns_a_value_inside_the_documented_enum() -> None:
    """Guards against a wrong `restype`/`argtypes`, which would return garbage
    that happens to compare equal to a valid state some of the time."""
    import ctypes

    lib = perms_mod._iokit()
    assert lib is not None
    fn = lib.IOHIDCheckAccess
    fn.restype = ctypes.c_uint32
    fn.argtypes = [ctypes.c_uint32]
    status = int(fn(perms_mod._HID_REQUEST_LISTEN_EVENT))
    assert status in {
        perms_mod._HID_ACCESS_GRANTED,
        perms_mod._HID_ACCESS_DENIED,
        perms_mod._HID_ACCESS_UNKNOWN,
    }, f"IOHIDCheckAccess returned {status}, which is not an IOHIDAccessType"


def test_check_input_monitoring_answers_without_raising() -> None:
    """End to end through the public method, on the real OS."""
    state = MacosPermissions().check_input_monitoring()
    assert isinstance(state, PermissionState)
    assert state in {
        PermissionState.OK,
        PermissionState.DENIED,
        PermissionState.UNKNOWN,
    }


def test_the_doctor_row_appears_on_a_real_mac() -> None:
    """The row is gated on `Platform.name`, and a comparison against a string no
    backend produces is how the Windows elevation row stayed invisible for
    releases (`tests/test_doctor_platform_names.py`). Prove it renders here."""
    from yazses.platform import get_platform
    from yazses.system.doctor import _input_monitoring_check

    # `get_platform()`, the same call `doctor` makes. The bug here was the *name*:
    # this asked `platform.factory` for `build_platform`, which does not exist
    # anywhere in that module -- factory imports a per-OS builder inside each
    # branch. `get_platform` itself is importable from either `yazses.platform` or
    # `yazses.platform.factory`; they are the same object. The package is used here
    # because it is the seam `doctor` imports from, not because the other fails.
    platform = get_platform()
    row = _input_monitoring_check(platform.permissions, platform.name)
    assert row is not None, "the Input monitoring row is missing on macOS itself"
    name, status, _detail = row
    assert name == "Input monitoring"
    assert status in {"OK", "WARN", "FAIL"}


def test_the_accessibility_check_still_answers_too() -> None:
    """The row this was added next to. A regression here would trade one broken
    permission for another."""
    assert isinstance(MacosPermissions().check_keyboard_capture(), PermissionState)
