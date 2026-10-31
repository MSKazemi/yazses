"""PLUX BITalino (r)evolution over a serial port (Bluetooth SPP or USB) as a source.

BITalino is an affordable do-it-yourself biosignal kit: an MCU block samples up to six
analog inputs (A1-A6) and streams them over UART. With PLUX's EMG sensor on a forearm or
jaw muscle, or the EEG/EOG sensor on the forehead, it produces exactly the
artifact-grade signals ADR-v2-152 switches on (muscle squeeze, jaw clench, blink). This
module turns its byte stream into :class:`~yazses.biosignal.types.SampleBlock`\\ s in
microvolts.

## Protocol (verified against PLUX's own documents and code)

Primary source — PLUX, "Microcontroller Unit (MCU) Block Data Sheet" (MCU 140616, REV A),
https://support.pluxbiosignals.com/wp-content/uploads/2021/11/revolution-mcu-block-datasheet.pdf
Cross-checked byte for byte against PLUX's official APIs:
https://github.com/BITalinoWorld/revolution-python-api (``bitalino.py``) and
https://github.com/BITalinoWorld/cpp-api (``bitalino.cpp``).

* **Commands** (one byte each, Figs. 4 and 6):
  set sampling rate ``<F F> 0 0 0 0 1 1`` with F = 00 (1 Hz), 01 (10 Hz), 10 (100 Hz),
  11 (1000 Hz) — sent in idle mode; start live ``A6 A5 A4 A3 A2 A1 0 1`` (channel mask);
  start simulated ``A6 ... A1 1 0``; go idle ``0x00`` (in live or simulated mode);
  firmware version ``0x07``; device status ``0x0B``. The serial link runs at 115200 baud
  (both official APIs open the port at 115200).
* **Data frame** (Fig. 5): CRC (4 bits), sequence number S (4 bits, wraps at 15), digital
  I1 I2 O1 O2, then the selected channels in ascending order. "The first four channels
  arrive with 10-bit resolution (0-1023) while the last two arrive with 6-bit (0-63)";
  the footnote makes this *positional*: with fewer than six channels selected, A5/A6 may
  be 10-bit (selecting [A3, A4, A5, A6] gives four 10-bit values). Frame length is
  ``n + 2`` bytes, plus one for 3-5 channels (``bitalino.cpp``), i.e. 3,4,6,7,8,8 bytes
  for 1..6 channels. The field extraction below is transcribed from both APIs (they
  agree): S = last byte >> 4; I1..O2 = bits 7..4 of the second-to-last byte; channel k
  straddles bytes counted from the end of the frame.
* **CRC-4**: computed over the whole frame with the CRC nibble (low 4 bits of the last
  byte) zeroed, bits MSB-first, generator x^4 + x + 1 — the bitwise loop in
  ``bitalino.py`` (``x <<= 1; if x & 0x10: x ^= 0x03; x ^= bit``); ``bitalino.cpp``
  computes the same thing with a nibble table. On a CRC failure ``bitalino.cpp``
  "tr[ies] to resynchronize with the next valid frame" by sliding one byte; so do we.

**Transfer functions** (each PLUX sensor datasheet, ``VCC = 3.3 V``, ``n`` = the channel's
bit width): ``X(V) = (ADC / 2**n - 1/2) * VCC / G``.

* EMG: G = 1009, ±1.64 mV — "Electromyography (EMG) Sensor Data Sheet" EMG 100716,
  https://support.pluxbiosignals.com/wp-content/uploads/2021/11/revolution-emg-sensor-datasheet-1.pdf
* EEG: G = 41782, ±39.49 µV — EEG 011020,
  https://support.pluxbiosignals.com/wp-content/uploads/2021/11/revolution-eeg-sensor-datasheet-revb.pdf
* EOG: G = 2038, ±0.81 mV — EOG 190918,
  https://support.pluxbiosignals.com/wp-content/uploads/2021/11/eog-sensor-datasheet-rev.pdf

Beware the *biosignalsplux* EEG sheet (G = 40000, VCC = 3 V, 16-bit): a different product
whose numbers circulate under BITalino's name. The ECG (G = 1100), EDA, ACC and LUX
sensors are refused: none is an artifact-switch signal and none maps to a
:class:`~yazses.biosignal.types.SignalKind`.

**Not verified**: behaviour of the pre-(r)evolution BITalino firmware (only the
(r)evolution datasheet was read), and what a board does with configuration commands
while it is still streaming from a crashed session — if a board will not start,
power-cycle it.

## Dropped frames and the clock

The 4-bit sequence number exposes loss: a jump from S to S' means ``(S' - S - 1) mod 16``
frames vanished. They are counted in :attr:`BITalinoParser.stats` (``dropped_frames``)
and **never fabricated**: the block ends before the gap and the next block's ``t0``
jumps by the lost frames, so time stays true and every delivered sample is a real
sample. A loss of 16 frames or more is indistinguishable modulo 16 and is under-counted
— an inherent limit of a 4-bit counter.

A 4-bit CRC passes one random window in sixteen, so after start-up or a CRC failure the
parser only (re)locks on **two** consecutive CRC-valid frames with consecutive sequence
numbers (a design choice, stricter than the vendor APIs). The cost is one frame of
latency at lock time — one second at the 1 Hz rate.

## Failure semantics

As :class:`~yazses.biosignal.sources.BrainFlowBlockSource`: a missing ``pyserial``
(the ``emg`` extra) or an unplugged/busy port leaves the source unavailable
(``available`` False, ``last_error`` set, ``read()`` -> ``None``) instead of raising out
of ``start()``. :func:`yazses.biosignal.thinkgear.import_serial` raises the ImportError
for callers that want it.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from yazses.biosignal.thinkgear import _parse_options, _split_options, import_serial
from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind

log = logging.getLogger(__name__)

__all__ = [
    "BITALINO_BAUD",
    "BITALINO_RATES",
    "BITALINO_VCC",
    "SENSOR_GAINS",
    "BITalinoFrame",
    "BITalinoParser",
    "BITalinoSource",
    "BITalinoStats",
    "adc_to_uv",
    "bitalino_from_spec",
    "channel_bits",
    "crc4",
    "decode_frame",
    "frame_size",
    "parse_bitalino_spec",
    "sampling_rate_command",
    "start_command",
]

BITALINO_BAUD = 115200
BITALINO_RATES = (1, 10, 100, 1000)
BITALINO_VCC = 3.3
_RATE_BITS = {1: 0b00, 10: 0b01, 100: 0b10, 1000: 0b11}

CMD_IDLE = 0x00
CMD_VERSION = 0x07
CMD_STATE = 0x0B

# sensor -> (gain, kind). Gains from the PLUX datasheets cited in the module docstring.
SENSOR_GAINS: dict[str, float] = {"emg": 1009.0, "eeg": 41782.0, "eog": 2038.0}
_SENSOR_KINDS: dict[str, SignalKind] = {
    "emg": SignalKind.EMG, "eeg": SignalKind.EEG, "eog": SignalKind.EOG,
}
_REFUSED_SENSORS = ("ecg", "eda", "acc", "lux", "egg", "pzt")

_READ_CHUNK = 4096


# ====================================================================================
# pure protocol helpers
# ====================================================================================


def _check_n(n_channels: int) -> int:
    n = int(n_channels)
    if not 1 <= n <= 6:
        raise ValueError(f"a BITalino frame carries 1-6 analog channels, not {n_channels}")
    return n


def frame_size(n_channels: int) -> int:
    """Bytes per data frame for ``n_channels`` selected channels (3,4,6,7,8,8)."""
    n = _check_n(n_channels)
    return n + 2 + (1 if 3 <= n <= 5 else 0)


def channel_bits(n_channels: int) -> tuple[int, ...]:
    """Bit width of each *position* in a frame: the first four are 10-bit, then 6-bit."""
    n = _check_n(n_channels)
    return tuple(10 if pos < 4 else 6 for pos in range(n))


def sampling_rate_command(fs: int) -> int:
    """``<F F> 0 0 0 0 1 1`` — the idle-mode command selecting 1/10/100/1000 Hz."""
    try:
        return (_RATE_BITS[int(fs)] << 6) | 0x03
    except (KeyError, ValueError, TypeError):
        raise ValueError(f"BITalino sampling rate must be one of {BITALINO_RATES}, "
                         f"not {fs!r}") from None


def start_command(channels: Iterable[int], *, simulated: bool = False) -> int:
    """``A6 .. A1 0 1`` (live) or ``A6 .. A1 1 0`` (simulated); channels are 0-based (0 = A1)."""
    mask = 0
    for ch in channels:
        if not 0 <= int(ch) <= 5:
            raise ValueError(f"BITalino analog channel index must be 0-5 (A1-A6), not {ch!r}")
        mask |= 1 << int(ch)
    if not mask:
        raise ValueError("select at least one BITalino analog channel")
    return (mask << 2) | (0x02 if simulated else 0x01)


def crc4(frame: bytes | bytearray) -> int:
    """The 4-bit CRC PLUX's firmware puts in the low nibble of a frame's last byte.

    Computed over every bit of ``frame`` (MSB first, first byte first) with that nibble
    taken as zero — PLUX's ``revolution-python-api`` loop, masked to 4 bits as it goes.
    """
    x = 0
    last = len(frame) - 1
    for i, byte in enumerate(frame):
        if i == last:
            byte &= 0xF0
        for bit in range(7, -1, -1):
            x = (x << 1) & 0x1F
            if x & 0x10:
                x ^= 0x13           # x^4 + x + 1; clears bit 4, same low nibble as `^ 0x03`
            x ^= (byte >> bit) & 0x01
    return x & 0x0F


def _crc_ok(buf: bytes | bytearray, start: int, size: int) -> bool:
    frame = buf[start:start + size]
    return crc4(frame) == (frame[-1] & 0x0F)


@dataclass(frozen=True)
class BITalinoFrame:
    """One decoded data frame.

    ``analog`` are raw ADC codes for the selected channels in ascending channel order;
    ``digital`` is (I1, I2, O1, O2). ``lost_before`` is filled by :class:`BITalinoParser`:
    frames the sequence counter says vanished just before this one (mod 16).
    """

    seq: int
    digital: tuple[int, int, int, int]
    analog: tuple[int, ...]
    lost_before: int = 0


def decode_frame(frame: bytes | bytearray, n_channels: int) -> BITalinoFrame:
    """Unpack a frame (CRC not checked). Field formulas transcribed from PLUX's APIs."""
    n = _check_n(n_channels)
    d = bytes(frame)
    if len(d) != frame_size(n):
        raise ValueError(f"a {n}-channel frame is {frame_size(n)} bytes, got {len(d)}")
    seq = d[-1] >> 4
    digital = ((d[-2] >> 7) & 1, (d[-2] >> 6) & 1, (d[-2] >> 5) & 1, (d[-2] >> 4) & 1)
    analog = [((d[-2] & 0x0F) << 6) | (d[-3] >> 2)]
    if n > 1:
        analog.append(((d[-3] & 0x03) << 8) | d[-4])
    if n > 2:
        analog.append((d[-5] << 2) | (d[-6] >> 6))
    if n > 3:
        analog.append(((d[-6] & 0x3F) << 4) | (d[-7] >> 4))
    if n > 4:
        analog.append(((d[-7] & 0x0F) << 2) | (d[-8] >> 6))
    if n > 5:
        analog.append(d[-8] & 0x3F)
    return BITalinoFrame(seq=seq, digital=digital, analog=tuple(analog))


