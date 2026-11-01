"""EDF, EDF+ and BDF/BDF+ files: read real recordings, write ones other tools open.

Pure numpy + stdlib — no ``pyedflib`` or ``mne``. EDF is the format nearly every EEG/EMG
device's software exports (OpenBCI GUI, EDFbrowser, MNE, BioSemi ActiView, g.tec, Emotiv)
and the one most public datasets ship in (PhysioNet's EEG Motor Movement/Imagery and
Sleep-EDF, for example), so this module is what lets a detector be scored on a labelled
real recording instead of only on the synthetic generator.

## Specifications followed

* EDF — https://www.edfplus.info/specs/edf.html (header layout, field widths, 2-byte
  two's-complement samples) and the EDF FAQ https://www.edfplus.info/specs/edffaq.html
  (Q10: samples are little-endian; Q6: gain = (phys max - phys min) / (dig max - dig min);
  Q11: ``-1`` records only while recording).
* EDF+ — https://www.edfplus.info/specs/edfplus.html (``EDF+C`` / ``EDF+D`` in the
  reserved field, the ``EDF Annotations`` signal, TALs, the per-record time-keeping TAL,
  UTF-8 annotation text, ``X`` for unknown identification subfields).
* BDF — https://www.biosemi.com/faq/file_format.htm (first byte 255 then ``BIOSEMI``,
  ``24BIT`` in the 44-byte field, digital range -8388608..8388607, the trailing ``Status``
  channel) and BDF+ — https://www.teuniz.net/edfbrowser/bdfplus%20format%20description.html
  (``BDF+C`` / ``BDF+D``, ``BDF Annotations``, 3-byte little-endian two's complement).

Digital-to-physical scaling is the linear map that sends the digital extremes onto the
physical extremes: ``phys = (dig - dig_min) * gain + phys_min`` with the FAQ's ``gain``.

## Reading (:func:`load_edf`)

The reader is defensive: a header whose numbers do not parse, whose byte count disagrees
with its signal count, a file shorter than its records, an absurd size (``max_bytes``) or a
truncated final record raises ``ValueError`` naming the field. It never allocates more
than the bytes actually present in the file. Free-text header fields are decoded as
Latin-1 (the spec allows only ASCII 32..126, but real files carry accented names and a
``µ`` in ``µV``); numeric fields must be ASCII numbers.

**Channel selection.** EDF lets every signal have its own rate; a :class:`SampleBlock`
has one. The reader therefore returns *one* rate group:

* ``channels=[...]`` — exactly those labels, in that order; they must share a rate.
* ``fs=...`` — every eligible signal recorded at that rate.
* neither — the rate shared by the most eligible signals (ties: the higher rate; a design
  choice, since an artifact detector wants bandwidth).

A signal is *eligible* for automatic selection when its physical dimension is a voltage
(``nV``/``uV``/``µV``/``mV``/``V``, case-insensitive, also spelled out) and its label maps
to a :class:`SignalKind` (see :func:`guess_kind`) or has an entry in ``kinds=``. So a BDF
``Status`` channel (dimension ``Boo``), a temperature or an ECG channel stays out unless
named. Every selected signal is scaled to microvolts.

**Kinds.** :func:`guess_kind` is a heuristic: an ``EMG``/``EOG``/``EEG`` token in the label,
then in the transducer type, then a 10-20/10-10 electrode name (``Fp1``, ``Cz``, ``C3-A2``,
PhysioNet's ``Fc5.``), then ``LOC``/``ROC``/``chin``. ``ECG``/``EKG``, respiration,
temperature and trigger labels map to ``None`` (not a kind a detector reads). Anything
else gets ``default_kind`` (EEG). Override any of it with ``kinds={"EXG1": "emg"}``.

**Time.** ``t0`` is the time-keeping onset of the first data record (0 for plain EDF), and
event times are seconds after the header's start date/time — the same clock the replayed
samples use. An ``EDF+D`` (interrupted) file is replayed with its gaps closed, so every
annotation onset is moved onto that gapless timeline (``t0 + record_index * duration +
offset_in_record``); an annotation that falls inside a gap has no sample and is dropped
with a warning.

**Annotations → ground truth.** Annotation text is normalised (lower case, ``_``/``-`` as
spaces) and looked up in an event map (:data:`DEFAULT_EVENT_MAP`, or ``event_map=``) to an
:class:`EventKind`. A ``squeeze`` annotation with a duration also yields a ``SQUEEZE_OFF``
at its end, because ``evaluate`` scores the release as its own kind. Unmapped annotations
are kept in ``annotations`` and simply produce no event. A malformed TAL is skipped with a
warning rather than failing the whole file (a design choice: the samples are still good).

## Writing (:func:`write_edf`)

Always EDF+C (16-bit) or BDF+C (24-bit), so the file carries a time-keeping annotation
signal and, optionally, ``BioEvent``s as annotations (text = ``EventKind.value``, which
:data:`DEFAULT_EVENT_MAP` maps back). The file is created with mode ``0o600``: a recording
is raw biometric-adjacent signal — keep it local.

* **Physical range** — by default each channel's own ``[min, max]`` (at least 1 µV wide),
  rounded *outward* to what fits the 8-character header field, so nothing clips and the
  quantisation step is ``range / 65535`` (EDF) or ``range / 16777215`` (BDF). An explicit
  ``physical_range=(lo, hi)`` applies to every channel and **clips** samples outside it
  (counted in a warning).
* **Records** — ``record_seconds`` (default 1 s) must hold a whole number of samples. The
  last record is padded by repeating the final sample (edge padding, so no step is added);
  a reader therefore sees up to one record more than was written.
* **Identification** — defaults are the spec's anonymous values: patient ``X X X X``,
  recording ``Startdate X X X YazSes``, start ``01.01.85 00.00.00``. Pass ``start=`` to
  record the real date.
* Labels are the channel names verbatim (≤16 printable ASCII characters); the kind goes in
  the transducer field (``"EMG electrode"``), which :func:`guess_kind` reads back.
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SampleBlock, SignalKind

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_EVENT_MAP",
    "Annotation",
    "EdfHeader",
    "EdfRecording",
    "EdfSignal",
    "annotation_kind",
    "annotations_to_events",
    "guess_kind",
    "load_edf",
    "read_edf_header",
    "unit_scale",
    "write_edf",
]

_FIXED_HEADER = 256
_EDF_VERSION = b"0       "
_BDF_VERSION = b"\xffBIOSEMI"
_EDF_DIGITAL = (-32768, 32767)
_BDF_DIGITAL = (-8388608, 8388607)
_ANNOTATION_LABELS = ("EDF Annotations", "BDF Annotations")
_EDF_RECORD_LIMIT = 61440        # EDF spec's recommended maximum data-record size, bytes
_DEFAULT_MAX_BYTES = 2 << 30     # 2 GiB of sample data: a sanity cap, not a format limit
_MAX_SIGNALS = 9999              # the 4-character ``ns`` field cannot say more
_TAL_SEP = 0x14                  # 20: ends every annotation text
_TAL_DUR = 0x15                  # 21: separates onset from duration
_ONSET_RE = re.compile(r"^[+-]\d+(\.\d*)?$")
_DURATION_RE = re.compile(r"^\d+(\.\d*)?$")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


# ====================================================================================
# data classes
# ====================================================================================


@dataclass(frozen=True)
class EdfSignal:
    """One signal's header entry, verbatim (strings stripped)."""

    label: str
    transducer: str
    physical_dimension: str
    physical_min: float
    physical_max: float
    digital_min: int
    digital_max: int
    prefiltering: str
    samples_per_record: int

    @property
    def is_annotation(self) -> bool:
        return self.label in _ANNOTATION_LABELS


