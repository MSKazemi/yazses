"""The camera gate decides the same way everywhere, and never guesses "yes".

EYE-PERM-001 (#414). Three camera features exist -- Glance-Type gaze, the
Face-Gesture Switch and the Head-Pointer -- and before this there was no single
answer to "may this install open the camera?". Each backend opened a
`cv2.VideoCapture` and discovered the answer by failing.

Two properties are worth more than the rest of the file and are tested first:

* **camera features off => the OS is never asked.** On macOS the act of asking
  is what raises the permission dialog, so this is not a tidiness point: a
  machine that has never enabled a camera feature must never see a camera
  prompt. The guarantee lives in the *order* :func:`evaluate` checks things in,
  so the order is what is pinned.
* **"I could not tell" is never "granted".** Every probe failure -- no PyObjC on
  a Mac, an unreadable registry on Windows, an exception out of the backend --
  lands on ``NOT_DETERMINED``, and ``NOT_DETERMINED`` does not open the camera.

⚠ Everything here runs against fakes. No camera, no Mac and no Windows machine is
involved, and none of it is evidence that the macOS or Windows probes behave
correctly on real hardware -- only that the mapping and the decision do.
"""

from __future__ import annotations

import pytest

from yazses.cameraperm import (
    CAMERA_FEATURES,
    CameraBlocker,
    CameraFacts,
    CameraPermission,
    enabled_camera_features,
    evaluate,
    missing_camera_modules,
    needs_permission_probe,
    profile_for,
    resolve,
)
from yazses.config import Config


def _facts(**kw) -> CameraFacts:
    """Facts for an install that can run the camera, with gaze on."""
    base = dict(
        features_enabled=("gaze",),
        package_label="a source / PyPI install",
        package_can_run_camera=True,
        runtime_missing=(),
    )
    base.update(kw)
    return CameraFacts(**base)


# ---- the guard is not vacuous -------------------------------------------


def test_every_camera_feature_names_a_real_config_section() -> None:
    """A list of section names that have drifted out of `config.py` would leave a
    camera feature outside the gate entirely, and every assertion below would
    still pass."""
    cfg = Config()
    assert CAMERA_FEATURES, "the camera feature list is empty; nothing is gated"
    for name in CAMERA_FEATURES:
        section = getattr(cfg, name, None)
        assert section is not None, f"[{name}] is not a config section any more"
        assert hasattr(section, "enabled"), f"[{name}] has no `enabled` key"


def test_every_camera_feature_ships_off() -> None:
    """Rule 2 of AGENTS.md, and the precondition for the prompt guarantee below:
    if any of these defaulted to on, a fresh install would reach the probe."""
    cfg = Config()
    on = [n for n in CAMERA_FEATURES if getattr(getattr(cfg, n), "enabled", False)]
    assert not on, f"{on} ship enabled; a fresh install would open a camera"


# ---- nothing asks the OS unless a feature wants a camera ------------------


def test_a_default_install_never_probes_the_camera() -> None:
    """The first acceptance criterion, stated as the thing it protects."""
    assert not needs_permission_probe(CameraFacts())
    assert enabled_camera_features(Config()) == ()


def test_resolve_on_a_default_config_calls_no_probe() -> None:
    """Not the same assertion as the one above: this one watches the call.

    `needs_permission_probe` could be correct and `resolve` could still call the
    backend anyway -- which is exactly how a "we check first" claim becomes
    decorative. So the probe raises if it is ever reached.
    """

    def exploded() -> CameraPermission:  # pragma: no cover - must not run
        raise AssertionError("the OS was asked about the camera with every feature off")

    gate = resolve(Config(), probe=exploded, remedy=lambda: "")
    assert gate.blocker is CameraBlocker.FEATURE_OFF
    assert gate.allowed is False


def test_a_package_that_cannot_run_a_camera_never_probes_either() -> None:
    """R-21 from the other side: the MSIX must not ask for consent it cannot use."""
    cfg = Config()
    cfg.gaze.enabled = True

    def exploded() -> CameraPermission:  # pragma: no cover - must not run
        raise AssertionError("a camera-less package asked the OS for camera access")

    gate = resolve(
        cfg,
        probe=exploded,
        remedy=lambda: "",
        profile=profile_for("windows-msix"),
        find_module=lambda name: True,
    )
    assert gate.blocker is CameraBlocker.PACKAGING
    assert "MSIX" in gate.reason
    assert gate.remedy, "a packaging refusal with no way out is a dead end"


def test_a_missing_runtime_stops_before_the_probe() -> None:
    def exploded() -> CameraPermission:  # pragma: no cover - must not run
        raise AssertionError("the OS was asked before the camera runtime was present")

    cfg = Config()
    cfg.facegesture.enabled = True
    gate = resolve(cfg, probe=exploded, remedy=lambda: "", find_module=lambda name: False)
    assert gate.blocker is CameraBlocker.RUNTIME_MISSING
    assert "cv2" in gate.reason and "mediapipe" in gate.reason


