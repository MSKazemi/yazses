"""The cross-platform camera permission + packaging contract (EYE-PERM-001).

One place answers "may this install open the camera, and if not, why?", so that
gaze, the face-gesture switch and the head pointer cannot each invent their own
answer -- the same reasoning ADR-v2-145 applies to the camera *device* itself,
applied one layer up to the permission to reach it.

Public API::

    from yazses.cameraperm import (
        CameraPermission,   # granted / denied / not-determined / unavailable /
                            # unsupported-platform
        CameraBlocker,      # why it is not available, one value per fix location
        CameraFacts,        # the inputs, plain data
        CameraGate,         # the decision
        evaluate,           # pure: CameraFacts -> CameraGate
        needs_permission_probe,  # pure: may the OS be asked at all?
        resolve,            # gather the facts from this machine, then evaluate
        current_profile,    # which install format this is
        PACKAGE_PROFILES,   # the checked-in packaging matrix
    )

Nothing in this package imports a camera library, and importing it cannot reach
the operating system: the OS probe lives behind
``PermissionsBackend.check_camera`` in the platform seam and is called only from
:func:`~yazses.cameraperm.probe.resolve`, after the feature switch and the
packaging matrix have both said yes.
"""

from __future__ import annotations

from yazses.cameraperm.contract import (
    CAMERA_FEATURES,
    CameraBlocker,
    CameraFacts,
    CameraGate,
    CameraPermission,
    evaluate,
    needs_permission_probe,
)
from yazses.cameraperm.matrix import (
    CAMERA_MODULES,
    CAMERA_PACKAGES,
    PACKAGE_PROFILES,
    PackageProfile,
    current_profile,
    detect_profile_key,
    profile_for,
    profile_key_for,
)
from yazses.cameraperm.probe import (
    enabled_camera_features,
    missing_camera_modules,
    resolve,
)

__all__ = [
    "CAMERA_FEATURES",
    "CAMERA_MODULES",
    "CAMERA_PACKAGES",
    "PACKAGE_PROFILES",
    "CameraBlocker",
    "CameraFacts",
    "CameraGate",
    "CameraPermission",
    "PackageProfile",
    "current_profile",
    "detect_profile_key",
    "enabled_camera_features",
    "evaluate",
    "missing_camera_modules",
    "needs_permission_probe",
    "profile_for",
    "profile_key_for",
    "resolve",
]