def adc_to_uv(adc: Any, bits: int, sensor: str, *, vcc: float = BITALINO_VCC) -> Any:
    """PLUX transfer function in µV: ``(ADC / 2**bits - 1/2) * VCC / G * 1e6``."""
    gain = SENSOR_GAINS[_normalise_sensor(sensor)]
    return (np.asarray(adc, dtype=np.float64) / float(2 ** int(bits)) - 0.5) * vcc / gain * 1e6


def _normalise_sensor(sensor: str) -> str:
    key = str(sensor).strip().lower()
    if key in SENSOR_GAINS:
        return key
    if key in _REFUSED_SENSORS:
        raise ValueError(f"BITalino sensor {sensor!r} is not supported: only emg, eeg and eog "
                         "carry the artifacts a biosignal switch uses")
    raise ValueError(f"unknown BITalino sensor {sensor!r} (expected emg, eeg or eog)")


# ====================================================================================
# incremental parser
# ====================================================================================


@dataclass
class BITalinoStats:
    """Running counters of what the parser accepted, rejected and inferred lost."""

    frames: int = 0             # CRC-valid frames delivered
    crc_errors: int = 0         # times a locked stream failed its CRC (each starts a resync)
    skipped_bytes: int = 0      # bytes discarded while (re)synchronising
    dropped_frames: int = 0     # frames the sequence counter says were lost (mod 16)
    seq_gaps: int = 0           # number of separate gaps


