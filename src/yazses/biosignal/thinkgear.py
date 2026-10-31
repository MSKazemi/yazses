"""NeuroSky ThinkGear serial stream (MindWave Mobile 2 and other TGAM headsets) as a source.

A ThinkGear headset has one dry electrode at Fp1 (forehead, above the left eye) referenced
to an ear clip. Fp1 sits right over the eye, so a blink and a jaw clench are the two
largest things it records — which is exactly what an artifact-grade switch needs
(ADR-v2-152). This module turns the headset's serial byte stream into
:class:`~yazses.biosignal.types.SampleBlock`\\ s of **raw EEG in microvolts** and nothing
else.

## What is deliberately NOT exposed

The stream also carries NeuroSky's eSense "attention" / "meditation" scores (codes
0x04 / 0x05), band powers (0x81 / 0x83) and, on some firmware, a blink-strength value.
These are vendor heuristics whose definition is not published, so they are not a
*specific, checkable* signal (AGENTS.md rule 9; ADR-021). The parser walks past them by
their declared lengths and never reports them; a detector downstream sees only the raw
waveform and makes its own, testable decision. The one non-raw value kept is
POOR_SIGNAL (0x02), surfaced as *quality metadata* on the source
(:attr:`ThinkGearSource.poor_signal`), never as an event.

## Protocol (verified against NeuroSky's own documentation)

Source: NeuroSky, "ThinkGear Communications Protocol",
https://developer.neurosky.com/docs/doku.php?id=thinkgear_communications_protocol

* A packet is ``[SYNC=0xAA][SYNC=0xAA][PLENGTH][PAYLOAD x PLENGTH][CHKSUM]``.
  ``PLENGTH`` is 0..169; "any higher value indicates an error". "If [PLENGTH] is 170
  ([SYNC]), then repeat step 3" — i.e. extra 0xAA bytes after the sync pair are skipped.
* ``CHKSUM`` = one's complement of the low 8 bits of the sum of the payload bytes
  (``~sum & 0xFF``). On a mismatch "the entire Packet should be discarded". The doc's
  own example ``AA AA 08 02 20 01 7E 04 12 05 60 E3`` is a regression test.
* The payload is a series of DataRows ``[EXCODE 0x55 ...][CODE][VLENGTH][VALUE...]``.
  Each leading 0x55 raises the extended-code level by one. A CODE below 0x80 has an
  implied 1-byte value and no VLENGTH byte; a CODE of 0x80 or above is followed by a
  VLENGTH byte.
* Code 0x02 POOR_SIGNAL: 0..255, "any non-zero value indicates that some sort of noise
  contamination is detected"; "200 ... the ThinkGear electrodes aren't contacting a
  person's skin"; "typically output every second".
* Code 0x80 RAW Wave Value: 2 bytes, big-endian, two's-complement signed 16-bit
  ("The first byte of the Value represents the high-order bits"). The ASIC "outputs
  this value 512 times a second"; raw 16-bit output "requires 57,600 baud and above".

Raw counts to microvolts — NeuroSky support, "How to convert raw values to voltage?",
https://support.neurosky.com/kb/science/how-to-convert-raw-values-to-voltage :
``V = rawValue * (1.8 / 4096) / 2000`` for TGAT/TGAM/MindWave/MindWave Mobile ("a 2000
gain, 4096 value range, and 1.8V input voltage"), so one count is ~0.2197 µV. The same
page warns "the gain on actual hardware may be slightly off from 2000x (maybe +/- 5%?)";
``uv_scale`` is the knob for a per-headset calibration.

**Not verified from a NeuroSky document** (kept as configurable defaults, never relied on
for correctness): that a MindWave Mobile 2 paired over Bluetooth SPP streams at 57600
baud (the protocol doc only says raw output needs >= 57600; a Bluetooth virtual serial
port usually ignores the baud anyway), and any meaning of codes not in the doc's table
(e.g. 0x01 battery in its example, 0x16 blink strength). Unknown codes are skipped by
the length rule above and are never interpreted.

## Lost packets and the clock

ThinkGear packets carry no sequence number, so a packet rejected by its checksum cannot
be placed in time. The source therefore does **not** fabricate a sample for it and does
not move the clock: ``t0`` counts delivered samples at the nominal 512 Hz, and every
rejection is counted in :attr:`ThinkGearParser.stats` (``bad_checksum``, ``bad_length``,
``malformed``) and summarised by :attr:`ThinkGearSource.lost_packets`. A lost raw packet
is ~2 ms, so the clock drifts by that much per loss; a caller that cares can compare
``lost_packets`` against its own budget.

## Failure semantics

Like :class:`yazses.biosignal.sources.BrainFlowBlockSource`: an unplugged, busy or
missing port, and a missing ``pyserial``, leave the source *unavailable*
(``available`` False, reason in ``last_error``, ``read()`` returns ``None``) instead of
raising out of ``start()`` — an optional headset must never take the dictation daemon
down. :func:`import_serial` is the lazy import itself and raises a clear
``ImportError`` naming the ``emg`` extra, for callers (``doctor``) that want the error.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind

log = logging.getLogger(__name__)

__all__ = [
    "THINKGEAR_BAUD",
    "THINKGEAR_FS",
    "THINKGEAR_RAW_TO_UV",
    "ThinkGearPacket",
    "ThinkGearParser",
    "ThinkGearSource",
    "ThinkGearStats",
    "import_serial",
    "parse_thinkgear_spec",
    "thinkgear_checksum",
    "thinkgear_from_spec",
]

SYNC = 0xAA
EXCODE = 0x55
MAX_PLENGTH = 169                      # "any higher value indicates an error"
CODE_POOR_SIGNAL = 0x02
CODE_RAW = 0x80
POOR_SIGNAL_NO_CONTACT = 200           # "electrodes aren't contacting a person's skin"

THINKGEAR_FS = 512.0                   # ASIC raw output rate ("512 times a second")
THINKGEAR_BAUD = 57600                 # raw 16-bit output needs >= 57600 baud
# NeuroSky: V = raw * (1.8 / 4096) / 2000  ->  µV per count
THINKGEAR_RAW_TO_UV = 1.8 / 4096.0 / 2000.0 * 1e6

_READ_CHUNK = 4096
# A garbage-only stream must not grow the buffer without bound: beyond this many bytes
# without a sync pair the head is dropped (counted as skipped).
_MAX_BUFFER = 1 << 16


def thinkgear_checksum(payload: bytes | bytearray) -> int:
    """NeuroSky checksum: one's complement of the low byte of the payload sum."""
    return (~sum(payload)) & 0xFF


