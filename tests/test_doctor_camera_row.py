"""`yazses doctor` tells four camera failures apart, and stays silent otherwise.

EYE-PERM-001 (#414), acceptance criterion five: doctor must distinguish a
missing dependency, a missing model, a missing device and a permission denial
"where the OS exposes that distinction". Before this there was no camera row at
all -- a user who enabled Glance-Type and got nothing had no way to find out
which of the four had happened, and the two camera backends discovered it by
failing to open `cv2.VideoCapture`.

The first test is the one that protects everyone else's attention. Every camera
feature ships off, so on an ordinary install there must be **no row** -- ADR-v2-021
again: a line that appears when nothing is wrong is a line people learn to skip,
and this one would appear on every `doctor` run ever printed.

Nothing here touches the host: the install format, the installed packages and the
model cache are all injected, because a diagnostic test that reads the developer's
machine passes for reasons unrelated to the code.
"""

from __future__ import annotations

import pytest

from yazses.cameraperm import CameraPermission, profile_for
from yazses.config import Config
from yazses.system.doctor import _camera_check


class _Perms:
    """A permissions backend that answers one camera state."""

    def __init__(self, state: CameraPermission) -> None:
        self._state = state

    def check_camera(self) -> CameraPermission:
        return self._state

    def how_to_grant_camera(self) -> str:
        return "REMEDY-TEXT"


def _row(
    state: CameraPermission = CameraPermission.GRANTED,
    *,
    cfg: Config | None = None,
    key: str = "source",
    runtime: bool = True,
    model: bool = True,
):
    if cfg is None:
        cfg = Config()
        cfg.gaze.enabled = True
    return _camera_check(
        _Perms(state),
        cfg,
        profile=profile_for(key),
        find_module=lambda name: runtime,
        model_present=lambda: model,
    )


# ---- silence is the default ----------------------------------------------


def test_there_is_no_camera_row_on_an_ordinary_install() -> None:
    """Every camera feature ships `enabled = False`, so this is what almost every
    `doctor` run must look like."""
    assert _row(cfg=Config()) is None


def test_the_row_appears_once_a_camera_feature_is_enabled() -> None:
    """The other half; without it the test above is satisfied by a row that never
    appears at all."""
    row = _row()
    assert row is not None
    assert row[0] == "Camera"


def test_the_row_does_not_reuse_another_rows_label() -> None:
    """`doctor` printed **Microphone** twice once already, for two different
    questions, and a reader could not tell which had failed (see
    `tests/test_doctor_labels_are_unique.py`)."""
    from pathlib import Path

    from yazses.system.doctor import _config_summary

    labels = {r[0] for r in _config_summary(Config(), Path("/nonexistent/config.toml"))}
    assert labels, "the summary produced no rows; this guard is blind"
    assert "Camera" not in labels
    assert "Microphone" not in labels


# ---- the four failures are four different rows ---------------------------


def test_a_granted_camera_is_an_ok_row() -> None:
    row = _row(CameraPermission.GRANTED)
    assert row is not None and row[1] == "OK"


@pytest.mark.parametrize(
    ("state", "status", "must_say"),
    [
        (CameraPermission.DENIED, "FAIL", "refused"),
        (CameraPermission.UNAVAILABLE, "FAIL", "no camera device"),
        # "never asked" and "could not answer" are one value to a process that
        # has not asked. A red line in front of a user who has simply not run the
        # feature yet is a false alarm, so it is a WARN.
        (CameraPermission.NOT_DETERMINED, "WARN", "undetermined"),
        (CameraPermission.UNSUPPORTED_PLATFORM, "WARN", "no YazSes"),
    ],
)
def test_each_permission_state_grades_and_explains_itself(
    state: CameraPermission, status: str, must_say: str
) -> None:
    row = _row(state)
    assert row is not None
    assert row[1] == status
    assert must_say in row[2]


def test_a_missing_runtime_is_named_as_a_dependency_not_a_permission() -> None:
    """The most common failure by far, and the one most easily mistaken for a
    refusal: mediapipe and opencv are an optional extra."""
    row = _row(runtime=False)
    assert row is not None
    assert row[1] == "FAIL"
    assert "cv2" in row[2] and "mediapipe" in row[2]
    assert "REMEDY-TEXT" not in row[2], "a dependency gap was described as a permission"


def test_a_frozen_bundle_says_no_permission_will_help() -> None:
    """R-21 rendered. The .dmg, the .exe, the MSIX, the snap and the flatpak ship
    no camera runtime and cannot add one, so sending that reader to a privacy
    pane would be advice that cannot work."""
    row = _row(key="snap")
    assert row is not None
    assert row[1] == "FAIL"
    assert "snap" in row[2]
    assert "pipx install" in row[2], "the refusal offers no way out"


def test_a_missing_model_is_reported_without_failing_the_row() -> None:
    """The landmark model downloads once on first use, so its absence is a note.
    Grading it FAIL would put a red line in front of a working install."""
    row = _row(model=False)
    assert row is not None
    assert row[1] == "OK"
    assert "3.7 MB" in row[2]


def test_the_four_failures_do_not_print_the_same_sentence() -> None:
    """The acceptance criterion, stated as the thing a user needs: four causes,
    four different next actions."""
    details = {
        _row(runtime=False)[2],
        _row(key="windows-msix")[2],
        _row(CameraPermission.UNAVAILABLE)[2],
        _row(CameraPermission.DENIED)[2],
    }
    assert len(details) == 4, f"camera failures collapsed into {len(details)} messages"


# ---- a backend without the methods is not a crash, and not a pass ---------


def test_a_backend_that_cannot_answer_is_undetermined_not_granted() -> None:
    """A third-party or older `PermissionsBackend` predating `check_camera` must
    read as "cannot tell". `_input_monitoring_check` skips such a backend
    entirely; the camera cannot, because the row is about whether access exists
    -- and absence of an answer is not access."""

    class _Old:
        pass

    cfg = Config()
    cfg.gaze.enabled = True
    row = _camera_check(
        _Old(),
        cfg,
        profile=profile_for("source"),
        find_module=lambda name: True,
        model_present=lambda: True,
    )
    assert row is not None
    assert row[1] == "WARN"
    assert "undetermined" in row[2]
