"""Companion -> desktop wire format for the XR adapter (pure, stdlib only, hostile input).

The companion app is a separate device on a network link, so every frame is untrusted
bytes. One frame is one UTF-8 JSON object, at most ``max_bytes`` long::

    {"v": 1, "t": "sample",     "device_time_s": 12.5, "source": "eye",
     "origin": [0, 1.6, 0], "direction": [0, 0, -1], "confidence": 0.9}
    {"v": 1, "t": "gesture",    "device_time_s": 12.6, "kind": "pinch_start", "confidence": 1}
    {"v": 1, "t": "panel",      "panel_id": "p1", "center": [0, 1.5, -2], "normal": [0, 0, 1],
     "up": [0, 1, 0], "width": 1.2, "height": 0.8, "label": "notes"}
    {"v": 1, "t": "panel_gone", "panel_id": "p1"}

The frame type is ``t`` (not ``kind``) because a gesture frame already has a ``kind``.
Every field is required and unknown keys are refused. Whatever is wrong with a frame,
:func:`decode_frame` raises :class:`WireError` and nothing else; the caller drops the
frame and counts it. A ``sample``/``gesture`` decodes with its **device** timestamp;
map it onto the desktop clock with :class:`ClockMap` (see :func:`rebase`).
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from yazses.xr.geometry import dot, normalize, scale, sub
from yazses.xr.types import (
    GestureEvent,
    GestureKind,
    Panel,
    Ray,
    RaySource,
    Vec3,
    XrSample,
)

WIRE_VERSION = 1
DEFAULT_MAX_BYTES = 4096

# A direction this close to unit length is accepted as sent, bit for bit (so encode ->
# decode is exact); further out, up to the tolerance, it is renormalised; beyond, refused.
_PASSTHROUGH_TOL = 1e-9
_UNIT_TOL = 1e-3

_MAX_TIME_S = 1e9        # ~31 years of device uptime; anything larger is garbage
_MAX_COORD_M = 1e6       # keeps every downstream product finite and exact enough
_MAX_INT_DIGITS = 20     # integers wider than this never reach the bignum parser
_ID_MAX = 128
_LABEL_MAX = 256


class WireError(ValueError):
    """A frame was refused. The only exception :func:`decode_frame` lets escape."""


@dataclass(frozen=True)
class PanelUpdate:
    """A panel appeared or moved: the companion's latest geometry for ``panel.panel_id``."""

    panel: Panel


@dataclass(frozen=True)
class PanelGone:
    """The companion closed the panel ``panel_id``."""

    panel_id: str

    def __post_init__(self) -> None:
        _check_id("panel_id", self.panel_id)


Frame = XrSample | GestureEvent | PanelUpdate | PanelGone

_FIELDS: dict[str, frozenset[str]] = {
    "sample": frozenset({"device_time_s", "source", "origin", "direction", "confidence"}),
    "gesture": frozenset({"device_time_s", "kind", "confidence"}),
    "panel": frozenset(
        {"panel_id", "center", "normal", "up", "width", "height", "label"}
    ),
    "panel_gone": frozenset({"panel_id"}),
}


def _short(value: object) -> str:
    """A bounded repr, so a hostile 4 KiB key cannot flood a log line."""
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


# ── JSON hooks ───────────────────────────────────────────────────────────────


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise WireError(f"duplicate key {_short(key)}")
        out[key] = value
    return out


def _reject_constant(name: str) -> Any:
    # json accepts the non-standard NaN / Infinity / -Infinity literals; we do not.
    raise WireError(f"non-finite number literal {name}")


def _parse_int(text: str) -> int:
    if len(text) > _MAX_INT_DIGITS:
        raise WireError("integer too large")
    return int(text)


# ── field validators (every failure is a WireError) ─────────────────────────


def _check_id(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _ID_MAX
        or not value.isprintable()
    ):
        raise WireError(f"{name} must be a printable, non-empty string up to {_ID_MAX} chars")
    return value


