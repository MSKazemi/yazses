"""Lab Streaming Layer (LSL) as a :class:`~yazses.biosignal.types.BlockSource`.

LSL is the streaming protocol most research and consumer biosignal software can publish
to: OpenBCI GUI, Muse via muse-lsl / BlueMuse, Brain Products, g.tec g.NEEDaccess,
neuroelectrics NIC2, EmotivPRO, Wearable Sensing and others (the LSL project's list:
https://labstreaminglayer.readthedocs.io/info/supported_devices.html). Reading LSL means
YazSes needs no per-vendor driver: the vendor's own app owns the device, YazSes subscribes
to the stream it publishes. Scope is unchanged by the transport: artifact-grade switches
(EMG squeeze, blink, jaw clench) only — see ADR-v2-152.

## Nothing leaves the machine: discovery is pinned to this host

Out of the box liblsl discovers streams by UDP multicast across the *site* (the default
``ResolveScope``), and queries any ``KnownPeers`` by unicast. Both are network traffic
YazSes must not cause. Before the first liblsl call this module therefore pins liblsl's
configuration to a machine-only scope, twice over:

* ``pylsl.set_config_content(...)`` (liblsl >= 1.17.7) — in-memory content, which liblsl
  consults **before** every configuration file, including ``$LSLAPICFG``;
* ``LSLAPICFG`` pointed at a private ``lsl_api.cfg`` (a fresh ``0700`` temp directory, the
  file ``0600``) holding the same text — the fallback for an older liblsl (``LSLAPICFG``
  exists since liblsl 1.13). The variable is restored and the file deleted as soon as the
  first resolve has run, because liblsl reads its configuration exactly once per process,
  lazily, on first use.

The pinned text sets ``[multicast] ResolveScope = machine`` (query targets: only
``MachineAddresses``, multicast TTL 0), ``MachineAddresses = {127.0.0.1}`` (liblsl's own
default, pinned so a config file cannot widen it), ``TTLOverride = 0`` and
``[lab] KnownPeers = {}`` (no unicast peers). Key names, defaults and the precedence
order (content > ``LSLAPICFG`` > API-set filename > ``./lsl_api.cfg`` >
``~/lsl_api/lsl_api.cfg`` > ``/etc/lsl_api/lsl_api.cfg``) are read from liblsl's source,
``src/api_config.cpp``: https://github.com/sccn/liblsl/blob/main/src/api_config.cpp
(user-facing page: https://labstreaminglayer.readthedocs.io/info/lslapicfg.html).

**A user's own ``LSLAPICFG`` is deliberately overridden, never honoured** (design choice):
it may widen discovery to the LAN, and a headset on another computer is a new egress
decision under ADR-019, not a configuration knob. The override is logged at INFO. Because
liblsl's configuration is a once-per-process singleton, the pin only works if YazSes makes
the first liblsl call in the process. Nothing else in YazSes imports ``pylsl``; as a second
line of defence a stream whose ``hostname`` differs from this machine's is refused.

What the pin cannot control: the *publishing* app (OpenBCI GUI, BlueMuse, ...) runs its own
liblsl with its own configuration and may announce its stream on the LAN. That is the
vendor app's traffic, not YazSes's.

## Failure semantics: as BrainFlow — a missing stream is a logged no-op

``start()`` never raises: a missing ``pylsl`` (``ImportError`` naming the ``lsl`` extra), no
matching stream, an ambiguous match, an irregular-rate (``nominal_srate == 0``) or
non-numeric stream, or channel metadata that cannot be mapped to microvolts all leave the
source *unavailable* with the reason in ``last_error``; ``read()`` then returns ``None``.
Spec parsing, by contrast, raises ``ValueError``: there the user typed the input.

## Timestamps

LSL stamps every sample. ``t0`` is the first sample's LSL timestamp minus the first
timestamp ever seen (so a stream starts at ``0.0``, like :class:`BrainFlowBlockSource`).
Within :data:`_TS_TOLERANCE_S` of the running sample clock a timestamp is jitter and is
snapped; a larger forward jump is a gap — the pending block is closed, ``gap_samples``
grows by the estimated loss, and the clock resynchronises. The clock never runs backwards.
"""

from __future__ import annotations