@dataclass
class BITalinoParser:
    """Incremental bytes -> :class:`BITalinoFrame` parser for ``n_channels``. Pure.

    Frames have no sync marker; framing comes from the CRC. Locked: each frame-sized
    window must pass its CRC or the lock is lost. Unlocked (at start and after a
    failure): slide one byte at a time until two consecutive CRC-valid frames with
    consecutive sequence numbers appear (see the module docstring for why two).
    """

    n_channels: int
    stats: BITalinoStats = field(default_factory=BITalinoStats)
    _buf: bytearray = field(default_factory=bytearray, repr=False)
    _locked: bool = field(default=False, repr=False)
    _last_seq: int | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._size = frame_size(self.n_channels)

    def feed(self, data: bytes | bytearray) -> list[BITalinoFrame]:
        buf = self._buf
        buf.extend(data)
        size = self._size
        out: list[BITalinoFrame] = []
        i = 0
        while len(buf) - i >= size:
            if self._locked:
                if _crc_ok(buf, i, size):
                    out.append(self._accept(buf, i))
                    i += size
                    continue
                self._locked = False
                self.stats.crc_errors += 1
            if len(buf) - i < 2 * size:
                break                                   # need a second frame to confirm
            if (_crc_ok(buf, i, size) and _crc_ok(buf, i + size, size)
                    and (buf[i + 2 * size - 1] >> 4) == ((buf[i + size - 1] >> 4) + 1) & 0x0F):
                self._locked = True
                out.append(self._accept(buf, i))
                i += size
                continue
            i += 1
            self.stats.skipped_bytes += 1
        del buf[:i]
        return out

    def reset(self) -> None:
        """Forget buffered bytes, the lock and the sequence history (counters are kept)."""
        self._buf.clear()
        self._locked = False
        self._last_seq = None

    def _accept(self, buf: bytearray, i: int) -> BITalinoFrame:
        frame = decode_frame(buf[i:i + self._size], self.n_channels)
        lost = 0
        if self._last_seq is not None:
            lost = (frame.seq - self._last_seq - 1) & 0x0F
            if lost:
                self.stats.dropped_frames += lost
                self.stats.seq_gaps += 1
        self._last_seq = frame.seq
        self.stats.frames += 1
        if lost:
            frame = BITalinoFrame(frame.seq, frame.digital, frame.analog, lost_before=lost)
        return frame


