"""Tests for yazses.xr.wire — the companion frame format, treated as hostile input."""
from __future__ import annotations

import json
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from yazses.xr.geometry import cross, normalize
from yazses.xr.types import (
    GestureEvent,
    GestureKind,
    Panel,
    Ray,
    RaySource,
    Vec3,
    XrSample,
)
from yazses.xr.wire import (
    ClockMap,
    PanelGone,
    PanelUpdate,
    WireError,
    decode_frame,
    encode_frame,
    rebase,
)


def sample_obj(**over: object) -> dict[str, object]:
    obj: dict[str, object] = {
        "v": 1, "t": "sample", "device_time_s": 12.5, "source": "eye",
        "origin": [0, 1.6, 0], "direction": [0, 0, -1], "confidence": 0.9,
    }
    obj.update(over)
    return obj


def gesture_obj(**over: object) -> dict[str, object]:
    obj: dict[str, object] = {
        "v": 1, "t": "gesture", "device_time_s": 3.0, "kind": "tap", "confidence": 1,
    }
    obj.update(over)
    return obj


def panel_obj(**over: object) -> dict[str, object]:
    obj: dict[str, object] = {
        "v": 1, "t": "panel", "panel_id": "p1", "center": [0, 1.5, -2],
        "normal": [0, 0, 1], "up": [0, 1, 0], "width": 1.2, "height": 0.8, "label": "notes",
    }
    obj.update(over)
    return obj


def gone_obj(**over: object) -> dict[str, object]:
    obj: dict[str, object] = {"v": 1, "t": "panel_gone", "panel_id": "p1"}
    obj.update(over)
    return obj


def dumps(obj: object) -> str:
    return json.dumps(obj)


# ── round trips ─────────────────────────────────────────────────────────────


def test_round_trip_every_kind() -> None:
    frames = [
        XrSample(1.25, RaySource.HAND, Ray(Vec3(0.1, 1.5, -0.3), Vec3(0.6, 0.8, 0.0)), 0.75),
        GestureEvent(2.0, GestureKind.PINCH_START, 0.5),
        PanelUpdate(Panel("panel-7", Vec3(1, 2, 3), Vec3(0, 0, 1), Vec3(0, 1, 0), 2.0, 1.0, "hi")),
        PanelGone("panel-7"),
    ]
    for frame in frames:
        assert decode_frame(encode_frame(frame)) == frame


def test_every_enum_member_round_trips() -> None:
    ray = Ray(Vec3(0, 0, 0), Vec3(0, 0, -1))
    for src in RaySource:
        assert decode_frame(encode_frame(XrSample(0.0, src, ray, 1.0))).source is src
    for kind in GestureKind:
        assert decode_frame(encode_frame(GestureEvent(0.0, kind))).kind is kind


def test_decode_accepts_str_and_bytes_alike() -> None:
    text = dumps(sample_obj())
    assert decode_frame(text) == decode_frame(text.encode())


def test_integers_are_numbers() -> None:
    s = decode_frame(dumps(sample_obj(device_time_s=7, confidence=1)))
    assert isinstance(s, XrSample)
    assert s.timestamp_s == 7.0 and s.confidence == 1.0


def test_encode_is_ascii_and_compact() -> None:
    raw = encode_frame(PanelUpdate(Panel("é", Vec3(0, 0, 0), Vec3(0, 0, 1), Vec3(0, 1, 0), 1, 1, "日本語")))
    assert raw.isascii() and b" " not in raw
    assert decode_frame(raw).panel.label == "日本語"  # type: ignore[union-attr]


def test_encode_rejects_foreign_objects() -> None:
    with pytest.raises(TypeError):
        encode_frame({"v": 1})  # type: ignore[arg-type]


finite = st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False)


@st.composite
def unit_vectors(draw: st.DrawFn) -> Vec3:
    v = Vec3(draw(finite), draw(finite), draw(finite))
    if math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) < 1e-3:
        v = Vec3(0.0, 0.0, -1.0)
    return normalize(v)


@given(
    t=st.floats(min_value=0, max_value=1e9, allow_nan=False),
    origin=st.builds(Vec3, finite, finite, finite),
    direction=unit_vectors(),
    conf=st.floats(min_value=0, max_value=1, allow_nan=False),
    source=st.sampled_from(list(RaySource)),
)
def test_hypothesis_sample_round_trip_is_exact(t, origin, direction, conf, source) -> None:  # type: ignore[no-untyped-def]
    s = XrSample(t, source, Ray(origin, direction), conf)
    assert decode_frame(encode_frame(s)) == s


