"""Glance-Type P1 — look-to-pane core (design/v2-cognitive-layer §3.3).

The dependency-free core: fit a calibration map from gaze angles to screen points,
then map a point to a coarse zone or to the window under it. The gaze *backend*
(L2CS-Net + webcam) lives in the optional `gaze` extra and is mocked here.
"""
from __future__ import annotations

from yazses.config import GazeConfig
from yazses.gaze.calibrate import fit_calibration
from yazses.gaze.factory import build_gaze
from yazses.gaze.zones import grid_zone, window_at_point

# ---- calibration fit (pure least-squares) ----------------------------------

def test_calibration_recovers_a_linear_mapping():
    # Synthetic ground truth: screen_x = 100*yaw + 960, screen_y = 100*pitch + 540.
    samples = []
    for yaw in (-2.0, 0.0, 2.0):
        for pitch in (-1.0, 0.0, 1.0):
            samples.append(((yaw, pitch), (100 * yaw + 960, 100 * pitch + 540)))
    cal = fit_calibration(samples)
    x, y = cal.predict(1.0, -1.0)
    assert abs(x - 1060) < 1e-3
    assert abs(y - 440) < 1e-3


def test_calibration_needs_at_least_three_points():
    import pytest

    with pytest.raises(ValueError):
        fit_calibration([((0.0, 0.0), (0.0, 0.0))])


# ---- zone mapping ----------------------------------------------------------

def test_grid3x3_zone_indices():
    # 1920x1080 screen, 3x3 grid → 9 zones (row-major 0..8).
    assert grid_zone(10, 10, 1920, 1080, 3, 3) == 0          # top-left
    assert grid_zone(960, 540, 1920, 1080, 3, 3) == 4        # centre
    assert grid_zone(1910, 1070, 1920, 1080, 3, 3) == 8      # bottom-right


def test_grid_clamps_out_of_bounds_points():
    assert grid_zone(-50, -50, 1920, 1080, 3, 3) == 0
    assert grid_zone(99999, 99999, 1920, 1080, 3, 3) == 8


def test_window_at_point_selects_containing_window():
    windows = [
        ("editor", 0, 0, 960, 1080),
        ("browser", 960, 0, 960, 1080),
    ]
    assert window_at_point(100, 500, windows) == "editor"
    assert window_at_point(1500, 500, windows) == "browser"
    assert window_at_point(99999, 500, windows) is None  # outside all


def test_window_at_point_prefers_smallest_containing_window():
    # A full-screen desktop/root window listed first must NOT shadow the real
    # window under the gaze point — the smallest (most specific) one wins.
    windows = [
        ("desktop", 0, 0, 1920, 1200),   # spans everything, listed first
        ("editor", 0, 0, 960, 1080),
        ("browser", 960, 0, 960, 1080),
    ]
    assert window_at_point(100, 500, windows) == "editor"
    assert window_at_point(1500, 500, windows) == "browser"


# ---- factory dormancy ------------------------------------------------------

def test_factory_none_when_dormant():
    assert build_gaze(GazeConfig(enabled=False)) is None


def test_factory_degrades_to_none_when_backend_unavailable():
    # enabled but l2cs-net/opencv not installed → None (stay dormant).
    assert build_gaze(GazeConfig(enabled=True, backend="l2cs")) is None


def test_factory_unknown_backend_none():
    assert build_gaze(GazeConfig(enabled=True, backend="nope")) is None


# ---- end-to-end target resolution (calibration + zones) --------------------

def test_resolve_target_window_from_gaze():
    from yazses.gaze.calibrate import fit_calibration
    from yazses.gaze.zones import resolve_window

    # Calibration: gaze yaw maps to screen x (left half vs right half).
    samples = [((-1.0, 0.0), (200, 540)), ((1.0, 0.0), (1400, 540)), ((0.0, 1.0), (960, 800))]
    cal = fit_calibration(samples)
    windows = [("editor", 0, 0, 960, 1080), ("browser", 960, 0, 960, 1080)]
    # Looking left → editor; looking right → browser.
    assert resolve_window(cal, -1.0, 0.0, windows) == "editor"
    assert resolve_window(cal, 1.0, 0.0, windows) == "browser"