@dataclass(frozen=True)
class EdfHeader:
    """The parsed header. ``variant`` is ``EDF``, ``EDF+C``, ``EDF+D``, ``BDF``, ``BDF+C``
    or ``BDF+D``; ``n_records`` is the number actually present in the file."""

    variant: str
    patient: str
    recording: str
    start_date: str
    start_time: str
    header_bytes: int
    n_records: int
    record_duration: float
    signals: tuple[EdfSignal, ...]

    @property
    def bytes_per_sample(self) -> int:
        return 3 if self.variant.startswith("BDF") else 2

    @property
    def record_bytes(self) -> int:
        return sum(s.samples_per_record for s in self.signals) * self.bytes_per_sample

    @property
    def discontinuous(self) -> bool:
        return self.variant.endswith("+D")


@dataclass(frozen=True)
class Annotation:
    """One EDF+ annotation: ``onset`` in seconds after the file start, optional duration."""

    onset: float
    text: str
    duration: float | None = None


@dataclass(frozen=True)
class EdfRecording:
    """What :func:`load_edf` returns: one rate group, scaled to µV, plus ground truth.

    ``data`` is ``(n_channels, n_samples)`` float64 in microvolts; ``events`` are the
    annotations that map to an :class:`EventKind`, on the replay clock (see module
    docstring); ``annotations`` are all of them, on the file's own clock.
    """

    data: np.ndarray
    fs: float
    channels: tuple[ChannelInfo, ...]
    t0: float
    events: tuple[BioEvent, ...]
    annotations: tuple[Annotation, ...]
    header: EdfHeader

    @property
    def n_samples(self) -> int:
        return int(self.data.shape[1])

    @property
    def duration(self) -> float:
        return self.n_samples / self.fs


# ====================================================================================
# units, kinds, event names
# ====================================================================================

_UNIT_SCALE: dict[str, float] = {
    "nv": 1e-3, "nanovolt": 1e-3, "nanovolts": 1e-3,
    "uv": 1.0, "µv": 1.0, "μv": 1.0, "microvolt": 1.0, "microvolts": 1.0,
    "mv": 1e3, "millivolt": 1e3, "millivolts": 1e3,
    "v": 1e6, "volt": 1e6, "volts": 1e6,
}


def unit_scale(unit: str | None) -> float | None:
    """Factor that converts ``unit`` to microvolts, or ``None`` if it is not a voltage.

    Case-insensitive (``mV`` and ``MV`` are both millivolts — no biosignal is in megavolts).
    """
    if unit is None:
        return None
    return _UNIT_SCALE.get(unit.strip().lower())


_TOKEN = r"(?<![A-Za-z]){}(?![A-Za-z])"
_KIND_TOKENS: tuple[tuple[re.Pattern[str], SignalKind | None], ...] = (
    (re.compile(_TOKEN.format("EMG"), re.I), SignalKind.EMG),
    (re.compile(_TOKEN.format("EOG"), re.I), SignalKind.EOG),
    (re.compile(_TOKEN.format("[HV]EOG"), re.I), SignalKind.EOG),
    (re.compile(_TOKEN.format("EEG"), re.I), SignalKind.EEG),
    (re.compile(_TOKEN.format("(?:ECG|EKG)"), re.I), None),
)
# Labels that are clearly not an electrode a detector reads (respiration, temperature,
# triggers, oximetry...). Matched as whole words.
_NOT_A_KIND = re.compile(
    r"(?<![A-Za-z])(?:resp\w*|temp\w*|status|trigger|marker|event|spo2|pleth|pulse|"
    r"flow|thor\w*|abdo\w*|snore|light|position|acc\w*|gyro\w*)(?![A-Za-z])", re.I)