@given(normal=unit_vectors(), helper=unit_vectors(), w=st.floats(0.01, 100), h=st.floats(0.01, 100))
def test_hypothesis_panel_round_trip_is_exact(normal, helper, w, h) -> None:  # type: ignore[no-untyped-def]
    side = cross(normal, helper)
    if math.sqrt(side.x**2 + side.y**2 + side.z**2) < 0.1:
        return
    up = normalize(side)
    p = Panel("a", Vec3(1, 2, 3), normal, up, w, h, "")
    assert decode_frame(encode_frame(PanelUpdate(p))) == PanelUpdate(p)


# ── normalisation ───────────────────────────────────────────────────────────


def test_direction_within_tolerance_is_renormalised() -> None:
    s = decode_frame(dumps(sample_obj(direction=[0, 0, -1.0005])))
    assert isinstance(s, XrSample)
    d = s.ray.direction
    assert math.isclose(math.sqrt(d.x**2 + d.y**2 + d.z**2), 1.0, abs_tol=1e-12)
    assert d.z == pytest.approx(-1.0)


def test_direction_beyond_tolerance_is_refused() -> None:
    for bad in ([0, 0, -1.01], [0, 0, -0.99], [0, 0, 0], [1, 1, 1]):
        with pytest.raises(WireError):
            decode_frame(dumps(sample_obj(direction=bad)))


def test_direction_tolerance_boundary() -> None:
    decode_frame(dumps(sample_obj(direction=[0, 0, -(1 + 9e-4)])))
    with pytest.raises(WireError):
        decode_frame(dumps(sample_obj(direction=[0, 0, -(1 + 2e-3)])))


def test_panel_axes_slightly_off_are_repaired() -> None:
    p = decode_frame(dumps(panel_obj(normal=[0, 0, 1.0004], up=[0, 1, 0.0005])))
    assert isinstance(p, PanelUpdate)  # Panel itself demands 1e-6, so this proves the repair
    assert p.panel.up.z == pytest.approx(0.0, abs=1e-9)


def test_panel_axes_not_perpendicular_are_refused() -> None:
    with pytest.raises(WireError):
        decode_frame(dumps(panel_obj(up=[0, 0.6, 0.8])))


# ── python-json quirks ──────────────────────────────────────────────────────


def text_with(old: str, new: str) -> str:
    return dumps(sample_obj()).replace(old, new)


def test_nan_and_infinity_literals_are_refused() -> None:
    base = dumps(sample_obj())
    for lit in ("NaN", "Infinity", "-Infinity"):
        for field in ('"device_time_s": 12.5', '"confidence": 0.9'):
            name = field.split(":")[0]
            with pytest.raises(WireError):
                decode_frame(base.replace(field, f"{name}: {lit}"))
        with pytest.raises(WireError):
            decode_frame(base.replace("[0, 0, -1]", f"[0, {lit}, -1]"))


def test_overflowing_float_literal_is_refused() -> None:
    for lit in ("1e999", "-1e999"):
        with pytest.raises(WireError):
            decode_frame(text_with("12.5", lit))
        with pytest.raises(WireError):
            decode_frame(text_with("[0, 1.6, 0]", f"[0, {lit}, 0]"))


def test_negative_zero_is_accepted_and_normalised() -> None:
    s = decode_frame(text_with("12.5", "-0.0"))
    assert isinstance(s, XrSample)
    assert s.timestamp_s == 0.0 and math.copysign(1.0, s.timestamp_s) == 1.0
    o = decode_frame(text_with("[0, 1.6, 0]", "[-0.0, 1.6, -0.0]"))
    assert isinstance(o, XrSample) and math.copysign(1.0, o.ray.origin.x) == 1.0


def test_duplicate_keys_are_refused() -> None:
    raw = '{"v":1,"t":"panel_gone","panel_id":"a","panel_id":"b"}'
    with pytest.raises(WireError, match="duplicate"):
        decode_frame(raw)
    with pytest.raises(WireError):
        decode_frame('{"v":1,"v":1,"t":"panel_gone","panel_id":"a"}')