import logging
import math
import os
import platform
import shutil
import tempfile
import threading
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import numpy as np

from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind

log = logging.getLogger(__name__)

__all__ = [
    "LIBLSL_CONFIG",
    "LSL_SPEC_HELP",
    "LSLBlockSource",
    "LslChannelMeta",
    "LslLayout",
    "LslSpec",
    "LslStreamError",
    "LslTimeline",
    "StreamSummary",
    "check_stream_usable",
    "is_local_host",
    "list_lsl_streams",
    "open_lsl_source",
    "parse_channel_metadata",
    "parse_lsl_spec",
    "resolve_channels",
    "select_stream",
    "unit_scale_to_uv",
]

_DEFAULT_BLOCK_SECONDS = 0.04          # same as sources.py: 25 blocks/s
_DEFAULT_TIMEOUT_SECONDS = 2.0         # resolve / full-info wait. Design choice.
# Inlet buffer, seconds. Small on purpose (design choice): a stalled reader must lose old
# samples (seen as a gap) rather than replay a minute of stale muscle activity as triggers.
_INLET_BUFFER_SECONDS = 5
_MAX_XML_BYTES = 1 << 20               # a stream description larger than this is ignored
_TS_TOLERANCE_S = 0.05                 # as sources.py: jitter below, a real gap above

LSL_SPEC_HELP = ("expected 'lsl:<stream name>', 'lsl:name=<name>', 'lsl:type=<type>' "
                 "(for example 'lsl:type=EEG') or 'lsl:source_id=<id>'")

#: The liblsl configuration pinned before the first liblsl call. No comments: keep the
#: text trivially parseable by every liblsl ini reader. See the module docstring.
LIBLSL_CONFIG = (
    "[multicast]\n"
    "ResolveScope = machine\n"
    "MachineAddresses = {127.0.0.1}\n"
    "TTLOverride = 0\n"
    "\n"
    "[lab]\n"
    "KnownPeers = {}\n"
)

# liblsl's lsl_channel_format_t values (pylsl.cf_*): numeric formats only. 3 is
# cf_string and 0 cf_undefined — neither carries a voltage.
_NUMERIC_FORMATS = {1: "float32", 2: "double64", 4: "int32", 5: "int16", 6: "int8",
                    7: "int64"}
_SPEC_PROPS = ("name", "type", "source_id")

# Channel / stream ``type`` strings that name an electrode signal YazSes can use. The XDF
# meta-data convention lists "EEG, EMG, EOG, ..." as channel types
# (https://github.com/sccn/xdf/wiki/EEG-Meta-Data). Anything else (ACC, AUX, PPG, ECG,
# Markers, ...) is excluded unless `channel_kinds` names the channel explicitly.
_TYPE_KINDS = {"eeg": SignalKind.EEG, "emg": SignalKind.EMG, "eog": SignalKind.EOG}

# Unit string (casefolded, spaces removed) -> factor into microvolts. Casefolding maps the
# micro sign U+00B5 onto Greek mu U+03BC, so "µV" and "μV" both land on "μv". "MV" is read
# as millivolts, not megavolts — no electrode reports megavolts. An empty unit is taken as
# microvolts, the XDF convention's "strongly preferred unit" (design choice).
_UNIT_SCALES = {
    "": 1.0, "uv": 1.0, "μv": 1.0, "microvolt": 1.0, "microvolts": 1.0,
    "mv": 1e3, "millivolt": 1e3, "millivolts": 1e3,
    "v": 1e6, "volt": 1e6, "volts": 1e6,
    "nv": 1e-3, "nanovolt": 1e-3, "nanovolts": 1e-3,
}


class LslStreamError(RuntimeError):
    """A stream that cannot be used: none found, ambiguous, or the wrong shape."""


# ====================================================================================
# 1. spec parsing and stream selection (pure)
# ====================================================================================


@dataclass(frozen=True)
class LslSpec:
    """Which stream to subscribe to: an LSL property and the exact value it must have."""

    prop: str                              # "name" | "type" | "source_id"
    value: str


