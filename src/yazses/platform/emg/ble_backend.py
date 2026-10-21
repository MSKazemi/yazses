"""EMG silent-speech BLE backend — implements HotkeyBackend over Bluetooth LE (YESP).

Uses the Nordic UART Service (NUS) for transparent serial-over-BLE:
  Service UUID : 6E400001-B5A3-F393-E0A9-E50E24DCCA9E
  TX char UUID : 6E400003-B5A3-F393-E0A9-E50E24DCCA9E  (device → host, notify)
  RX char UUID : 6E400002-B5A3-F393-E0A9-E50E24DCCA9E  (host → device, write)

bleak is an optional dependency (the ``ble`` extra); when it is missing, ``run()``
logs the install command for the way YazSes was installed (``system/remedy.py``).
See docs/emg-protocol.md for the full YESP message specification.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

_NUS_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

try:
    import bleak  # noqa: F401 — probe import only
    _BLEAK_AVAILABLE = True
except ImportError:
    bleak = None  # type: ignore[assignment]
    _BLEAK_AVAILABLE = False


class BLEEMGBackend:
    """HotkeyBackend for BLE-connected EMG devices speaking YESP over NUS.

    Duck-types the HotkeyBackend Protocol — same interface as EMGBackend (USB
    serial). Swap ``device_port`` for ``address`` in config to use BLE instead
    of USB without any other daemon changes.

    Parameters
    ----------
    address:
        BLE MAC address or UUID, e.g. ``"AA:BB:CC:DD:EE:FF"`` (Linux/Windows)
        or a CoreBluetooth UUID string (macOS).
    on_hold_start:
        Called with 0 leaked characters when HOLD_START or COMMAND fires.
    on_hold_end:
        Called when HOLD_END or COMMAND fires.
    command_map:
        Mapping from COMMAND label to intent string; unknown labels are ignored.
    """

    def __init__(
        self,
        address: str,
        on_hold_start: Callable[[int], None] = lambda n: None,
        on_hold_end: Callable[[], None] = lambda: None,
        command_map: dict[str, str] | None = None,
    ) -> None:
        self._address = address
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._command_map: dict[str, str] = command_map if command_map is not None else {}
        import threading
        self._stop_event = threading.Event()
        self._pending_command: str | None = None
        self._line_buf: str = ""

    # ------------------------------------------------------------------
    # HotkeyBackend protocol
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Connect over BLE and dispatch YESP messages until stop() is called."""
        if not _BLEAK_AVAILABLE:
            from yazses.system.remedy import install_hint

            log.warning(
                "BLEEMGBackend: bleak is not installed; BLE EMG input is disabled. %s",
                install_hint("ble"),
            )
            return

        log.info("BLEEMGBackend: connecting to %s", self._address)
        asyncio.run(self._run_async())
        log.info("BLEEMGBackend: BLE loop exited for %s", self._address)

    def stop(self) -> None:
        """Signal run() to exit at the next polling tick."""
        log.debug("BLEEMGBackend: stop() called")
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal — asyncio BLE loop
    # ------------------------------------------------------------------

    async def _run_async(self) -> None:
        from bleak import BleakClient

        def _notify_handler(_sender: object, data: bytearray) -> None:
            self._line_buf += data.decode("ascii", errors="ignore")
            while "\n" in self._line_buf:
                line, self._line_buf = self._line_buf.split("\n", 1)
                line = line.strip()
                if line:
                    self._dispatch(line)

        try:
            async with BleakClient(self._address) as client:
                log.info("BLEEMGBackend: connected to %s", self._address)
                await client.start_notify(_NUS_TX_CHAR_UUID, _notify_handler)
                while not self._stop_event.is_set():
                    await asyncio.sleep(0.1)
                await client.stop_notify(_NUS_TX_CHAR_UUID)
        except Exception as exc:
            log.warning("BLEEMGBackend: BLE error for %s: %s", self._address, exc)

    # ------------------------------------------------------------------
    # Internal — YESP dispatcher (identical logic to EMGBackend)
    # ------------------------------------------------------------------

    def _dispatch(self, line: str) -> None:
        if line == "HOLD_START":
            log.debug("BLEEMGBackend: HOLD_START")
            self._on_hold_start(0)

        elif line == "HOLD_END":
            log.debug("BLEEMGBackend: HOLD_END")
            self._on_hold_end()

        elif line.startswith("COMMAND:"):
            label = line[len("COMMAND:"):]
            action = self._command_map.get(label)
            if action is None:
                log.debug("BLEEMGBackend: COMMAND label %r not in command_map, ignoring", label)
                return
            log.debug("BLEEMGBackend: COMMAND %r -> %r", label, action)
            self._pending_command = action
            self._on_hold_start(0)
            self._on_hold_end()

        elif line.startswith("TEXT:"):
            text = line[len("TEXT:"):]
            log.debug("BLEEMGBackend: TEXT (reserved, no-op): %r", text)

        elif line == "HEARTBEAT":
            log.debug("BLEEMGBackend: HEARTBEAT")

        else:
            log.debug("BLEEMGBackend: unknown YESP message: %r", line)