def test_big_integers_are_refused_not_overflowed() -> None:
    for n in ("9" * 25, "9" * 400, "9" * 3000):
        with pytest.raises(WireError):
            decode_frame(text_with("12.5", n))


def test_big_int_digit_limit_cannot_leak_a_valueerror(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    old = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(640)
    try:
        with pytest.raises(WireError):
            decode_frame(text_with("12.5", "1" * 700))
    finally:
        sys.set_int_max_str_digits(old)


def test_huge_but_finite_float_is_range_checked() -> None:
    with pytest.raises(WireError):
        decode_frame(text_with("12.5", "1e300"))


def test_json_with_bom_is_refused() -> None:
    with pytest.raises(WireError):
        decode_frame(b"\xef\xbb\xbf" + dumps(sample_obj()).encode())


def test_utf16_is_not_sniffed() -> None:
    with pytest.raises(WireError):
        decode_frame(dumps(sample_obj()).encode("utf-16"))


# ── size and shape ──────────────────────────────────────────────────────────


def test_oversize_is_refused_before_parsing() -> None:
    padded = dumps(panel_obj(label="x" * 256)) + " " * 4096
    with pytest.raises(WireError, match="too large"):
        decode_frame(padded)
    with pytest.raises(WireError, match="too large"):
        decode_frame(padded.encode())


def test_max_bytes_is_exact_and_counts_bytes_not_characters() -> None:
    raw = dumps(gone_obj()).encode()
    assert decode_frame(raw, max_bytes=len(raw)) == PanelGone("p1")
    with pytest.raises(WireError):
        decode_frame(raw, max_bytes=len(raw) - 1)
    multibyte = json.dumps(gone_obj(), ensure_ascii=False).replace("p1", "é" * 40)
    assert len(multibyte) < 100 < len(multibyte.encode())
    with pytest.raises(WireError):
        decode_frame(multibyte, max_bytes=100)


def test_max_bytes_argument_is_validated() -> None:
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            decode_frame("{}", max_bytes=bad)  # type: ignore[arg-type]


def test_deep_nesting_raises_wireerror() -> None:
    with pytest.raises(WireError):
        decode_frame("[" * 4000 + "]" * 4000, max_bytes=10_000)
    with pytest.raises(WireError):
        decode_frame('{"a":' * 2000 + "1" + "}" * 2000, max_bytes=20_000)
    with pytest.raises(WireError):
        decode_frame("[" * 4090)  # unterminated and deep


def test_valid_frame_with_nested_junk_is_refused() -> None:
    with pytest.raises(WireError):
        decode_frame(dumps(gone_obj(panel_id=[[[["x"]]]])))


MALFORMED = [
    pytest.param(b"", id="empty"),
    pytest.param(b"   ", id="blank"),
    pytest.param(b"\xff\xfe\xfa", id="invalid-utf8"),
    pytest.param(b'{"v":1', id="truncated"),
    pytest.param(b"not json", id="not-json"),
    pytest.param(b"[]", id="array"),
    pytest.param(b"null", id="null"),
    pytest.param(b'"sample"', id="string"),
    pytest.param(b"42", id="number"),
    pytest.param(dumps({"t": "sample"}).encode(), id="no-version"),
    pytest.param(dumps(sample_obj(v=2)).encode(), id="future-version"),
    pytest.param(dumps(sample_obj(v=True)).encode(), id="bool-version"),
    pytest.param(dumps(sample_obj(v=1.0)).encode(), id="float-version"),
    pytest.param(dumps(sample_obj(v="1")).encode(), id="string-version"),
    pytest.param(dumps(sample_obj(t="bogus")).encode(), id="unknown-type"),
    pytest.param(dumps(sample_obj(t=["sample"])).encode(), id="unhashable-type"),
    pytest.param(dumps(sample_obj(extra=1)).encode(), id="extra-field"),
    pytest.param(dumps({k: v for k, v in sample_obj().items() if k != "origin"}).encode(), id="missing-field"),
    pytest.param(dumps(gesture_obj(confidence=True)).encode(), id="bool-confidence"),
    pytest.param(dumps(sample_obj(device_time_s="1")).encode(), id="string-time"),
    pytest.param(dumps(sample_obj(device_time_s=None)).encode(), id="null-time"),
    pytest.param(dumps(sample_obj(device_time_s=-0.001)).encode(), id="negative-time"),
    pytest.param(dumps(sample_obj(device_time_s=2e9)).encode(), id="huge-time"),
    pytest.param(dumps(sample_obj(confidence=1.01)).encode(), id="confidence-high"),
    pytest.param(dumps(sample_obj(confidence=-0.01)).encode(), id="confidence-low"),
    pytest.param(dumps(sample_obj(source="foot")).encode(), id="unknown-source"),
    pytest.param(dumps(sample_obj(source=3)).encode(), id="int-source"),
    pytest.param(dumps(sample_obj(origin=[0, 0])).encode(), id="short-origin"),
    pytest.param(dumps(sample_obj(origin=[0, 0, 0, 0])).encode(), id="long-origin"),
    pytest.param(dumps(sample_obj(origin=[0, 0, "0"])).encode(), id="string-in-origin"),
    pytest.param(dumps(sample_obj(origin=[0, 0, True])).encode(), id="bool-in-origin"),
    pytest.param(dumps(sample_obj(origin={"x": 0})).encode(), id="object-origin"),
    pytest.param(dumps(sample_obj(origin=[0, 0, 1e7])).encode(), id="origin-out-of-range"),
    pytest.param(dumps(gesture_obj(kind="wave")).encode(), id="unknown-gesture"),
    pytest.param(dumps(gesture_obj(kind=None)).encode(), id="null-gesture"),
    pytest.param(dumps(panel_obj(panel_id="")).encode(), id="empty-panel-id"),
    pytest.param(dumps(panel_obj(panel_id="x" * 129)).encode(), id="long-panel-id"),
    pytest.param(dumps(panel_obj(panel_id="a\nb")).encode(), id="control-in-panel-id"),
    pytest.param(dumps(panel_obj(panel_id=7)).encode(), id="int-panel-id"),
    pytest.param(dumps(panel_obj(width=0)).encode(), id="zero-width"),
    pytest.param(dumps(panel_obj(height=-1)).encode(), id="negative-height"),
    pytest.param(dumps(panel_obj(label="x" * 257)).encode(), id="long-label"),
    pytest.param(dumps(panel_obj(label="a\x00b")).encode(), id="nul-in-label"),
    pytest.param(b'{"v":1,"t":"panel_gone","panel_id":"\\ud800"}', id="lone-surrogate-id"),
    pytest.param(dumps(panel_obj(label=None)).encode(), id="null-label"),
    pytest.param(dumps(gone_obj(panel_id=None)).encode(), id="null-gone-id"),
    pytest.param(dumps(gone_obj(extra="x")).encode(), id="gone-extra"),
]


@pytest.mark.parametrize("raw", MALFORMED)
def test_malformed_input_raises_wireerror_only(raw: bytes) -> None:
    with pytest.raises(WireError):
        decode_frame(raw, max_bytes=10_000)
    with pytest.raises(WireError):
        decode_frame(raw.decode("utf-8", "surrogatepass") if _is_utf8(raw) else raw, max_bytes=10_000)


def _is_utf8(raw: bytes) -> bool:
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def test_wrong_input_types_raise_wireerror() -> None:
    for bad in (None, 5, [], {"v": 1}):
        with pytest.raises(WireError):
            decode_frame(bad)  # type: ignore[arg-type]


def test_str_with_lone_surrogate_raises_wireerror() -> None:
    with pytest.raises(WireError):
        decode_frame('{"v":1,"t":"panel_gone","panel_id":"\ud800"}')


def test_error_messages_do_not_echo_unbounded_input() -> None:
    key = "k" * 3000
    with pytest.raises(WireError) as info:
        decode_frame(json.dumps({"v": 1, "t": "panel_gone", "panel_id": "a", key: 1}), max_bytes=10_000)
    assert len(str(info.value)) < 400


# ── property: only a value or WireError ─────────────────────────────────────


def _outcome(data: bytes | str) -> None:
    try:
        decode_frame(data)
    except WireError:
        pass


@settings(max_examples=400, deadline=None)
@given(st.binary(max_size=300))
def test_hypothesis_arbitrary_bytes_never_escape(data: bytes) -> None:
    _outcome(data)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=300))