def parse_lsl_spec(spec: str) -> LslSpec:
    """``"lsl:Muse"`` / ``"lsl:name=Muse"`` / ``"lsl:type=EEG"`` / ``"lsl:source_id=x"`` -> LslSpec.

    The text after the first colon is a stream *name*, unless what precedes its first
    ``=`` is one of ``name`` / ``type`` / ``source_id`` (case-insensitive) — so a stream
    literally called ``a=b`` still works as ``lsl:a=b``. Values are matched exactly, as
    LSL does. A single or double quote is refused: liblsl pastes the value unescaped into
    an XPath predicate between single quotes (``resolver_impl::build_query`` in
    https://github.com/sccn/liblsl/blob/main/src/resolver_impl.cpp), so a quote would
    change the query rather than match a name. Raises ``ValueError``.
    """
    scheme, sep, rest = spec.strip().partition(":")
    if not sep or scheme.strip().lower() != "lsl":
        raise ValueError(f"not an LSL spec {spec!r}; {LSL_SPEC_HELP}")
    key, eq, value = rest.partition("=")
    if eq and key.strip().lower() in _SPEC_PROPS:
        prop, value = key.strip().lower(), value.strip()
    else:
        prop, value = "name", rest.strip()
    if not value:
        raise ValueError(f"LSL spec {spec!r} names no stream; {LSL_SPEC_HELP}")
    if any(q in value for q in "'\"") or any(ord(c) < 32 for c in value):
        raise ValueError(f"LSL spec {spec!r}: quotes and control characters are not "
                         "allowed in a stream property")
    return LslSpec(prop, value)


@dataclass(frozen=True)
class StreamSummary:
    """The core fields of one resolved LSL stream (no channel metadata)."""

    name: str
    type: str
    source_id: str = ""
    hostname: str = ""
    uid: str = ""
    channel_count: int = 0
    nominal_srate: float = 0.0
    channel_format: int = 0

    def prop(self, prop: str) -> str:
        return {"name": self.name, "type": self.type, "source_id": self.source_id}[prop]

    def format(self) -> str:
        """One line for ``doctor`` / a stream listing."""
        fmt = _NUMERIC_FORMATS.get(self.channel_format, f"format {self.channel_format}")
        rate = f"{self.nominal_srate:g} Hz" if self.nominal_srate > 0 else "irregular rate"
        sid = f", source_id={self.source_id}" if self.source_id else ""
        return (f"{self.name!r} type={self.type!r}{sid}: {self.channel_count} channel(s), "
                f"{rate}, {fmt}")


def select_stream(candidates: Sequence[StreamSummary], spec: LslSpec) -> StreamSummary:
    """The one candidate matching ``spec``; ``LslStreamError`` for none or several.

    Duplicates of one outlet (the same ``uid`` reached twice) count once. Several distinct
    matches fail closed instead of picking one (design choice): subscribing to the wrong
    headset is a silent error, naming them all lets the user choose by ``source_id``.
    """
    seen: set[str] = set()
    matches: list[StreamSummary] = []
    for cand in candidates:
        if cand.prop(spec.prop) != spec.value:
            continue                       # the resolver should not return these; be sure
        key = cand.uid or f"{cand.name}\0{cand.source_id}\0{cand.hostname}"
        if key in seen:
            continue
        seen.add(key)
        matches.append(cand)
    if not matches:
        raise LslStreamError(f"no LSL stream with {spec.prop}={spec.value!r} on this machine "
                             "(is the publishing app streaming to LSL?)")
    if len(matches) > 1:
        listed = "; ".join(m.format() for m in matches)
        raise LslStreamError(f"{len(matches)} LSL streams match {spec.prop}={spec.value!r} "
                             f"({listed}); choose one with 'lsl:source_id=<id>' or by name")
    return matches[0]


def check_stream_usable(stream: StreamSummary) -> None:
    """Fail closed on a stream no artifact detector can read; ``LslStreamError`` says why."""
    srate = stream.nominal_srate
    if not math.isfinite(srate) or srate <= 0.0:
        raise LslStreamError(f"LSL stream {stream.name!r} has an irregular sampling rate "
                             f"(nominal_srate={srate:g}); detectors need a fixed rate")
    if stream.channel_format not in _NUMERIC_FORMATS:
        raise LslStreamError(f"LSL stream {stream.name!r} is not numeric (channel_format="
                             f"{stream.channel_format}); a marker/string stream is not ExG")
    if stream.channel_count < 1:
        raise LslStreamError(f"LSL stream {stream.name!r} has no channels")


