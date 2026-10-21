"""The Windows click observer, on Linux, against a fake low-level mouse hook (#607).

`src/yazses/platform/windows/click_observer.py` is the Windows producer behind the
`ClickObserver` seam #397 landed. What is worth pinning here is the shape of the hook, not
Win32 itself:

* one button-down message becomes exactly one `ClickEvent`, carrying a monotonic timestamp
  and the hook's coordinates — and nothing else, because the value has no other field;
* wheel, move, button-up and X-button messages are not clicks and produce nothing;
* the hook procedure always returns what `CallNextHookEx` returned and never ``1``: this
  backend listens, it does not swallow the user's click;
* the hook procedure hands the click to a queue and returns **before** the callback runs,
  because `LowLevelHooksTimeout` (300 ms by default) silently unhooks a slow procedure;
* a failed `SetWindowsHookExW` is a `ClickObserverError` that names the Win32 error code
  and leaves no thread behind; start twice is a no-op; stop is idempotent and posts
  `WM_QUIT` once; a raising callback is contained and later clicks still arrive.

ctypes works on Linux, so the real `MSLLHOOKSTRUCT` is packed and read back here — the
sign of a negative coordinate (a monitor left of the primary) is genuinely exercised. What
no test here proves is that a hook was ever installed on a Windows desktop; see the
"### Windows" subsection of `design/specs/eye-implicit-calibration.md`.
"""
from __future__ import annotations

import ctypes
import threading
import time
from typing import Any

import pytest

from yazses.gaze.clicks import ClickEvent, ClickObserver, ClickObserverError
from yazses.platform.windows import click_observer as backend
from yazses.platform.windows.click_observer import (
    CLICK_MESSAGES,
    WH_MOUSE_LL,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MBUTTONDOWN,
    WM_MOUSEMOVE,
    WM_MOUSEWHEEL,
    WM_QUIT,
    WM_RBUTTONDOWN,
    WM_XBUTTONDOWN,
    WindowsClickObserver,
    point_of,
    to_canonical,
)

WAIT_S = 2.0


# --------------------------------------------------------------------------- #
# The fake: user32's hook surface, as the backend's `MouseHookApi` sees it
# --------------------------------------------------------------------------- #


class FakeHookApi:
    """Records every call the observer makes and lets a test fire a mouse message.

    `pump()` blocks the way `GetMessageW` does until `post_quit` arrives, so the hook
    thread's lifetime is real. `fire()` builds a real `MSLLHOOKSTRUCT` and calls the
    installed procedure with its address, exactly as Windows would.
    """

    CALL_NEXT_RESULT = 7  # anything that is neither 0 nor 1, so a pass-through is visible
    HOOK_HANDLE = 0xBEEF
    THREAD_ID = 4242

    def __init__(self, *, install_error: int | None = None) -> None:
        self.proc: Any = None
        self.installs = 0
        self.uninstalls: list[int] = []
        self.quit_posts: list[int] = []
        self.call_next: list[tuple[int, int, int]] = []
        self._quit = threading.Event()
        self._install_error = install_error

    # -- the MouseHookApi protocol ------------------------------------------
    def make_proc(self, callback: Any) -> Any:
        return callback

    def current_thread_id(self) -> int:
        return self.THREAD_ID

    def install(self, proc: Any) -> int:
        self.installs += 1
        if self._install_error is not None:
            return 0
        self.proc = proc
        return self.HOOK_HANDLE

    def last_error(self) -> int:
        return self._install_error or 0

    def call_next_hook(self, hook: int, n_code: int, w_param: int, l_param: int) -> int:
        self.call_next.append((hook, n_code, w_param))
        return self.CALL_NEXT_RESULT

    def pump(self) -> None:
        self._quit.wait(timeout=WAIT_S * 5)

    def post_quit(self, thread_id: int) -> None:
        self.quit_posts.append(thread_id)
        self._quit.set()

    def uninstall(self, hook: int) -> None:
        self.uninstalls.append(hook)

    # -- the test's hand -----------------------------------------------------
    def fire(self, message: int, x: int, y: int, *, n_code: int = 0) -> int:
        assert self.proc is not None, "no hook installed: nothing can fire"
        record = backend._MSLLHOOKSTRUCT()
        record.pt.x = x
        record.pt.y = y
        return int(self.proc(n_code, message, ctypes.addressof(record)))


