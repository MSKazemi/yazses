"""Persist the gaze→screen calibration map (ADR-011: a coarse geometric map only).

The fitted :class:`~yazses.gaze.calibrate.CalibrationMap` is a 2x3 affine matrix —
no biometric data, no frames. It is written as plain JSON to ``data_dir`` so the
daemon can load it at startup without re-calibrating each session.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from yazses.gaze.calibrate import CalibrationMap

FILENAME = "gaze_calibration.json"


def calibration_path(data_dir: Path) -> Path:
    """Return the calibration file path under *data_dir*."""
    return Path(data_dir) / FILENAME


def save_calibration(cal: CalibrationMap, data_dir: Path) -> Path:
    """Write *cal* to ``data_dir/gaze_calibration.json`` and return the path."""
    path = calibration_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "A": cal.A.tolist()}, indent=2))
    return path


def load_calibration(data_dir: Path) -> CalibrationMap | None:
    """Load the calibration map from *data_dir*, or ``None`` if absent/unreadable."""
    path = calibration_path(data_dir)
    try:
        raw = json.loads(path.read_text())
        A = np.array(raw["A"], dtype="float64")
    except (OSError, ValueError, KeyError):
        return None
    if A.shape != (2, 3):
        return None
    return CalibrationMap(A=A)