def _short_host(name: str) -> str:
    return name.strip().split(".")[0].casefold()


def is_local_host(stream_host: str, local_host: str | None = None) -> bool:
    """True when ``stream_host`` is this machine (short name, case-insensitive), or empty.

    ``platform.node()`` is the comparison point; it is what liblsl's outlet reports as
    ``hostname`` on the same host. FQDN vs. short name and ``.local`` suffixes compare equal.
    """
    if not stream_host.strip():
        return True
    local = platform.node() if local_host is None else local_host
    return _short_host(stream_host) == _short_host(local)


# ====================================================================================
# 2. channel metadata -> ChannelInfo + microvolt scaling (pure)
# ====================================================================================


@dataclass(frozen=True)
class LslChannelMeta:
    """``desc/channels/channel`` as published: each field ``""`` when absent."""

    label: str = ""
    type: str = ""
    unit: str = ""


def parse_channel_metadata(xml_text: str) -> list[LslChannelMeta]:
    """Read ``desc/channels/channel/{label,type,unit}`` from a stream's ``as_xml()``.

    ``[]`` when there is no channel list, the XML does not parse, or it is larger than
    :data:`_MAX_XML_BYTES` (then the stream ``type`` alone decides the kinds). The XML comes
    from a local publisher; it is parsed with the standard library, which resolves no
    external entities, and size-capped as a defence against a hostile local process.
    """
    if not xml_text or len(xml_text.encode("utf-8", "replace")) > _MAX_XML_BYTES:
        if xml_text:
            log.warning("LSL stream description is larger than %d bytes; ignoring its "
                        "channel metadata", _MAX_XML_BYTES)
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        log.warning("LSL stream description is not valid XML; ignoring its channel metadata")
        return []

    def text(node: ET.Element, tag: str) -> str:
        child = node.find(tag)
        return (child.text or "").strip() if child is not None else ""

    return [LslChannelMeta(text(ch, "label"), text(ch, "type"), text(ch, "unit"))
            for ch in root.iterfind("./desc/channels/channel")]


def unit_scale_to_uv(unit: str) -> float | None:
    """Factor turning ``unit`` into microvolts; ``None`` for a unit that is not a voltage."""
    return _UNIT_SCALES.get("".join(unit.split()).casefold())


def _kind_of(type_text: str) -> SignalKind | None:
    return _TYPE_KINDS.get(type_text.strip().casefold())


def _coerce_kind(value: SignalKind | str) -> SignalKind:
    if isinstance(value, SignalKind):
        return value
    try:
        return SignalKind(str(value).strip().lower())
    except ValueError:
        valid = ", ".join(k.value for k in SignalKind)
        raise ValueError(f"unknown signal kind {value!r} (expected one of: {valid})") from None


@dataclass(frozen=True)
class LslLayout:
    """Which stream columns to keep, as which channels, and their factor into µV."""

    indices: tuple[int, ...]
    channels: tuple[ChannelInfo, ...]
    scales: tuple[float, ...]


