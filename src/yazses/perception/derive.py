"""One FaceLandmarker result → three derived channels, as pure arithmetic (ADR-v2-145).

MediaPipe's FaceLandmarker answers a single ``detect`` call with three things about
the same face at the same instant: 478 landmarks (iris included), a 4x4 facial
transformation matrix, and 52 ARKit-style blendshape activations. Three YazSes
features want exactly one of those each — Glance-Type wants the irises, the
Head-Pointer wants the matrix, the Face-Gesture Switch wants the blendshapes — and
before ADR-v2-145 two of them ran their own camera and their own model to get them.

This module is the derivation half of repairing that, and it is deliberately the
half with no camera in it: every function takes the *values* MediaPipe produced,
never a frame and never a model handle, so each branch below is testable with a
list of numbers. The capture, the model and the lifecycle live in
``src/yazses/perception/mediapipe_backend.py`` and ``src/yazses/perception/source.py``.

Two rules shape every function here.

**A channel that cannot be derived returns ``None``, it does not raise.** ADR-v2-145
invariant 6 says one channel failing must not take the others with it, and the
cheapest way to keep that true is for a derivation to have no way of ending another
one. A missing transform costs head pose; the irises in the same result still
produce gaze.

**Absent is never zero.** A degenerate transformation matrix would decompose into
yaw/pitch/roll of exactly ``0, 0, 0`` — a confident "looking straight ahead" made
out of nothing, and the reading a dwell-click would act on. So the matrix is checked
for being a rotation before it is believed, and a matrix that is not one is a
missing channel rather than a centered pose.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from yazses.gaze.confidence import eye_agreement_confidence
from yazses.perception.signals import FaceSignal, GazeSignal, HeadPoseSignal

__all__ = [
    "IRIS_LEFT",
    "IRIS_RIGHT",
    "blendshape_activations",
    "derive_face",
    "derive_gaze",
    "derive_head_pose",
    "euler_angles",
    "iris_offset",
]

#: MediaPipe iris (478-landmark) indices: iris centre, outer corner, inner corner.
#: The corners normalise the offset by the eye's own width, which is what makes it
#: invariant to how far the user is sitting from the camera. Same triples the
#: shipped gaze backend uses (``src/yazses/gaze/mediapipe_backend.py``); #396 folds
#: that backend onto this module so there is one copy rather than two that drift.
IRIS_LEFT = (468, 33, 133)
IRIS_RIGHT = (473, 362, 263)

#: How far the 3x3 block of a facial transformation matrix may stray from being a
#: true rotation before it is refused. MediaPipe's is orthonormal to float32
#: precision (~1e-7), so this is loose by three orders of magnitude on purpose: the
#: check exists to catch a zero, truncated or garbage matrix, not to grade a good one.
ROTATION_TOLERANCE = 1e-3


def iris_offset(
    landmarks: Sequence, iris: int, corner_a: int, corner_b: int
) -> tuple[float, float] | None:
    """Iris centre offset from the eye midpoint, normalised by eye width, or ``None``.

    ``None`` for anything the landmark list cannot answer — too short, no ``x``/``y``,
    a non-finite coordinate. Pure.
    """
    try:
        a, b, centre = landmarks[corner_a], landmarks[corner_b], landmarks[iris]
        ax, ay, bx = float(a.x), float(a.y), float(b.x)
        by, cx, cy = float(b.y), float(centre.x), float(centre.y)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (ax, ay, bx, by, cx, cy)):
        return None
    # `or 1e-6` guards the degenerate eye — the two corners landing on the same x,
    # which happens on a profile view and would otherwise divide by zero.
    width = abs(bx - ax) or 1e-6
    offset = ((cx - (ax + bx) / 2.0) / width, (cy - (ay + by) / 2.0) / width)
    if not all(math.isfinite(value) for value in offset):
        return None
    return offset


def derive_gaze(landmarks: Sequence, timestamp_s: float) -> GazeSignal | None:
    """The gaze channel from one face's landmarks, or ``None``. Pure.

    The signal is the mean of the two eyes' normalised iris offsets and the
    confidence is how closely they agreed, which is the per-frame landmark-quality
    number ``src/yazses/gaze/confidence.py`` already defines and the shipped gaze
    backend already uses. Reused rather than re-derived: two copies of a confidence
    formula is two thresholds meaning different things.

    ``None`` when either eye could not be measured. Half a gaze estimate is not a
    weaker estimate, it is a different one — an offset from one eye carries the head's
    own rotation, so falling back to it would move the pointer when the user turned.
    """
    left = iris_offset(landmarks, *IRIS_LEFT)
    right = iris_offset(landmarks, *IRIS_RIGHT)
    if left is None or right is None:
        return None
    return GazeSignal(
        timestamp_s=timestamp_s,
        raw_x=(left[0] + right[0]) / 2.0,
        raw_y=(left[1] + right[1]) / 2.0,
        confidence=eye_agreement_confidence(left, right),
    )


def _rotation_block(matrix: Sequence) -> list[list[float]] | None:
    """The upper-left 3x3 of a 3x3/4x4 row-major matrix, as finite floats, or ``None``."""
    try:
        rows = [matrix[index] for index in range(3)]
        block = [[float(rows[r][c]) for c in range(3)] for r in range(3)]
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for row in block for value in row):
        return None
    return block


def _is_rotation(block: Sequence[Sequence[float]], tolerance: float) -> bool:
    """Whether *block* is a proper rotation: orthonormal columns, positive determinant.

    The gate on believing a pose at all. A matrix of zeros is orthogonal to nothing
    and decomposes into ``0, 0, 0``, so without this check the absence of a face
    orientation would read as the most common real one.
    """
    columns = [[block[row][col] for row in range(3)] for col in range(3)]
    for column in columns:
        if abs(math.hypot(*column) - 1.0) > tolerance:
            return False
    for first, second in ((0, 1), (0, 2), (1, 2)):
        dot = sum(columns[first][i] * columns[second][i] for i in range(3))
        if abs(dot) > tolerance:
            return False
    # Orthonormal columns make the determinant ±1; the sign separates a rotation
    # from a reflection, which is a mirrored face rather than a turned one.
    determinant = (
        block[0][0] * (block[1][1] * block[2][2] - block[1][2] * block[2][1])
        - block[0][1] * (block[1][0] * block[2][2] - block[1][2] * block[2][0])
        + block[0][2] * (block[1][0] * block[2][1] - block[1][1] * block[2][0])
    )
    return determinant > 0.0


def euler_angles(
    matrix: Sequence, tolerance: float = ROTATION_TOLERANCE
) -> tuple[float, float, float] | None:
    """``(yaw, pitch, roll)`` in **radians** from a facial transformation matrix. Pure.

    The matrix is read as row-major with the rotation in its upper-left 3x3 — the
    shape MediaPipe's ``facial_transformation_matrixes`` entry has — and decomposed
    as ``R = Rz(roll) · Ry(yaw) · Rx(pitch)``: yaw about the vertical axis, pitch
    about the lateral one, roll about the view axis. At ``|yaw| = 90°`` pitch and
    roll stop being separable (gimbal lock), and there the convention is the usual
    one: all of the remaining rotation is reported as pitch and roll is zero.

    Radians because ``pose_to_cursor`` in ``src/yazses/headpointer/pointer.py``
    already takes radians and expresses its deadzone in them. **Which screen
    direction a positive yaw should move a pointer is not decided here**: the sign
    follows the matrix's own axes, and mapping it to a direction a user would call
    correct needs a real camera and belongs to the head-pointer adapter.

    ``None`` when the matrix is missing, mis-shaped, non-finite or not a rotation.
    """
    block = _rotation_block(matrix)
    if block is None or not _is_rotation(block, tolerance):
        return None
    yaw = math.atan2(-block[2][0], math.hypot(block[0][0], block[1][0]))
    if abs(math.cos(yaw)) <= tolerance:
        # Gimbal lock: only `pitch - roll` is observable, so it is all reported as
        # pitch. Reporting a split the matrix does not contain would be invention.
        return yaw, math.atan2(-block[1][2], block[1][1]), 0.0
    return yaw, math.atan2(block[2][1], block[2][2]), math.atan2(block[1][0], block[0][0])


def derive_head_pose(
    matrix: Sequence | None, timestamp_s: float, confidence: float
) -> HeadPoseSignal | None:
    """The head-pose channel from one facial transformation matrix, or ``None``. Pure."""
    if matrix is None:
        return None
    angles = euler_angles(matrix)
    if angles is None:
        return None
    yaw, pitch, roll = angles
    return HeadPoseSignal(
        timestamp_s=timestamp_s, yaw=yaw, pitch=pitch, roll=roll, confidence=confidence
    )


def blendshape_activations(categories: Iterable) -> dict[str, float]:
    """MediaPipe's blendshape category list flattened to ``{name: score}``. Pure.

    A category whose score is missing, unreadable, non-finite or outside 0..1 is
    **dropped**, and dropping it is what keeps the channel independent: every score
    on a :class:`~yazses.perception.signals.FaceSignal` is validated into 0..1 and a
    single bad one would raise, taking gaze and head pose down with it. Dropped also
    means the switch detector reads it as "not reported" rather than as "relaxed",
    which is the distinction ``FaceSignal.score`` exists to keep.

    Not shared with ``facegesture/detector.py``'s flattener, which is the consumer
    side of this boundary: that one does no range validation, and perception
    depending on a feature package would invert the layering ADR-v2-145 sets up.
    """
    scores: dict[str, float] = {}
    for category in categories or ():
        name = getattr(category, "category_name", None)
        raw = getattr(category, "score", None)
        if name is None or raw is None:
            continue
        try:
            score = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(score) and 0.0 <= score <= 1.0:
            scores[str(name)] = score
    return scores


def derive_face(
    categories: Iterable | None, timestamp_s: float, confidence: float
) -> FaceSignal | None:
    """The face channel from one face's blendshape categories, or ``None``. Pure.

    ``None`` only when there were no categories *at all* to read — the model was not
    asked for blendshapes, or reported none for this face. A category list that is
    present but yields no usable score still produces a signal with an empty
    mapping, because "a face is there and no switch score came with it" is a
    different fact from "there is no face", and ``FaceSignal`` is where the contract
    says that distinction lives.
    """
    if categories is None:
        return None
    scores: Mapping[str, float] = blendshape_activations(categories)
    return FaceSignal(timestamp_s=timestamp_s, confidence=confidence, blendshapes=scores)
