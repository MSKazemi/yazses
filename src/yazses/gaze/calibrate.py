"""Gaze→screen calibration (pure least-squares, no model dependency).

Fits an affine map from gaze angle ``(yaw, pitch)`` to a screen point ``(x, y)``
from a handful of calibration samples (the user looks at known points once). Coarse
by design — it drives look-to-PANE, not look-to-caret.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


def calibration_blocker(*, enabled: bool, desktop_ok: bool) -> str | None:
    """Why calibration cannot work here, or ``None`` if it can. Pure.

    Both answers are free -- one is a config flag, the other a ``xdotool`` probe -- and
    both used to be checked *after* the webcam dependencies were fetched. On a default
    install that meant ``yazses gaze calibrate`` downloaded **~219 MB** and then said
    "Ensure `[gaze] enabled = true`"; on Wayland it downloaded the same 219 MB to
    announce that external window focus is forbidden there, which no download can fix.

    The project already settled this question elsewhere -- ``system/backends.py`` exists
    so a factory "never sends the user after an extra that cannot supply that backend" --
    so the rule is applied here rather than re-argued: ask the free questions first.

    Deliberately does not decide the *dependency* case. That one genuinely cannot be
    answered before an install, and it is the one an install actually repairs.
    """
    if not enabled:
        return (
            "Look-to-pane is off, so there is nothing to calibrate yet.\n"
            "  Turn it on (this also installs the webcam deps):\n"
            "    yazses features enable gaze --force"
        )
    if not desktop_ok:
        return (
            "Gaze routing needs an X11 session with `xdotool` installed "
            "(Wayland forbids external window focus).\n"
            "  Nothing to install here -- the webcam deps cannot make this work."
        )
    return None


@dataclass(frozen=True)
class CalibrationMap:
    """Affine map: [x, y] = A @ [yaw, pitch, 1]. ``A`` is 2x3."""
    A: np.ndarray

    def predict(self, yaw: float, pitch: float) -> tuple[float, float]:
        v = np.array([yaw, pitch, 1.0], dtype="float64")
        x, y = self.A @ v
        return float(x), float(y)


def fit_calibration(
    samples: list[tuple[tuple[float, float], tuple[float, float]]],
) -> CalibrationMap:
    """Least-squares fit of the gaze→screen affine map.

    ``samples`` is ``[((yaw, pitch), (x, y)), ...]``; needs >= 3 non-degenerate
    points (the affine map has 3 coefficients per axis).
    """
    if len(samples) < 3:
        raise ValueError("calibration needs at least 3 points")
    M = np.array([[yaw, pitch, 1.0] for (yaw, pitch), _ in samples], dtype="float64")
    targets = np.array([[x, y] for _, (x, y) in samples], dtype="float64")
    # Solve M @ coeffs = targets for coeffs (3x2); A is its transpose (2x3).
    coeffs, *_ = np.linalg.lstsq(M, targets, rcond=None)
    return CalibrationMap(A=coeffs.T)


# ---- interactive calibration (I/O-agnostic, so it is unit-testable) --------


def default_targets(width: int, height: int, points: int) -> list[tuple[str, tuple[int, int]]]:
    """Screen calibration points as ``(label, (x, y))``, inset from the edges.

    ``points >= 9`` gives a labelled 3x3 grid; ``4`` gives the corners; anything
    else the four corners plus centre (5). Coarse by design — look-to-PANE.
    """
    m = 0.1  # 10% inset so the user isn't asked to look off-screen
    xs = (int(width * m), width // 2, int(width * (1 - m)))
    ys = (int(height * m), height // 2, int(height * (1 - m)))
    grid = [
        ("top-left", (xs[0], ys[0])), ("top-centre", (xs[1], ys[0])), ("top-right", (xs[2], ys[0])),
        ("middle-left", (xs[0], ys[1])), ("centre", (xs[1], ys[1])), ("middle-right", (xs[2], ys[1])),
        ("bottom-left", (xs[0], ys[2])), ("bottom-centre", (xs[1], ys[2])), ("bottom-right", (xs[2], ys[2])),
    ]
    if points >= 9:
        return grid
    if points == 4:
        return [grid[0], grid[2], grid[6], grid[8]]
    return [grid[0], grid[2], grid[4], grid[6], grid[8]]  # corners + centre


def collect_samples(
    backend,
    targets: list[tuple[str, tuple[int, int]]],
    before_point: Callable[[str, tuple[int, int]], None],
    per_point: int = 8,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Sample gaze at each target and pair the mean angle with the screen point.

    ``before_point(label, xy)`` is called once per target to prompt the user (in
    the CLI it prints "look here" and waits for Enter); tests pass a no-op. For
    each target up to ``per_point`` gaze reads are averaged, skipping ``None``
    (no-face) reads. Targets with no valid read are dropped. Returns the
    ``[((yaw, pitch), (x, y)), ...]`` list ready for :func:`fit_calibration`.
    """
    samples: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for label, xy in targets:
        before_point(label, xy)
        reads = []
        for _ in range(per_point):
            g = backend.estimate()
            if g is not None:
                reads.append(g)
        if not reads:
            continue
        arr = np.array(reads, dtype="float64")
        yaw, pitch = float(arr[:, 0].mean()), float(arr[:, 1].mean())
        samples.append(((yaw, pitch), (float(xy[0]), float(xy[1]))))
    return samples