class Collector:
    """A callback that counts, keeps, and can be told to wait or to raise."""

    def __init__(self) -> None:
        self.events: list[ClickEvent] = []
        self.arrived = threading.Semaphore(0)
        self.gate: threading.Event | None = None
        self.raise_first = False

    def __call__(self, event: ClickEvent) -> None:
        if self.gate is not None:
            self.gate.wait(timeout=WAIT_S)
        self.events.append(event)
        self.arrived.release()
        if self.raise_first:
            self.raise_first = False
            raise RuntimeError("the sink is unhappy")

    def wait(self, n: int = 1) -> None:
        for _ in range(n):
            assert self.arrived.acquire(timeout=WAIT_S), "no click was delivered in time"


def _observer_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith(backend.THREAD_NAME_PREFIX)]


@pytest.fixture
def started():
    api = FakeHookApi()
    observer = WindowsClickObserver(api=api)
    sink = Collector()
    observer.start(sink)
    yield api, observer, sink
    observer.stop()
    for _ in range(50):
        if not _observer_threads():
            break
        time.sleep(0.02)
    assert _observer_threads() == []


# --------------------------------------------------------------------------- #
# Constants and the struct
# --------------------------------------------------------------------------- #


def test_the_hook_type_and_messages_are_the_documented_win32_values() -> None:
    assert WH_MOUSE_LL == 14
    assert WM_QUIT == 0x0012
    assert CLICK_MESSAGES == frozenset({0x0201, 0x0204, 0x0207})
    assert (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN) == (0x0201, 0x0204, 0x0207)


def test_the_hook_struct_has_the_documented_field_order() -> None:
    """https://learn.microsoft.com/windows/win32/api/winuser/ns-winuser-msllhookstruct"""
    names = [name for name, _ in backend._MSLLHOOKSTRUCT._fields_]
    assert names == ["pt", "mouseData", "flags", "time", "dwExtraInfo"]
    assert [name for name, _ in backend._POINT._fields_] == ["x", "y"]


def test_point_of_reads_a_negative_coordinate_back_as_negative() -> None:
    record = backend._MSLLHOOKSTRUCT()
    record.pt.x = -1920
    record.pt.y = -7
    assert point_of(ctypes.addressof(record)) == (-1920, -7)


def test_to_canonical_keeps_the_hooks_units_and_sign_and_returns_floats() -> None:
    x, y = to_canonical(-1920, 1080)
    assert (x, y) == (-1920.0, 1080.0)
    assert isinstance(x, float) and isinstance(y, float)


# --------------------------------------------------------------------------- #
# Construction and the Linux refusal
# --------------------------------------------------------------------------- #


def test_the_backend_satisfies_the_observer_protocol() -> None:
    assert isinstance(WindowsClickObserver(api=FakeHookApi()), ClickObserver)