def resolve_channels(
    stream_type: str,
    channel_count: int,
    metas: Sequence[LslChannelMeta],
    *,
    channel_kinds: Mapping[str, SignalKind | str] | None = None,
    uv_scale: float | None = None,
) -> LslLayout:
    """Map an LSL stream's columns to ``ChannelInfo`` and microvolt factors.

    * Labels come from the metadata, else ``<KIND><n>`` / ``CH<n>``; a repeated label gets
      ``#2``, ``#3`` so names stay unique keys. Metadata whose length differs from
      ``channel_count`` is ignored entirely (not aligned: do not guess).
    * A channel's own ``type`` decides its kind (``EEG`` / ``EMG`` / ``EOG``); a channel
      without one inherits the stream type. Any other type (``ACC``, ``AUX``, ``PPG`` ...)
      is dropped.
    * ``channel_kinds`` (label -> kind) is the override, as in BrainFlowBlockSource: only
      the named channels are kept, with the given kind — how Muse's ``Right AUX`` becomes
      an EMG electrode.
    * ``uv_scale`` overrides every unit; otherwise each kept channel's ``unit`` must be a
      voltage (V / mV / µV / nV, or empty = µV). Any other unit fails closed.

    Raises ``LslStreamError`` when nothing usable remains or a unit is not a voltage.
    """
    if metas and len(metas) != channel_count:
        log.warning("LSL stream describes %d channel(s) but carries %d; ignoring the "
                    "channel metadata", len(metas), channel_count)
        metas = ()
    stream_kind = _kind_of(stream_type)
    labels: list[str] = []
    kinds: list[SignalKind | None] = []
    units: list[str] = []
    counts: dict[str, int] = {}
    for i in range(channel_count):
        meta = metas[i] if metas else LslChannelMeta()
        kind = _kind_of(meta.type) if meta.type else stream_kind
        base = meta.label or (f"{kind.value.upper()}{i + 1}" if kind else f"CH{i + 1}")
        counts[base] = counts.get(base, 0) + 1
        labels.append(base if counts[base] == 1 else f"{base}#{counts[base]}")
        kinds.append(kind)
        units.append(meta.unit)

    if channel_kinds:
        wanted = {name: _coerce_kind(kind) for name, kind in channel_kinds.items()}
        unknown = sorted(set(wanted) - set(labels))
        if unknown:
            log.warning("channel_kinds names unknown LSL channel(s) %s (have: %s)",
                        unknown, ", ".join(labels))
        kinds = [wanted.get(label) for label in labels]

    keep = [(i, k) for i, k in enumerate(kinds) if k is not None]
    if not keep:
        raise LslStreamError(
            f"LSL stream (type {stream_type!r}) has no EEG/EMG/EOG channel YazSes can read; "
            f"name the channels to use with channel_kinds (have: {', '.join(labels)})")
    scales: list[float] = []
    for i, _ in keep:
        factor = float(uv_scale) if uv_scale is not None else unit_scale_to_uv(units[i])
        if factor is None or not math.isfinite(factor) or factor <= 0.0:
            raise LslStreamError(f"LSL channel {labels[i]!r} reports unit {units[i]!r}, "
                                 "which is not a voltage; pass uv_scale to convert it")
        scales.append(factor)
    return LslLayout(
        indices=tuple(i for i, _ in keep),
        channels=tuple(ChannelInfo(labels[i], k) for i, k in keep),
        scales=tuple(scales),
    )


# ====================================================================================
# 3. LSL timestamps -> block t0, gaps, and block assembly (pure)
# ====================================================================================


