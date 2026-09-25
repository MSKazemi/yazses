"""No sensor value may reach `doctor` or `status` — R-09, ADR-v2-145, ADR-019.

`doctor` output is what people paste into public issues. A blendshape score, a head angle
or a gaze coordinate printed there is one published, and ADR-019 puts face data in the
category that may never leave the machine **at all** — not classified, not registered, not
with an opt-in. So the observability surface may carry names, states, ages, counts and
capability flags, and nothing else.

Two guards, because either alone is escapable.

**The structural one** reads :class:`HandsFreeFacts` and asserts no field can hold a value
in the first place. It is the guard that catches the change nobody thought about: adding
``last_gaze_x: float`` for a debugging session fails here, before any renderer is written.
A per-string assertion would not have noticed.

**The behavioural one** builds a fully populated :class:`PerceptionSample` — gaze feature,
head yaw/pitch/roll, two blendshapes, confidences — with values chosen so that a leak is
unmistakable in the output, derives the facts the way the real caller does (``channels`` and
``age_s``, which are the *only* two things a consumer is allowed to take), and asserts every
one of those numbers is absent from every surface. Picking distinctive constants matters:
an assertion against ``0.5`` would be satisfied by an unrelated ``0.5`` somewhere in the
wording, and a leak of ``0.0`` would be invisible.

What this cannot guard, and says so instead of pretending: a *caller* that puts a
coordinate into a fault reason string. `handsfree/safety.py` takes an arbitrary reason from
whoever reports the fault, and the renderer passes it through. The constraint is therefore on
the reporter, and the last test below sweeps every `fault(...)` call site under `src/` for an
interpolated value — a literal reason cannot carry a measurement.
"""

from __future__ import annotations

import dataclasses
import json
import typing

from yazses.config import Config
from yazses.handsfree.observability import (
    PERCEPTION_RUNNING,
    HandsFreeFacts,
    as_payload,
    doctor_rows,
    health_rows,
    render_status_lines,
)
from yazses.handsfree.probe import facts_from_config
from yazses.handsfree.safety import HandsFreeSafety, SafetyLimits, SafetyStatus
from yazses.perception.signals import FaceSignal, GazeSignal, HeadPoseSignal, PerceptionSample

#: Values that exist nowhere in the wording, so finding one in the output is proof of a leak.
_GAZE_X = 0.137911
_GAZE_Y = -0.914733
_YAW = 0.226155
_PITCH = -0.331277
_ROLL = 0.448399
_CONFIDENCE = 0.817263
_JAW_OPEN = 0.723841
_BROW = 0.611927
_SAMPLE_AT_S = 1234.567891


def _sample() -> PerceptionSample:
    return PerceptionSample(
        timestamp_s=_SAMPLE_AT_S,
        gaze=GazeSignal(_SAMPLE_AT_S, _GAZE_X, _GAZE_Y, _CONFIDENCE),
        head_pose=HeadPoseSignal(_SAMPLE_AT_S, _YAW, _PITCH, _ROLL, _CONFIDENCE),
        face=FaceSignal(_SAMPLE_AT_S, _CONFIDENCE,
                        {"jawOpen": _JAW_OPEN, "browInnerUp": _BROW}),
    )


def _every_surface() -> str:
    """Every rendering of a machine whose camera is delivering a full sample. One string."""
    sample = _sample()
    cfg = Config()
    cfg.gaze.enabled = True
    cfg.facegesture.enabled = True
    cfg.headpointer.enabled = True
    cfg.handsfree_safety.enabled = True
    gate = HandsFreeSafety(("facegesture", "headpointer"),
                           limits=SafetyLimits(500.0), clock=lambda: 10_000.0)
    gate.sample("facegesture")
    gate.sample("headpointer")
    gate.resume()
    facts = dataclasses.replace(
        facts_from_config(cfg, unwired=frozenset()),
        camera_ready=True,
        perception_state=PERCEPTION_RUNNING,
        # The two things a consumer may take from a sample, taken the real way.
        perception_channels=sample.channels,
        perception_age_ms=sample.age_s(_SAMPLE_AT_S + 0.041) * 1000.0,
        perception_consumers=2,
        safety=gate.status(at_ms=10_030.0),
        pointer_backend="x11",
        pointer_relative=True,
        pointer_absolute=True,
        pointer_buttons=3,
        calibration_validity="valid",
        calibration_reason="the screen layout and camera are unchanged",
    )
    payload = as_payload(facts)
    parts = [
        repr(health_rows(facts)),
        repr(doctor_rows(facts)),
        json.dumps(payload, sort_keys=True),
        "\n".join(render_status_lines(payload)),
    ]
    return "\n".join(parts)