# ====================================================================================
# source
# ====================================================================================


def _channel_index(ch: int | str) -> int:
    """``0``..``5`` (PLUX API numbering, 0 = A1) or ``"A1"``..``"A6"`` -> 0-based index."""
    if isinstance(ch, str):
        text = ch.strip().upper()
        if len(text) == 2 and text[0] == "A" and text[1] in "123456":
            return int(text[1]) - 1
        raise ValueError(f"BITalino channel {ch!r} must be 'A1'..'A6' or an index 0-5")
    if isinstance(ch, bool) or not 0 <= int(ch) <= 5:
        raise ValueError(f"BITalino channel index must be 0-5 (A1-A6), not {ch!r}")
    return int(ch)


def _resolve_sensors(
    channels: Sequence[int | str],
    sensors: str | Sequence[str] | Mapping[int | str, str],
) -> list[tuple[int, str]]:
    idx = [_channel_index(c) for c in channels]
    if not idx:
        raise ValueError("select at least one BITalino analog channel")
    if len(set(idx)) != len(idx):
        raise ValueError(f"duplicate BITalino channel in {list(channels)!r}")
    if isinstance(sensors, str):
        per = [sensors] * len(idx)
    elif isinstance(sensors, Mapping):
        by_idx = {_channel_index(k): v for k, v in sensors.items()}
        missing = [f"A{i + 1}" for i in idx if i not in by_idx]
        if missing:
            raise ValueError(f"no sensor given for BITalino channel(s) {', '.join(missing)}")
        per = [by_idx[i] for i in idx]
    else:
        per = list(sensors)
        if len(per) != len(idx):
            raise ValueError(f"{len(idx)} channel(s) but {len(per)} sensor(s)")
    pairs = sorted(zip(idx, (_normalise_sensor(s) for s in per)))
    return pairs                           # the device sends channels in ascending order


