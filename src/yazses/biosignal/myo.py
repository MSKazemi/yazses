"""Thalmic Labs Myo armband as a :class:`~yazses.biosignal.types.BlockSource` (raw EMG over BLE).

The Myo is a forearm band with eight dry surface-EMG electrodes. It was discontinued in
2018, but many research labs still own one, and its Bluetooth LE protocol is public:
Thalmic published it as the C header ``myohw.h`` in ``thalmiclabs/myo-bluetooth``
(https://github.com/thalmiclabs/myo-bluetooth/blob/master/myohw.h, Apache-2.0). Every
UUID, command byte and payload layout below is read from that header; the line numbers
quoted are the header's.

## What the header says (and what it does not)

* **UUIDs** (header lines 52-85): a 16-bit short id replaces bytes 12-13 of the base
  UUID. The header's own worked example is ``ControlService`` (``0x0001``) ->
  ``d5060001-a904-deb9-4748-2c7f4a124842``. Used here: ``CommandCharacteristic``
  ``0x0401`` (write-only) and the four notify-only ``EmgData0..3Characteristic``
  ``0x0105``, ``0x0205``, ``0x0305``, ``0x0405`` of ``EmgDataService`` ``0x0005``.
* **Set mode** (lines 160-207): ``[0x01, 3, emg_mode, imu_mode, classifier_mode]``.
  ``emg_mode`` is ``0x00`` none, ``0x02`` "Send filtered EMG data", ``0x03`` "Send raw
  (unfiltered) EMG data". This module sends IMU ``0x00`` and classifier ``0x00``
  (disabled): only EMG is needed.
* **Sleep mode** (lines 241-252): ``[0x09, 1, sleep_mode]``, ``0`` normal (sleeps after
  inactivity), ``1`` never sleep. Sent before streaming so the band does not doze off
  while the arm rests.
* **EMG payload** (lines 381-390): ``myohw_emg_data_t`` is 16 bytes, ``int8_t
  sample1[8]`` then ``int8_t sample2[8]`` -- two consecutive samples of all eight
  sensors per notification; ``MYOHW_EMG_DEFAULT_STREAMING_RATE`` is 200 (Hz).

Not stated by the header, and therefore **design choices here, unverified on hardware**:
the order in which the four EMG characteristics interleave (samples are ordered by
arrival); which characteristics carry the *filtered* (``0x02``) stream (assumed the same
four); and whether a write needs a response (bleak picks from the characteristic's
properties). Nothing here unlocks the band or reads its pose classifier.

## Units: raw Myo EMG is NOT microvolts

The header gives no gain: the samples are unitless signed 8-bit ADC counts (-128..127).
:class:`~yazses.biosignal.types.SampleBlock` documents its data as µV, so this source
says plainly what it delivers instead: counts multiplied by ``scale`` (default 1.0, so
the numbers *are* counts). Do not read them as µV and do not compare them with a µV
threshold. The squeeze detector is fine with that as long as it is **calibrated on the
same stream**: its thresholds are multiples of a per-session baseline measured with
``bandlimited_rms`` (relaxed and maximum contraction), so the unit cancels. Absolute-µV
checks elsewhere (the signal-quality flatline and saturation limits) do not cancel.
Do **not** pass the int8 rail as the detector's ``rail_limit_uv``: an 8-bit band clips
during an ordinary hard squeeze, so the saturation test would blank exactly the event it
should report (seen on synthetic clipped counts, not on a real band).
:attr:`MyoSource.full_scale` gives the rail in output units for a quality check of a
*relaxed* recording, where clipping really is a fault.

## Threading

bleak is asynchronous; :class:`BlockSource` is synchronous. ``start()`` runs one
background thread with its own event loop; notifications land in a **bounded** queue
(``max_buffer_s`` of data). When the consumer falls behind, the *oldest* notification is
dropped and counted (``dropped_samples``) -- the queue never grows without bound -- and the
loss shows up as a forward jump in the next block's ``t0``, which the detector treats
as a gap. ``stop()`` asks the loop to stop the notifications, put the band back to EMG
off / normal sleep (best effort), disconnect, and joins the thread.

## Failure semantics

A missing ``bleak`` raises ``ImportError`` from ``start()`` naming the ``ble`` extra: the
caller named this source explicitly. A band that is off, out of range or busy is the
common case and is *not* an exception: as with ``BrainFlowBlockSource`` it is logged,
``available`` stays ``False`` with the reason in ``last_error``, and ``read()`` returns
``None``. Bluetooth LE is a radio link to a device the user wears; nothing here opens a
network socket or sends data anywhere.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind

log = logging.getLogger(__name__)

__all__ = [
    "COMMAND_UUID",
    "EMG_DATA_UUIDS",
    "EMG_MODES",
    "MYO_EMG_FS",
    "MYO_N_CHANNELS",
    "MyoSource",
    "decode_emg_notification",
    "myo_uuid",
    "parse_myo_spec",
    "set_mode_command",
    "sleep_mode_command",
    "source_from_spec",
]

# ====================================================================================
# 1. Protocol constants, from myohw.h (line numbers are the header's)
# ====================================================================================

#: ``myohw_num_emg_sensors`` (line 45).
MYO_N_CHANNELS = 8
#: ``MYOHW_EMG_DEFAULT_STREAMING_RATE`` (line 382), Hz.
MYO_EMG_FS = 200.0
#: ``sizeof(myohw_emg_data_t)`` (line 390): two samples x eight int8 sensors.
_EMG_PAYLOAD_BYTES = 16
_SAMPLES_PER_NOTIFICATION = 2

# Short ids (lines 63-85).
_COMMAND_CHARACTERISTIC = 0x0401
_EMG_DATA_CHARACTERISTICS = (0x0105, 0x0205, 0x0305, 0x0405)

# Commands (lines 160-169) and their payload sizes (lines 202, 249).
_CMD_SET_MODE = 0x01
_CMD_SET_SLEEP_MODE = 0x09
_SET_MODE_PAYLOAD = 3
_SET_SLEEP_PAYLOAD = 1
_IMU_MODE_NONE = 0x00          # line 187
_CLASSIFIER_DISABLED = 0x00    # line 196
_SLEEP_NORMAL = 0              # line 243
_SLEEP_NEVER = 1               # line 244

#: ``myohw_emg_mode_t`` (lines 179-183) by name.
EMG_MODES: dict[str, int] = {"none": 0x00, "filtered": 0x02, "raw": 0x03}

#: int8 full scale in counts (|-128| is the larger rail).
_INT8_FULL_SCALE = 128.0


def myo_uuid(short: int) -> str:
    """The full 128-bit UUID string for a Myo 16-bit short id.

    ``myohw.h`` lines 52-55: the short id replaces the two ``0x00`` bytes of
    ``MYO_SERVICE_BASE_UUID``, whose bytes are listed in little-endian order; the
    header's own example is ``ControlService`` -> ``d5060001-a904-deb9-4748-2c7f4a124842``.
    """
    if not 0 <= int(short) <= 0xFFFF:
        raise ValueError(f"a Myo short UUID is 16 bits, got {short!r}")
    return f"d506{int(short):04x}-a904-deb9-4748-2c7f4a124842"


COMMAND_UUID = myo_uuid(_COMMAND_CHARACTERISTIC)
EMG_DATA_UUIDS: tuple[str, ...] = tuple(myo_uuid(s) for s in _EMG_DATA_CHARACTERISTICS)


def _emg_mode_byte(mode: str | int) -> int:
    """A mode name (``"raw"``) or its ``myohw_emg_mode_t`` byte -> the byte."""
    if isinstance(mode, int) and not isinstance(mode, bool) and mode in EMG_MODES.values():
        return mode
    key = mode.strip().lower() if isinstance(mode, str) else None
    if key is None or key not in EMG_MODES:
        raise ValueError(f"unknown Myo EMG mode {mode!r} "
                         f"(expected one of: {', '.join(EMG_MODES)})")
    return EMG_MODES[key]


def set_mode_command(emg_mode: str | int = "raw") -> bytes:
    """``myohw_command_set_mode_t`` (5 bytes): EMG mode on, IMU and classifier off."""
    return bytes((_CMD_SET_MODE, _SET_MODE_PAYLOAD, _emg_mode_byte(emg_mode),
                  _IMU_MODE_NONE, _CLASSIFIER_DISABLED))


def sleep_mode_command(*, never_sleep: bool) -> bytes:
    """``myohw_command_set_sleep_mode_t`` (3 bytes)."""
    return bytes((_CMD_SET_SLEEP_MODE, _SET_SLEEP_PAYLOAD,
                  _SLEEP_NEVER if never_sleep else _SLEEP_NORMAL))


def decode_emg_notification(payload: bytes | bytearray | memoryview) -> np.ndarray:
    """One EMG notification -> an ``(8, 2)`` int8 array (sensors x samples, oldest first).

    Pure. ``myohw_emg_data_t`` is ``int8_t sample1[8]`` then ``int8_t sample2[8]``, so
    column 0 is the first sample and row ``k`` is sensor ``k``. Raises ``ValueError`` for
    any payload that is not exactly 16 bytes -- a truncated packet is not guessed at.
    """
    raw = bytes(payload)
    if len(raw) != _EMG_PAYLOAD_BYTES:
        raise ValueError(f"a Myo EMG notification is {_EMG_PAYLOAD_BYTES} bytes, got {len(raw)}")
    samples = np.frombuffer(raw, dtype=np.int8).reshape(_SAMPLES_PER_NOTIFICATION, MYO_N_CHANNELS)
    return samples.T.copy()


# ====================================================================================
# 2. Spec parsing: ``myo:<address>``
# ====================================================================================

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
_UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
_SPEC_HELP = ("expected 'myo:<address>' with a Bluetooth MAC address (AA:BB:CC:DD:EE:FF, "
              "Linux/Windows) or a CoreBluetooth UUID (macOS)")


def parse_myo_spec(spec: str) -> str:
    """``"myo:AA:BB:CC:DD:EE:FF"`` -> ``"AA:BB:CC:DD:EE:FF"``; ``ValueError`` otherwise.

    Everything after the first colon is the address (a MAC address contains colons).
    The scheme is case-insensitive and surrounding whitespace is ignored; the address
    must be a MAC address or a CoreBluetooth UUID, so a typo fails here rather than as a
    30-second connection timeout.
    """
    scheme, sep, rest = str(spec).strip().partition(":")
    if scheme.strip().lower() != "myo" or not sep:
        raise ValueError(f"not a Myo spec: {spec!r} ({_SPEC_HELP})")
    address = rest.strip()
    if not (_MAC_RE.match(address) or _UUID_RE.match(address)):
        raise ValueError(f"Myo spec {spec!r} has no valid address ({_SPEC_HELP})")
    return address


def source_from_spec(spec: str, **kw: Any) -> MyoSource:
    """Build (not start) a :class:`MyoSource` from ``myo:<address>``; ``kw`` go to it."""
    return MyoSource(parse_myo_spec(spec), **kw)


# ====================================================================================
# 3. The source
# ====================================================================================

# Defaults below are design choices, not values from the header.
_DEFAULT_MAX_BUFFER_S = 2.0        # how much unread data the queue holds before dropping
_DEFAULT_CONNECT_TIMEOUT_S = 10.0  # bleak's own default is 30 s; a worn band answers fast
_START_GRACE_S = 5.0               # setup writes + subscriptions after the connection
_POLL_S = 0.05                     # how often the BLE loop checks for stop()
_JOIN_TIMEOUT_S = 5.0
# Arrival time minus the sample clock, above its running minimum by more than this, is
# a real hole in the stream (notifications the link lost) and resynchronises ``t0``;
# less is BLE connection-interval batching and scheduling jitter, and is snapped to the
# continuous sample clock. Several connection intervals; a design choice.
_ARRIVAL_TOLERANCE_S = 0.25


@dataclass
class _Packet:
    t: float               # host arrival time (the ``clock``)
    samples: np.ndarray    # (8, 2) int8
    lost_before: int = 0   # samples dropped from the queue immediately before this one


class MyoSource:
    """A Myo armband's eight raw EMG channels at 200 Hz, as a :class:`BlockSource`.

    ``address`` is the band's Bluetooth MAC address (Linux/Windows) or CoreBluetooth
    UUID (macOS). ``emg_mode`` is ``"raw"`` (``0x03``, the default) or ``"filtered"``
    (``0x02``). ``scale`` multiplies the int8 counts (see the module docstring: the
    output is counts x ``scale``, never µV unless you supply a measured gain).
    ``use_channels`` picks sensors by 1-based number (``(3, 4, 5)``); the detector
    averages its channels, so leave out sensors that sit over no working muscle.
    ``keep_awake`` sends "never sleep" before streaming and "normal" at ``stop()``.

    ``fs`` and ``channels`` are known before ``start()``. After ``start()`` check
    ``available``; ``last_error`` holds the reason when it is ``False``. Counters:
    ``dropped_samples`` (queue overflow, oldest dropped), ``gap_samples`` (all samples
    the stream skipped over, including link losses estimated from arrival times) and
    ``bad_packets`` (notifications that were not 16 bytes).

    ``client_factory`` (tests) replaces ``bleak.BleakClient``; ``clock`` stamps arrivals.
    """

    def __init__(
        self,
        address: str,
        *,
        emg_mode: str = "raw",
        scale: float = 1.0,
        use_channels: Sequence[int] | None = None,
        keep_awake: bool = True,
        max_buffer_s: float = _DEFAULT_MAX_BUFFER_S,
        connect_timeout_s: float = _DEFAULT_CONNECT_TIMEOUT_S,
        client_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        address = str(address).strip()
        if not address:
            raise ValueError("MyoSource needs the band's Bluetooth address")
        self._mode_byte = _emg_mode_byte(emg_mode)
        if self._mode_byte == EMG_MODES["none"]:
            raise ValueError("emg_mode 'none' streams nothing; use 'raw' or 'filtered'")
        if not (np.isfinite(scale) and scale > 0):
            raise ValueError(f"scale must be a positive finite number, got {scale!r}")
        if not max_buffer_s > 0:
            raise ValueError("max_buffer_s must be > 0")
        if not connect_timeout_s > 0:
            raise ValueError("connect_timeout_s must be > 0")
        if use_channels is None:
            rows = tuple(range(MYO_N_CHANNELS))
        else:
            picked = [int(c) for c in use_channels]
            if not picked or len(set(picked)) != len(picked) or not all(
                    1 <= c <= MYO_N_CHANNELS for c in picked):
                raise ValueError(f"use_channels must be distinct sensor numbers 1..{MYO_N_CHANNELS}, "
                                 f"got {tuple(use_channels)!r}")
            rows = tuple(c - 1 for c in picked)
        self.address = address
        self.emg_mode = next(k for k, v in EMG_MODES.items() if v == self._mode_byte)
        self.scale = float(scale)
        self._rows = rows
        self._keep_awake = bool(keep_awake)
        self._capacity = max(1, int(round(max_buffer_s * MYO_EMG_FS / _SAMPLES_PER_NOTIFICATION)))
        self._connect_timeout_s = float(connect_timeout_s)
        self._client_factory = client_factory
        self._clock = clock

        self.fs: float = MYO_EMG_FS
        self.channels: tuple[ChannelInfo, ...] = tuple(
            ChannelInfo(f"EMG{r + 1}", SignalKind.EMG) for r in rows)
        self.available = False
        self.last_error = ""
        self.dropped_samples = 0
        self.gap_samples = 0
        self.bad_packets = 0

        self._lock = threading.Lock()
        self._queue: deque[_Packet] = deque()
        self._pending: list[_Packet] = []
        self._stop_evt = threading.Event()
        self._ready_evt = threading.Event()
        self._link_lost = threading.Event()
        self._thread: threading.Thread | None = None
        self._reset_clock()

    # ---- derived ----------------------------------------------------------

    @property
    def full_scale(self) -> float:
        """The int8 rail in output units (``128 * scale``), since the µV defaults do not
        apply. For a quality check of a relaxed recording (``adc_limit_uv``); not for the
        squeeze detector's ``rail_limit_uv`` (see the module docstring)."""
        return _INT8_FULL_SCALE * self.scale

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Connect and start streaming; blocks until streaming or failed (bounded).

        Raises ``ImportError`` when bleak is missing (and no ``client_factory`` was
        injected). Any Bluetooth failure is logged and leaves ``available`` ``False``.
        """
        if self._thread is not None:
            return
        client_cls = self._client_factory or _import_bleak_client()
        self.available = False
        self.last_error = ""
        self._stop_evt.clear()
        self._ready_evt.clear()
        self._link_lost.clear()
        with self._lock:
            self._queue.clear()
        self._pending = []
        self._reset_clock()
        self._thread = threading.Thread(
            target=self._thread_main, args=(client_cls,), name=f"myo-{self.address}", daemon=True)
        self._thread.start()
        if not self._ready_evt.wait(self._connect_timeout_s + _START_GRACE_S):
            self._record_failure(f"Myo {self.address}: no stream after "
                                 f"{self._connect_timeout_s + _START_GRACE_S:g} s; giving up")
            self.stop()
            return
        if self.available:
            log.info("Myo %s streaming %s EMG (%d channel(s) at %g Hz).",
                     self.address, self.emg_mode, len(self.channels), self.fs)

    def read(self) -> SampleBlock | None:
        """Every sample received since the last call (up to the next discontinuity), or None.

        Never raises. A block never spans a discontinuity: after a loss the next block
        starts at the resynchronised ``t0``.
        """
        with self._lock:
            fresh = list(self._queue)
            self._queue.clear()
        packets = self._pending + fresh
        self._pending = []
        if not packets:
            return None
        cols: list[np.ndarray] = []
        t0 = 0.0
        for i, pkt in enumerate(packets):
            jump = self._measure_jump(pkt)
            if cols and jump:
                self._pending = packets[i:]      # measured again, and applied, next call
                break
            self._apply_jump(jump)
            if not cols:
                t0 = self._next_t
            cols.append(pkt.samples)
            self._next_t += _SAMPLES_PER_NOTIFICATION / self.fs
        data = np.concatenate(cols, axis=1)[list(self._rows), :].astype(np.float64) * self.scale
        return SampleBlock(data=data, fs=self.fs, channels=self.channels, t0=t0)

    def stop(self) -> None:
        """Stop streaming, restore the band's modes (best effort), disconnect, join."""
        thread, self._thread = self._thread, None
        self._stop_evt.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(_JOIN_TIMEOUT_S)
            if thread.is_alive():  # pragma: no cover - a wedged Bluetooth stack
                log.warning("Myo %s: Bluetooth thread did not exit within %g s",
                            self.address, _JOIN_TIMEOUT_S)
        self.available = False
        with self._lock:
            self._queue.clear()
        self._pending = []

    # ---- the BLE thread -----------------------------------------------------

    def _thread_main(self, client_cls: Any) -> None:
        import asyncio

        try:
            asyncio.run(self._session(client_cls))
        except Exception as exc:
            self._record_failure(f"Myo {self.address} unavailable ({exc}); continuing without it.")
        finally:
            self.available = False
            self._ready_evt.set()

    async def _session(self, client_cls: Any) -> None:
        import asyncio

        client = client_cls(self.address, disconnected_callback=self._on_disconnect,
                            timeout=self._connect_timeout_s)
        async with client:
            if self._keep_awake:
                await client.write_gatt_char(COMMAND_UUID, sleep_mode_command(never_sleep=True))
            await client.write_gatt_char(COMMAND_UUID, set_mode_command(self._mode_byte))
            for uuid in EMG_DATA_UUIDS:
                await client.start_notify(uuid, self._on_notify)
            self.available = True
            self._ready_evt.set()
            while not self._stop_evt.is_set() and not self._link_lost.is_set():
                await asyncio.sleep(_POLL_S)
            if self._link_lost.is_set():
                return
            await self._wind_down(client)

    async def _wind_down(self, client: Any) -> None:
        """Undo what ``_session`` set up; every step is best effort."""
        steps: list[tuple[str, Any]] = [(f"stop_notify {u}", client.stop_notify(u))
                                        for u in EMG_DATA_UUIDS]
        steps.append(("EMG off", client.write_gatt_char(COMMAND_UUID, set_mode_command("none"))))
        if self._keep_awake:
            steps.append(("normal sleep", client.write_gatt_char(
                COMMAND_UUID, sleep_mode_command(never_sleep=False))))
        for what, coro in steps:
            try:
                await coro
            except Exception:
                log.debug("Myo %s: %s failed during stop", self.address, what, exc_info=True)

    def _on_disconnect(self, _client: Any) -> None:
        if not self._stop_evt.is_set():
            self._record_failure(f"Myo {self.address} disconnected")
        self._link_lost.set()
        self.available = False

    def _on_notify(self, _sender: Any, data: bytes | bytearray) -> None:
        """bleak callback: decode and enqueue, dropping the oldest packet when full."""
        t = self._clock()
        try:
            samples = decode_emg_notification(data)
        except ValueError:
            self.bad_packets += 1
            log.debug("Myo %s: ignored a %d-byte EMG notification", self.address, len(data))
            return
        pkt = _Packet(t, samples)
        with self._lock:
            if len(self._queue) >= self._capacity:
                old = self._queue.popleft()
                lost = old.lost_before + _SAMPLES_PER_NOTIFICATION
                self.dropped_samples += _SAMPLES_PER_NOTIFICATION
                head = self._queue[0] if self._queue else pkt
                head.lost_before += lost
            self._queue.append(pkt)

    def _record_failure(self, message: str) -> None:
        self.last_error = message
        self.available = False
        log.warning("%s", message)

    # ---- sample clock -------------------------------------------------------

    def _reset_clock(self) -> None:
        self._next_t = 0.0                # t0 of the next sample on the sample clock
        self._t_origin: float | None = None
        self._excess_floor = 0.0

    def _measure_jump(self, pkt: _Packet) -> float:
        """Seconds of stream missing before ``pkt`` (0.0 when it is contiguous).

        Two sources of loss: packets the queue dropped (exact, ``lost_before``) and
        packets the radio link lost (estimated: the packet arrived more than
        ``_ARRIVAL_TOLERANCE_S`` later than the sample clock predicts, measured against
        the least-delayed arrival so far, so a constant latency costs nothing). Only the
        running floor is updated, so measuring the same packet twice gives the same answer.
        """
        jump = pkt.lost_before / self.fs
        last_sample_t = self._next_t + jump + (_SAMPLES_PER_NOTIFICATION - 1) / self.fs
        if self._t_origin is None:
            # Arrival ~ the packet's last sample (plus latency, absorbed by the floor).
            self._t_origin = pkt.t - last_sample_t
        excess = (pkt.t - self._t_origin) - last_sample_t
        if excess < self._excess_floor:
            self._excess_floor = excess    # the least-delayed packet so far sets the floor
        elif excess - self._excess_floor > _ARRIVAL_TOLERANCE_S:
            jump += excess - self._excess_floor
        return jump

    def _apply_jump(self, jump: float) -> None:
        if jump <= 0:
            return
        self._next_t += jump
        lost = int(round(jump * self.fs))
        self.gap_samples += lost
        log.warning("Myo %s: ~%d sample(s) (%.3f s) missing before t=%.3f s",
                    self.address, lost, jump, self._next_t)


def _import_bleak_client() -> Any:
    """``bleak.BleakClient``, or ImportError naming the ``ble`` extra."""
    try:
        from bleak import BleakClient
    except ImportError as exc:
        hint = ""
        try:
            from yazses.system.remedy import install_hint

            hint = install_hint("ble")
        except Exception:  # pragma: no cover - the hint is a courtesy
            log.debug("install hint unavailable", exc_info=True)
        raise ImportError(
            "the Myo source needs bleak, from the `ble` extra. "
            + hint
        ) from exc
    return BleakClient