@dataclass(frozen=True)
class ThinkGearPacket:
    """One checksum-valid packet, reduced to what the pipeline may use.

    ``raw`` holds every 0x80 raw value in the packet (signed counts, in order);
    ``poor_signal`` is the 0x02 value when the packet had one. Every other row (eSense,
    band powers, unknown codes) is skipped by design — see the module docstring.
    """

    raw: tuple[int, ...] = ()
    poor_signal: int | None = None


@dataclass
class ThinkGearStats:
    """Running counters of what the parser accepted and rejected."""

    packets: int = 0            # checksum-valid, well-formed packets
    raw_samples: int = 0
    bad_checksum: int = 0       # discarded: CHKSUM mismatch
    bad_length: int = 0         # discarded: PLENGTH > 169
    malformed: int = 0          # checksum OK but a DataRow overran the payload
    skipped_bytes: int = 0      # bytes discarded while hunting for SYNC SYNC

    @property
    def rejected_packets(self) -> int:
        return self.bad_checksum + self.bad_length + self.malformed


@dataclass
class ThinkGearParser:
    """Incremental bytes -> :class:`ThinkGearPacket` parser. Pure: no I/O, no clock.

    Feed it arbitrary chunks (a packet may be split across any number of ``feed`` calls);
    it resynchronises after garbage by hunting for the next ``0xAA 0xAA`` and, after a
    rejected packet, restarts the hunt at the rejected packet's PLENGTH byte (just past
    its sync run) — so a real packet that began inside the rejected bytes is still
    found, and a rejected packet is counted once.
    """

    stats: ThinkGearStats = field(default_factory=ThinkGearStats)
    _buf: bytearray = field(default_factory=bytearray, repr=False)

    def feed(self, data: bytes | bytearray) -> list[ThinkGearPacket]:
        self._buf.extend(data)
        out: list[ThinkGearPacket] = []
        buf = self._buf
        i = 0
        n = len(buf)
        while True:
            # 1. hunt for SYNC SYNC
            j = buf.find(b"\xaa\xaa", i)
            if j < 0:
                # keep a trailing 0xAA: it may be the first half of the next sync pair
                keep = 1 if n and buf[n - 1] == SYNC else 0
                self.stats.skipped_bytes += max(0, n - keep - i)
                i = n - keep
                break
            self.stats.skipped_bytes += j - i
            i = j
            # 2. PLENGTH, skipping extra SYNC bytes ("if PLENGTH is 170, repeat step 3")
            k = i + 2
            while k < n and buf[k] == SYNC:
                k += 1
            if k >= n:
                break                                     # need more bytes
            plength = buf[k]
            if plength > MAX_PLENGTH:
                self.stats.bad_length += 1
                i = k                                     # resync after the sync run
                continue
            end = k + 1 + plength                         # index of CHKSUM
            if end >= n:
                break                                     # need more bytes
            payload = bytes(buf[k + 1:end])
            if thinkgear_checksum(payload) != buf[end]:
                self.stats.bad_checksum += 1
                i = k                                     # a real packet may start in the payload
                continue
            packet = self._parse_payload(payload)
            if packet is None:
                self.stats.malformed += 1
            else:
                self.stats.packets += 1
                self.stats.raw_samples += len(packet.raw)
                out.append(packet)
            i = end + 1
        del buf[:i]
        if len(buf) > _MAX_BUFFER:                        # pragma: no cover - defensive
            drop = len(buf) - _MAX_BUFFER
            self.stats.skipped_bytes += drop
            del buf[:drop]
        return out

    def reset(self) -> None:
        """Drop buffered bytes (counters are kept)."""
        self._buf.clear()

    @staticmethod
    def _parse_payload(payload: bytes) -> ThinkGearPacket | None:
        """Walk the DataRows; None when a row runs past the end (checksum collision)."""
        raw: list[int] = []
        poor: int | None = None
        i, n = 0, len(payload)
        while i < n:
            level = 0
            while i < n and payload[i] == EXCODE:
                level += 1
                i += 1
            if i >= n:
                return None
            code = payload[i]
            i += 1
            if code >= 0x80:
                if i >= n:
                    return None
                vlen = payload[i]
                i += 1
            else:
                vlen = 1
            if i + vlen > n:
                return None
            value = payload[i:i + vlen]
            i += vlen
            if level != 0:
                continue                                  # extended codes: none defined
            if code == CODE_RAW and vlen == 2:
                raw.append(int.from_bytes(value, "big", signed=True))
            elif code == CODE_POOR_SIGNAL:
                poor = value[0]
            # everything else (eSense 0x04/0x05, band powers, unknown) is ignored on purpose
        return ThinkGearPacket(raw=tuple(raw), poor_signal=poor)