# 10-20 / 10-10 electrode names (Fp1, AF3, Fz, FT7, C3, CP5, TP9, T7, P3, PO8, O1, Iz,
# Nz, A1/A2, M1/M2), possibly bipolar ("C3-A2") and with PhysioNet's trailing dots.
_TEN_TWENTY = re.compile(r"^(?:Nz|Fp|AF|FT|FC|F|T|TP|CP|C|P|PO|O|I|A|M)(?:z|\d{1,2})$", re.I)
_EOG_NAMES = re.compile(r"^(?:LOC|ROC)$", re.I)
_EMG_NAMES = re.compile(r"^(?:chin|submental)$", re.I)


def guess_kind(
    label: str,
    transducer: str = "",
    default: SignalKind | None = SignalKind.EEG,
) -> SignalKind | None:
    """Heuristic :class:`SignalKind` for an EDF label (see the module docstring).

    Returns ``None`` for a channel that is recognisably *not* EEG/EMG/EOG (ECG, resp,
    triggers), and ``default`` for one that says nothing about itself.
    """
    for text in (label, transducer):
        for pattern, kind in _KIND_TOKENS:
            if pattern.search(text):
                return kind
    if _NOT_A_KIND.search(label):
        return None
    head = re.split(r"[-\s/]", label.strip(), maxsplit=1)[0].rstrip(".")
    if _TEN_TWENTY.match(head):
        return SignalKind.EEG
    if _EOG_NAMES.match(head):
        return SignalKind.EOG
    if _EMG_NAMES.match(head):
        return SignalKind.EMG
    return default


def _normalise_text(text: str) -> str:
    return " ".join(text.replace("_", " ").replace("-", " ").lower().split())


#: Annotation text (normalised: lower case, ``_``/``-`` as spaces) -> event kind. Every
#: ``EventKind.value`` is included, so a file written by :func:`write_edf` maps back.
DEFAULT_EVENT_MAP: Mapping[str, EventKind] = {
    "blink": EventKind.BLINK,
    "eye blink": EventKind.BLINK,
    "eyeblink": EventKind.BLINK,
    "double blink": EventKind.DOUBLE_BLINK,
    "doubleblink": EventKind.DOUBLE_BLINK,
    "jaw clench": EventKind.JAW_CLENCH,
    "clench": EventKind.JAW_CLENCH,
    "teeth clench": EventKind.JAW_CLENCH,
    "squeeze": EventKind.SQUEEZE_ON,
    "squeeze on": EventKind.SQUEEZE_ON,
    "squeeze off": EventKind.SQUEEZE_OFF,
}


def _coerce_event_kind(value: EventKind | str) -> EventKind:
    if isinstance(value, EventKind):
        return value
    try:
        return EventKind(str(value).strip().lower())
    except ValueError:
        valid = ", ".join(k.value for k in EventKind)
        raise ValueError(f"unknown event kind {value!r} (expected one of: {valid})") from None


def _prepare_map(event_map: Mapping[str, EventKind | str] | None) -> dict[str, EventKind]:
    if event_map is None:
        return dict(DEFAULT_EVENT_MAP)
    return {_normalise_text(k): _coerce_event_kind(v) for k, v in event_map.items()}


def annotation_kind(
    text: str, event_map: Mapping[str, EventKind | str] | None = None
) -> EventKind | None:
    """The :class:`EventKind` an annotation text names, or ``None``.

    ``event_map`` *replaces* the default; to extend it pass
    ``{**DEFAULT_EVENT_MAP, "my label": "blink"}``.
    """
    return _prepare_map(event_map).get(_normalise_text(text))


def annotations_to_events(
    annotations: Iterable[Annotation],
    event_map: Mapping[str, EventKind | str] | None = None,
    *,
    source: str = "edf",
) -> list[BioEvent]:
    """Map annotations to ground-truth :class:`BioEvent`s, sorted by time.

    A ``SQUEEZE_ON`` annotation with a positive duration also yields a ``SQUEEZE_OFF`` at
    ``onset + duration``. Times are taken as they are (no clock conversion).
    """
    table = _prepare_map(event_map)
    events: list[BioEvent] = []
    for ann in annotations:
        kind = table.get(_normalise_text(ann.text))
        if kind is None:
            continue
        detail: dict = {"annotation": ann.text, "source": source}
        if ann.duration is not None:
            detail["duration"] = ann.duration
        events.append(BioEvent(kind=kind, t=ann.onset, detail=detail))
        if kind is EventKind.SQUEEZE_ON and ann.duration:
            events.append(BioEvent(kind=EventKind.SQUEEZE_OFF, t=ann.onset + ann.duration,
                                   detail=dict(detail)))
    events.sort(key=lambda e: e.t)
    return events


# ====================================================================================
# reading
# ====================================================================================


def _text(raw: bytes) -> str:
    return raw.decode("latin-1").strip()