def _num(name: str, value: object, *, lo: float, hi: float) -> float:
    """A finite JSON number in [lo, hi]. ``bool`` is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WireError(f"{name} must be a number")
    try:
        number = float(value)
    except OverflowError:  # an int too wide for a float (10**400)
        raise WireError(f"{name} is outside [{lo:g}, {hi:g}]") from None
    if not math.isfinite(number):
        raise WireError(f"{name} must be finite")
    if not lo <= number <= hi:
        raise WireError(f"{name} is outside [{lo:g}, {hi:g}]")
    return number + 0.0  # -0.0 -> 0.0


def _vec3(name: str, value: object, *, limit: float) -> Vec3:
    if not isinstance(value, list) or len(value) != 3:
        raise WireError(f"{name} must be an array of 3 numbers")
    x, y, z = (_num(f"{name}[{i}]", c, lo=-limit, hi=limit) for i, c in enumerate(value))
    return Vec3(x, y, z)


def _unit(name: str, value: object) -> Vec3:
    """A direction: unit length within 1e-3; renormalised unless already exact enough."""
    vec = _vec3(name, value, limit=2.0)
    length = math.hypot(vec.x, vec.y, vec.z)
    if abs(length - 1.0) > _UNIT_TOL:
        raise WireError(f"{name} must be unit length (got length {length:.6g})")
    return vec if abs(length - 1.0) <= _PASSTHROUGH_TOL else normalize(vec)


def _confidence(value: object) -> float:
    return _num("confidence", value, lo=0.0, hi=1.0)


def _time(value: object) -> float:
    return _num("device_time_s", value, lo=0.0, hi=_MAX_TIME_S)


def _enum(name: str, value: object, enum: Any) -> Any:
    if not isinstance(value, str):
        raise WireError(f"{name} must be a string")
    try:
        return enum(value)
    except ValueError:
        raise WireError(f"unknown {name} {_short(value)}") from None


def _label(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _LABEL_MAX
        or not value.isprintable()  # also refuses controls and lone surrogates
    ):
        raise WireError(f"label must be printable text up to {_LABEL_MAX} chars")
    return value


# ── frame builders ───────────────────────────────────────────────────────────


def _sample(o: dict[str, Any]) -> XrSample:
    return XrSample(
        timestamp_s=_time(o["device_time_s"]),
        source=_enum("source", o["source"], RaySource),
        ray=Ray(
            _vec3("origin", o["origin"], limit=_MAX_COORD_M),
            _unit("direction", o["direction"]),
        ),
        confidence=_confidence(o["confidence"]),
    )


def _gesture(o: dict[str, Any]) -> GestureEvent:
    return GestureEvent(
        timestamp_s=_time(o["device_time_s"]),
        kind=_enum("kind", o["kind"], GestureKind),
        confidence=_confidence(o["confidence"]),
    )


def _panel(o: dict[str, Any]) -> PanelUpdate:
    normal = _unit("normal", o["normal"])
    up = _unit("up", o["up"])
    tilt = dot(normal, up)
    if abs(tilt) > _UNIT_TOL:
        raise WireError("normal and up must be perpendicular")
    if abs(tilt) > _PASSTHROUGH_TOL:
        up = normalize(sub(up, scale(normal, tilt)))  # Gram-Schmidt, then back to unit
    return PanelUpdate(
        Panel(
            panel_id=_check_id("panel_id", o["panel_id"]),
            center=_vec3("center", o["center"], limit=_MAX_COORD_M),
            normal=normal,
            up=up,
            width=_num("width", o["width"], lo=1e-6, hi=_MAX_COORD_M),
            height=_num("height", o["height"], lo=1e-6, hi=_MAX_COORD_M),
            label=_label(o["label"]),
        )
    )


def _panel_gone(o: dict[str, Any]) -> PanelGone:
    return PanelGone(_check_id("panel_id", o["panel_id"]))


_BUILDERS: dict[str, Callable[[dict[str, Any]], Frame]] = {
    "sample": _sample,
    "gesture": _gesture,
    "panel": _panel,
    "panel_gone": _panel_gone,
}


# ── public API ───────────────────────────────────────────────────────────────


def _to_text(data: object, max_bytes: int) -> str:
    if isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    if isinstance(data, str):
        if len(data) > max_bytes:  # a character is at least one byte
            raise WireError("frame too large")
        try:
            raw = data.encode("utf-8")
        except UnicodeEncodeError:
            raise WireError("frame is not valid UTF-8") from None
    elif isinstance(data, bytes):
        raw = data
    else:
        raise WireError("frame must be bytes or str")
    if len(raw) > max_bytes:
        raise WireError("frame too large")
    try:
        return raw.decode("utf-8")  # strict; json.loads(bytes) would also sniff UTF-16/32
    except UnicodeDecodeError:
        raise WireError("frame is not valid UTF-8") from None


def decode_frame(data: bytes | str, *, max_bytes: int = DEFAULT_MAX_BYTES) -> Frame:
    """Parse and validate one frame. Returns a value or raises :class:`WireError`."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    text = _to_text(data, max_bytes)
    try:
        obj = json.loads(
            text,
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_constant,
            parse_int=_parse_int,
        )
    except WireError:
        raise
    except RecursionError:
        raise WireError("frame is nested too deeply") from None
    except ValueError as exc:  # JSONDecodeError and int-digit limits
        raise WireError(f"invalid JSON: {exc}") from None
    if not isinstance(obj, dict):
        raise WireError("frame must be a JSON object")

    version = obj.get("v")
    if isinstance(version, bool) or not isinstance(version, int) or version != WIRE_VERSION:
        raise WireError(f"unsupported version {_short(version)}")
    frame_type = obj.get("t")
    if not isinstance(frame_type, str) or frame_type not in _FIELDS:
        raise WireError(f"unknown frame type {_short(frame_type)}")

    expected = _FIELDS[frame_type]
    present = set(obj) - {"v", "t"}
    if present != expected:
        missing = sorted(expected - present)
        extra = sorted(present - expected)
        raise WireError(f"bad fields for {frame_type!r}: missing {missing}, unexpected {extra}"[:200])

    try:
        return _BUILDERS[frame_type](obj)
    except WireError:
        raise
    except (ValueError, TypeError, OverflowError) as exc:  # a contract constructor refused
        raise WireError(f"invalid {frame_type} frame: {exc}"[:200]) from None