# ====================================================================================
# transport
# ====================================================================================


def import_serial() -> Any:
    """The ``serial`` (pyserial) module, imported lazily.

    Raises ``ImportError`` naming the ``emg`` extra that ships it.
    """
    try:
        import serial  # type: ignore[import-untyped]
    except ImportError as exc:
        hint = ""
        try:
            from yazses.system.remedy import install_hint

            hint = install_hint("emg")
        except Exception:  # pragma: no cover - the hint is a courtesy
            log.debug("install_hint('emg') failed", exc_info=True)
        # The remedy text comes from install_hint: a hard-coded `pip install` line is
        # wrong for pipx/uv-tool/system installs (tests/test_install_hints_are_for_end_users).
        raise ImportError(
            "pyserial is not installed; serial biosignal headsets need the YazSes 'emg' "
            "extra." + (f" {hint}" if hint else "")
        ) from exc
    return serial


def _open_serial(port: str, baudrate: int) -> Any:
    serial = import_serial()
    # timeout=0: non-blocking reads, so read() never stalls the caller's loop
    return serial.Serial(port, baudrate, timeout=0)


def _split_options(rest: str) -> tuple[str, str]:
    """``"<port>[:<options>]"`` -> (port, options). Options contain '=' or are a known flag."""
    port, sep, tail = rest.rpartition(":")
    if sep and ("=" in tail or tail.strip().lower() in _FLAG_OPTIONS):
        return port.strip(), tail.strip()
    return rest.strip(), ""