class BITalinoSource:
    """A BITalino (r)evolution board as a :class:`~yazses.biosignal.types.BlockSource`.

    ``channels`` are the analog inputs to stream, as PLUX's 0-based indices (0 = A1) or
    ``"A1"``..``"A6"``; ``sensors`` says which PLUX sensor sits on each — one name for
    all, a sequence aligned with ``channels``, or a mapping — and picks both the µV
    transfer function and the :class:`SignalKind` (emg -> EMG, eeg -> EEG, eog -> EOG).
    Channels are emitted in ascending A-order (the order the device sends them) and
    named ``A1``..``A6`` unless ``names`` (aligned with that ascending order) says
    otherwise. ``fs`` is 1, 10, 100 or 1000 Hz. ``simulated=True`` asks the firmware for
    its synthetic waveforms (a no-sensor bench test). ``fs`` and ``channels`` are valid
    before ``start()``.

    A channel that lands in a 6-bit frame slot (the 5th/6th of five or six selected)
    keeps its full range at 1/16 of the resolution; a warning says so at construction.
    Dropped frames: see the module docstring — counted in :attr:`dropped_frames`, never
    fabricated, the clock jumps across them.
    """

    def __init__(
        self,
        port: str,
        channels: Sequence[int | str] = (0,),
        sensors: str | Sequence[str] | Mapping[int | str, str] = "emg",
        fs: int = 1000,
        *,
        names: Sequence[str] | None = None,
        baudrate: int = BITALINO_BAUD,
        simulated: bool = False,
        vcc: float = BITALINO_VCC,
        serial_factory: Callable[[], Any] | None = None,
        read_chunk: int = _READ_CHUNK,
    ) -> None:
        self._rate_cmd = sampling_rate_command(fs)
        pairs = _resolve_sensors(channels, sensors)
        if names is not None:
            names = [str(n) for n in names]
            if len(names) != len(pairs) or any(not n.strip() for n in names):
                raise ValueError(f"names must give {len(pairs)} non-empty channel name(s)")
        if read_chunk <= 0:
            raise ValueError("read_chunk must be > 0")
        self.port = port
        self.baudrate = int(baudrate)
        self.simulated = bool(simulated)
        self.fs: float = float(int(fs))
        self._indices = tuple(i for i, _ in pairs)
        self.sensors = tuple(s for _, s in pairs)
        self.channels: tuple[ChannelInfo, ...] = tuple(
            ChannelInfo(names[pos] if names else f"A{i + 1}", _SENSOR_KINDS[s])
            for pos, (i, s) in enumerate(pairs))
        self.bits = channel_bits(len(pairs))
        self._start_cmd = start_command(self._indices, simulated=self.simulated)
        bits = np.asarray(self.bits, dtype=np.float64)[:, None]
        gains = np.asarray([SENSOR_GAINS[s] for s in self.sensors], dtype=np.float64)[:, None]
        self._scale = 2.0 ** bits                  # ADC full scale per channel
        self._uv_per_v = float(vcc) / gains * 1e6
        for pos, b in enumerate(self.bits):
            if b == 6:
                log.warning("BITalino channel A%d (%s) arrives with 6-bit resolution in a "
                            "%d-channel frame; select fewer channels to get 10 bits.",
                            self._indices[pos] + 1, self.sensors[pos], len(pairs))
        self._serial_factory = serial_factory
        self._read_chunk = int(read_chunk)
        self._ser: Any = None
        self.parser = BITalinoParser(len(pairs))
        self._next_index = 0                       # sample index of the next frame (incl. losses)
        self._pending: deque[SampleBlock] = deque()
        self.available = False
        self.last_error = ""
        self.digital: tuple[int, int, int, int] | None = None

    @property
    def dropped_frames(self) -> int:
        return self.parser.stats.dropped_frames

    @property
    def crc_errors(self) -> int:
        return self.parser.stats.crc_errors

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._ser is not None:
            return
        self.available = False
        self.last_error = ""
        try:
            ser = (self._serial_factory() if self._serial_factory is not None
                   else import_serial().Serial(self.port, self.baudrate, timeout=0))
        except ImportError as exc:
            self.last_error = str(exc)
            log.info("BITalino source disabled: %s", exc)
            return
        except Exception as exc:
            self._fail(f"BITalino on {self.port!r} unavailable ({exc}); continuing without it.",
                       None)
            return
        try:
            reset = getattr(ser, "reset_input_buffer", None)
            if callable(reset):
                reset()                             # stale bytes would only cost a resync
            ser.write(bytes([self._rate_cmd]))      # idle mode: set the sampling rate
            ser.write(bytes([self._start_cmd]))     # then start live/simulated acquisition
        except Exception as exc:
            self._fail(f"BITalino on {self.port!r} did not accept the start commands ({exc})", ser)
            return
        self._ser = ser
        self.parser = BITalinoParser(len(self.channels))
        self._next_index = 0
        self._pending.clear()
        self.available = True
        log.info("BITalino source streaming from %s (%d channel(s) at %g Hz%s).", self.port,
                 len(self.channels), self.fs, ", simulated" if self.simulated else "")

    def read(self) -> SampleBlock | None:
        """The next contiguous run of decoded samples, or None if there is none yet."""
        if self._pending:
            return self._pending.popleft()
        if not self.available or self._ser is None:
            return None
        try:
            waiting = int(getattr(self._ser, "in_waiting", 0) or 0)
            data = self._ser.read(max(waiting, self._read_chunk))
        except Exception as exc:
            self._fail(f"BITalino on {self.port!r} stopped streaming ({exc})", self._ser)
            return None
        if data:
            self._ingest(self.parser.feed(data))
        return self._pending.popleft() if self._pending else None

    def stop(self) -> None:
        ser, self._ser = self._ser, None
        self.available = False
        self._pending.clear()
        if ser is not None:
            try:
                ser.write(bytes([CMD_IDLE]))        # live/simulated -> idle
            except Exception:  # pragma: no cover - the port may already be gone
                log.debug("BITalino idle command failed", exc_info=True)
            _close_quietly(ser)

    # ---- internals -------------------------------------------------------

    def _ingest(self, frames: list[BITalinoFrame]) -> None:
        run: list[tuple[int, ...]] = []
        run_start = self._next_index
        for frame in frames:
            if frame.lost_before:
                if run:
                    self._pending.append(self._block(run, run_start))
                    run = []
                log.warning("BITalino %s: %d frame(s) lost before t=%.3f s (sequence gap); "
                            "no samples were substituted.", self.port, frame.lost_before,
                            (self._next_index + frame.lost_before) / self.fs)
                self._next_index += frame.lost_before
                run_start = self._next_index
            run.append(frame.analog)
            self._next_index += 1
            self.digital = frame.digital
        if run:
            self._pending.append(self._block(run, run_start))

    def _block(self, run: list[tuple[int, ...]], start_index: int) -> SampleBlock:
        adc = np.asarray(run, dtype=np.float64).T          # (channels, samples)
        uv = (adc / self._scale - 0.5) * self._uv_per_v
        return SampleBlock(data=uv, fs=self.fs, channels=self.channels, t0=start_index / self.fs)

    def _fail(self, message: str, ser: Any | None) -> None:
        self.last_error = message
        self.available = False
        log.warning("%s", message)
        if ser is not None:
            _close_quietly(ser)
        if ser is self._ser:
            self._ser = None


