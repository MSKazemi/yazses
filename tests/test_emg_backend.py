"""Tests for the EMG silent-speech backend (yazses.platform.emg.backend).

pyserial is mocked throughout; the real library is never required.
"""
from __future__ import annotations

import threading
import time

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_serial_mock(mocker, lines: list[bytes], stop_event=None):
    """Return a mock serial.Serial instance whose readline() yields each element of
    *lines* in order.  After the last line is consumed the stop_event is set (so the
    backend's while loop exits) and b"" is returned indefinitely."""
    iterator = iter(lines)

    def fake_readline():
        try:
            value = next(iterator)
            return value
        except StopIteration:
            if stop_event is not None:
                stop_event.set()
            return b""

    mock_ser = mocker.MagicMock()
    mock_ser.readline = fake_readline
    return mock_ser


def _patch_serial(mocker, mock_ser):
    """Patch serial.Serial so that it is instantiated directly (not as context manager)."""
    mock_serial_mod = mocker.MagicMock()
    mock_serial_mod.Serial.return_value = mock_ser
    # serial.SerialException must be a real exception class so 'except' clauses work.
    mock_serial_mod.SerialException = IOError
    mocker.patch.dict("sys.modules", {"serial": mock_serial_mod})
    mocker.patch("yazses.platform.emg.backend.serial", mock_serial_mod)
    mocker.patch("yazses.platform.emg.backend._SERIAL_AVAILABLE", True)
    return mock_serial_mod


# ---------------------------------------------------------------------------
# Disabled-backend test
# ---------------------------------------------------------------------------


def test_backend_disabled_when_serial_unavailable(mocker):
    """When _SERIAL_AVAILABLE is False run() must return immediately without touching serial."""
    mocker.patch("yazses.platform.emg.backend._SERIAL_AVAILABLE", False)

    from yazses.platform.emg.backend import EMGBackend

    called = []
    backend = EMGBackend(
        device_port="/dev/ttyUSB0",
        on_hold_start=lambda n: called.append("start"),
        on_hold_end=lambda: called.append("end"),
    )
    backend.run()
    assert called == [], "Callbacks must not fire when serial is unavailable"


# ---------------------------------------------------------------------------
# HOLD_START
# ---------------------------------------------------------------------------


def test_hold_start_fires_callback(mocker):
    """HOLD_START must invoke on_hold_start with 0 leaked chars."""
    hold_starts: list[int] = []

    from yazses.platform.emg.backend import EMGBackend

    backend = EMGBackend(
        device_port="/dev/ttyUSB0",
        on_hold_start=lambda n: hold_starts.append(n),
        on_hold_end=lambda: None,
    )
    # After the one data line is consumed, fake_readline sets _stop_event so the loop exits.
    mock_ser = _make_serial_mock(mocker, [b"HOLD_START\n"], stop_event=backend._stop_event)
    _patch_serial(mocker, mock_ser)
    backend.run()

    assert hold_starts == [0]


# ---------------------------------------------------------------------------
# HOLD_END
# ---------------------------------------------------------------------------


def test_hold_end_fires_callback(mocker):
    """HOLD_END must invoke on_hold_end."""
    hold_ends: list[bool] = []

    from yazses.platform.emg.backend import EMGBackend

    backend = EMGBackend(
        device_port="/dev/ttyUSB0",
        on_hold_start=lambda n: None,
        on_hold_end=lambda: hold_ends.append(True),
    )
    mock_ser = _make_serial_mock(mocker, [b"HOLD_END\n"], stop_event=backend._stop_event)
    _patch_serial(mocker, mock_ser)
    backend.run()

    assert hold_ends == [True]


# ---------------------------------------------------------------------------
# COMMAND
# ---------------------------------------------------------------------------


def test_command_fires_both_callbacks(mocker):
    """A COMMAND message with a known label must fire both on_hold_start and on_hold_end."""
    hold_starts: list[int] = []
    hold_ends: list[bool] = []

    from yazses.platform.emg.backend import EMGBackend

    backend = EMGBackend(
        device_port="/dev/ttyUSB0",
        on_hold_start=lambda n: hold_starts.append(n),
        on_hold_end=lambda: hold_ends.append(True),
        command_map={"save": "save file"},
    )
    mock_ser = _make_serial_mock(mocker, [b"COMMAND:save\n"], stop_event=backend._stop_event)
    _patch_serial(mocker, mock_ser)
    backend.run()

    assert hold_starts == [0]
    assert hold_ends == [True]
    assert backend._pending_command == "save file"


