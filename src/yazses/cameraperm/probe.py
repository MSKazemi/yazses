"""Gather the facts the camera gate decides on -- the only impure half.

:mod:`yazses.cameraperm.contract` decides and :mod:`yazses.cameraperm.matrix`
remembers what each install format can do; this module is what reads the live
config, the installed packages and -- **only when the first two say it may** --
the operating system.

That ordering is the whole point of putting it in its own module. The OS probe
is reached through one function, :func:`resolve`, which asks
:func:`~yazses.cameraperm.contract.needs_permission_probe` first, so "a machine
with no camera feature enabled never raises a camera permission prompt" is a
property of one readable call path rather than a claim about every caller.

Backends are injected (``probe=``, ``find_module=``) so the tests exercise every
branch with no camera, no mediapipe and no macOS. That matters more than usual
here: the Windows and macOS probes cannot be run anywhere this project is
developed, so what CI proves about them is the *mapping*, not the device.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
    PackageProfile,
    current_profile,
)

__all__ = [
    "enabled_camera_features",
    "explain_open_failure",
    "missing_camera_modules",
    "resolve",
]


def enabled_camera_features(cfg: Any) -> tuple[str, ...]:
    """The camera features switched on in *cfg*, in :data:`CAMERA_FEATURES` order.

    ``getattr`` twice rather than attribute access: `doctor` runs with ``cfg``
    set to ``None`` when the config file will not parse, and a diagnostic that
    crashes on a broken config is the one case where it was most needed.
    """
    if cfg is None:
        return ()
    found = []
    for name in CAMERA_FEATURES:
        section = getattr(cfg, name, None)
        if section is not None and bool(getattr(section, "enabled", False)):
            found.append(name)
    return tuple(found)


def missing_camera_modules(
    find_module: Callable[[str], bool] | None = None,
) -> tuple[str, ...]:
    """Which of :data:`CAMERA_MODULES` cannot be imported here.

    ``find_spec`` rather than ``import``: importing OpenCV and MediaPipe costs
    hundreds of milliseconds and initialises native libraries, and `doctor`
    only needs to know whether they are present. Rule 3 of AGENTS.md -- heavy
    dependencies are never imported at module scope -- is the same rule.
    """
    if find_module is None:
        from importlib.util import find_spec

        def find_module(name: str) -> bool:
            try:
                return find_spec(name) is not None
            except (ImportError, ValueError):  # pragma: no cover - defensive
                return False

    return tuple(name for name in CAMERA_MODULES if not find_module(name))


def _model_note(model_present: Callable[[], bool] | None) -> tuple[str, ...]:
    """A note when the FaceLandmarker asset has not been fetched yet.

    A note and not a blocker: the model is downloaded once on first use
    (``gaze/download.py``, registered FETCH in ADR-019), so its absence means
    "the first run will fetch 3.7 MB", not "this will fail". `doctor` still says
    so, because the acceptance criterion asks it to tell a missing model apart
    from a missing device and a refused permission.
    """
    if model_present is None:
        def model_present() -> bool:
            try:
                from yazses.gaze.download import model_dir

                asset = model_dir() / "face_landmarker.task"
                return asset.is_file() and asset.stat().st_size > 0
            except Exception:  # pragma: no cover - defensive
                return True  # cannot tell -> do not invent a warning

    if model_present():
        return ()
    return (
        "the MediaPipe face-landmarker model (~3.7 MB) is not in the cache yet; "
        "the first camera run downloads it once",
    )


def resolve(
    cfg: Any,
    *,
    probe: Callable[[], CameraPermission] | None = None,
    remedy: Callable[[], str] | None = None,
    profile: PackageProfile | None = None,
    find_module: Callable[[str], bool] | None = None,
    model_present: Callable[[], bool] | None = None,
) -> CameraGate:
    """Decide whether this install may open the camera, and why not when it may not.

    ``probe``/``remedy`` default to the active platform's
    ``PermissionsBackend.check_camera`` / ``how_to_grant_camera``. They are
    resolved lazily and **only if** the packaging and runtime pre-filters passed,
    so importing this module cannot by itself reach the OS.

    An OS with no YazSes backend answers
    :data:`CameraPermission.UNSUPPORTED_PLATFORM` rather than raising: the whole
    point of this path is to explain an absence, and turning an unsupported
    system into a traceback out of `yazses doctor` would be the same bug in a
    louder form.
    """
    profile = profile or current_profile()
    features = enabled_camera_features(cfg)
    missing = missing_camera_modules(find_module) if features else ()

    facts = CameraFacts(
        features_enabled=features,
        package_label=profile.label,
        package_can_run_camera=profile.can_run_camera,
        package_declaration=profile.declaration,
        package_remedy=profile.remedy,
        runtime_missing=missing,
        runtime_packages=CAMERA_PACKAGES if missing else (),
        notes=_model_note(model_present) if features else (),
    )

    if not needs_permission_probe(facts):
        return evaluate(facts)

    if probe is None or remedy is None:
        probe, remedy = _platform_camera_probe(probe, remedy)

    state, advice = _ask(probe, remedy)

    return evaluate(
        CameraFacts(
            features_enabled=facts.features_enabled,
            package_label=facts.package_label,
            package_can_run_camera=facts.package_can_run_camera,
            package_declaration=facts.package_declaration,
            package_remedy=facts.package_remedy,
            runtime_missing=facts.runtime_missing,
            runtime_packages=facts.runtime_packages,
            permission=state,
            permission_remedy=advice,
            notes=facts.notes,
        )
    )


def _ask(
    probe: Callable[[], CameraPermission],
    remedy: Callable[[], str],
) -> tuple[CameraPermission, str]:
    """Run the OS probe and its remedy, once each, never raising.

    No caching, on purpose: macOS TCC and the Windows ConsentStore change while this
    process runs (the user flips a switch in Settings), and an answer remembered from
    the first call would keep reporting a refusal after the grant. Every call asks again.
    """
    try:
        state = probe()
    except Exception:  # pragma: no cover - defensive
        # A probe that raised told us nothing, and "nothing" is never "granted".
        state = CameraPermission.NOT_DETERMINED
    try:
        advice = remedy()
    except Exception:  # pragma: no cover - defensive
        advice = ""
    return state, advice


#: One short sentence per blocker, for the places that have room for a sentence and not
#: a paragraph -- the shared source truncates a failure reason to 200 characters, and the
#: full remedy (a macOS one runs to ten lines) belongs to `yazses doctor`.
_OPEN_FAILURE_TEXT: dict[CameraBlocker, str] = {
    CameraBlocker.RUNTIME_MISSING: "{missing} is not installed (see `yazses doctor`)",
    CameraBlocker.PACKAGING: (
        "{label} ships no camera runtime and cannot add one (see `yazses doctor`)"
    ),
    CameraBlocker.PERMISSION_DENIED: (
        "the OS has refused camera access; grant it (`yazses doctor` shows how), "
        "then restart YazSes"
    ),
    CameraBlocker.PERMISSION_UNKNOWN: (
        "camera permission is not granted yet; answer the OS prompt or see "
        "`yazses doctor`, then restart YazSes"
    ),
    CameraBlocker.NO_DEVICE: "no camera device is visible to this machine",
    CameraBlocker.UNSUPPORTED: "this OS has no camera-permission backend",
    CameraBlocker.NONE: (
        "the OS reports camera access is granted, so another application probably "
        "holds the camera"
    ),
}


def explain_open_failure(
    *,
    probe: Callable[[], CameraPermission] | None = None,
    remedy: Callable[[], str] | None = None,
    profile: PackageProfile | None = None,
    find_module: Callable[[str], bool] | None = None,
) -> str:
    """Why a camera that was *just attempted* would not open -- one short sentence.

    :func:`resolve` answers "may we try?" and runs before anything is attempted. This is
    the other direction: the attempt has already failed, and the only evidence is that
    OpenCV returned a closed handle -- which it does identically for a refused permission,
    a busy device, an unplugged one and a macOS prompt still waiting for an answer. The
    OS probe is what tells those apart, so it is asked *now*, after the failure, and
    never before: asking first would be a gate, and a gate on macOS must not stand between
    the user and the one-time prompt that only an actual open can raise.

    Never raises -- it runs inside an error path, and an exception here would replace the
    failure being explained -- and returns ``""`` when it learned nothing, so the caller
    keeps its own generic wording.
    """
    try:
        profile = profile or current_profile()
        missing = missing_camera_modules(find_module)
        facts = CameraFacts(
            features_enabled=("camera",),
            package_label=profile.label,
            package_can_run_camera=profile.can_run_camera,
            runtime_missing=missing,
        )
        if needs_permission_probe(facts):
            if probe is None or remedy is None:
                probe, remedy = _platform_camera_probe(probe, remedy)
            state, _ = _ask(probe, remedy)
            facts = CameraFacts(
                features_enabled=facts.features_enabled,
                package_label=facts.package_label,
                package_can_run_camera=facts.package_can_run_camera,
                runtime_missing=facts.runtime_missing,
                permission=state,
            )
        gate = evaluate(facts)
        template = _OPEN_FAILURE_TEXT.get(gate.blocker, "")
        return template.format(missing=", ".join(missing), label=profile.label)
    except Exception:  # pragma: no cover - defensive
        return ""


def _platform_camera_probe(
    probe: Callable[[], CameraPermission] | None,
    remedy: Callable[[], str] | None,
) -> tuple[Callable[[], CameraPermission], Callable[[], str]]:
    """The active platform's camera probe, or an honest stand-in for it.

    ``getattr`` against the backend, not a bare attribute: a third-party or
    older `PermissionsBackend` that predates ``check_camera`` must read as
    "cannot tell", exactly as ``_input_monitoring_check`` treats a backend
    without ``check_input_monitoring``. A missing method is not permission.
    """
    from yazses.platform.base import UnsupportedPlatformError
    from yazses.platform.factory import get_platform

    try:
        perms = get_platform().permissions
    except UnsupportedPlatformError:
        return (
            lambda: CameraPermission.UNSUPPORTED_PLATFORM,
            lambda: "",
        )

    found_probe = probe or getattr(perms, "check_camera", None)
    found_remedy = remedy or getattr(perms, "how_to_grant_camera", None)
    return (
        found_probe or (lambda: CameraPermission.NOT_DETERMINED),
        found_remedy or (lambda: ""),
    )
