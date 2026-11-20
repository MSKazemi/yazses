"""Toggle dictation must register a quick tap of a modifier key on every backend (#869).

The hold threshold exists to tell a held dictation key from a tap that must type: only
keys that also type a character (``space``) need it. The X11 key-grab and macOS backends
used to wait it out for modifiers too, so in ``[hotkey] mode = "toggle"`` every press had
to last ``hold_threshold_ms`` -- the very hold toggle mode is meant to remove. A modifier
now starts on key-down everywhere; ``space`` keeps the guard (a tap still types a space)
and ``doctor`` plus the daemon log say so.

Fakes only: no X server, no Quartz, no Win32 hook and no evdev device is opened. The
backends' press/release handlers are driven directly, with the real daemon toggle
handlers (and stand-in hold handlers) on the other end.
"""
from __future__ import annotations

import logging
import threading
import time

import pytest

from yazses.config import Config, load_config
from yazses.hotkeys.toggle import CHARACTER_KEYS, toggle_key_note
from yazses.platform.base import TrayState

#: Far longer than any test waits, so a start can only come from key-down itself.
_LONG_MS = 10_000


# --- the pure note ---------------------------------------------------------------------


def test_no_note_in_hold_mode():
    assert toggle_key_note("hold", "space", 500) is None


@pytest.mark.parametrize("key", ["right_ctrl", "right_alt", "right_option", "left_meta"])
def test_no_note_for_a_key_that_types_nothing(key):
    assert toggle_key_note("toggle", key, 500) is None


@pytest.mark.parametrize("key", ["space", "Space", " space "])
def test_space_in_toggle_mode_names_the_threshold_and_a_better_key(key):
    note = toggle_key_note("toggle", key, 650)
    assert note is not None
    assert "650 ms" in note
    assert "right_ctrl" in note


def test_every_backend_agrees_which_keys_type():
    from yazses.platform.linux import hotkey_xgrab
    from yazses.platform.macos import hotkey as mac
    from yazses.platform.windows import hotkey as win

    for module in (hotkey_xgrab, mac, win):
        assert module._CHARACTER_KEYS == CHARACTER_KEYS, module.__name__


def test_evdev_backend_agrees_which_keys_type():
    pytest.importorskip("evdev", reason="evdev is a Linux-only dependency")
    from yazses.platform.linux import hotkey as lin

    assert lin._CHARACTER_KEYS == CHARACTER_KEYS


# --- doctor and the daemon log ---------------------------------------------------------


def _cfg(mode: str, key: str) -> Config:
    cfg = load_config(None)
    cfg.hotkey.mode = mode
    cfg.hotkey.key = key
    cfg.hotkey.hold_threshold_ms = 500
    return cfg


def test_doctor_warns_for_toggle_on_space():
    from yazses.system import doctor

    row = doctor._toggle_key_check(_cfg("toggle", "space"), "right_alt")
    assert row is not None
    name, status, detail = row
    assert status == "WARN"
    assert "500 ms" in detail and "right_ctrl" in detail


@pytest.mark.parametrize("mode,key", [("toggle", "right_ctrl"), ("toggle", "auto"),
                                      ("hold", "space")])
def test_doctor_is_silent_where_a_tap_works_or_hold_is_on(mode, key):
    from yazses.system import doctor

    assert doctor._toggle_key_check(_cfg(mode, key), "right_alt") is None


def test_doctor_summary_carries_the_row(tmp_path):
    from yazses.system import doctor

    checks = doctor._config_summary(_cfg("toggle", "space"), tmp_path / "config.toml")
    assert any(n == "Hotkey mode" and s == "WARN" for n, s, _ in checks)


def _daemon(cfg: Config):
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    return Daemon(config=cfg, platform=get_platform())


def test_daemon_logs_the_limitation_for_toggle_on_space(caplog):
    cfg = _cfg("toggle", "space")
    with caplog.at_level(logging.WARNING):
        assert _daemon(cfg)._build_toggle(cfg) is not None
    assert "hold_threshold_ms (500 ms)" in caplog.text