def test_the_fixture_really_carries_values() -> None:
    """A leak test built on an empty sample proves nothing (the memory hazard, verbatim)."""
    sample = _sample()
    assert sample.channels == ("gaze", "head_pose", "face")
    assert sample.gaze is not None and sample.gaze.raw_x == _GAZE_X
    assert sample.face is not None and sample.face.score("jawOpen") == _JAW_OPEN
    surfaces = _every_surface()
    assert "x11" in surfaces, "the surfaces did not render — the sweep below would be vacuous"
    assert "gaze" in surfaces


def test_no_sensor_value_reaches_any_surface() -> None:
    surfaces = _every_surface()
    for name, value in (
        ("gaze raw_x", _GAZE_X), ("gaze raw_y", _GAZE_Y),
        ("head yaw", _YAW), ("head pitch", _PITCH), ("head roll", _ROLL),
        ("confidence", _CONFIDENCE),
        ("jawOpen score", _JAW_OPEN), ("browInnerUp score", _BROW),
    ):
        for spelling in (repr(value), f"{value:.4f}", f"{value:.2f}"):
            assert spelling not in surfaces, (
                f"{name} ({spelling}) reached the observability surface:\n{surfaces}"
            )


def test_the_channel_names_are_reported_and_the_channel_values_are_not() -> None:
    """The distinction the whole design rests on: *that* a head pose arrived is a state,
    *what* the head pose was is biometric."""
    surfaces = _every_surface()
    assert "head_pose" in surfaces
    assert "jawOpen" not in surfaces, "a blendshape category leaked with its score"


def test_no_facts_field_can_hold_a_sample_value() -> None:
    """The structural guard — it fails on a field added, not on a string printed."""
    allowed = {
        "tuple[str, ...]", "tuple[str, ...] | None", "str", "bool", "bool | None",
        "int | None", "float | None", "SafetyStatus | None",
    }
    hints = {f.name: f.type for f in dataclasses.fields(HandsFreeFacts)}
    unexpected = {
        name: kind for name, kind in hints.items()
        if str(kind).replace("yazses.handsfree.safety.", "") not in allowed
    }
    assert not unexpected, (
        "a hands-free facts field is typed to hold something other than a name, a state, a "
        f"flag, a count or an age: {unexpected}"
    )


def test_the_one_object_field_is_itself_value_free() -> None:
    """``SafetyStatus`` is the single non-primitive, and it is only safe because it too
    carries names, flags and ages. Pinned here so growing it cannot open a hole."""
    fields = {f.name for f in dataclasses.fields(SafetyStatus)}
    assert fields == {"state", "reason", "terminal", "user_paused", "epoch", "sources"}
    source_fields = {
        f.name for f in dataclasses.fields(typing.get_args(
            typing.get_type_hints(SafetyStatus)["sources"])[0])
    }
    assert source_fields == {"name", "armed", "stale", "faulted", "reason", "age_ms", "epoch"}


def test_the_payload_carries_only_primitives() -> None:
    """The wire is where a leak becomes a file on disk and a paste into an issue."""
    cfg = Config()
    cfg.gaze.enabled = True
    payload = as_payload(dataclasses.replace(
        facts_from_config(cfg, unwired=frozenset()), camera_ready=True))
    assert payload is not None

    def _check(value, path: str) -> None:
        if isinstance(value, (str, bool, int, float)) or value is None:
            return
        if isinstance(value, list):
            for i, item in enumerate(value):
                _check(item, f"{path}[{i}]")
            return
        if isinstance(value, dict):
            for key, item in value.items():
                assert isinstance(key, str), f"{path}: non-string key {key!r}"
                _check(item, f"{path}.{key}")
            return
        raise AssertionError(f"{path} is a {type(value).__name__}, not a printable primitive")

    for key, value in payload.items():
        _check(value, key)


def test_no_reporter_in_this_tree_puts_a_value_into_a_fault_reason() -> None:
    """The one hole a renderer cannot close, checked at its source instead.

    `handsfree/safety.py` accepts an arbitrary reason string from whoever reports a fault,
    and the rows print it. So the constraint lives on the reporters: every `fault(...)` call
    site in `src/` must pass a literal, never a formatted value. A new caller that
    interpolates a score fails here.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "yazses"
    offenders = []
    for path in root.rglob("*.py"):
        for match in re.finditer(r"\.fault\(\s*([^)]*)\)", path.read_text(encoding="utf-8")):
            args = match.group(1)
            if "%" in args or "f\"" in args or "f'" in args or ".format(" in args:
                offenders.append(f"{path.relative_to(root)}: {args.strip()[:80]}")
    assert not offenders, (
        "a fault reason is built from a formatted value; a reason string is printed by "
        "`doctor` and `status`, so it must be a literal:\n  " + "\n  ".join(offenders)
    )