class LslTimeline:
    """Turn per-sample LSL timestamps into contiguous :class:`SampleBlock`s.

    ``push`` takes ``data`` (channels x samples, µV) and the matching LSL timestamps.
    Samples accumulate until at least ``min_samples`` are pending, then become one block
    (``pop``). A sample whose timestamp is more than ``tolerance_s`` *later* than the
    running clock predicts starts a new segment: the pending samples are released as a
    (possibly short) block first, ``gap_samples`` grows by the estimated loss, and the
    clock resynchronises. A timestamp that is early is jitter or a clock step back and is
    ignored — ``t0`` never decreases and blocks never overlap.

    Known limit (shared with BrainFlowBlockSource): the clock advances at the *nominal*
    rate. A device slower than nominal is periodically resynchronised (each time counted
    as a small gap); one faster than nominal is never pulled back, so ``t0`` runs ahead of
    the LSL clock by ``(1 - nominal/actual) x elapsed``.
    """

    def __init__(
        self,
        fs: float,
        channels: tuple[ChannelInfo, ...],
        *,
        min_samples: int = 1,
        tolerance_s: float = _TS_TOLERANCE_S,
    ) -> None:
        if not fs > 0:
            raise ValueError(f"fs must be positive, got {fs!r}")
        self.fs = float(fs)
        self.channels = channels
        self.min_samples = max(1, int(min_samples))
        self.tolerance_s = float(tolerance_s)
        self.origin: float | None = None   # first LSL timestamp seen; t0 is relative to it
        self.gap_samples = 0
        self._expected: float | None = None
        self._pending: list[np.ndarray] = []
        self._pending_n = 0
        self._pending_t0 = 0.0
        self._ready: deque[SampleBlock] = deque()

    def push(self, data: np.ndarray, timestamps: np.ndarray) -> None:
        data = np.asarray(data, dtype=np.float64)
        ts = np.array(timestamps, dtype=np.float64).reshape(-1)
        n = int(data.shape[1]) if data.ndim == 2 else 0
        if n == 0:
            return
        if ts.shape[0] != n:
            raise ValueError(f"{n} sample(s) but {ts.shape[0]} timestamp(s)")
        ts[~np.isfinite(ts)] = np.nan       # NaN = "no usable timestamp": treated as on time
        if self.origin is None:
            finite = ts[np.isfinite(ts)]
            self.origin = float(finite[0]) if finite.size else 0.0
        rel = ts - self.origin
        i = 0
        while i < n:
            if self._expected is None:
                self._expected = float(rel[i]) if np.isfinite(rel[i]) else 0.0
            ahead = rel[i:] - (self._expected + np.arange(n - i) / self.fs)
            # NaN compares False: a missing timestamp is treated as on time.
            late = np.flatnonzero(ahead > self.tolerance_s)
            j = int(late[0]) if late.size else n - i
            if j == 0:
                gap = float(ahead[0])
                lost = int(round(gap * self.fs))
                self.gap_samples += lost
                log.warning("LSL stream: ~%d sample(s) (%.3f s) missing before t=%.3f s",
                            lost, gap, float(rel[i]))
                self._release()
                self._expected = float(rel[i])
                continue
            self._append(data[:, i:i + j])
            i += j
        if self._pending_n >= self.min_samples:
            self._release()

    def pop(self) -> SampleBlock | None:
        return self._ready.popleft() if self._ready else None

    def _append(self, part: np.ndarray) -> None:
        assert self._expected is not None
        if not self._pending:
            self._pending_t0 = self._expected
        self._pending.append(part)
        self._pending_n += int(part.shape[1])
        self._expected += part.shape[1] / self.fs

    def _release(self) -> None:
        if not self._pending:
            return
        data = np.concatenate(self._pending, axis=1)
        self._ready.append(SampleBlock(data=data, fs=self.fs, channels=self.channels,
                                       t0=self._pending_t0))
        self._pending, self._pending_n = [], 0


# ====================================================================================
# 4. liblsl confinement and the pylsl import
# ====================================================================================

_PIN_LOCK = threading.Lock()
_pinned = False                            # liblsl has loaded our config in this process


def _import_pylsl() -> Any:
    """The ``pylsl`` module, or ``ImportError`` that names the ``lsl`` extra."""
    try:
        import pylsl
    except ImportError as exc:
        from yazses.system.remedy import install_hint

        raise ImportError(
            "pylsl is not installed, so the LSL biosignal source is unavailable "
            "(it comes with YazSes's 'lsl' extra). "
            + (install_hint("lsl") or "")
        ) from exc
    return pylsl


@contextmanager
def _liblsl_confined() -> Iterator[Any]:
    """Yield ``pylsl`` with liblsl pinned to machine-only discovery for its first call.

    Run the first resolve *inside* the ``with``: liblsl loads its configuration once, on
    first use. Afterwards ``LSLAPICFG`` is restored to the user's value (or unset) and the
    private file is removed; later calls just import (the singleton is already ours).
    """
    global _pinned
    with _PIN_LOCK:
        if _pinned:
            yield _import_pylsl()
            return
        tmpdir = tempfile.mkdtemp(prefix="yazses-lsl-")        # 0700 on POSIX
        path = os.path.join(tmpdir, "lsl_api.cfg")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, LIBLSL_CONFIG.encode("utf-8"))
        finally:
            os.close(fd)
        prior = os.environ.get("LSLAPICFG")
        if prior:
            log.info("Ignoring LSLAPICFG=%s for YazSes' LSL source: discovery is pinned to "
                     "this machine (a wider scope would be network egress).", prior)
        os.environ["LSLAPICFG"] = path
        try:
            pylsl = _import_pylsl()
            setter = getattr(pylsl, "set_config_content", None)
            if callable(setter):
                try:
                    setter(LIBLSL_CONFIG)
                except NotImplementedError:
                    log.debug("liblsl < 1.17.7: relying on LSLAPICFG for the machine scope")
            yield pylsl
            _pinned = True
        finally:
            if prior is None:
                os.environ.pop("LSLAPICFG", None)
            else:
                os.environ["LSLAPICFG"] = prior
            shutil.rmtree(tmpdir, ignore_errors=True)