def test_daemon_says_nothing_for_toggle_on_a_modifier(caplog):
    cfg = _cfg("toggle", "right_ctrl")
    with caplog.at_level(logging.WARNING):
        _daemon(cfg)._build_toggle(cfg)
    assert "hold_threshold_ms" not in caplog.text


# --- each backend, wired to the real daemon toggle handlers ----------------------------


class _Wired:
    """A daemon in toggle mode whose hold handlers only record and move the state."""

    def __init__(self, monkeypatch) -> None:
        cfg = _cfg("toggle", "right_ctrl")
        self.daemon = d = _daemon(cfg)
        d._toggle = d._build_toggle(cfg)
        d._state.state = TrayState.IDLE
        self.log: list[str] = []
        self.started = threading.Event()
        self.ended = threading.Event()

        def start(leaked: int) -> None:
            self.log.append(f"start:{leaked}")
            d._hold_start_failed = False
            d._state.state = TrayState.RECORDING
            self.started.set()

        def end() -> None:
            self.log.append("end")
            d._state.state = TrayState.IDLE
            self.ended.set()

        monkeypatch.setattr(d, "_on_hold_start", start)
        monkeypatch.setattr(d, "_on_hold_end", end)

    @property
    def on_down(self):
        return self.daemon._on_toggle_press

    @property
    def on_up(self):
        return self.daemon._on_toggle_release


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


# X11 key grab (snap, BSD) -------------------------------------------------------------


def _xgrab(key_id, threshold_ms, on_down, on_up):
    from yazses.platform.linux.hotkey_xgrab import X11GrabHotkey

    return X11GrabHotkey(key_id=key_id, threshold_ms=threshold_ms,
                         on_hold_start=on_down, on_hold_end=on_up)


def test_xgrab_two_quick_taps_of_a_modifier_start_then_stop(monkeypatch):
    w = _Wired(monkeypatch)
    hk = _xgrab("right_ctrl", _LONG_MS, w.on_down, w.on_up)
    hk._handle_press()
    hk._handle_release()
    assert w.log == ["start:0"]
    assert w.daemon._state.state == TrayState.RECORDING
    hk._handle_press()
    hk._handle_release()
    assert w.log == ["start:0", "end"]


def test_xgrab_modifier_starts_on_key_down_in_hold_mode_too():
    starts: list[int] = []
    ends: list[int] = []
    hk = _xgrab("right_alt", _LONG_MS, starts.append, lambda: ends.append(1))
    hk._handle_press()
    assert _wait_for(lambda: starts == [0])  # the zero-delay Timer, not the 10 s threshold
    hk._handle_press()  # a second key-down with no key-up starts nothing more
    time.sleep(0.05)
    assert starts == [0]
    hk._handle_release()
    assert ends == [1]


def test_xgrab_space_tap_still_starts_nothing():
    starts: list[int] = []
    hk = _xgrab("space", 500, starts.append, lambda: None)
    hk._handle_press()
    time.sleep(0.05)
    hk._handle_release()
    time.sleep(0.6)  # past the threshold: a cancelled timer must stay cancelled
    assert starts == []


def test_xgrab_space_toggles_after_the_threshold(monkeypatch):
    w = _Wired(monkeypatch)
    hk = _xgrab("space", 30, w.on_down, w.on_up)
    hk._handle_press()
    assert _wait_for(w.started.is_set)
    hk._handle_release()
    assert w.log == ["start:1"]
    w.started.clear()
    hk._handle_press()
    assert _wait_for(w.ended.is_set)
    hk._handle_release()
    assert w.log == ["start:1", "end"]


# macOS CGEventTap ---------------------------------------------------------------------


def _mac(key_id, threshold_ms, on_down, on_up):
    from yazses.platform.macos.hotkey import MacosHotkey

    return MacosHotkey(key_id=key_id, threshold_ms=threshold_ms,
                       on_hold_start=on_down, on_hold_end=on_up)


