"""XDF recordings (Lab Streaming Layer / LabRecorder) via the optional ``pyxdf`` package.

XDF is the file LabRecorder writes when it records Lab Streaming Layer streams, so any
device with an LSL outlet — OpenBCI GUI's LSL widget, ``muselsl``, BrainFlow's streamer,
g.tec, Emotiv, a marker stream from a stimulus program — ends up in one. Format:
https://github.com/sccn/xdf/wiki/Specifications ; channel metadata follows the
``desc/channels/channel`` convention (``label``, ``type``, ``unit``) of
https://github.com/sccn/xdf/wiki/EEG-Meta-Data , whose "strongly preferred unit" is
microvolts.

``pyxdf`` is imported **lazily**, inside :func:`load_xdf` / :func:`list_xdf_streams`
only, so a base install imports this module fine; calling either without the package
raises ``ImportError`` naming the ``xdf`` extra.

## How a recording becomes one sample stream

* **Stream** — ``stream=`` (exact name) and/or ``stream_type=`` (case-insensitive) pick
  it. With neither, the single numeric regular-rate stream is used; with several, the one
  typed ``EEG``/``EMG``/``EOG``/``ExG``, and if that is still ambiguous a ``ValueError``
  lists them (a design choice: guessing between two headsets is worse than asking).
* **Channels** — labels, types and units come from ``desc/channels/channel``; a stream
  without that metadata gets ``ch1``, ``ch2``, ... A channel's kind is ``kinds[label]``,
  else its ``<type>`` (``ECG``/``AUX``/``ACC``/... mean "not an electrode we read"), else
  :func:`yazses.biosignal.edf.guess_kind` on the label with the stream's type (or EEG) as
  the default for a label that says nothing. Automatic selection keeps the channels whose kind is EEG/EMG/EOG and whose
  unit is a voltage (or absent); ``channels=[...]`` picks labels explicitly.
* **Units** — scaled to microvolts by the same table as EDF. A channel **with no unit is
  assumed to be in microvolts** (LSL's preferred unit, and what OpenBCI and BrainFlow
  outlets send); that is an assumption, logged once.
* **Time** — XDF time stamps are LSL clock seconds. Replay is gapless at the nominal rate
  starting at ``t0 = 0``; every marker time stamp is moved onto that timeline by
  interpolating against the stream's own sample time stamps, so an event stays on the
  sample it was recorded next to even when samples were dropped. Markers outside the
  stream's time span are dropped with a warning.
* **Markers → ground truth** — string streams (and irregular-rate numeric streams) are
  marker streams; each sample's first value is the annotation text, mapped through the
  same event map as EDF (:data:`yazses.biosignal.edf.DEFAULT_EVENT_MAP`, or
  ``event_map=``). ``marker_streams=[names]`` restricts which ones are read.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from yazses.biosignal.edf import Annotation, annotations_to_events, guess_kind, unit_scale
from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SignalKind

log = logging.getLogger(__name__)

__all__ = [
    "XdfRecording",
    "list_xdf_streams",
    "load_xdf",
]

_EXTRA = "xdf"
_EXG_TYPES = ("eeg", "emg", "eog", "exg")
# Channel <type> values that name something other than an electrode a detector reads.
_NON_EXG_TYPES = frozenset({
    "ecg", "ekg", "aux", "acc", "accel", "accelerometer", "gyro", "gyroscope", "misc",
    "stim", "trigger", "marker", "markers", "resp", "temp", "ppg", "gsr", "eda", "spo2",
})


@dataclass(frozen=True)
class XdfRecording:
    """What :func:`load_xdf` returns. ``data`` is ``(n_channels, n_samples)`` float64 µV."""

    data: np.ndarray
    fs: float
    channels: tuple[ChannelInfo, ...]
    t0: float
    events: tuple[BioEvent, ...]
    annotations: tuple[Annotation, ...]
    stream_name: str
    stream_type: str
    effective_srate: float | None

    @property
    def n_samples(self) -> int:
        return int(self.data.shape[1])

    @property
    def duration(self) -> float:
        return self.n_samples / self.fs


def _import_pyxdf() -> Any:
    try:
        import pyxdf  # type: ignore[import-not-found,unused-ignore]
    except ModuleNotFoundError:
        from yazses.system.remedy import install_hint

        raise ImportError(
            f"reading .xdf files needs the optional 'pyxdf' package — install the "
            f"'{_EXTRA}' extra. " + (install_hint(_EXTRA) or "")
        ) from None
    return pyxdf


def _first(node: Any, key: str) -> Any:
    """``node[key][0]`` for pyxdf's list-wrapped XML dicts, or None at any missing step."""
    if not isinstance(node, Mapping):
        return None
    value = node.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _text(node: Any, key: str) -> str:
    value = _first(node, key)
    return value.strip() if isinstance(value, str) else ""


def _srate(info: Any) -> float:
    try:
        return float(_text(info, "nominal_srate") or 0.0)
    except ValueError:
        return 0.0


