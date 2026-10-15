"""Gather the panel's inputs and carry out its actions — the impure half of #420.

`handsfree/panel.py` decides what the hands-free panel says and what each button means; this
module is what looks at the world to fill it in and what performs a button's effect. Split the
way `probe.py` is split from `observability.py`, for the same reason: the view-model is then
testable against a fabricated faulted pointer, and every path that touches the machine
arrives through one readable place with its seams injected.

**Nothing here opens a camera.** The facts come from the daemon's existing ``status`` and
``headpointer status`` replies, the saved config, the camera *permission* verdict
(`cameraperm.resolve` reads a device node's access bits; it never reads a frame), the stored
gaze calibration and the stored face-switch baseline. A test holds that line by making
``cv2`` and ``mediapipe`` unimportable and gathering anyway.

**Nothing here raises into the window.** Every failure becomes a fact (``UNKNOWN``) or an
:class:`ActionResult` with ``ok=False`` and a sentence — an exception escaping a Qt slot is
how a settings window closes under a user who has no other way to operate YazSes.

**Slow work stays off the UI thread.** :func:`gather_panel_inputs` may spawn a subprocess (the
display-topology query behind the calibration check on a real desktop), so the window calls it
from a worker thread; :func:`perform_action` is one short socket round-trip or one file write.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from yazses.handsfree.observability import HandsFreeFacts, facts_from_payload
from yazses.handsfree.panel import (
    CAMERA_FEATURES,
    ActionSpec,
    ConfigSet,
    ConfigTableArray,
    FeatureFact,
    PanelInputs,
    merge_facts,
)

__all__ = ["ActionResult", "gather_panel_inputs", "perform_action"]

#: ``ipc(method, params) -> reply``; raises when the daemon cannot be reached.
IpcCaller = Callable[[str, dict[str, object]], Any]
KeyWriter = Callable[[str, str, object, bool | None], None]
TableWriter = Callable[[str, Iterable[Iterable[tuple[str, str]]]], None]


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str
    #: True when a config write landed but the running daemon did not take the change.
    saved_only: bool = False


def _feature_facts(
    cfg: Any,
    staged: Mapping[str, bool],
    deps_probe: Callable[[Iterable[str]], list[str]] | None,
    blocked_probe: Callable[[tuple[str, ...]], str | None] | None,
) -> tuple[FeatureFact, ...]:
    from yazses.system.deps import install_blocked_reason, missing_modules
    from yazses.system.features import EXPERIMENTAL, find_feature

    probe = deps_probe or missing_modules
    blocked = blocked_probe or install_blocked_reason
    out = []
    for slug, label, _summary in CAMERA_FEATURES:
        feat = find_feature(cfg, slug)
        if feat is None:
            continue
        missing: tuple[str, ...] = ()
        if feat.pip_packages and (not feat.check_modules or probe(feat.check_modules)):
            missing = tuple(feat.pip_packages)
        out.append(
            FeatureFact(
                slug=slug,
                label=label,
                enabled=bool(feat.on and feat.wired),
                wired=bool(feat.wired),
                experimental=feat.tier == EXPERIMENTAL,
                missing_packages=missing,
                blocked=(blocked(tuple(feat.pip_packages)) or "") if missing else "",
                staged=staged.get(slug),
            )
        )
    return tuple(out)


def gather_panel_inputs(
    cfg: Any,
    platform: Any,
    ipc: IpcCaller | None,
    *,
    staged: Mapping[str, bool] | None = None,
    deps_probe: Callable[[Iterable[str]], list[str]] | None = None,
    blocked_probe: Callable[[tuple[str, ...]], str | None] | None = None,
    camera_gate: Any | None = None,
    read_context: Callable[[], Any] | None = None,
    unwired: frozenset[str] | None = None,
) -> PanelInputs:
    """Everything the panel needs, without opening the camera. Never raises."""
    staged = staged or {}
    features = _feature_facts(cfg, staged, deps_probe, blocked_probe)

    # ---- the running daemon -------------------------------------------------
    reachable = False
    live: HandsFreeFacts | None = None
    headpointer: Mapping[str, Any] | None = None
    if ipc is not None:
        try:
            status = ipc("status", {"consume_notifications": False})
            reachable = isinstance(status, dict)
            if isinstance(status, dict):
                live = facts_from_payload(status.get("handsfree"))
        except Exception:
            reachable = False
    hp_enabled = any(f.slug == "headpointer" and f.enabled for f in features)
    if reachable and ipc is not None and hp_enabled:
        try:
            reply = ipc("headpointer", {"action": "status"})
            headpointer = reply if isinstance(reply, dict) else None
        except Exception:
            headpointer = {"ok": False, "reason": "the daemon did not answer"}

    # ---- facts that follow from config and the OS ----------------------------
    static = HandsFreeFacts()
    camera_reason = camera_remedy = ""
    try:
        from yazses.handsfree.probe import (
            calibration_facts,
            facts_from_config,
            gaze_target_facts,
            pointer_facts,
        )

        static = facts_from_config(cfg, unwired=unwired)
        static = pointer_facts(static, platform)
        if "gaze" in static.features_requested:
            validity, reason = calibration_facts(
                platform.paths.data_dir,
                str(getattr(getattr(cfg, "gaze", None), "camera_index", 0)),
                read_context=read_context,
            )
            static = replace(static, calibration_validity=validity, calibration_reason=reason)
            static = gaze_target_facts(static)
        if static.features_requested:
            gate = camera_gate if camera_gate is not None else _camera_gate(cfg, platform)
            if gate is not None:
                static = replace(static, camera_ready=_ready(gate))
                camera_reason = str(getattr(gate, "reason", "") or "")
                camera_remedy = str(getattr(gate, "remedy", "") or "")
    except Exception:
        # Whatever could not be determined stays at its "not determined" default.
        pass
    facts = merge_facts(static, live)

    # ---- saved face-switch settings -----------------------------------------
    face = getattr(cfg, "facegesture", None)
    primary = str(getattr(face, "gesture", "jaw_open") or "jaw_open")
    baseline = ""
    release_issues: tuple[tuple[str, str], ...] = ()
    if face is not None and any(f.slug == "facegesture" and f.enabled for f in features):
        baseline = _baseline(platform, primary)
        try:
            from yazses.handsfree.probe import face_release_findings

            release_issues = tuple(
                (f.message, f.remedy) for f in face_release_findings(cfg, platform.paths.data_dir)
            )
        except Exception:
            release_issues = ()
    return PanelInputs(
        daemon_reachable=reachable,
        features=features,
        safety_configured=bool(getattr(getattr(cfg, "handsfree_safety", None), "enabled", False)),
        dwell_configured=bool(getattr(getattr(cfg, "headpointer", None), "dwell_enabled", False)),
        facts=facts,
        camera_reason=camera_reason,
        camera_remedy=camera_remedy,
        headpointer=headpointer,
        switches=tuple(
            dict(s) for s in (getattr(face, "switches", None) or []) if isinstance(s, dict)
        ),
        primary_gesture=primary,
        mode=str(getattr(face, "mode", "full_text") or "full_text"),
        use_baseline=bool(getattr(face, "use_baseline", False)),
        baseline=baseline,
        release_issues=release_issues,
    )


def _camera_gate(cfg: Any, platform: Any) -> Any | None:
    from yazses.cameraperm import CameraPermission, resolve

    perms = getattr(platform, "permissions", None)
    probe = getattr(perms, "check_camera", None) or (lambda: CameraPermission.NOT_DETERMINED)
    remedy = getattr(perms, "how_to_grant_camera", None) or (lambda: "")
    return resolve(cfg, probe=probe, remedy=remedy)


def _ready(gate: Any) -> bool | None:
    """The gate as a tri-state, exactly as `doctor` reads its Camera row. Pure."""
    from yazses.cameraperm import CameraBlocker

    if gate.allowed:
        return True
    soft = {
        CameraBlocker.PERMISSION_UNKNOWN,
        CameraBlocker.UNSUPPORTED,
        CameraBlocker.NOT_PROBED,
        CameraBlocker.FEATURE_OFF,
    }
    return None if gate.blocker in soft else False


def _baseline(platform: Any, gesture: str) -> str:
    try:
        from yazses.facegesture.calibration import baseline_path, load_baselines

        stored = load_baselines(baseline_path(platform.paths.data_dir))
        return "stored" if gesture in stored else "missing"
    except Exception:
        return ""


# ------------------------------------------------------------------------------ doing


def perform_action(
    spec: ActionSpec,
    *,
    ipc: IpcCaller | None,
    write_key: KeyWriter | None,
    write_table: TableWriter | None,
) -> ActionResult:
    """Carry out one button. Never raises; says what happened in one sentence.

    The daemon call comes first so a stop takes effect before anything else is attempted.
    A config write that accompanies it (dwell) then makes the choice survive a restart; if the
    daemon was not reachable the write alone still lands and the message says so.
    """
    if not spec.enabled:
        return ActionResult(False, spec.why_disabled or "That is not available right now.")
    live_ok: bool | None = None
    live_message = ""
    refused = False  # the daemon answered and said no — distinct from "could not ask"
    if spec.ipc is not None:
        if ipc is None:
            live_ok, live_message = False, "YazSes is not running."
        else:
            try:
                reply = ipc(spec.ipc.method, dict(spec.ipc.params))
            except Exception:
                live_ok, live_message = False, "YazSes did not answer — is it running?"
            else:
                if isinstance(reply, dict):
                    live_ok = bool(reply.get("ok"))
                    live_message = str(reply.get("reason") or "")
                    refused = not live_ok
                else:
                    live_ok, live_message = False, "YazSes sent an unreadable reply."
    if refused and not spec.config_always:
        # A running daemon that refuses (e.g. dwell-click held off because nothing would show
        # its ring) must not have the refusal written into the config behind its back.
        return ActionResult(False, live_message or "YazSes would not do that.")
    wrote = False
    if spec.config:
        try:
            for change in spec.config:
                if isinstance(change, ConfigSet):
                    if write_key is None:
                        raise OSError("config writing is not available here")
                    write_key(change.section, change.key, change.value, None)
                elif isinstance(change, ConfigTableArray):
                    if write_table is None:
                        raise OSError("config writing is not available here")
                    write_table(change.name, change.entries)
            wrote = True
        except Exception as exc:
            return ActionResult(
                False, f"Could not save the setting: {exc}"
            )
    if spec.ipc is None:
        note = " It applies after `yazses restart`." if spec.needs_restart else ""
        return ActionResult(True, "Saved." + note)
    if live_ok:
        return ActionResult(True, "Done." + (" Saved." if wrote else ""))
    if wrote:
        return ActionResult(
            True,
            "Saved, and it will apply when YazSes starts. "
            + (live_message or "The running program did not take it now."),
            saved_only=True,
        )
    return ActionResult(False, live_message or "That did not take effect.")