def test_hypothesis_arbitrary_text_never_escape(data: str) -> None:
    _outcome(data)


_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=12),
    lambda kids: st.lists(kids, max_size=4) | st.dictionaries(st.text(max_size=8), kids, max_size=4),
    max_leaves=12,
)


@settings(max_examples=300, deadline=None)
@given(_json)
def test_hypothesis_arbitrary_json_never_escapes(obj: object) -> None:
    _outcome(json.dumps(obj))  # includes NaN / Infinity literals


_VALID = [
    dumps(f).encode() for f in (sample_obj(), gesture_obj(), panel_obj(), gone_obj())
]


@settings(max_examples=500, deadline=None)
@given(
    base=st.sampled_from(_VALID),
    pos=st.integers(min_value=0, max_value=400),
    byte=st.integers(min_value=0, max_value=255),
    cut=st.integers(min_value=0, max_value=400),
)
def test_hypothesis_mutated_valid_frames_never_escape(base: bytes, pos: int, byte: int, cut: int) -> None:
    mutated = bytearray(base)
    mutated[pos % len(mutated)] = byte
    _outcome(bytes(mutated))
    _outcome(bytes(mutated[: cut % (len(mutated) + 1)]))


# ── ClockMap ────────────────────────────────────────────────────────────────


def test_first_frame_anchors_the_offset() -> None:
    clock = ClockMap()
    assert clock.offset_s is None
    assert clock.map(100.0, 5.0) == pytest.approx(5.0)  # arrival is the best estimate
    assert clock.offset_s == pytest.approx(-95.0)
    assert clock.map(101.0, 6.0) == pytest.approx(6.0)