def encode_frame(frame: Frame) -> bytes:
    """Serialise a frame; the inverse of :func:`decode_frame` (ASCII, compact, no NaN)."""
    obj: dict[str, Any]
    if isinstance(frame, XrSample):
        r = frame.ray
        obj = {
            "t": "sample",
            "device_time_s": frame.timestamp_s,
            "source": frame.source.value,
            "origin": [r.origin.x, r.origin.y, r.origin.z],
            "direction": [r.direction.x, r.direction.y, r.direction.z],
            "confidence": frame.confidence,
        }
    elif isinstance(frame, GestureEvent):
        obj = {
            "t": "gesture",
            "device_time_s": frame.timestamp_s,
            "kind": frame.kind.value,
            "confidence": frame.confidence,
        }
    elif isinstance(frame, PanelUpdate):
        p = frame.panel
        obj = {
            "t": "panel",
            "panel_id": p.panel_id,
            "center": [p.center.x, p.center.y, p.center.z],
            "normal": [p.normal.x, p.normal.y, p.normal.z],
            "up": [p.up.x, p.up.y, p.up.z],
            "width": p.width,
            "height": p.height,
            "label": p.label,
        }
    elif isinstance(frame, PanelGone):
        obj = {"t": "panel_gone", "panel_id": frame.panel_id}
    else:
        raise TypeError(f"cannot encode {type(frame).__name__}")
    obj = {"v": WIRE_VERSION, **obj}
    return json.dumps(obj, allow_nan=False, separators=(",", ":")).encode("ascii")