def _summarize(info: Any) -> StreamSummary:
    """A pylsl ``StreamInfo`` as a plain :class:`StreamSummary`."""

    def field(name: str, default: Any) -> Any:
        try:
            return getattr(info, name)()
        except Exception:
            return default

    return StreamSummary(
        name=str(field("name", "")),
        type=str(field("type", "")),
        source_id=str(field("source_id", "")),
        hostname=str(field("hostname", "")),
        uid=str(field("uid", "")),
        channel_count=int(field("channel_count", 0)),
        nominal_srate=float(field("nominal_srate", 0.0)),
        channel_format=int(field("channel_format", 0)),
    )


def list_lsl_streams(timeout_s: float = 1.0) -> list[StreamSummary]:
    """Every LSL stream visible *on this machine*, for ``doctor``. ``ImportError`` without pylsl."""
    with _liblsl_confined() as pylsl:
        infos = pylsl.resolve_streams(wait_time=float(timeout_s))
    return [_summarize(i) for i in infos]


# ====================================================================================
# 5. the source
# ====================================================================================


class LSLBlockSource:
    """One LSL stream on this machine as a :class:`BlockSource`.

    ``stream`` is matched exactly against the LSL property ``prop`` (``"name"``,
    ``"type"`` or ``"source_id"``); exactly one distinct stream must match. ``timeout_s``
    bounds the resolve and the full-description fetch in ``start()``. ``block_s`` is the
    minimum block length (``0`` = whatever arrived); a gap closes a block early.
    ``channel_kinds`` and ``uv_scale`` are as in :func:`resolve_channels`.

    ``fs`` / ``channels`` are ``0.0`` / ``()`` until ``start()`` succeeds; check
    ``available`` afterwards — when ``False`` the reason is in ``last_error`` and
    ``read()`` returns ``None`` (a logged no-op, never a crash). ``stream_info`` holds the
    subscribed stream's summary, ``gap_samples`` the estimated samples lost so far.
    """

    def __init__(
        self,
        stream: str,
        *,
        prop: str = "name",
        timeout_s: float = _DEFAULT_TIMEOUT_SECONDS,
        block_s: float = _DEFAULT_BLOCK_SECONDS,
        channel_kinds: Mapping[str, SignalKind | str] | None = None,
        uv_scale: float | None = None,
    ) -> None:
        prop = prop.strip().lower()
        if prop not in _SPEC_PROPS:
            raise ValueError(f"prop must be one of {', '.join(_SPEC_PROPS)}, got {prop!r}")
        # Same validation as a typed spec: quotes would rewrite liblsl's query.
        self._spec = parse_lsl_spec(f"lsl:{prop}={stream}")
        if not (math.isfinite(timeout_s) and timeout_s > 0):
            raise ValueError(f"timeout_s must be positive, got {timeout_s!r}")
        if not (math.isfinite(block_s) and block_s >= 0):
            raise ValueError(f"block_s must be >= 0, got {block_s!r}")
        self._timeout_s = float(timeout_s)
        self._block_s = float(block_s)
        self._channel_kinds = dict(channel_kinds) if channel_kinds else None
        self._uv_scale = uv_scale
        self._inlet: Any = None
        self._layout: LslLayout | None = None
        self._timeline: LslTimeline | None = None
        self._n_columns = 0
        self._max_pull = 1024
        self.fs: float = 0.0
        self.channels: tuple[ChannelInfo, ...] = ()
        self.stream_info: StreamSummary | None = None
        self.available = False
        self.last_error = ""

    @property
    def spec(self) -> LslSpec:
        return self._spec

    @property
    def gap_samples(self) -> int:
        return self._timeline.gap_samples if self._timeline is not None else 0

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._inlet is not None:
            return
        self.available = False
        self.last_error = ""
        inlet = None
        try:
            with _liblsl_confined() as pylsl:
                infos = pylsl.resolve_byprop(self._spec.prop, self._spec.value,
                                             minimum=1, timeout=self._timeout_s)
            summaries = [_summarize(i) for i in infos]
            chosen = select_stream(summaries, self._spec)
            info = infos[summaries.index(chosen)]
            check_stream_usable(chosen)
            if not is_local_host(chosen.hostname):
                raise LslStreamError(
                    f"LSL stream {chosen.name!r} is published by host {chosen.hostname!r}, "
                    f"not this machine ({platform.node()!r}); only local streams are read")
            inlet = pylsl.StreamInlet(
                info, max_buflen=_INLET_BUFFER_SECONDS, max_chunklen=0, recover=True,
                processing_flags=int(getattr(pylsl, "proc_clocksync", 1)))
            full = inlet.info(timeout=self._timeout_s)
            metas = parse_channel_metadata(str(full.as_xml()))
            layout = resolve_channels(chosen.type, chosen.channel_count, metas,
                                      channel_kinds=self._channel_kinds,
                                      uv_scale=self._uv_scale)
            inlet.open_stream(timeout=self._timeout_s)
        except ImportError as exc:
            self._fail(str(exc), inlet, level=logging.INFO)
            return
        except Exception as exc:
            self._fail(f"LSL stream {self._spec.prop}={self._spec.value!r} unavailable "
                       f"({exc}); continuing without it.", inlet)
            return
        fs = float(chosen.nominal_srate)
        self._inlet, self._layout = inlet, layout
        self._n_columns = chosen.channel_count
        self._max_pull = max(1024, int(fs))            # up to ~1 s per pull
        self._timeline = LslTimeline(
            fs, layout.channels, min_samples=max(1, int(round(self._block_s * fs))))
        self.fs, self.channels, self.stream_info = fs, layout.channels, chosen
        self.available = True
        log.info("LSL block source streaming %s (%d of %d channel(s) at %g Hz).",
                 chosen.format(), len(layout.channels), chosen.channel_count, fs)

    def read(self) -> SampleBlock | None:
        """The next contiguous block, or ``None`` if not enough has arrived yet."""
        if not self.available or self._inlet is None or self._timeline is None:
            return None
        ready = self._timeline.pop()
        if ready is not None:
            return ready
        try:
            samples, stamps = self._inlet.pull_chunk(timeout=0.0, max_samples=self._max_pull)
        except Exception as exc:
            self._fail(f"LSL stream {self._spec.value!r} stopped streaming ({exc})",
                       self._inlet)
            return None
        if samples is None or len(samples) == 0:
            return None
        block = self._convert(samples, stamps)
        if block is not None:
            self._timeline.push(*block)
        return self._timeline.pop()

    def stop(self) -> None:
        inlet, self._inlet = self._inlet, None
        self.available = False
        if inlet is not None:
            self._close(inlet)

    # ---- internals -------------------------------------------------------

    def _convert(self, samples: Any, stamps: Any) -> tuple[np.ndarray, np.ndarray] | None:
        layout = self._layout
        assert layout is not None
        try:
            raw = np.asarray(samples, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            self._fail(f"LSL stream {self._spec.value!r} sent non-numeric samples ({exc})",
                       self._inlet)
            return None
        if raw.ndim != 2 or raw.shape[1] != self._n_columns:
            self._fail(f"LSL stream {self._spec.value!r} sent samples of shape {raw.shape}; "
                       f"expected (n, {self._n_columns})", self._inlet)
            return None
        data = raw[:, list(layout.indices)].T * np.asarray(layout.scales)[:, None]
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
        return data, np.asarray(stamps, dtype=np.float64)

    def _fail(self, message: str, inlet: Any | None, *, level: int = logging.WARNING) -> None:
        self.last_error = message
        self.available = False
        log.log(level, "%s", message)
        if inlet is not None:
            self._close(inlet)
        if inlet is self._inlet:
            self._inlet = None

    @staticmethod
    def _close(inlet: Any) -> None:
        try:
            inlet.close_stream()
        except Exception:  # pragma: no cover - teardown is best effort
            log.debug("LSL close_stream failed", exc_info=True)


def open_lsl_source(spec: str, **kw: Any) -> LSLBlockSource:
    """``open_source`` helper: an unstarted :class:`LSLBlockSource` for an ``lsl:...`` spec."""
    parsed = parse_lsl_spec(spec)
    return LSLBlockSource(parsed.value, prop=parsed.prop, **kw)