def test_small_jitter_is_absorbed_and_never_maps_to_the_future() -> None:
    clock = ClockMap()
    clock.map(10.0, 50.0)
    assert clock.map(10.2, 50.3) < 50.3          # late frame: mapped to when it happened
    assert clock.map(10.5, 50.49) == pytest.approx(50.49)  # early by 10 ms: offset steps down
    assert clock.offset_s == pytest.approx(39.99)


def test_clock_jump_raises_and_leaves_state_untouched() -> None:
    clock = ClockMap(max_jump_s=0.5)
    clock.map(10.0, 20.0)
    before = clock.offset_s
    for bad_dev in (14.0, 5.0, 0.0):  # device clock stepped forward / back / reset
        with pytest.raises(WireError, match="jumped"):
            clock.map(bad_dev, 21.0)
    assert clock.offset_s == before
    assert clock.map(11.0, 21.0) == pytest.approx(21.0)  # still usable afterwards


def test_jump_boundary() -> None:
    clock = ClockMap(max_jump_s=0.5)
    clock.map(10.0, 20.0)
    clock.map(11.0, 21.4)  # 0.4 s late: ok
    with pytest.raises(WireError):
        clock.map(12.0, 23.0)  # 1.0 s late relative to the anchor: jump


def test_slow_drift_is_tracked_within_the_drift_bound() -> None:
    clock = ClockMap(max_jump_s=0.5, max_drift=1e-3)
    clock.map(0.0, 0.0)
    for i in range(1, 1500):  # the device clock runs 0.05 % slow for 25 minutes
        now = float(i)
        clock.map(now * 0.9995, now)
    assert clock.offset_s is not None and clock.offset_s > 0.5


def test_fast_drift_beyond_the_bound_is_a_jump() -> None:
    clock = ClockMap(max_jump_s=0.5, max_drift=1e-3)
    clock.map(0.0, 0.0)
    with pytest.raises(WireError):
        # 2 % slow: the slew cannot keep up, so the gap grows past max_jump_s
        for i in range(1, 200):
            clock.map(i * 0.98, float(i))


def test_fast_device_clock_cannot_move_the_offset() -> None:
    """Reviewer reproducer: a device clock 50x fast used to be accepted indefinitely."""
    c = ClockMap()
    c.map(0, 1000.0)
    start = c.offset_s
    now, dev, refused = 1000.0, 0.0, 0
    for _ in range(1000):
        now += 0.01
        dev += 0.01 + 0.49
        try:
            c.map(dev, now)
        except WireError:
            refused += 1
    assert refused == 1000
    assert c.offset_s == start  # unchanged on every rejection


def test_downward_offset_movement_is_bounded_by_jitter_plus_drift() -> None:
    c = ClockMap(max_jump_s=10.0, max_drift=1e-3, jitter_s=0.02)
    c.map(0.0, 100.0)
    start = c.offset_s
    assert start is not None
    now, dev = 100.0, 0.0
    for _ in range(600):  # 60 s of frames, each trying to pull the offset down 5 ms
        now += 0.1
        dev += 0.1 + 0.005
        try:
            c.map(dev, now)
        except WireError:
            pass
    assert c.offset_s is not None
    assert start - c.offset_s <= 0.02 + 1e-3 * 60.0 + 1e-9