_FLAG_OPTIONS = frozenset({"simulated"})


def _parse_options(text: str) -> dict[str, str]:
    opts: dict[str, str] = {}
    for item in filter(None, (p.strip() for p in text.split(","))):
        key, sep, value = item.partition("=")
        opts[key.strip().lower()] = value.strip() if sep else ""
    return opts


_TG_SPEC_HELP = "expected 'thinkgear:<port>[:baud=<n>,name=<channel>]'"


def parse_thinkgear_spec(spec: str) -> dict[str, Any]:
    """``thinkgear:<port>[:baud=57600,name=Fp1]`` (scheme optional) -> constructor kwargs.

    Raises ``ValueError`` for a missing port or an unknown/malformed option.
    """
    text = spec.strip()
    if text.lower().startswith("thinkgear:"):
        text = text[len("thinkgear:"):]
    port, options = _split_options(text)
    if not port:
        raise ValueError(f"thinkgear spec {spec!r} has no serial port ({_TG_SPEC_HELP})")
    kw: dict[str, Any] = {"port": port}
    for key, value in _parse_options(options).items():
        if key == "baud":
            try:
                kw["baudrate"] = int(value)
            except ValueError:
                raise ValueError(f"thinkgear spec {spec!r}: baud must be an integer") from None
        elif key == "name":
            if not value:
                raise ValueError(f"thinkgear spec {spec!r}: name must not be empty")
            kw["channel_name"] = value
        else:
            raise ValueError(f"thinkgear spec {spec!r}: unknown option {key!r} ({_TG_SPEC_HELP})")
    return kw


def thinkgear_from_spec(spec: str, **kw: Any) -> ThinkGearSource:
    """Build a :class:`ThinkGearSource` from ``thinkgear:<port>[:<options>]`` (or the part
    after ``thinkgear:``). Extra keyword arguments override the spec's."""
    return ThinkGearSource(**{**parse_thinkgear_spec(spec), **kw})


