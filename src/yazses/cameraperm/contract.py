"""The camera permission contract — pure decision logic, no imports beyond stdlib.

Three camera-shaped accessibility features exist (Glance-Type gaze, the
Face-Gesture Switch, and the Head-Pointer core), and ADR-v2-145 gives them one
shared camera owner. This module answers the question that comes *before* any of
them touches a device: **may this install open the camera at all, and if not,
why, and what does the user do about it?**

It is deliberately dependency-free and side-effect-free. Everything it needs is
handed to it as :class:`CameraFacts`; the OS probe lives behind
``PermissionsBackend.check_camera`` in the platform seam, and the packaging half
lives in :mod:`yazses.cameraperm.matrix`. Gathering the facts is
:mod:`yazses.cameraperm.probe`'s job.

Two rules shape the whole file, and both are here because the alternative is a
feature that silently does nothing:

* **Fail closed, and never fail closed silently.** Every non-``GRANTED`` outcome
  carries a `reason` naming what is wrong and, where one exists, a `remedy` the
  reader can act on. Ordinary dictation is never in the path -- a camera gate
  that returns "no" is not allowed to be an error anyone else sees (R-08).
* **"I could not tell" is never "yes".** :data:`CameraPermission.NOT_DETERMINED`
  is its own state and it does **not** open the camera. A probe that cannot
  answer -- no PyObjC on a Mac, an unreadable registry on Windows -- returns that
  state, not ``GRANTED``. A default that reads as granted is how a permission
  contract becomes decorative.

The evaluation order matters and is asserted in the tests: a disabled feature is
checked *before* anything else, so a machine with no camera feature enabled never
reaches a probe and therefore can never raise an OS permission prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "CAMERA_FEATURES",
    "CameraBlocker",
    "CameraFacts",
    "CameraGate",
    "CameraPermission",
    "evaluate",
    "needs_permission_probe",
]


#: Config sections whose feature opens a camera, in the order `doctor` reports
#: them. Every one of these ships ``enabled = False``; the matrix and the gate
#: are inert until a user turns one on, which is the first acceptance criterion
#: of EYE-PERM-001 and the reason nothing here runs on an ordinary install.
#:
#: `tests/test_camera_permission_contract.py` holds this list against
#: `yazses.config`, so a section renamed there cannot leave a camera feature
#: silently outside the gate.
CAMERA_FEATURES: tuple[str, ...] = (
    "gaze",
    "facegesture",
    "headpointer",
    "lipread",
    "sign",
)


class CameraPermission(str, Enum):
    """What the operating system says about camera access for this process.

    Five states, not the four of :class:`yazses.platform.base.PermissionState`,
    because the camera needs distinctions that one does not carry:

    * :data:`GRANTED` -- the OS will hand over a camera now.
    * :data:`DENIED` -- the OS has been asked and refused. Actionable.
    * :data:`NOT_DETERMINED` -- **the honest "I do not know"**. Covers macOS's
      ``AVAuthorizationStatusNotDetermined`` (nothing has asked yet, so the OS
      will prompt) *and* a probe that could not run at all. Both mean "do not
      claim access"; they differ only in whether a prompt is expected, which
      :attr:`CameraGate.may_prompt` carries.
    * :data:`UNAVAILABLE` -- the permission question does not arise because the
      machine exposes no camera device.
    * :data:`UNSUPPORTED_PLATFORM` -- this OS has no YazSes backend, so nothing
      here can speak for it.

    ``NOT_DETERMINED`` and ``UNAVAILABLE`` are kept apart on purpose: "you have
    not granted it" and "there is no camera" send a reader to two different
    places, and collapsing them is what makes a diagnostic useless.
    """

    GRANTED = "granted"
    DENIED = "denied"
    NOT_DETERMINED = "not-determined"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED_PLATFORM = "unsupported-platform"


class CameraBlocker(str, Enum):
    """Why the camera is not available -- one value per *place the fix lives*.

    The point of an enum rather than prose is that each value routes the reader
    somewhere different: `PACKAGING` is fixed by installing YazSes another way,
    `RUNTIME_MISSING` by installing an extra, `PERMISSION_DENIED` in a settings
    pane, `NO_DEVICE` by plugging something in. A single "camera unavailable"
    would send all four to the same dead end.
    """

    NONE = "none"
    FEATURE_OFF = "feature-off"
    PACKAGING = "packaging"
    RUNTIME_MISSING = "runtime-missing"
    NOT_PROBED = "not-probed"
    PERMISSION_DENIED = "permission-denied"
    PERMISSION_UNKNOWN = "permission-unknown"
    NO_DEVICE = "no-device"
    UNSUPPORTED = "unsupported-platform"


@dataclass(frozen=True)
class CameraFacts:
    """Everything :func:`evaluate` is allowed to know. Plain data, no behaviour.

    ``permission`` is ``None`` when no probe was run, which is the correct state
    whenever :func:`needs_permission_probe` said not to run one. ``None`` is
    *not* treated as permissive -- see :data:`CameraBlocker.NOT_PROBED`.
    """

    #: Config sections whose camera feature is switched on, e.g. ``("gaze",)``.
    #: Empty means no feature wants a camera, which is the shipped default.
    features_enabled: tuple[str, ...] = ()
    #: Human name of the install format, for the message ("the Windows MSIX").
    package_label: str = "this install"
    #: Whether a camera feature can run in this install format at all.
    package_can_run_camera: bool = True
    #: The OS declaration a camera-capable build of this format must carry
    #: (``"NSCameraUsageDescription"``, ``"DeviceCapability webcam"``, ...), or
    #: ``None`` where the format has no manifest to declare anything in.
    package_declaration: str | None = None
    #: How a user of this format *could* get a camera-capable install, if at all.
    package_remedy: str = ""
    #: Import names of camera runtime packages that are not installed.
    runtime_missing: tuple[str, ...] = ()
    #: The pip requirement strings that would supply them.
    runtime_packages: tuple[str, ...] = ()
    #: The OS answer, or ``None`` when deliberately not asked.
    permission: CameraPermission | None = None
    #: ``PermissionsBackend.how_to_grant_camera()`` output, when there is one.
    permission_remedy: str = ""
    #: Non-blocking observations, e.g. a landmark model not downloaded yet.
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CameraGate:
    """The decision. ``allowed`` is the only thing a caller may treat as "yes"."""

    allowed: bool
    blocker: CameraBlocker
    reason: str
    remedy: str = ""
    #: True only for :data:`CameraPermission.NOT_DETERMINED` *from a working
    #: probe on an OS that prompts*. It means "asking would show the user a
    #: dialog", which is a decision for the feature that wants the camera, not
    #: for this module. It is never a licence to open the device.
    may_prompt: bool = False
    permission: CameraPermission | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def needs_permission_probe(facts: CameraFacts) -> bool:
    """Whether the OS may be asked about the camera at all.

    This is the acceptance criterion "given camera features disabled, no camera
    permission prompt occurs", written as one function so it can be tested
    without a camera, an OS, or a mock of either. It is also why the probe is
    not simply called eagerly and interpreted afterwards: on macOS the *act of
    asking* is what raises the prompt, so the order is the guarantee.

    A format that cannot run a camera feature is excluded for the same reason,
    one step earlier (R-21): asking a user of the Windows MSIX for camera
    consent that nothing in that package could use is a prompt with no upside.
    """
    if not facts.features_enabled:
        return False
    if not facts.package_can_run_camera:
        return False
    return not facts.runtime_missing


def evaluate(facts: CameraFacts) -> CameraGate:
    """Decide, in the one order that keeps the guarantees above true.

    The sequence is: feature switch -> packaging -> runtime -> OS permission.
    Each step is strictly more specific than the last, so the first failure is
    always the one the reader should fix first, and no later step can be reached
    by a machine that should never have asked the question.
    """
    if not facts.features_enabled:
        return CameraGate(
            allowed=False,
            blocker=CameraBlocker.FEATURE_OFF,
            reason="no camera feature is enabled, so nothing opens the camera",
            permission=None,
            notes=facts.notes,
        )

    on = ", ".join(facts.features_enabled)

    if not facts.package_can_run_camera:
        declaration = (
            f" It declares no {facts.package_declaration}, deliberately: an unused "
            "camera capability is a permission request nobody here can honour."
            if facts.package_declaration
            else ""
        )
        return CameraGate(
            allowed=False,
            blocker=CameraBlocker.PACKAGING,
            reason=(
                f"{on} is enabled, but {facts.package_label} ships no camera runtime "
                f"and cannot add one.{declaration}"
            ),
            remedy=facts.package_remedy,
            permission=None,
            notes=facts.notes,
        )

    if facts.runtime_missing:
        missing = ", ".join(facts.runtime_missing)
        packages = " ".join(facts.runtime_packages)
        return CameraGate(
            allowed=False,
            blocker=CameraBlocker.RUNTIME_MISSING,
            reason=f"{on} is enabled, but {missing} is not installed",
            remedy=(f"pip install {packages}" if packages else ""),
            permission=None,
            notes=facts.notes,
        )

    if facts.permission is None:
        # Reached only if a caller skipped the probe it was told to run. Fail
        # closed and say so, rather than inventing an answer -- an absent probe
        # result that reads as permission is precisely the defect this contract
        # exists to prevent.
        return CameraGate(
            allowed=False,
            blocker=CameraBlocker.NOT_PROBED,
            reason="camera permission was never checked, so access is not assumed",
            permission=None,
            notes=facts.notes,
        )

    if facts.permission is CameraPermission.GRANTED:
        return CameraGate(
            allowed=True,
            blocker=CameraBlocker.NONE,
            reason=f"camera access is granted ({on} enabled)",
            permission=facts.permission,
            notes=facts.notes,
        )

    if facts.permission is CameraPermission.UNSUPPORTED_PLATFORM:
        return CameraGate(
            allowed=False,
            blocker=CameraBlocker.UNSUPPORTED,
            reason="this operating system has no YazSes camera-permission backend",
            permission=facts.permission,
            notes=facts.notes,
        )

    if facts.permission is CameraPermission.UNAVAILABLE:
        return CameraGate(
            allowed=False,
            blocker=CameraBlocker.NO_DEVICE,
            reason="no camera device is visible to this machine",
            remedy=facts.permission_remedy,
            permission=facts.permission,
            notes=facts.notes,
        )

    if facts.permission is CameraPermission.DENIED:
        return CameraGate(
            allowed=False,
            blocker=CameraBlocker.PERMISSION_DENIED,
            reason="the operating system refused camera access",
            remedy=facts.permission_remedy,
            permission=facts.permission,
            notes=facts.notes,
        )

    # NOT_DETERMINED. Not an error and not a yes: on macOS the OS will prompt the
    # first time something opens the camera, and on Windows and Linux it is what
    # an unreadable probe reports. Either way the caller does not have access.
    return CameraGate(
        allowed=False,
        blocker=CameraBlocker.PERMISSION_UNKNOWN,
        reason=(
            "camera permission is undetermined — the OS has not been asked, or the "
            "probe could not answer. Access is not assumed."
        ),
        remedy=facts.permission_remedy,
        may_prompt=True,
        permission=facts.permission,
        notes=facts.notes,
    )