class ClockMap:
    """Map the companion's clock onto the desktop monotonic clock with one offset.

    The offset is fixed by the first frame (``desktop_now - device_time``). After that
    it can only move two ways, and **both are rate-bounded**, because the offset is what
    a hostile or broken companion would manipulate:

    * **Up** (frames arrive with more apparent latency, or the device clock runs slow):
      by at most ``max_drift`` seconds per desktop second. Over any ``T`` seconds of
      desktop time the offset rises by at most ``max_drift * T`` (defaults: 1 ms per
      second, 3.6 s per hour).
    * **Down** (a frame arrives with less apparent latency, or the device clock runs
      fast): paid for from a *credit* that starts at ``jitter_s`` when the offset is
      anchored and is refilled at ``max_drift`` per desktop second (capped at
      ``jitter_s``). A frame needing more than the credit available is refused. Over any
      ``T`` seconds the offset falls by at most ``jitter_s + max_drift * T`` in total,
      however many frames carry it (defaults: 0.02 s + 1 ms per second, e.g. 0.03 s in
      10 s, 0.08 s in 60 s, 3.62 s in an hour). A device clock running 50x fast therefore
      cannot move the mapping; its frames are refused one by one.

    Either way a sample is never mapped into the future (``mapped <= desktop_now``).
    A frame whose apparent offset is more than ``max_jump_s`` from the current one, or
    that would need more downward credit than is available, means the device clock
    stepped or runs fast (reboot, NTP, a replayed or forged stream): that raises
    :class:`WireError` and leaves the mapping untouched, never a silent shift.

    Trade-off, stated plainly: an honest first frame that arrived more than ``jitter_s``
    later than the link's steady latency makes the following on-time frames look like a
    fast clock, so they are refused until enough credit refills or the caller calls
    :meth:`reset` to re-anchor deliberately (pair it with a settled link).
    """

    def __init__(
        self, *, max_jump_s: float = 0.5, max_drift: float = 1e-3, jitter_s: float = 0.02
    ) -> None:
        for name, value in (
            ("max_jump_s", max_jump_s),
            ("max_drift", max_drift),
            ("jitter_s", jitter_s),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and > 0")
        self._max_jump_s = float(max_jump_s)
        self._max_drift = float(max_drift)
        self._jitter_s = float(jitter_s)
        self._offset: float | None = None
        self._last_now = 0.0
        self._credit = self._jitter_s

    @property
    def offset_s(self) -> float | None:
        """Current desktop-minus-device offset, or None before the first frame."""
        return self._offset

    def reset(self) -> None:
        self._offset = None
        self._credit = self._jitter_s

    def map(self, device_time_s: float, desktop_now_s: float) -> float:
        """Desktop-clock time of a frame stamped ``device_time_s`` that arrived at ``desktop_now_s``.

        Raises :class:`WireError` for a bad device time or a refused clock step, and
        :class:`ValueError` for a bad ``desktop_now_s``; nothing else escapes.
        """
        if isinstance(desktop_now_s, bool) or not isinstance(desktop_now_s, (int, float)):
            raise ValueError("desktop_now_s must be a finite number")
        try:
            now = float(desktop_now_s)
        except OverflowError:  # 10**400
            raise ValueError("desktop_now_s must be a finite number") from None
        if not math.isfinite(now):
            raise ValueError("desktop_now_s must be a finite number")
        dev = _num("device_time_s", device_time_s, lo=0.0, hi=_MAX_TIME_S)
        observed = now - dev
        first = self._offset is None
        credit = self._jitter_s
        if self._offset is None:
            offset = observed
        else:
            delta = observed - self._offset
            if abs(delta) > self._max_jump_s:
                raise WireError(
                    f"device clock jumped {delta:+.3f}s (limit {self._max_jump_s:g}s)"
                )
            dt = max(0.0, now - self._last_now)
            refill = self._max_drift * dt
            if delta < 0:
                budget = min(self._jitter_s, self._credit + refill)
                if -delta > budget + 1e-12:
                    raise WireError(
                        f"device clock ran ahead {-delta:.3f}s (allowed {budget:.3f}s now)"
                    )
                offset = observed
                credit = max(0.0, budget + delta)
            else:
                offset = self._offset + min(delta, refill)
                credit = min(self._jitter_s, self._credit + refill)
        mapped = dev + offset
        if mapped < 0 or not math.isfinite(mapped):
            raise WireError("frame maps before the desktop clock's origin")
        self._offset = offset
        self._credit = credit
        self._last_now = now if first else max(self._last_now, now)
        return mapped


def rebase(frame: Frame, clock: ClockMap, desktop_now_s: float) -> Frame:
    """Return ``frame`` with its timestamp mapped onto the desktop clock.

    Panel frames carry no time and pass through unchanged.
    """
    if isinstance(frame, (XrSample, GestureEvent)):
        return replace(frame, timestamp_s=clock.map(frame.timestamp_s, desktop_now_s))
    return frame