def test_macos_two_quick_taps_of_a_modifier_start_then_stop(monkeypatch):
    w = _Wired(monkeypatch)
    hk = _mac("right_option", _LONG_MS, w.on_down, w.on_up)
    hk._press()
    hk._release()
    hk._press()
    hk._release()
    assert w.log == ["start:0", "end"]


def test_macos_modifier_hold_starts_on_key_down():
    """flagsChanged never repeats, so a start gated on the threshold could never fire."""
    starts: list[int] = []
    ends: list[int] = []
    hk = _mac("right_option", 500, starts.append, lambda: ends.append(1))
    hk._press()
    assert starts == [0]
    hk._release()
    assert ends == [1]


def test_macos_space_tap_types_and_starts_nothing(monkeypatch):
    from yazses.platform.macos import hotkey as mac

    clock = [100.0]
    monkeypatch.setattr(mac.time, "monotonic", lambda: clock[0])
    starts: list[int] = []
    hk = _mac("space", 500, starts.append, lambda: None)
    hk._press()
    clock[0] += 0.1
    hk._release()
    assert starts == []


def test_macos_space_starts_on_a_repeat_past_the_threshold(monkeypatch):
    from yazses.platform.macos import hotkey as mac

    clock = [100.0]
    monkeypatch.setattr(mac.time, "monotonic", lambda: clock[0])
    starts: list[int] = []
    hk = _mac("space", 500, starts.append, lambda: None)
    hk._press()
    clock[0] += 0.2
    hk._press()  # auto-repeat, before the threshold
    assert starts == []
    clock[0] += 0.4
    hk._press()  # auto-repeat past it
    assert starts == [3]  # three leaked spaces to clean up


# Windows low-level hook ---------------------------------------------------------------


def test_windows_two_quick_taps_of_a_modifier_start_then_stop(monkeypatch):
    from yazses.platform.windows.hotkey import WindowsHotkey

    w = _Wired(monkeypatch)
    hk = WindowsHotkey(key_id="right_ctrl", threshold_ms=_LONG_MS,
                       on_hold_start=w.on_down, on_hold_end=w.on_up)
    try:
        hk._press()
        assert _wait_for(w.started.is_set)
        hk._release()  # queued in order behind the start, so it lands before the next press
        hk._press()
        assert _wait_for(w.ended.is_set)
        hk._release()
        assert w.log == ["start:0", "end"]
    finally:
        hk._callbacks.close()


# evdev (Linux default) ----------------------------------------------------------------


def test_evdev_two_quick_taps_of_a_modifier_start_then_stop(monkeypatch):
    pytest.importorskip("evdev", reason="evdev is a Linux-only dependency")
    from evdev import ecodes

    from yazses.hotkeys.evdev_hold import EvdevHoldListener

    w = _Wired(monkeypatch)
    lis = EvdevHoldListener(threshold_ms=_LONG_MS, on_hold_start=w.on_down,
                            on_hold_end=w.on_up, key_code=ecodes.KEY_RIGHTCTRL,
                            produces_char=False)
    lis._handle_event(1, t=0.0)
    lis._handle_event(0, t=0.05)
    lis._handle_event(1, t=1.0)
    lis._handle_event(0, t=1.05)
    assert w.log == ["start:0", "end"]


def test_evdev_space_tap_starts_nothing():
    pytest.importorskip("evdev", reason="evdev is a Linux-only dependency")
    from evdev import ecodes

    from yazses.hotkeys.evdev_hold import EvdevHoldListener

    starts: list[int] = []
    lis = EvdevHoldListener(threshold_ms=500, on_hold_start=starts.append,
                            on_hold_end=lambda: None, key_code=ecodes.KEY_SPACE,
                            produces_char=True)
    lis._handle_event(1, t=0.0)
    lis._handle_event(0, t=0.1)
    assert starts == []