# ---- unknown is never granted --------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        CameraPermission.DENIED,
        CameraPermission.NOT_DETERMINED,
        CameraPermission.UNAVAILABLE,
        CameraPermission.UNSUPPORTED_PLATFORM,
    ],
)
def test_only_granted_opens_the_camera(state: CameraPermission) -> None:
    gate = evaluate(_facts(permission=state))
    assert gate.allowed is False, f"{state} was treated as access"


def test_granted_opens_the_camera() -> None:
    """The other direction; without it the test above passes on a gate that is
    simply always closed."""
    gate = evaluate(_facts(permission=CameraPermission.GRANTED))
    assert gate.allowed is True
    assert gate.blocker is CameraBlocker.NONE


def test_an_unprobed_state_is_refused_rather_than_assumed() -> None:
    """`permission=None` reaching `evaluate` means a caller skipped the probe.
    It must not read as permission."""
    gate = evaluate(_facts(permission=None))
    assert gate.allowed is False
    assert gate.blocker is CameraBlocker.NOT_PROBED


def test_a_probe_that_raises_is_undetermined_not_granted() -> None:
    """A backend can throw -- PyObjC half-installed, a registry hive locked. The
    exception must not become an optimistic default."""

    def broken() -> CameraPermission:
        raise RuntimeError("IOKit says no")

    cfg = Config()
    cfg.gaze.enabled = True
    gate = resolve(cfg, probe=broken, remedy=lambda: "", find_module=lambda name: True)
    assert gate.allowed is False
    assert gate.permission is CameraPermission.NOT_DETERMINED


def test_not_determined_says_a_prompt_is_possible_without_claiming_access() -> None:
    """macOS's NotDetermined is "you will be asked", not "you were refused" --
    but it is still not access, and the two facts travel in separate fields."""
    gate = evaluate(_facts(permission=CameraPermission.NOT_DETERMINED))
    assert gate.may_prompt is True
    assert gate.allowed is False


def test_only_not_determined_offers_a_prompt() -> None:
    for state in (
        CameraPermission.GRANTED,
        CameraPermission.DENIED,
        CameraPermission.UNAVAILABLE,
        CameraPermission.UNSUPPORTED_PLATFORM,
    ):
        assert evaluate(_facts(permission=state)).may_prompt is False


# ---- every refusal is actionable and distinguishable ----------------------


def test_the_four_failures_are_four_different_blockers() -> None:
    """The acceptance criterion `doctor` renders: missing dependency, missing
    device and permission denial must not collapse into one answer."""
    blockers = {
        evaluate(_facts(package_can_run_camera=False, package_label="the snap")).blocker,
        evaluate(_facts(runtime_missing=("cv2",))).blocker,
        evaluate(_facts(permission=CameraPermission.UNAVAILABLE)).blocker,
        evaluate(_facts(permission=CameraPermission.DENIED)).blocker,
    }
    assert len(blockers) == 4, f"failures collapsed into {blockers}"


def test_a_denial_carries_the_remedy_it_was_given() -> None:
    gate = evaluate(
        _facts(permission=CameraPermission.DENIED, permission_remedy="OPEN-THE-PANE")
    )
    assert "OPEN-THE-PANE" in gate.remedy


def test_every_refusal_says_something() -> None:
    """An empty reason is the failure mode this replaces: a camera feature that
    does nothing and explains nothing."""
    for facts in (
        _facts(features_enabled=()),
        _facts(package_can_run_camera=False, package_label="the flatpak"),
        _facts(runtime_missing=("cv2", "mediapipe")),
        _facts(permission=None),
        _facts(permission=CameraPermission.DENIED),
        _facts(permission=CameraPermission.UNAVAILABLE),
        _facts(permission=CameraPermission.NOT_DETERMINED),
        _facts(permission=CameraPermission.UNSUPPORTED_PLATFORM),
    ):
        assert len(evaluate(facts).reason) > 20, facts


def test_a_missing_model_is_a_note_and_not_a_refusal() -> None:
    """The landmark model downloads itself on first use (ADR-019 FETCH), so its
    absence is "this will fetch 3.7 MB", not "this is broken". Calling it a
    failure would train the reader to ignore the row."""
    gate = evaluate(_facts(permission=CameraPermission.GRANTED, notes=("model absent",)))
    assert gate.allowed is True
    assert "model absent" in gate.notes


# ---- the live wiring -------------------------------------------------------


def test_enabled_features_are_reported_in_order_and_survive_a_broken_config() -> None:
    cfg = Config()
    cfg.facegesture.enabled = True
    cfg.gaze.enabled = True
    assert enabled_camera_features(cfg) == ("gaze", "facegesture")
    # `doctor` passes None when the config file will not parse.
    assert enabled_camera_features(None) == ()


def test_the_module_probe_reports_what_is_actually_absent() -> None:
    assert missing_camera_modules(lambda name: False) == ("cv2", "mediapipe")
    assert missing_camera_modules(lambda name: True) == ()


# ---- the per-OS probes map; they do not guess -----------------------------
#
# ⚠ Read this before trusting anything below. These exercise the *mapping* each
# backend applies to an OS answer. They are not evidence that the OS answers
# correctly, and on macOS a CI runner would not be evidence either: TCC on a
# hosted runner is permissive, so an `[OK]` there is the runner, not the
# contract. No real Mac and no real Windows machine ran any of this.