def _close_quietly(ser: Any) -> None:
    try:
        ser.close()
    except Exception:  # pragma: no cover - teardown is best effort
        log.debug("closing serial port failed", exc_info=True)


# ====================================================================================
# spec parsing
# ====================================================================================

_BIT_SPEC_HELP = ("expected 'bitalino:<port>[:A1=emg,A4=eeg,fs=1000,simulated,baud=115200]'")


def parse_bitalino_spec(spec: str) -> dict[str, Any]:
    """``bitalino:<port>[:<options>]`` (scheme optional) -> :class:`BITalinoSource` kwargs.

    Options, comma-separated: ``A1``..``A6`` ``=emg|eeg|eog`` (which inputs to stream and
    the sensor on each; default ``A1=emg``), ``fs=1|10|100|1000``, ``simulated``,
    ``baud=<n>``. The options are the text after the port's last colon and are
    recognised by containing ``=`` (or being ``simulated``), so ``/dev/rfcomm0`` and
    ``COM5`` need no quoting. Raises ``ValueError`` for anything malformed.
    """
    text = spec.strip()
    if text.lower().startswith("bitalino:"):
        text = text[len("bitalino:"):]
    port, options = _split_options(text)
    if not port:
        raise ValueError(f"bitalino spec {spec!r} has no serial port ({_BIT_SPEC_HELP})")
    kw: dict[str, Any] = {"port": port}
    sensors: dict[int | str, str] = {}
    for key, value in _parse_options(options).items():
        if key.upper() in {f"A{i}" for i in range(1, 7)}:
            if not value:
                raise ValueError(f"bitalino spec {spec!r}: {key.upper()} needs a sensor "
                                 "(emg, eeg or eog)")
            sensors[key.upper()] = _normalise_sensor(value)
        elif key == "fs":
            try:
                kw["fs"] = int(value)
            except ValueError:
                raise ValueError(f"bitalino spec {spec!r}: fs must be an integer") from None
            sampling_rate_command(kw["fs"])          # validate now, with the spec in hand
        elif key == "simulated":
            kw["simulated"] = True
        elif key == "baud":
            try:
                kw["baudrate"] = int(value)
            except ValueError:
                raise ValueError(f"bitalino spec {spec!r}: baud must be an integer") from None
        else:
            raise ValueError(f"bitalino spec {spec!r}: unknown option {key!r} ({_BIT_SPEC_HELP})")
    if sensors:
        kw["channels"] = tuple(sensors)
        kw["sensors"] = sensors
    return kw


def bitalino_from_spec(spec: str, **kw: Any) -> BITalinoSource:
    """Build a :class:`BITalinoSource` from ``bitalino:<port>[:<options>]`` (or the part
    after ``bitalino:``). Extra keyword arguments override the spec's."""
    return BITalinoSource(**{**parse_bitalino_spec(spec), **kw})