def test_burst_of_frames_cannot_spend_the_jitter_allowance_twice() -> None:
    c = ClockMap(max_jump_s=10.0)
    c.map(0.0, 100.0)
    now, dev = 100.0, 0.0
    for _ in range(100):  # same desktop instant, device clock racing ahead by 15 ms a frame
        dev += 0.015
        try:
            c.map(dev, now)
        except WireError:
            pass
    assert c.offset_s is not None and 100.0 - c.offset_s <= 0.02 + 1e-9


def test_honest_late_and_early_frames_within_the_allowance_are_accepted() -> None:
    c = ClockMap()
    c.map(10.0, 50.0)
    for i in range(1, 100):  # +-10 ms of network jitter around a steady link
        jitter = 0.01 if i % 2 else -0.005
        c.map(10.0 + i * 0.1, 50.0 + i * 0.1 + jitter)


def test_downward_step_beyond_the_allowance_is_refused_and_leaves_state() -> None:
    c = ClockMap()
    c.map(10.0, 50.0)
    before = c.offset_s
    with pytest.raises(WireError, match="ahead"):
        c.map(10.3, 50.25)  # 50 ms less latency than the anchor: more than jitter_s
    assert c.offset_s == before


@pytest.mark.parametrize("big", [10**400, -(10**400), 10**309])
def test_huge_device_time_is_a_wire_error(big: int) -> None:
    with pytest.raises(WireError):
        ClockMap().map(big, 1.0)


@pytest.mark.parametrize("big", [10**400, -(10**400)])
def test_huge_desktop_time_is_a_value_error(big: int) -> None:
    with pytest.raises(ValueError):
        ClockMap().map(1.0, big)


def test_reset_reanchors() -> None:
    clock = ClockMap()
    clock.map(10.0, 20.0)
    clock.reset()
    assert clock.map(0.0, 30.0) == pytest.approx(30.0)


def test_mapping_before_the_origin_is_refused() -> None:
    clock = ClockMap()
    clock.map(10.0, 1.0)
    with pytest.raises(WireError):
        clock.map(5.0, 1.0)  # would land at -4 s: jump anyway
    clock2 = ClockMap(max_jump_s=100)
    clock2.map(10.0, 1.0)
    with pytest.raises(WireError, match="origin"):
        clock2.map(0.0, 1.0)  # offset -9 -> mapped -9 + 0 < 0


def test_clockmap_validates_arguments() -> None:
    for bad in (0, -1, math.nan, math.inf, True, "1"):
        with pytest.raises(ValueError):
            ClockMap(max_jump_s=bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            ClockMap(jitter_s=bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            ClockMap(max_drift=bad)  # type: ignore[arg-type]
    clock = ClockMap()
    with pytest.raises(ValueError):
        clock.map(1.0, math.nan)
    with pytest.raises(WireError):
        clock.map(math.nan, 1.0)
    with pytest.raises(WireError):
        clock.map(-1.0, 1.0)


def test_desktop_clock_going_backwards_does_not_break_drift_maths() -> None:
    clock = ClockMap()
    clock.map(1.0, 10.0)
    clock.map(1.0, 9.99)  # desktop clock stepped back 10 ms: zero elapsed, no crash
    assert clock.offset_s is not None


def test_rebase_maps_samples_and_gestures_only() -> None:
    clock = ClockMap()
    s = decode_frame(dumps(sample_obj(device_time_s=100.0)))
    g = decode_frame(dumps(gesture_obj(device_time_s=100.5)))
    p = decode_frame(dumps(panel_obj()))
    assert isinstance(s, XrSample) and isinstance(g, GestureEvent)
    s2 = rebase(s, clock, 7.0)
    g2 = rebase(g, clock, 7.5)
    assert isinstance(s2, XrSample) and s2.timestamp_s == pytest.approx(7.0)
    assert isinstance(g2, GestureEvent) and g2.timestamp_s == pytest.approx(7.5)
    assert s2.ray == s.ray and g2.kind == g.kind
    assert rebase(p, clock, 8.0) is p