import sys as _sys
import types as _types

from yazses.platform.linux import permissions as _linux_perms
from yazses.platform.macos.permissions import MacosPermissions
from yazses.platform.windows.permissions import WindowsPermissions, camera_consent_state


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (("Allow", "Allow", "Allow"), CameraPermission.GRANTED),
        # One refusal is a refusal: Windows ANDs the device, user and
        # desktop-app switches, and the last is the one usually off.
        (("Allow", "Allow", "Deny"), CameraPermission.DENIED),
        (("Deny", "Allow", "Allow"), CameraPermission.DENIED),
        (("Allow", None, None), CameraPermission.GRANTED),
        # Nothing explicit anywhere. Windows would in fact allow access, and we
        # still do not say so -- an absent key is not a recorded decision.
        ((None, None, None), CameraPermission.NOT_DETERMINED),
        ((), CameraPermission.NOT_DETERMINED),
    ],
)
def test_the_windows_consent_values_map_without_an_optimistic_default(
    values, expected
) -> None:
    assert camera_consent_state(values) is expected


def test_the_windows_probe_off_windows_is_undetermined() -> None:
    """There is no `winreg` here, so the probe learns nothing -- and nothing is
    not access. (This is also what a locked or missing hive produces.)"""
    assert WindowsPermissions().check_camera() is CameraPermission.NOT_DETERMINED


def test_the_macos_probe_without_pyobjc_is_undetermined() -> None:
    """A base install ships no AVFoundation binding. The permissive value would
    make `doctor` print a clean camera row on every Mac that has never installed
    the extra."""
    assert MacosPermissions().check_camera() is CameraPermission.NOT_DETERMINED


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (3, CameraPermission.GRANTED),          # AVAuthorizationStatusAuthorized
        (2, CameraPermission.DENIED),           # ...Denied
        (1, CameraPermission.DENIED),           # ...Restricted (MDM / Screen Time)
        (0, CameraPermission.NOT_DETERMINED),   # ...NotDetermined -> macOS will ask
    ],
)
def test_the_macos_authorization_status_maps(monkeypatch, status, expected) -> None:
    """The four AVFoundation values, against a stand-in framework.

    ⚠ A stand-in, not a Mac. What this pins is that `Restricted` is a refusal and
    `NotDetermined` is not access -- the two arms most easily collapsed into the
    wrong neighbour.
    """
    fake = _types.ModuleType("AVFoundation")
    fake.AVMediaTypeVideo = "vide"  # type: ignore[attr-defined]
    fake.AVCaptureDevice = _types.SimpleNamespace(  # type: ignore[attr-defined]
        authorizationStatusForMediaType_=lambda media: status
    )
    monkeypatch.setitem(_sys.modules, "AVFoundation", fake)
    assert MacosPermissions().check_camera() is expected


@pytest.mark.parametrize(
    ("nodes", "openable", "expected"),
    [
        ([], True, CameraPermission.UNAVAILABLE),
        (["video0"], True, CameraPermission.GRANTED),
        # The node exists and this user cannot open it -- almost always the
        # `video` group. A different problem from "there is no camera", and a
        # different sentence in `doctor`.
        (["video0", "video1"], False, CameraPermission.DENIED),
    ],
)
def test_the_linux_probe_separates_no_device_from_no_access(
    tmp_path, monkeypatch, nodes, openable, expected
) -> None:
    for name in nodes:
        (tmp_path / name).write_bytes(b"")
    monkeypatch.setattr(_linux_perms, "Path", lambda _p: tmp_path)
    monkeypatch.setattr(_linux_perms.os, "access", lambda path, mode: openable)
    assert _linux_perms.LinuxPermissions().check_camera() is expected


def test_the_linux_probe_asks_for_write_access_too(tmp_path, monkeypatch) -> None:
    """V4L2 capture issues ioctls, which are writes. `R_OK` alone would answer
    "granted" on a node that then refuses to stream -- the optimistic default
    again, one layer down."""
    (tmp_path / "video0").write_bytes(b"")
    seen: list[int] = []

    def access(path, mode):
        seen.append(mode)
        return True

    monkeypatch.setattr(_linux_perms, "Path", lambda _p: tmp_path)
    monkeypatch.setattr(_linux_perms.os, "access", access)
    _linux_perms.LinuxPermissions().check_camera()
    import os as _os

    assert seen and all(m & _os.W_OK for m in seen), f"write access was not required: {seen}"


def test_every_backend_implements_the_camera_half_of_the_protocol() -> None:
    """A `Platform` whose permissions backend lacks these would type-check and
    then answer "undetermined" forever, which reads as a feature nobody enabled."""
    for backend in (_linux_perms.LinuxPermissions(), MacosPermissions(), WindowsPermissions()):
        assert callable(getattr(backend, "check_camera", None)), backend
        advice = getattr(backend, "how_to_grant_camera", None)
        assert callable(advice), backend
        assert len(advice()) > 60, f"{backend} offers no usable camera remedy"
