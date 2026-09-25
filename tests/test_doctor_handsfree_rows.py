"""`yazses doctor` had nothing to say about any camera input — EYE-OBS-001 (#416).

The Camera row from EYE-PERM-001 (#414) answers one question: may this install open the
device? Everything after that was silent. A face switch whose signal died, a head pointer
enabled on a build that drives nothing, a calibration fitted on a monitor since unplugged,
a pointer backend that does not exist on this session — all of them end as *nothing
happens*, and `doctor` is where somebody looks after it did not.

Two things this file exists to hold, beyond the wording:

**Nothing new appears on an ordinary install.** It is checked with a platform object that
raises on *any* attribute access, so "no row" is proved by the probe not touching the
machine rather than by an absent string. That is the same claim `_camera_check` already
makes and the visible half of EYE-PERM-001's first criterion: camera features off, nothing
reaches the OS, no permission prompt.

**One blocked camera is one failure.** The Camera row carries the reason and the fix, so the
perception row points at it instead of restating it; otherwise `doctor` closes with
"2 problems to fix" for one cause, and a count that overstates is a count people stop
reading.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yazses.config import Config
from yazses.system.doctor import _camera_ready, _handsfree_checks

HANDSFREE_LABELS = {
    "Hands-free safety", "Hands-free perception", "Head tracking", "Face switch",
    "Pointer output", "Gaze calibration",
}


class _Explodes:
    """A platform that fails on any attribute read — proof the probe asked it nothing."""

    def __getattr__(self, name):
        raise AssertionError(f"the hands-free probe read platform.{name} on a default install")


class _Platform:
    """A platform that can answer about paths and knows nothing about pointers."""

    name = "linux"

    class paths:
        data_dir = Path("/nonexistent/yazses-data")


def _labels(rows) -> set[str]:
    return {label for label, _status, _detail in rows}


def _by_label(rows) -> dict[str, tuple[str, str]]:
    return {label: (status, detail) for label, status, detail in rows}


def _never_read_context():
    raise AssertionError("the calibration topology was read when it should not have been")


def test_a_default_install_gets_no_hands_free_rows_and_no_probing() -> None:
    rows = _handsfree_checks(Config(), _Explodes(), None, unwired=frozenset())
    assert rows == []


def test_a_broken_config_gets_no_rows_rather_than_a_traceback() -> None:
    """`doctor` loads `cfg = None` when the config file will not parse, and that is exactly
    the run where a crash costs the user the explanation."""
    assert _handsfree_checks(None, _Explodes(), None, unwired=frozenset()) == []


def test_enabling_a_camera_feature_is_what_makes_the_rows_appear() -> None:
    cfg = Config()
    cfg.facegesture.enabled = True
    rows = _handsfree_checks(cfg, _Platform(), ("Camera", "OK", "ready"),
                             unwired=frozenset())
    assert _labels(rows), "enabling a camera feature produced no hands-free rows"
    assert _labels(rows) <= HANDSFREE_LABELS, _labels(rows)


def test_the_new_labels_do_not_collide_with_the_rows_doctor_already_prints() -> None:
    """Two rows sharing a name make a pasted `doctor` report unanswerable — the defect
    `tests/test_doctor_labels_are_unique.py` was written for."""
    from yazses.system.doctor import _config_summary

    cfg = Config()
    cfg.gaze.enabled = True
    cfg.facegesture.enabled = True
    cfg.headpointer.enabled = True
    cfg.handsfree_safety.enabled = True
    rows = _handsfree_checks(cfg, _Platform(), ("Camera", "OK", "ready"),
                             unwired=frozenset({"headpointer"}),
                             read_context=lambda: None)
    labels = [label for label, _s, _d in rows]
    assert len(labels) == len(set(labels)), labels
    existing = {row[0] for row in _config_summary(Config(), Path("/nonexistent/config.toml"))}
    existing.add("Camera")
    assert not (set(labels) & existing), set(labels) & existing


def test_a_blocked_camera_produces_exactly_one_failure() -> None:
    cfg = Config()
    cfg.gaze.enabled = True
    rows = _handsfree_checks(cfg, _Platform(), ("Camera", "FAIL", "no camera device"),
                             unwired=frozenset(), read_context=lambda: None)
    assert [s for _l, s, _d in rows if s == "FAIL"] == [], rows
    perception = _by_label(rows)["Hands-free perception"]
    assert perception[0] == "SKIP"
    assert "Camera row" in perception[1]


def test_the_undecided_camera_row_is_not_read_as_available() -> None:
    """WARN on the Camera row is the soft set — permission unknown, never asked,
    unsupported platform. "We did not ask" must not become "yes"."""
    assert _camera_ready(("Camera", "OK", "")) is True
    assert _camera_ready(("Camera", "FAIL", "")) is False
    assert _camera_ready(("Camera", "WARN", "")) is None
    assert _camera_ready(None) is None


def test_the_calibration_topology_is_only_read_for_gaze() -> None:
    """Reading it costs a subprocess on a real session; a face-switch user pays nothing."""
    cfg = Config()
    cfg.facegesture.enabled = True
    rows = _handsfree_checks(cfg, _Platform(), ("Camera", "OK", "ready"),
                             unwired=frozenset(), read_context=_never_read_context)
    assert "Gaze calibration" not in _labels(rows)


def test_an_unreadable_calibration_is_reported_as_unknown() -> None:
    """Not as valid, and not as a crash: `doctor` must survive a corrupt state file."""
    def boom():
        raise OSError("the display layout could not be read")

    cfg = Config()
    cfg.gaze.enabled = True
    rows = _handsfree_checks(cfg, _Platform(), ("Camera", "OK", "ready"),
                             unwired=frozenset(), read_context=boom)
    status, detail = _by_label(rows)["Gaze calibration"]
    assert status == "SKIP"
    assert "unknown" in detail


def test_a_platform_that_cannot_name_its_pointer_backend_says_unknown() -> None:
    cfg = Config()
    cfg.headpointer.enabled = True
    rows = _handsfree_checks(cfg, _Platform(), ("Camera", "OK", "ready"),
                             unwired=frozenset({"headpointer"}))
    status, detail = _by_label(rows)["Pointer output"]
    assert status == "SKIP"
    assert "unknown" in detail


def test_a_platform_that_can_name_it_is_reported() -> None:
    from yazses.pointer import PointerButton, PointerCapabilities

    class _WithPointer(_Platform):
        @staticmethod
        def pointer_capabilities():
            return PointerCapabilities(
                backend="x11", relative_motion=True, absolute_motion=True,
                buttons=frozenset({PointerButton.LEFT, PointerButton.RIGHT}),
            )

    cfg = Config()
    cfg.headpointer.enabled = True
    rows = _handsfree_checks(cfg, _WithPointer(), ("Camera", "OK", "ready"),
                             unwired=frozenset({"headpointer"}))
    status, detail = _by_label(rows)["Pointer output"]
    assert status == "OK"
    assert "x11" in detail
    assert "2 button(s)" in detail


def test_a_pointer_report_that_raises_does_not_take_doctor_down() -> None:
    class _AngryPointer(_Platform):
        @staticmethod
        def pointer_capabilities():
            raise RuntimeError("the compositor refused")

    cfg = Config()
    cfg.headpointer.enabled = True
    rows = _handsfree_checks(cfg, _AngryPointer(), ("Camera", "OK", "ready"),
                             unwired=frozenset({"headpointer"}))
    status, detail = _by_label(rows)["Pointer output"]
    assert status == "SKIP"
    assert "could not report" in detail


@pytest.mark.parametrize("feature", ["gaze", "facegesture", "headpointer", "lipread", "sign"])
def test_every_camera_feature_gets_at_least_the_shared_perception_row(feature) -> None:
    """A camera capability nobody wired a dedicated row for still has to be visible —
    otherwise enabling `[lipread]` is silent in the one command that explains silence."""
    cfg = Config()
    getattr(cfg, feature).enabled = True
    rows = _handsfree_checks(cfg, _Platform(), ("Camera", "OK", "ready"),
                             unwired=frozenset(), read_context=lambda: None)
    detail = _by_label(rows)["Hands-free perception"][1]
    assert feature in detail, detail