class ThinkGearSource:
    """A NeuroSky ThinkGear headset (MindWave Mobile 2, TGAM boards) as a ``BlockSource``.

    One channel, ``channel_name`` (default ``"Fp1"``), of kind EEG at 512 Hz, in µV
    (``uv_scale`` µV per raw count, NeuroSky's nominal conversion by default). ``fs`` and
    ``channels`` are fixed by the protocol, so they are valid before ``start()``.

    ``read()`` drains whatever bytes the port has, returns every raw sample decoded so
    far as one block (``None`` when there is none yet), and updates
    :attr:`poor_signal` — the latest POOR_SIGNAL value (0 = no noise flagged, 200 = no
    skin contact, ``None`` until the headset has sent one). ``serial_factory`` is
    injected by tests (a fake port); production passes ``None`` and pyserial is opened
    on ``port`` at ``baudrate``.
    """

    def __init__(
        self,
        port: str,
        *,
        baudrate: int = THINKGEAR_BAUD,
        channel_name: str = "Fp1",
        uv_scale: float = THINKGEAR_RAW_TO_UV,
        serial_factory: Callable[[], Any] | None = None,
        read_chunk: int = _READ_CHUNK,
    ) -> None:
        if not channel_name.strip():
            raise ValueError("channel_name must not be empty")
        if read_chunk <= 0:
            raise ValueError("read_chunk must be > 0")
        self.port = port
        self.baudrate = int(baudrate)
        self.fs: float = THINKGEAR_FS
        self.channels: tuple[ChannelInfo, ...] = (ChannelInfo(channel_name, SignalKind.EEG),)
        self._uv_scale = float(uv_scale)
        self._serial_factory = serial_factory
        self._read_chunk = int(read_chunk)
        self._ser: Any = None
        self.parser = ThinkGearParser()
        self._emitted = 0
        self.poor_signal: int | None = None
        self.available = False
        self.last_error = ""
        self._reported_lost = 0

    @property
    def lost_packets(self) -> int:
        """Packets discarded by the parser (bad checksum, bad length, malformed)."""
        return self.parser.stats.rejected_packets

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._ser is not None:
            return
        self.available = False
        self.last_error = ""
        try:
            ser = (self._serial_factory() if self._serial_factory is not None
                   else _open_serial(self.port, self.baudrate))
        except ImportError as exc:
            self.last_error = str(exc)
            log.info("ThinkGear source disabled: %s", exc)
            return
        except Exception as exc:
            self._fail(f"ThinkGear headset on {self.port!r} unavailable ({exc}); "
                       "continuing without it.")
            return
        self._ser = ser
        self.parser = ThinkGearParser()
        self._emitted = 0
        self._reported_lost = 0
        self.poor_signal = None
        self.available = True
        log.info("ThinkGear source streaming from %s (1 channel at %g Hz).", self.port, self.fs)

    def read(self) -> SampleBlock | None:
        if not self.available or self._ser is None:
            return None
        try:
            waiting = int(getattr(self._ser, "in_waiting", 0) or 0)
            data = self._ser.read(max(waiting, self._read_chunk))
        except Exception as exc:
            self._fail(f"ThinkGear headset on {self.port!r} stopped streaming ({exc})")
            return None
        if not data:
            return None
        raw: list[int] = []
        for packet in self.parser.feed(data):
            raw.extend(packet.raw)
            if packet.poor_signal is not None:
                self.poor_signal = packet.poor_signal
        lost = self.lost_packets
        if lost > self._reported_lost:
            log.warning("ThinkGear %s: %d packet(s) rejected (checksum/length); no samples "
                        "were substituted (total %d).", self.port, lost - self._reported_lost, lost)
            self._reported_lost = lost
        if not raw:
            return None
        data_uv = np.asarray(raw, dtype=np.float64)[None, :] * self._uv_scale
        block = SampleBlock(data=data_uv, fs=self.fs, channels=self.channels,
                            t0=self._emitted / self.fs)
        self._emitted += len(raw)
        return block

    def stop(self) -> None:
        ser, self._ser = self._ser, None
        self.available = False
        if ser is not None:
            _close_quietly(ser)

    # ---- internals -------------------------------------------------------

    def _fail(self, message: str) -> None:
        self.last_error = message
        self.available = False
        log.warning("%s", message)
        ser, self._ser = self._ser, None
        if ser is not None:
            _close_quietly(ser)


def _close_quietly(ser: Any) -> None:
    try:
        ser.close()
    except Exception:  # pragma: no cover - teardown is best effort
        log.debug("closing serial port failed", exc_info=True)