def _channel_meta(info: Any, n_ch: int, where: str) -> list[tuple[str, str, str]]:
    """``(label, type, unit)`` per channel from ``desc/channels/channel``."""
    channels = _first(_first(info, "desc"), "channels")
    entries = channels.get("channel") if isinstance(channels, Mapping) else None
    if isinstance(entries, list) and len(entries) == n_ch:
        meta = []
        for i, entry in enumerate(entries):
            label = _text(entry, "label") or _text(entry, "name") or f"ch{i + 1}"
            meta.append((label, _text(entry, "type"), _text(entry, "unit")))
        return meta
    if entries:
        log.warning("%s: channel metadata lists %d channels but the stream has %d; "
                    "using generic names", where, len(entries), n_ch)
    return [(f"ch{i + 1}", "", "") for i in range(n_ch)]


def _as_kind(text: str) -> SignalKind | None:
    try:
        return SignalKind(text.strip().lower())
    except ValueError:
        return None


def _is_signal(stream: Mapping[str, Any]) -> bool:
    ts = stream.get("time_series")
    return (isinstance(ts, np.ndarray) and ts.ndim == 2 and ts.dtype.kind in "fiu"
            and _srate(stream.get("info")) > 0)


def _describe(stream: Mapping[str, Any]) -> str:
    info = stream.get("info")
    return (f"{_text(info, 'name') or '?'!r} (type {_text(info, 'type') or '?'}, "
            f"{_srate(info):g} Hz)")


def _pick_stream(streams: Sequence[Mapping[str, Any]], name: str | None,
                 stream_type: str | None, where: str) -> Mapping[str, Any]:
    candidates = [s for s in streams if _is_signal(s)]
    if name is not None:
        candidates = [s for s in candidates if _text(s.get("info"), "name") == name]
    if stream_type is not None:
        wanted = stream_type.strip().lower()
        candidates = [s for s in candidates
                      if _text(s.get("info"), "type").lower() == wanted]
    if len(candidates) > 1 and name is None and stream_type is None:
        exg = [s for s in candidates if _text(s.get("info"), "type").lower() in _EXG_TYPES]
        if exg:
            candidates = exg
    if len(candidates) == 1:
        return candidates[0]
    listing = "; ".join(_describe(s) for s in streams) or "none"
    if not candidates:
        raise ValueError(f"{where}: no numeric regular-rate stream matches "
                         f"(name={name!r}, type={stream_type!r}); streams: {listing}")
    raise ValueError(f"{where}: {len(candidates)} streams match — choose one with stream= "
                     f"or stream_type=; streams: {listing}")


def _replay_times(marker_ts: np.ndarray, stamps: np.ndarray, fs: float) -> np.ndarray:
    """Marker LSL times -> seconds on the gapless replay clock (NaN outside the stream)."""
    if stamps.size == 0:
        return np.full(marker_ts.shape, np.nan)
    if np.any(np.diff(stamps) < 0):
        stamps = np.maximum.accumulate(stamps)
    replay = np.arange(stamps.size, dtype=np.float64) / fs
    out = np.interp(marker_ts, stamps, replay)
    half = 0.5 / fs
    outside = (marker_ts < stamps[0] - half) | (marker_ts > stamps[-1] + half)
    out[outside] = np.nan
    return out


