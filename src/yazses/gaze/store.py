"""Persist the gaze→screen calibration map (ADR-011: a coarse geometric map only).

The fitted :class:`~yazses.gaze.calibrate.CalibrationMap` is a 2x3 affine matrix —
no biometric data, no frames. It is written as plain JSON to ``data_dir`` so the
daemon can load it at startup without re-calibrating each session.

Since ADR-v2-149 the file also carries the **calibration context**: which monitors
were attached, where, at what size and scale, and which camera produced the samples
(:mod:`yazses.gaze.topology`). Those coefficients are meaningless against a different
desktop, and without the context nothing can tell a good map from one calibrated on
a laptop that has since been docked to two 4K panels.

**A file written before that field existed still loads.** It simply has no context,
which reads as *unverified* rather than *stale* — see
:func:`yazses.gaze.topology.check_context`. Discarding a working calibration because
this schema grew a field would be the worst of the available answers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.topology import (
    CANONICAL_SPACE,
    CalibrationContext,
    ContextCheck,
    check_context,
)

FILENAME = "gaze_calibration.json"

#: Bumped from 1 when the context field was added. Version 1 files still load.
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class CalibrationRecord:
    """A stored calibration and the setup it was made on (``None`` = legacy file)."""

    calibration: CalibrationMap
    context: CalibrationContext | None = None


def calibration_path(data_dir: Path) -> Path:
    """Return the calibration file path under *data_dir*."""
    return Path(data_dir) / FILENAME


def save_calibration(
    cal: CalibrationMap,
    data_dir: Path,
    context: CalibrationContext | None = None,
) -> Path:
    """Write *cal* to ``data_dir/gaze_calibration.json`` and return the path.

    *context* records the desktop/camera the map was fitted against; omitting it
    writes a map nothing can later validate, so callers that can describe the
    machine should.
    """
    path = calibration_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"version": SCHEMA_VERSION, "space": CANONICAL_SPACE, "A": cal.A.tolist()}
    if context is not None:
        payload["context"] = context.as_dict()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_calibration(data_dir: Path) -> CalibrationMap | None:
    """Load the calibration map from *data_dir*, or ``None`` if absent/unreadable."""
    record = load_calibration_record(data_dir)
    return None if record is None else record.calibration


def load_calibration_record(data_dir: Path) -> CalibrationRecord | None:
    """Load the map *and* its stored context, or ``None`` if absent/unreadable.

    A malformed or absent context is not fatal: the map still loads with
    ``context=None``. Losing the ability to *verify* a calibration is a smaller
    harm than throwing away the calibration, and the verdict the caller gets for a
    missing context already says the binding is unchecked.
    """
    path = calibration_path(data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        A = np.array(raw["A"], dtype="float64")
    except (OSError, ValueError, KeyError, TypeError):
        # TypeError: the file may hold valid JSON that is not an object -- `"a string"["A"]`
        # raises "string indices must be integers". The docstring already promises None for
        # anything unreadable; a well-formed document of the wrong shape is unreadable too.
        return None
    if A.shape != (2, 3):
        return None
    context = None
    stored = raw.get("context") if isinstance(raw, dict) else None
    if stored is not None:
        try:
            context = CalibrationContext.from_dict(stored)
        except (ValueError, KeyError, TypeError):
            context = None
    return CalibrationRecord(calibration=CalibrationMap(A=A), context=context)


def calibration_state(
    data_dir: Path, current: CalibrationContext | None
) -> tuple[CalibrationMap | None, ContextCheck]:
    """Load the calibration and judge it against *current*.

    One call for every caller that needs both halves — the daemon deciding whether
    to build a targeter and ``yazses gaze status`` printing why it did not. Returns
    ``(None, verdict)`` when there is no calibration at all; the verdict is still
    meaningful (it reports what could be checked).
    """
    record = load_calibration_record(data_dir)
    stored = record.context if record is not None else None
    check = check_context(stored, current)
    return (record.calibration if record is not None else None), check