def _number(raw: bytes, field: str, path: Path, *, integer: bool = False) -> float:
    try:
        value = float(raw.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        raise ValueError(f"{path}: header field '{field}' is not a number: {raw!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{path}: header field '{field}' is not finite: {raw!r}")
    if integer and not value.is_integer():
        raise ValueError(f"{path}: header field '{field}' is not an integer: {raw!r}")
    return value


def _split(block: bytes, ns: int, width: int) -> list[bytes]:
    return [block[i * width:(i + 1) * width] for i in range(ns)]


def _parse_header(path: Path, file_size: int, max_bytes: int) -> EdfHeader:
    with path.open("rb") as fh:
        fixed = fh.read(_FIXED_HEADER)
        if len(fixed) < _FIXED_HEADER:
            raise ValueError(f"{path}: {len(fixed)} bytes is too short for an EDF/BDF header")
        version = fixed[0:8]
        if version == _BDF_VERSION:
            bdf = True
        elif version == _EDF_VERSION:
            bdf = False
        else:
            raise ValueError(f"{path}: not an EDF or BDF file (version field {version!r})")
        reserved = _text(fixed[192:236])
        header_bytes = int(_number(fixed[184:192], "number of bytes in header", path,
                                   integer=True))
        n_records = int(_number(fixed[236:244], "number of data records", path, integer=True))
        record_duration = _number(fixed[244:252], "duration of a data record", path)
        ns = int(_number(fixed[252:256], "number of signals", path, integer=True))
        if not 1 <= ns <= _MAX_SIGNALS:
            raise ValueError(f"{path}: number of signals must be 1..{_MAX_SIGNALS}, got {ns}")
        if header_bytes != _FIXED_HEADER * (ns + 1):
            raise ValueError(f"{path}: header says {header_bytes} bytes but {ns} signals "
                             f"need {_FIXED_HEADER * (ns + 1)}")
        if header_bytes > file_size:
            raise ValueError(f"{path}: file ({file_size} bytes) is shorter than its header "
                             f"({header_bytes} bytes)")
        if record_duration < 0:
            raise ValueError(f"{path}: negative data-record duration {record_duration}")
        if n_records < -1:
            raise ValueError(f"{path}: invalid number of data records {n_records}")
        sig = fh.read(header_bytes - _FIXED_HEADER)
    if len(sig) != header_bytes - _FIXED_HEADER:
        raise ValueError(f"{path}: signal header is truncated")

    widths = (("label", 16), ("transducer type", 80), ("physical dimension", 8),
              ("physical minimum", 8), ("physical maximum", 8), ("digital minimum", 8),
              ("digital maximum", 8), ("prefiltering", 80),
              ("nr of samples in each data record", 8), ("reserved", 32))
    columns: dict[str, list[bytes]] = {}
    offset = 0
    for name, width in widths:
        columns[name] = _split(sig[offset:offset + ns * width], ns, width)
        offset += ns * width

    signals: list[EdfSignal] = []
    for i in range(ns):
        label = _text(columns["label"][i])
        where = f"signal {i + 1} ({label!r})"
        spr = int(_number(columns["nr of samples in each data record"][i],
                          f"{where} samples per record", path, integer=True))
        dmin = int(_number(columns["digital minimum"][i], f"{where} digital minimum", path,
                           integer=True))
        dmax = int(_number(columns["digital maximum"][i], f"{where} digital maximum", path,
                           integer=True))
        pmin = _number(columns["physical minimum"][i], f"{where} physical minimum", path)
        pmax = _number(columns["physical maximum"][i], f"{where} physical maximum", path)
        if spr < 1:
            raise ValueError(f"{path}: {where} has {spr} samples per record (must be >= 1)")
        if dmax <= dmin:
            raise ValueError(f"{path}: {where} digital maximum {dmax} is not above its "
                             f"minimum {dmin}")
        if pmax == pmin:
            raise ValueError(f"{path}: {where} physical minimum and maximum are both {pmin}")
        signals.append(EdfSignal(
            label=label, transducer=_text(columns["transducer type"][i]),
            physical_dimension=_text(columns["physical dimension"][i]),
            physical_min=pmin, physical_max=pmax, digital_min=dmin, digital_max=dmax,
            prefiltering=_text(columns["prefiltering"][i]), samples_per_record=spr))

    prefix = "BDF" if bdf else "EDF"
    variant = prefix
    for suffix in ("+C", "+D"):
        if reserved.startswith(prefix + suffix):
            variant = prefix + suffix

    bps = 3 if bdf else 2
    record_bytes = sum(s.samples_per_record for s in signals) * bps
    available = file_size - header_bytes
    if n_records == -1:
        n_records, rest = divmod(available, record_bytes)
        log.warning("%s: number of data records is -1 (recording was not closed); "
                    "derived %d from the file size", path, n_records)
        if rest:
            raise ValueError(f"{path}: last data record is truncated ({rest} of "
                             f"{record_bytes} bytes)")
    else:
        needed = n_records * record_bytes
        if available < needed:
            raise ValueError(f"{path}: header promises {n_records} data records "
                             f"({needed} bytes) but the file holds {available} bytes — "
                             f"truncated recording")
        if available > needed:
            log.warning("%s: %d trailing bytes after the last data record ignored",
                        path, available - needed)
    if n_records * record_bytes > max_bytes:
        raise ValueError(f"{path}: {n_records * record_bytes} bytes of samples exceeds "
                         f"max_bytes={max_bytes}; raise it if this file is genuine")
    return EdfHeader(
        variant=variant, patient=_text(fixed[8:88]), recording=_text(fixed[88:168]),
        start_date=_text(fixed[168:176]), start_time=_text(fixed[176:184]),
        header_bytes=header_bytes, n_records=n_records, record_duration=record_duration,
        signals=tuple(signals))


def read_edf_header(
    path: str | os.PathLike[str], *, max_bytes: int = _DEFAULT_MAX_BYTES
) -> EdfHeader:
    """Parse and validate only the header (cheap; reads no samples)."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"recording not found: {p}")
    return _parse_header(p, p.stat().st_size, max_bytes)


def _decode_samples(raw: np.ndarray, bps: int) -> np.ndarray:
    """``raw`` is (..., n*bps) uint8 -> (..., n) int32, little-endian two's complement."""
    if bps == 2:
        return np.ascontiguousarray(raw).view("<i2").astype(np.int32)
    b = raw.reshape(*raw.shape[:-1], -1, 3).astype(np.int32)
    value = b[..., 0] | (b[..., 1] << 8) | (b[..., 2] << 16)
    return np.where(value >= 1 << 23, value - (1 << 24), value).astype(np.int32)


def _parse_tals(raw: bytes) -> tuple[list[Annotation], float | None, int]:
    """Annotations in one record's annotation bytes, its time-keeping onset, bad TAL count."""
    out: list[Annotation] = []
    keeping: float | None = None
    bad = 0
    first = True
    for chunk in raw.split(b"\x00"):
        if not chunk:
            continue
        parts = chunk.split(bytes([_TAL_SEP]))
        if len(parts) < 2 or parts[-1] != b"":
            bad += 1
            first = False
            continue
        stamp, texts = parts[0], parts[1:-1]
        onset_raw, _, dur_raw = stamp.partition(bytes([_TAL_DUR]))
        try:
            onset_s = onset_raw.decode("ascii")
            dur_s = dur_raw.decode("ascii")
        except UnicodeDecodeError:
            bad += 1
            first = False
            continue
        if not _ONSET_RE.match(onset_s) or (dur_s and not _DURATION_RE.match(dur_s)):
            bad += 1
            first = False
            continue
        onset = float(onset_s)
        duration = float(dur_s) if dur_s else None
        decoded = [t.decode("utf-8", errors="replace") for t in texts]
        if first and decoded and decoded[0] == "":
            keeping = onset
            decoded = decoded[1:]
        first = False
        out.extend(Annotation(onset=onset, text=t, duration=duration) for t in decoded if t)
    return out, keeping, bad


def _select(
    header: EdfHeader,
    channels: Sequence[str] | None,
    fs: float | None,
    kinds: Mapping[str, SignalKind | str],
    default_kind: SignalKind | None,
    path: Path,
) -> list[tuple[int, SignalKind]]:
    dur = header.record_duration
    rate = [s.samples_per_record / dur for s in header.signals]
    by_label = {s.label: i for i, s in enumerate(header.signals) if not s.is_annotation}

    def kind_of(i: int) -> SignalKind | None:
        s = header.signals[i]
        if s.label in kinds:
            return _coerce_signal_kind(kinds[s.label])
        return guess_kind(s.label, s.transducer, default_kind)

    if channels is not None:
        picked: list[tuple[int, SignalKind]] = []
        for name in channels:
            if name not in by_label:
                raise ValueError(f"{path}: no signal labelled {name!r} (have: "
                                 f"{', '.join(by_label)})")
            i = by_label[name]
            kind = kind_of(i)
            if kind is None:
                raise ValueError(f"{path}: cannot tell what {name!r} measures — give it a "
                                 f"kind with kinds={{{name!r}: 'emg'}}")
            if unit_scale(header.signals[i].physical_dimension) is None:
                dim = header.signals[i].physical_dimension
                if dim:
                    raise ValueError(f"{path}: {name!r} is in {dim!r}, not a voltage")
                log.warning("%s: %r has no physical dimension; assuming microvolts",
                            path, name)
            picked.append((i, kind))
        rates = {rate[i] for i, _ in picked}
        if len(rates) > 1:
            listing = ", ".join(f"{header.signals[i].label}={rate[i]:g} Hz" for i, _ in picked)
            raise ValueError(f"{path}: selected channels have different sampling rates "
                             f"({listing}); select channels that share one")
        if not picked:
            raise ValueError(f"{path}: channels=[] selects nothing")
        return picked

    eligible: list[tuple[int, SignalKind]] = []
    for i in by_label.values():
        kind = kind_of(i)
        if kind is not None and unit_scale(header.signals[i].physical_dimension) is not None:
            eligible.append((i, kind))
    if not eligible:
        listing = ", ".join(f"{s.label} [{s.physical_dimension or '?'}]"
                            for s in header.signals if not s.is_annotation)
        raise ValueError(f"{path}: no EEG/EMG/EOG voltage signal found ({listing}); name "
                         f"them with channels= and kinds=")
    groups: dict[float, list[tuple[int, SignalKind]]] = {}
    for i, kind in eligible:
        groups.setdefault(rate[i], []).append((i, kind))
    if fs is not None:
        for r, members in groups.items():
            if math.isclose(r, fs, rel_tol=1e-9, abs_tol=1e-6):
                return members
        raise ValueError(f"{path}: no eligible signal at {fs:g} Hz (rates: "
                         f"{', '.join(f'{r:g}' for r in sorted(groups))})")
    best = max(groups, key=lambda r: (len(groups[r]), r))
    if len(groups) > 1:
        dropped = [header.signals[i].label for r, m in groups.items() if r != best
                   for i, _ in m]
        log.info("%s: using the %g Hz group; other-rate signals skipped: %s",
                 path, best, ", ".join(dropped))
    return groups[best]


def _coerce_signal_kind(value: SignalKind | str) -> SignalKind:
    if isinstance(value, SignalKind):
        return value
    try:
        return SignalKind(str(value).strip().lower())
    except ValueError:
        valid = ", ".join(k.value for k in SignalKind)
        raise ValueError(f"unknown signal kind {value!r} (expected one of: {valid})") from None


def _gapless(onset: float, starts: np.ndarray, dur: float, t0: float) -> float | None:
    """Move an onset on the file clock onto the replay's gapless clock (None: in a gap)."""
    i = int(np.searchsorted(starts, onset + 1e-9, side="right")) - 1
    if i < 0:
        return None
    offset = float(onset - starts[i])
    if offset > dur + 1e-9:
        return None
    return float(t0 + i * dur + offset)


def load_edf(
    path: str | os.PathLike[str],
    *,
    channels: Sequence[str] | None = None,
    fs: float | None = None,
    kinds: Mapping[str, SignalKind | str] | None = None,
    default_kind: SignalKind | None = SignalKind.EEG,
    event_map: Mapping[str, EventKind | str] | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> EdfRecording:
    """Read an EDF/EDF+/BDF/BDF+ file into one µV rate group plus ground-truth events.

    See the module docstring for how channels, kinds, units and times are chosen.
    Raises ``FileNotFoundError`` for a missing file and ``ValueError`` for a malformed one.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"recording not found: {p}")
    header = _parse_header(p, p.stat().st_size, max_bytes)
    if header.record_duration <= 0:
        raise ValueError(f"{p}: data-record duration is {header.record_duration}; an "
                         f"annotation-only file has no samples to replay")
    if header.n_records == 0:
        raise ValueError(f"{p}: the file holds no data records")
    picked = _select(header, channels, fs, kinds or {}, default_kind, p)

    bps = header.bytes_per_sample
    n_rec = header.n_records
    with p.open("rb") as fh:
        fh.seek(header.header_bytes)
        raw = np.frombuffer(fh.read(n_rec * header.record_bytes), dtype=np.uint8)
    if raw.size != n_rec * header.record_bytes:     # file shrank between stat and read
        raise ValueError(f"{p}: file is truncated")
    records = raw.reshape(n_rec, header.record_bytes)
    offsets = np.cumsum([0] + [s.samples_per_record * bps for s in header.signals])

    rows: list[np.ndarray] = []
    infos: list[ChannelInfo] = []
    for i, kind in picked:
        s = header.signals[i]
        digital = _decode_samples(records[:, offsets[i]:offsets[i + 1]], bps).reshape(-1)
        gain = (s.physical_max - s.physical_min) / (s.digital_max - s.digital_min)
        scale = unit_scale(s.physical_dimension) or 1.0
        rows.append(((digital - s.digital_min) * gain + s.physical_min) * scale)
        infos.append(ChannelInfo(name=s.label, kind=kind))
    data = np.ascontiguousarray(np.vstack(rows), dtype=np.float64)
    rate = header.signals[picked[0][0]].samples_per_record / header.record_duration

    annotations: list[Annotation] = []
    starts = np.arange(n_rec, dtype=np.float64) * header.record_duration
    keeping_seen = False
    bad = 0
    ann_idx = [i for i, s in enumerate(header.signals) if s.is_annotation]
    for r in range(n_rec):
        for j, i in enumerate(ann_idx):
            chunk = records[r, offsets[i]:offsets[i + 1]].tobytes()
            found, keeping, n_bad = _parse_tals(chunk)
            annotations.extend(found)
            bad += n_bad
            if j == 0 and keeping is not None:
                starts[r] = keeping
                keeping_seen = True
    if bad:
        log.warning("%s: %d malformed annotation list(s) skipped", p, bad)
    t0 = float(starts[0]) if keeping_seen else 0.0
    if keeping_seen and not header.discontinuous:
        expected = t0 + np.arange(n_rec) * header.record_duration
        if np.max(np.abs(starts - expected)) > 1e-3:
            log.warning("%s: record time-keeping is not contiguous although the file "
                        "is not marked EDF+D; replay closes the gaps", p)

    on_clock: list[Annotation] = []
    in_gap = 0
    for ann in annotations:
        t = _gapless(ann.onset, starts, header.record_duration, t0)
        if t is None:
            in_gap += 1
            continue
        on_clock.append(Annotation(onset=t, text=ann.text, duration=ann.duration))
    if in_gap:
        log.warning("%s: %d annotation(s) fall outside the recorded samples (in a gap, "
                    "or before/after the recording); dropped from the events", p, in_gap)
    events = annotations_to_events(on_clock, event_map, source=p.suffix.lower().lstrip("."))
    return EdfRecording(data=data, fs=float(rate), channels=tuple(infos), t0=t0,
                        events=tuple(events), annotations=tuple(annotations), header=header)


# ====================================================================================
# writing
# ====================================================================================


def _ascii_field(value: str, width: int, what: str) -> bytes:
    if any(not 32 <= ord(c) <= 126 for c in value):
        raise ValueError(f"{what} {value!r} must be printable ASCII (EDF header rule)")
    if len(value) > width:
        raise ValueError(f"{what} {value!r} is longer than {width} characters")
    return value.ljust(width).encode("ascii")


def _fit_number(value: float, *, round_down: bool) -> str:
    """Shortest-precision text of ``value`` that fits 8 characters, rounded outward."""
    for decimals in range(6, -1, -1):
        factor = 10.0 ** decimals
        q = (math.floor if round_down else math.ceil)(value * factor) / factor
        text = f"{q:.{decimals}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        if text == "-0":
            text = "0"
        if len(text) <= 8:
            return text
    raise ValueError(f"physical limit {value!r} does not fit the 8-character EDF field")


def _fmt_seconds(value: float, *, signed: bool) -> str:
    text = f"{abs(value):.6f}".rstrip("0").rstrip(".") or "0"
    if signed:
        return ("-" if value < 0 else "+") + text
    return text


def _tal(onset: float, text: str = "", duration: float | None = None,
         timekeeping: bool = False) -> bytes:
    head = _fmt_seconds(onset, signed=True).encode("ascii")
    if duration is not None and duration > 0:
        head += bytes([_TAL_DUR]) + _fmt_seconds(duration, signed=False).encode("ascii")
    body = bytes([_TAL_SEP])
    if timekeeping:
        body += bytes([_TAL_SEP])
    if text:
        body += text.encode("utf-8") + bytes([_TAL_SEP])
    return head + body + b"\x00"


def _check_annotation_text(text: str) -> str:
    if any(c in text for c in ("\x00", "\x14", "\x15")):
        raise ValueError(f"annotation text {text!r} contains a reserved TAL byte")
    return text


def _start_fields(start: datetime | None) -> tuple[str, str, str]:
    """(dd.mm.yy, hh.mm.ss, recording-field start date) — anonymous when ``start`` is None."""
    if start is None:
        return "01.01.85", "00.00.00", "Startdate X"
    if not 1985 <= start.year <= 2084:
        raise ValueError("EDF can only store start years 1985..2084")
    return (f"{start.day:02d}.{start.month:02d}.{start.year % 100:02d}",
            f"{start.hour:02d}.{start.minute:02d}.{start.second:02d}",
            f"Startdate {start.day:02d}-{_MONTHS[start.month - 1]}-{start.year}")


def write_edf(
    path: str | os.PathLike[str],
    blocks: Iterable[SampleBlock],
    *,
    events: Iterable[BioEvent] = (),
    annotations: Iterable[Annotation] = (),
    fmt: str | None = None,
    record_seconds: float = 1.0,
    physical_range: tuple[float, float] | None = None,
    start: datetime | None = None,
    patient: str = "X X X X",
    recording: str | None = None,
) -> int:
    """Write blocks as EDF+C (``fmt="edf"``) or BDF+C (``"bdf"``); returns samples written.

    ``fmt=None`` picks BDF for a ``.bdf`` suffix and EDF otherwise. ``events`` are stored
    as annotations named ``EventKind.value`` at ``event.t - first_block.t0`` (a reader sees
    the recording start at t=0); ``annotations`` are written as given (onset relative to
    the first sample). Buffers every block in memory, like ``write_npz``. The file is
    created with mode ``0o600``. See the module docstring for ranges, padding and clipping.
    """
    target = Path(path).expanduser()
    fmt = (fmt or ("bdf" if target.suffix.lower() == ".bdf" else "edf")).lower()
    if fmt not in ("edf", "bdf"):
        raise ValueError(f"fmt must be 'edf' or 'bdf', not {fmt!r}")
    bdf = fmt == "bdf"

    chunks: list[np.ndarray] = []
    first: SampleBlock | None = None
    for block in blocks:
        if first is None:
            first = block
        elif block.channels != first.channels or block.fs != first.fs:
            raise ValueError("channels or sampling rate changed mid-recording")
        chunks.append(np.asarray(block.data, dtype=np.float64))
    if first is None:
        raise ValueError("no blocks to write")
    data = np.concatenate(chunks, axis=1)
    if not np.all(np.isfinite(data)):
        log.warning("%s: non-finite samples written as 0 (treated as a dropout)", target)
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    n_ch, n = data.shape
    fs = float(first.fs)

    if not record_seconds > 0:
        raise ValueError("record_seconds must be > 0")
    spr_f = fs * record_seconds
    spr = round(spr_f)
    if spr < 1 or abs(spr_f - spr) > 1e-6:
        raise ValueError(f"fs={fs:g} Hz x record_seconds={record_seconds:g} is not a whole "
                         f"number of samples; choose another record_seconds")
    n_rec = max(1, math.ceil(n / spr))
    if n_rec * spr > n:
        pad = np.repeat(data[:, -1:], n_rec * spr - n, axis=1)
        data = np.concatenate([data, pad], axis=1)

    dmin, dmax = _BDF_DIGITAL if bdf else _EDF_DIGITAL
    lows: list[str] = []
    highs: list[str] = []
    clipped = 0
    digital = np.empty(data.shape, dtype=np.int32)
    for c in range(n_ch):
        x = data[c]
        if physical_range is None:
            lo, hi = float(x.min()), float(x.max())
            if hi - lo < 1.0:
                mid = (hi + lo) / 2
                lo, hi = mid - 0.5, mid + 0.5
        else:
            lo, hi = (float(v) for v in physical_range)
            if not hi > lo:
                raise ValueError("physical_range must be (low, high) with high > low")
        lo_s, hi_s = _fit_number(lo, round_down=True), _fit_number(hi, round_down=False)
        lows.append(lo_s)
        highs.append(hi_s)
        plo, phi = float(lo_s), float(hi_s)
        clipped += int(np.count_nonzero((x < plo) | (x > phi)))
        d = np.rint((np.clip(x, plo, phi) - plo) / (phi - plo) * (dmax - dmin) + dmin)
        digital[c] = np.clip(d, dmin, dmax).astype(np.int32)
    if clipped:
        log.warning("%s: %d sample(s) outside physical_range were clipped", target, clipped)

    # Annotations, each in the record whose time span holds its onset.
    t_origin = float(first.t0)
    notes: list[tuple[float, str, float | None]] = []
    for ev in events:
        notes.append((ev.t - t_origin, ev.kind.value, None))
    for ann in annotations:
        notes.append((ann.onset, _check_annotation_text(ann.text), ann.duration))
    per_record: list[list[bytes]] = [[_tal(r * record_seconds, timekeeping=True)]
                                     for r in range(n_rec)]
    for onset, text, duration in sorted(notes, key=lambda x: x[0]):
        if not text:
            continue
        r = min(max(int(math.floor(onset / record_seconds)), 0), n_rec - 1)
        per_record[r].append(_tal(onset, text, duration))
    bps = 3 if bdf else 2
    ann_bytes = max(sum(len(t) for t in tals) for tals in per_record)
    ann_spr = max(1, math.ceil(ann_bytes / bps))
    ann_block = np.zeros((n_rec, ann_spr * bps), dtype=np.uint8)
    for r, tals in enumerate(per_record):
        blob = b"".join(tals)
        ann_block[r, :len(blob)] = np.frombuffer(blob, dtype=np.uint8)

    record_bytes = (n_ch * spr + ann_spr) * bps
    if not bdf and record_bytes > _EDF_RECORD_LIMIT:
        log.warning("%s: data records are %d bytes, above EDF's recommended %d; most "
                    "readers accept it, or lower record_seconds", target, record_bytes,
                    _EDF_RECORD_LIMIT)

    # Header.
    for info in first.channels:
        _ascii_field(info.name, 16, "channel name")
    date_s, time_s, rec_start = _start_fields(start)
    rec_text = recording if recording is not None else f"{rec_start} X X YazSes"
    ns = n_ch + 1
    ann_label = "BDF Annotations" if bdf else "EDF Annotations"
    labels = [c.name for c in first.channels] + [ann_label]
    transducers = [f"{c.kind.value.upper()} electrode" for c in first.channels] + [""]
    dims = ["uV"] * n_ch + [""]
    pmins = lows + ["-1"]
    pmaxs = highs + ["1"]
    dmins = [str(dmin)] * ns
    dmaxs = [str(dmax)] * ns
    sprs = [str(spr)] * n_ch + [str(ann_spr)]
    for info in first.channels:
        guessed = guess_kind(info.name, f"{info.kind.value.upper()} electrode")
        if guessed is not info.kind:
            log.warning("%s: channel %r (%s) will read back as %s; pass kinds= to "
                        "load_edf", target, info.name, info.kind.value,
                        guessed.value if guessed else "unknown")

    header = bytearray()
    header += _BDF_VERSION if bdf else _EDF_VERSION
    header += _ascii_field(patient, 80, "patient identification")
    header += _ascii_field(rec_text, 80, "recording identification")
    header += _ascii_field(date_s, 8, "start date")
    header += _ascii_field(time_s, 8, "start time")
    header += _ascii_field(str(_FIXED_HEADER * (ns + 1)), 8, "header bytes")
    header += _ascii_field("BDF+C" if bdf else "EDF+C", 44, "reserved")
    header += _ascii_field(str(n_rec), 8, "number of data records")
    header += _ascii_field(_fmt_seconds(record_seconds, signed=False), 8, "record duration")
    header += _ascii_field(str(ns), 4, "number of signals")
    for values, width, what in ((labels, 16, "label"), (transducers, 80, "transducer"),
                                (dims, 8, "physical dimension"), (pmins, 8, "physical min"),
                                (pmaxs, 8, "physical max"), (dmins, 8, "digital min"),
                                (dmaxs, 8, "digital max"), ([""] * ns, 80, "prefiltering"),
                                (sprs, 8, "samples per record"), ([""] * ns, 32, "reserved")):
        for v in values:
            header += _ascii_field(v, width, what)
    if len(header) != _FIXED_HEADER * (ns + 1):     # pragma: no cover - internal invariant
        raise AssertionError("EDF header size mismatch")

    # Data records: (n_rec, n_ch, spr) little-endian ints, then the annotation bytes.
    per = digital.reshape(n_ch, n_rec, spr).transpose(1, 0, 2)
    if bdf:
        as_bytes = np.ascontiguousarray(per).astype("<i4").view(np.uint8)
        sample_bytes = as_bytes.reshape(n_rec, n_ch, spr, 4)[..., :3].reshape(n_rec, -1)
    else:
        sample_bytes = np.ascontiguousarray(per).astype("<i2").view(np.uint8).reshape(n_rec, -1)
    body = np.concatenate([sample_bytes, ann_block], axis=1)

    from yazses.biosignal.sources import _open_private  # lazy: sources may import this module

    fh = _open_private(target, text=False)
    try:
        fh.write(bytes(header))
        fh.write(body.tobytes())
    finally:
        fh.close()
    return int(n)