def list_xdf_streams(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """The stream headers in an XDF file (``pyxdf.resolve_streams``), without the samples."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"recording not found: {p}")
    pyxdf = _import_pyxdf()
    try:
        return list(pyxdf.resolve_streams(str(p)))
    except Exception as exc:
        raise ValueError(f"{p}: not a readable XDF file ({exc})") from exc


def load_xdf(
    path: str | os.PathLike[str],
    *,
    stream: str | None = None,
    stream_type: str | None = None,
    channels: Sequence[str] | None = None,
    kinds: Mapping[str, SignalKind | str] | None = None,
    default_kind: SignalKind | None = SignalKind.EEG,
    marker_streams: Sequence[str] | None = None,
    event_map: Mapping[str, EventKind | str] | None = None,
) -> XdfRecording:
    """Read one signal stream of an XDF file into µV samples plus marker ground truth.

    See the module docstring for stream/channel selection, units and timing. Raises
    ``FileNotFoundError``, ``ImportError`` (no ``pyxdf``; install the ``xdf`` extra) or
    ``ValueError`` (unreadable file, no/ambiguous stream, bad channel selection).
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"recording not found: {p}")
    pyxdf = _import_pyxdf()
    try:
        loaded = pyxdf.load_xdf(str(p))
    except Exception as exc:
        raise ValueError(f"{p}: not a readable XDF file ({exc})") from exc
    streams = list(loaded[0]) if isinstance(loaded, tuple) else list(loaded)
    where = str(p)
    chosen = _pick_stream(streams, stream, stream_type, where)
    info = chosen.get("info")
    ts = np.asarray(chosen["time_series"])
    fs = _srate(info)
    s_name, s_type = _text(info, "name"), _text(info, "type")
    meta = _channel_meta(info, ts.shape[1], where)
    stream_kind = _as_kind(s_type)
    overrides = dict(kinds or {})

    def kind_of(label: str, ch_type: str) -> SignalKind | None:
        if label in overrides:
            value = overrides[label]
            return value if isinstance(value, SignalKind) else _coerce(value)
        if (explicit := _as_kind(ch_type)) is not None:
            return explicit
        if ch_type.lower() in _NON_EXG_TYPES:
            return None
        return guess_kind(label, "", stream_kind or default_kind)

    picked: list[tuple[int, SignalKind, float]] = []
    if channels is not None:
        index = {label: i for i, (label, _, _) in enumerate(meta)}
        for label in channels:
            if label not in index:
                raise ValueError(f"{where}: stream {s_name!r} has no channel {label!r} "
                                 f"(have: {', '.join(index)})")
            i = index[label]
            kind = kind_of(label, meta[i][1])
            if kind is None:
                raise ValueError(f"{where}: cannot tell what {label!r} measures — give it "
                                 f"a kind with kinds={{{label!r}: 'emg'}}")
            unit = meta[i][2]
            scale = unit_scale(unit) if unit else 1.0
            if scale is None:
                raise ValueError(f"{where}: {label!r} is in {unit!r}, not a voltage")
            picked.append((i, kind, scale))
        if not picked:
            raise ValueError(f"{where}: channels=[] selects nothing")
    else:
        for i, (label, ch_type, unit) in enumerate(meta):
            kind = kind_of(label, ch_type)
            scale = unit_scale(unit) if unit else 1.0
            if kind is not None and scale is not None:
                picked.append((i, kind, scale))
        if not picked:
            listing = ", ".join(f"{lbl} [{t or '?'}, {u or '?'}]" for lbl, t, u in meta)
            raise ValueError(f"{where}: stream {s_name!r} has no EEG/EMG/EOG voltage "
                             f"channel ({listing}); name them with channels= and kinds=")
    if any(not meta[i][2] for i, _, _ in picked):
        log.info("%s: stream %r declares no unit for some channels; assuming microvolts",
                 where, s_name)

    data = np.vstack([ts[:, i].astype(np.float64) * scale for i, _, scale in picked])
    if not np.all(np.isfinite(data)):
        log.warning("%s: non-finite samples replaced with 0 (treated as a dropout)", where)
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    infos = tuple(ChannelInfo(name=meta[i][0], kind=kind) for i, kind, _ in picked)

    stamps = np.asarray(chosen.get("time_stamps", np.zeros(0)), dtype=np.float64).reshape(-1)
    if stamps.size != ts.shape[0]:
        log.warning("%s: %d time stamps for %d samples; markers cannot be aligned",
                    where, stamps.size, ts.shape[0])
        stamps = np.zeros(0)
    elif stamps.size > 1 and float(np.max(np.diff(stamps))) > 2.0 / fs:
        log.warning("%s: stream %r has gaps in its time stamps; replay closes them and "
                    "markers are kept on their neighbouring samples", where, s_name)

    annotations: list[Annotation] = []
    outside = 0
    for s in streams:
        if s is chosen:
            continue
        s_info = s.get("info")
        if marker_streams is not None:
            if _text(s_info, "name") not in marker_streams:
                continue
        elif _is_signal(s):
            continue
        series = s.get("time_series")
        m_stamps = np.asarray(s.get("time_stamps", np.zeros(0)), dtype=np.float64).reshape(-1)
        if series is None or len(series) != m_stamps.size or m_stamps.size == 0:
            continue
        texts = [_marker_text(row) for row in series]
        replay = _replay_times(m_stamps, stamps, fs)
        for text, t in zip(texts, replay):
            if not text:
                continue
            if np.isnan(t):
                outside += 1
                continue
            annotations.append(Annotation(onset=float(t), text=text))
    if outside:
        log.warning("%s: %d marker(s) lie outside stream %r's time span; dropped",
                    where, outside, s_name)
    annotations.sort(key=lambda a: a.onset)
    events = annotations_to_events(annotations, event_map, source="xdf")
    eff = _first(info, "effective_srate")
    try:
        effective = float(eff) if eff is not None else None
    except (TypeError, ValueError):
        effective = None
    return XdfRecording(
        data=np.ascontiguousarray(data), fs=fs, channels=infos, t0=0.0,
        events=tuple(events), annotations=tuple(annotations), stream_name=s_name,
        stream_type=s_type, effective_srate=effective)


def _coerce(value: str) -> SignalKind:
    kind = _as_kind(str(value))
    if kind is None:
        valid = ", ".join(k.value for k in SignalKind)
        raise ValueError(f"unknown signal kind {value!r} (expected one of: {valid})")
    return kind


def _marker_text(row: Any) -> str:
    """First value of one marker sample as text (string or numeric marker streams)."""
    if isinstance(row, str):
        return row.strip()
    try:
        first = row[0]
    except (TypeError, IndexError, KeyError):
        return ""
    if isinstance(first, float) and first.is_integer():
        first = int(first)
    elif isinstance(first, np.floating) and float(first).is_integer():
        first = int(first)
    return str(first).strip()
