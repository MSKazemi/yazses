"""X11 XGrabKey global hotkey backend.

Works under strict snap confinement (x11 interface) without needing
/dev/input access. X11-only — does not work on pure Wayland sessions.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

_KEY_SYM_MAP: dict[str, str] = {
    "space": "space",
    "right_ctrl": "Control_R",
    "left_ctrl": "Control_L",
    "right_alt": "Alt_R",
    "left_alt": "Alt_L",
    "right_meta": "Super_R",
    "left_meta": "Super_L",
    "right_shift": "Shift_R",
    "left_shift": "Shift_L",
    "right_option": "Alt_R",
    "left_option": "Alt_L",
}

_CHARACTER_KEYS: frozenset[str] = frozenset({"space"})


class X11GrabHotkey:
    """Global hotkey via XGrabKey — works inside strict snap under x11 interface."""

    def __init__(
        self,
        key_id: str,
        threshold_ms: int,
        on_hold_start: Callable[[int], None],
        on_hold_end: Callable[[], None],
    ) -> None:
        name = key_id.lower()
        if name == "auto":
            name = "right_alt"
        if name not in _KEY_SYM_MAP:
            raise ValueError(
                f"Unknown hotkey {key_id!r}. Supported: {sorted(_KEY_SYM_MAP)} or 'auto'."
            )
        self._key_id = name
        self._key_sym_str = _KEY_SYM_MAP[name]
        self._produces_char = name in _CHARACTER_KEYS
        self._threshold_ms = threshold_ms
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._stop_event = threading.Event()
        self._timer: threading.Timer | None = None
        self._press_time: float | None = None
        self._recording = False
        self._leaked_count = 0
        # ``_fire_hold_start`` runs on a threading.Timer thread and ``_handle_release``
        # on the X listener thread. One lock serialises them -- including the user
        # callbacks -- so a release that arrives while ``on_hold_start`` is still
        # opening the microphone waits for it and then runs ``on_hold_end`` on a
        # recorder that is really recording, instead of racing it. ``_press_gen``
        # identifies the press a Timer belongs to, so one that fires after its press
        # was released (``Timer.cancel`` cannot stop a callback already running) is
        # recognised as stale and does nothing.
        self._lock = threading.Lock()
        self._press_gen = 0

    # ── public interface ──────────────────────────────────────────────────────

    def run(self) -> None:
        from Xlib import XK, X
        from Xlib import display as xdisplay

        d = xdisplay.Display()
        root = d.screen().root
        keysym = XK.string_to_keysym(self._key_sym_str)
        keycode = d.keysym_to_keycode(keysym)
        root.grab_key(keycode, X.AnyModifier, True, X.GrabModeAsync, X.GrabModeAsync)
        root.change_attributes(event_mask=X.KeyPressMask | X.KeyReleaseMask)
        d.flush()
        log.info("X11GrabHotkey: listening on key=%s keycode=%d", self._key_sym_str, keycode)

        try:
            while not self._stop_event.is_set():
                if d.pending_events():
                    event = d.next_event()
                    if event.type == X.KeyPress and event.detail == keycode:
                        self._handle_press()
                    elif event.type == X.KeyRelease and event.detail == keycode:
                        # Detect X11 auto-repeat: KeyRelease immediately followed
                        # by KeyPress for the same key — ignore both.
                        if d.pending_events():
                            next_ev = d.next_event()
                            if next_ev.type == X.KeyPress and next_ev.detail == keycode:
                                continue  # auto-repeat, skip
                            self._handle_release()
                            if next_ev.type == X.KeyPress:
                                self._handle_press()
                        else:
                            self._handle_release()
                else:
                    self._stop_event.wait(timeout=0.01)
        finally:
            self._cancel_timer()
            try:
                root.ungrab_key(keycode, X.AnyModifier)
                d.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._cancel_timer()
        self._stop_event.set()

    @property
    def key_id(self) -> str:
        return self._key_id

    # ── internal ──────────────────────────────────────────────────────────────

    def _acquire(self) -> bool:
        """Take ``_lock``, but give up once ``stop()`` has been called.

        The lock is held across the user callbacks, so while ``on_hold_start`` is
        opening the microphone a plain ``with self._lock`` would park the listener
        thread in ``_handle_release`` with no way out: ``run()`` would never see
        ``_stop_event`` and the daemon could not be stopped. Waiting in short slices
        and re-checking the event keeps shutdown reachable.
        """
        while not self._lock.acquire(timeout=0.05):
            if self._stop_event.is_set():
                return False
        return True

    def _handle_press(self) -> None:
        if not self._acquire():
            return
        try:
            if self._press_time is not None:
                return  # already tracking a press
            self._press_time = time.monotonic()
            self._press_gen += 1
            if self._produces_char:
                self._leaked_count += 1
            delay = self._threshold_ms / 1000.0
            self._timer = threading.Timer(delay, self._fire_hold_start, args=(self._press_gen,))
            self._timer.start()
        finally:
            self._lock.release()

    def _handle_release(self) -> None:
        if not self._acquire():
            return
        try:
            self._cancel_timer()
            was = self._recording
            self._recording = False
            self._press_time = None
            self._leaked_count = 0
            if was:
                self._on_hold_end()
        finally:
            self._lock.release()

    def _fire_hold_start(self, press_gen: int | None = None) -> None:
        if not self._acquire():
            return
        try:
            if press_gen is not None and press_gen != self._press_gen:
                return  # a stale Timer: its press was already released
            if self._press_time is not None and not self._recording:
                self._recording = True
                self._on_hold_start(self._leaked_count if self._produces_char else 0)
        finally:
            self._lock.release()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