def test_command_unknown_label_ignored(mocker):
    """A COMMAND message with a label not in command_map must be silently ignored."""
    hold_starts: list[int] = []
    hold_ends: list[bool] = []

    from yazses.platform.emg.backend import EMGBackend

    backend = EMGBackend(
        device_port="/dev/ttyUSB0",
        on_hold_start=lambda n: hold_starts.append(n),
        on_hold_end=lambda: hold_ends.append(True),
        command_map={"save": "save file"},
    )
    mock_ser = _make_serial_mock(mocker, [b"COMMAND:unknown_label\n"], stop_event=backend._stop_event)
    _patch_serial(mocker, mock_ser)
    backend.run()

    assert hold_starts == []
    assert hold_ends == []


# ---------------------------------------------------------------------------
# HEARTBEAT
# ---------------------------------------------------------------------------


def test_heartbeat_ignored(mocker):
    """HEARTBEAT must not trigger any callbacks."""
    hold_starts: list[int] = []
    hold_ends: list[bool] = []

    from yazses.platform.emg.backend import EMGBackend

    backend = EMGBackend(
        device_port="/dev/ttyUSB0",
        on_hold_start=lambda n: hold_starts.append(n),
        on_hold_end=lambda: hold_ends.append(True),
    )
    mock_ser = _make_serial_mock(mocker, [b"HEARTBEAT\n"], stop_event=backend._stop_event)
    _patch_serial(mocker, mock_ser)
    backend.run()

    assert hold_starts == []
    assert hold_ends == []


# ---------------------------------------------------------------------------
# Unknown message
# ---------------------------------------------------------------------------


def test_unknown_message_ignored(mocker):
    """An unrecognised YESP message must not trigger any callbacks."""
    hold_starts: list[int] = []
    hold_ends: list[bool] = []

    from yazses.platform.emg.backend import EMGBackend

    backend = EMGBackend(
        device_port="/dev/ttyUSB0",
        on_hold_start=lambda n: hold_starts.append(n),
        on_hold_end=lambda: hold_ends.append(True),
    )
    mock_ser = _make_serial_mock(mocker, [b"GIBBERISH\n"], stop_event=backend._stop_event)
    _patch_serial(mocker, mock_ser)
    backend.run()

    assert hold_starts == []
    assert hold_ends == []


# ---------------------------------------------------------------------------
# stop() from another thread
# ---------------------------------------------------------------------------


def test_stop_exits_run(mocker):
    """Calling stop() from another thread must cause run() to exit within 2 seconds."""
    # readline blocks briefly (simulating the 1-second serial timeout) then returns empty.
    call_count = 0

    def slow_readline():
        nonlocal call_count
        call_count += 1
        time.sleep(0.05)
        return b""

    mock_ser = mocker.MagicMock()
    mock_ser.readline = slow_readline
    _patch_serial(mocker, mock_ser)

    from yazses.platform.emg.backend import EMGBackend

    backend = EMGBackend(device_port="/dev/ttyUSB0")

    finished = threading.Event()

    def _run():
        backend.run()
        finished.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Give the loop one or two iterations then stop.
    time.sleep(0.15)
    backend.stop()

    assert finished.wait(timeout=2.0), "run() did not exit within 2 seconds after stop()"


# ---------------------------------------------------------------------------
# Serial exception exits run()
# ---------------------------------------------------------------------------


def test_serial_exception_exits_run(mocker):
    """A SerialException raised by readline must cause run() to exit cleanly."""
    mock_serial_mod = mocker.MagicMock()
    # Use a real exception class so the 'except serial.SerialException' clause matches.
    mock_serial_mod.SerialException = IOError

    mock_ser = mocker.MagicMock()
    mock_ser.readline.side_effect = IOError("device disconnected")
    mock_serial_mod.Serial.return_value = mock_ser

    mocker.patch.dict("sys.modules", {"serial": mock_serial_mod})
    mocker.patch("yazses.platform.emg.backend.serial", mock_serial_mod)
    mocker.patch("yazses.platform.emg.backend._SERIAL_AVAILABLE", True)

    from yazses.platform.emg.backend import EMGBackend

    backend = EMGBackend(device_port="/dev/ttyUSB0")
    # run() should return (not hang) because SerialException breaks the while loop.
    finished = threading.Event()

    def _run():
        backend.run()
        finished.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    assert finished.wait(timeout=2.0), "run() did not exit after SerialException"


# ---------------------------------------------------------------------------
# Port open failure
# ---------------------------------------------------------------------------


def test_serial_open_failure_exits_run(mocker):
    """If serial.Serial() raises SerialException on open, run() must return without crashing."""
    mock_serial_mod = mocker.MagicMock()
    mock_serial_mod.SerialException = IOError
    mock_serial_mod.Serial.side_effect = IOError("no such port")

    mocker.patch.dict("sys.modules", {"serial": mock_serial_mod})
    mocker.patch("yazses.platform.emg.backend.serial", mock_serial_mod)
    mocker.patch("yazses.platform.emg.backend._SERIAL_AVAILABLE", True)

    from yazses.platform.emg.backend import EMGBackend

    backend = EMGBackend(device_port="/dev/ttyUSB99")
    # Should return immediately without exception.
    backend.run()