def test_constructing_the_observer_loads_no_user32(monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(*_: Any, **__: Any) -> Any:
        raise AssertionError("user32 was loaded at construction time")

    monkeypatch.setattr(backend, "_Win32MouseHookApi", _explode)
    WindowsClickObserver()  # no api injected, and still nothing touched


@pytest.mark.skipif(hasattr(ctypes, "WinDLL"), reason="on Windows user32 exists")
def test_starting_without_windows_is_a_click_observer_error_not_a_crash() -> None:
    observer = WindowsClickObserver()
    with pytest.raises(ClickObserverError, match="Windows"):
        observer.start(lambda _e: None)
    assert _observer_threads() == []


# --------------------------------------------------------------------------- #
# One click, one event
# --------------------------------------------------------------------------- #


def test_one_left_button_down_is_exactly_one_click_with_its_coordinates(started) -> None:
    api, _observer, sink = started
    t0 = time.monotonic()
    api.fire(WM_LBUTTONDOWN, 640, 480)
    sink.wait()
    t1 = time.monotonic()
    assert len(sink.events) == 1
    event = sink.events[0]
    assert (event.x, event.y) == (640.0, 480.0)
    assert t0 <= event.timestamp_s <= t1, "the timestamp is not a monotonic reading"


def test_a_click_left_of_the_primary_monitor_keeps_its_negative_x(started) -> None:
    api, _observer, sink = started
    api.fire(WM_RBUTTONDOWN, -800, 12)
    sink.wait()
    assert (sink.events[0].x, sink.events[0].y) == (-800.0, 12.0)


def test_right_and_middle_count_but_the_event_does_not_say_which(started) -> None:
    api, _observer, sink = started
    api.fire(WM_RBUTTONDOWN, 1, 1)
    api.fire(WM_MBUTTONDOWN, 2, 2)
    sink.wait(2)
    assert [(e.x, e.y) for e in sink.events] == [(1.0, 1.0), (2.0, 2.0)]
    # The dataclass is the privacy boundary: there is no field a button id could live in.
    assert set(sink.events[0].__dataclass_fields__) == {"timestamp_s", "x", "y"}


@pytest.mark.parametrize(
    "message",
    [WM_MOUSEMOVE, WM_MOUSEWHEEL, WM_XBUTTONDOWN, WM_LBUTTONUP, 0x020A + 2, 0x0203],
    ids=["move", "wheel", "xbutton", "lbuttonup", "hwheel", "dblclk"],
)
def test_anything_but_a_button_down_produces_no_click(started, message: int) -> None:
    api, _observer, sink = started
    api.fire(message, 10, 10)
    api.fire(WM_LBUTTONDOWN, 20, 20)  # a marker: whatever arrives, arrives after the ignored one
    sink.wait()
    time.sleep(0.05)
    assert [(e.x, e.y) for e in sink.events] == [(20.0, 20.0)]


# --------------------------------------------------------------------------- #
# The hook procedure never swallows and never blocks
# --------------------------------------------------------------------------- #


def test_the_hook_proc_returns_call_next_hook_ex_for_clicks_and_non_clicks_alike(started) -> None:
    api, _observer, sink = started
    assert api.fire(WM_LBUTTONDOWN, 5, 5) == FakeHookApi.CALL_NEXT_RESULT
    assert api.fire(WM_MOUSEMOVE, 6, 6) == FakeHookApi.CALL_NEXT_RESULT
    sink.wait()
    assert api.call_next == [
        (FakeHookApi.HOOK_HANDLE, 0, WM_LBUTTONDOWN),
        (FakeHookApi.HOOK_HANDLE, 0, WM_MOUSEMOVE),
    ]
    assert 1 not in {FakeHookApi.CALL_NEXT_RESULT}  # the sentinel itself is not the swallow value


def test_a_negative_n_code_is_passed_on_untouched_and_not_counted(started) -> None:
    api, _observer, sink = started
    assert api.fire(WM_LBUTTONDOWN, 5, 5, n_code=-1) == FakeHookApi.CALL_NEXT_RESULT
    api.fire(WM_LBUTTONDOWN, 9, 9)
    sink.wait()
    time.sleep(0.05)
    assert [(e.x, e.y) for e in sink.events] == [(9.0, 9.0)]


def test_the_hook_proc_returns_before_the_callback_runs(started) -> None:
    """LowLevelHooksTimeout: a hook that waits on the consumer is a hook Windows removes."""
    api, _observer, sink = started
    sink.gate = threading.Event()
    deadline = time.monotonic() + WAIT_S
    rv = api.fire(WM_LBUTTONDOWN, 3, 4)
    assert time.monotonic() < deadline, "fire() blocked on the callback"
    assert rv == FakeHookApi.CALL_NEXT_RESULT
    assert sink.events == []  # the callback is still gated: nothing ran inside the hook
    sink.gate.set()
    sink.wait()
    assert (sink.events[0].x, sink.events[0].y) == (3.0, 4.0)


def test_a_raising_callback_is_contained_and_the_next_click_still_arrives(started, caplog) -> None:
    api, _observer, sink = started
    sink.raise_first = True
    with caplog.at_level("ERROR", logger=backend.__name__):
        api.fire(WM_LBUTTONDOWN, 1, 2)
        api.fire(WM_LBUTTONDOWN, 3, 4)
        sink.wait(2)
    assert [(e.x, e.y) for e in sink.events] == [(1.0, 2.0), (3.0, 4.0)]
    assert any("callback" in r.getMessage().lower() for r in caplog.records)
    assert _observer_threads() != [], "the observer gave up after one bad callback"


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


def test_start_installs_the_hook_on_its_own_thread_and_pins_the_proc(started) -> None:
    api, observer, _sink = started
    assert api.installs == 1
    assert observer._hook_proc is not None, "the C callback has no strong reference"
    names = _observer_threads()
    assert any("hook" in n for n in names) and any("deliver" in n for n in names)


def test_starting_twice_installs_once(started) -> None:
    api, observer, sink = started
    observer.start(sink)
    assert api.installs == 1
    assert api.quit_posts == []


def test_stop_posts_wm_quit_to_the_hook_thread_unhooks_and_is_idempotent() -> None:
    api = FakeHookApi()
    observer = WindowsClickObserver(api=api)
    observer.start(lambda _e: None)
    observer.stop()
    observer.stop()
    assert api.quit_posts == [FakeHookApi.THREAD_ID]
    assert api.uninstalls == [FakeHookApi.HOOK_HANDLE]
    assert _observer_threads() == []


def test_stop_before_start_does_nothing_and_never_raises() -> None:
    api = FakeHookApi()
    observer = WindowsClickObserver(api=api)
    observer.stop()
    assert api.quit_posts == [] and api.uninstalls == []


def test_stop_survives_a_failing_post_quit(caplog) -> None:
    class _Grumpy(FakeHookApi):
        def post_quit(self, thread_id: int) -> None:
            self._quit.set()  # let the fake pump end so no thread leaks
            raise OSError("PostThreadMessageW refused")

    api = _Grumpy()
    observer = WindowsClickObserver(api=api, join_timeout_s=0.5)
    observer.start(lambda _e: None)
    with caplog.at_level("ERROR", logger=backend.__name__):
        observer.stop()  # must not raise
    assert _observer_threads() == []


def test_a_click_after_stop_is_dropped_not_delivered() -> None:
    api = FakeHookApi()
    observer = WindowsClickObserver(api=api)
    sink = Collector()
    observer.start(sink)
    observer.stop()
    api.fire(WM_LBUTTONDOWN, 1, 1)  # Windows cannot do this after UnhookWindowsHookEx; a fake can
    time.sleep(0.05)
    assert sink.events == []


def test_restart_after_stop_installs_a_fresh_hook() -> None:
    api = FakeHookApi()
    observer = WindowsClickObserver(api=api)
    sink = Collector()
    observer.start(sink)
    observer.stop()
    api._quit.clear()
    observer.start(sink)
    api.fire(WM_LBUTTONDOWN, 7, 7)
    sink.wait()
    observer.stop()
    assert api.installs == 2
    assert [(e.x, e.y) for e in sink.events] == [(7.0, 7.0)]


# --------------------------------------------------------------------------- #
# Failure to install
# --------------------------------------------------------------------------- #


def test_a_failed_set_windows_hook_ex_names_the_error_code_and_leaves_no_thread() -> None:
    api = FakeHookApi(install_error=5)  # ERROR_ACCESS_DENIED
    observer = WindowsClickObserver(api=api)
    with pytest.raises(ClickObserverError) as excinfo:
        observer.start(lambda _e: None)
    message = str(excinfo.value)
    assert "SetWindowsHookEx" in message and "5" in message
    assert api.uninstalls == []  # nothing to unhook
    for _ in range(50):
        if not _observer_threads():
            break
        time.sleep(0.02)
    assert _observer_threads() == []
    # And the observer is reusable: a later start tries again rather than remembering failure.
    api._install_error = None
    observer.start(lambda _e: None)
    assert api.installs == 2
    observer.stop()


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_the_windows_platform_exposes_the_factory_and_builds_a_dormant_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`build_platform()` must not start anything: the daemon starts the observer only when
    `[gaze_refine] enabled = true` (daemon.py / refine_runtime.py)."""
    from yazses.platform import windows as win

    monkeypatch.setattr(backend, "_Win32MouseHookApi", lambda: pytest.fail("user32 loaded"))
    platform = win.build_platform()
    assert platform.click_observer_factory is not None
    observer = platform.click_observer_factory()
    assert isinstance(observer, WindowsClickObserver)
    assert isinstance(observer, ClickObserver)
    assert _observer_threads() == []

