"""Enabled features whose optional libraries are missing — found, named, and remedied.

A capability that needs an optional extra can end up switched on with nothing to
run it, by routes no single command sees:

* the user edited ``config.toml`` by hand, or copied it from another machine;
* `features enable` ran, and its install failed (the config key stands by design —
  see ``settingsui/deps.py`` and ``docs/architecture.md``);
* `features enable --no-install`, or the settings window with auto-install off;
* an upgrade or reinstall rebuilt the environment without the extra
  (``uv tool upgrade``, ``pipx reinstall``, ``uv tool install --force``);
* something removed one of the two OpenCV builds the camera features installed up to
  2.43.2 (an older YazSes's ``uv tool upgrade``, ``uv sync``, ``pip uninstall
  opencv-python``) and took the ``cv2`` files the other build shares with it. ``cv2``
  then still *imports*, as a namespace package, so the import probe calls it present;
  ``system/opencv_health.py`` sees the husk, and the remedy is the pinned repair an
  upgrade would print (``updater.cv2_repair_here``), not an install.

Each of those used to end the same way: the feature's own factory logged one line
at daemon start — often naming a developer command such as ``uv sync --extra tts``
that does nothing for an end user — and the capability was silently dead after
that. This module answers the one question all of those surfaces need, from the
feature registry rather than a hand-written list: *which enabled features cannot
run here, what is missing, and what is the one command that fixes it?* The daemon
announces it at start — with an **Install now** button where an install can work
(``system/ondemand.py``) — `yazses doctor` prints a row per feature, `yazses
features` marks the row, and ``yazses features install`` installs them all.

Pure apart from the injected probes, so every case tests without an optional
dependency installed. It never installs anything: installing is a network action
and stays a thing the user starts (AGENTS.md rule 1, ADR-019).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

#: Capabilities that only exist on a desktop. With no graphical session they could
#: not run even with every library present, so their missing Qt is not a finding: a
#: headless server ships with the tray "on" by default and must not be told to
#: download 648 MB of Qt it can never show.
DESKTOP_ONLY: frozenset[str] = frozenset({"tray", "overlay"})


@dataclass(frozen=True)
class DormantFeature:
    """One enabled capability that cannot run because its libraries are absent."""

    slug: str
    name: str
    missing: tuple[str, ...]      # import names that failed to resolve
    packages: tuple[str, ...]     # the requirements `features enable` installs
    remedy: str                   # the one thing to run (or why nothing can)
    #: False when installing is not the fix: this environment can never install them
    #: (a snap, a frozen bundle, the system Python), or they *are* installed and
    #: damaged (a half-deleted ``cv2``). No surface may then offer an "Install now"
    #: that refuses or changes nothing; the remedy says what to do instead.
    installable: bool = True
    command: str = ""             # the exact command that fixes it
    #: What is wrong when it is not "not installed" -- a half-deleted ``cv2``.
    problem: str = ""

    def what(self) -> str:
        """The finding without the remedy: "cv2 is not installed", or :attr:`problem`."""
        if self.problem:
            return self.problem
        return (
            f"{', '.join(self.missing)} "
            f"{'is' if len(self.missing) == 1 else 'are'} not installed"
        )

    def describe(self) -> str:
        """One line for a log, a toast or a doctor row.

        A :attr:`problem` finding is worded tighter: its remedy carries a full
        interpreter path, and on Windows the toast is relayed into a tray balloon that
        Windows drops over 255 characters (the toast's title already says the feature
        is on and cannot run).
        """
        if self.problem:
            return f"{self.name}: {self.problem}. {self.remedy}"
        return f"{self.name} is on, but {self.what()}, so it does nothing. {self.remedy}"


def enable_command(feat) -> str:
    """The exact command that installs *feat*'s libraries (and keeps it on).

    `features enable` on an already-enabled capability re-writes the same key and
    installs whatever is missing, so it is the remedy for every route above. An
    experimental capability refuses without ``--force``, so the remedy carries it —
    a printed command that then refuses is the failure this module exists to end.
    """
    from yazses.system.features import EXPERIMENTAL

    force = " --force" if getattr(feat, "tier", "") == EXPERIMENTAL else ""
    return f"yazses features enable {feat.slug}{force}"


def _default_missing(modules: Iterable[str]) -> list[str]:
    from yazses.system.deps import missing_modules

    return missing_modules(modules)


def _default_blocked(packages: Sequence[str]) -> str | None:
    from yazses.system.deps import install_blocked_reason

    return install_blocked_reason(packages)


def _default_graphical() -> bool:
    from yazses.system.graphical import has_graphical_session

    return has_graphical_session(os.environ)


def _default_cv2_broken() -> bool:
    from yazses.system.opencv_health import cv2_half_deleted

    return cv2_half_deleted()


def _default_cv2_repair() -> list[str] | None:
    # Imported only once a husk was found: `updater` carries the network imports a
    # start must not pay for.
    from yazses.system.updater import cv2_repair_here

    return cv2_repair_here()


#: The finding for a half-deleted ``cv2``; ``yazses doctor``'s OpenCV row says the same.
#: Short on purpose: on Windows the daemon's toast becomes a tray balloon, which
#: Windows drops over 255 characters, and the repair command after it carries the full
#: path of the environment's interpreter. ``yazses doctor`` and the docs say why.
CV2_HALF_DELETED = "OpenCV (cv2) is half-deleted"


def cv2_repair_remedy(repair: Sequence[str] | None) -> str:
    """The remedy for a half-deleted ``cv2``: the exact pinned repair when this install
    has one (``updater.cv2_repair_here``), else which package to reinstall."""
    if repair:
        from yazses.system.remedy import render_command

        return f"Repair it with:  {render_command(repair)}"
    return "Reinstall opencv-contrib-python with --force-reinstall --no-deps."


def _cv2_finding(feat, repair: Sequence[str]) -> DormantFeature:
    from yazses.system.remedy import render_command

    return DormantFeature(
        slug=feat.slug,
        name=feat.name,
        missing=("cv2",),
        packages=tuple(feat.pip_packages),
        remedy=cv2_repair_remedy(repair),
        installable=False,
        command=render_command(repair) if repair else "",
        problem=CV2_HALF_DELETED,
    )


def _runs_here(feat) -> bool:
    """On, wired, and backed by optional libraries — the only rows that can be dormant."""
    return bool(
        getattr(feat, "on", False)
        and getattr(feat, "wired", True)
        and getattr(feat, "pip_packages", ())
        and getattr(feat, "check_modules", ())
    )


def dormant_features(
    cfg,
    *,
    features: Sequence | None = None,
    missing: Callable[[Iterable[str]], Sequence[str]] | None = None,
    blocked: Callable[[Sequence[str]], str | None] | None = None,
    graphical: Callable[[], bool] | None = None,
    cv2_broken: Callable[[], bool] | None = None,
    cv2_repair: Callable[[], Sequence[str] | None] | None = None,
) -> list[DormantFeature]:
    """Every enabled capability in *cfg* whose optional libraries are not importable
    -- or, for a camera feature, whose ``cv2`` imports only as a half-deleted husk.

    Derived from the registry (``features.feature_status``), so a capability added
    with a ``_FEATURE_DEPS`` entry is covered with no edit here. An unwired
    capability is skipped — it cannot run whatever is installed, and `features`
    already marks it — as is a desktop-only one when there is no desktop.

    When the environment can never install the libraries (a snap, a frozen
    ``.app``/``.exe``), the remedy is that reason rather than a command that would
    refuse.

    A camera feature (its registry row checks for ``cv2``) whose libraries all import
    is asked one more question, at most once per call: is ``cv2`` a husk
    (``system/opencv_health.py``)? One ``find_spec`` and one directory listing, never
    an import of ``cv2``; nobody without a camera feature switched on pays even that.
    The repair command is built only when a husk is found. A caller that injects
    *missing* describes a hypothetical environment, so the real ``cv2`` is consulted
    only if *cv2_broken* is injected too.
    """
    if features is None:
        from yazses.system.features import feature_status

        features = feature_status(cfg)
    probe = missing or _default_missing
    why_blocked = blocked or _default_blocked
    is_graphical = graphical or _default_graphical
    if cv2_broken is None:
        cv2_broken = _default_cv2_broken if missing is None else (lambda: False)
    repair_for = cv2_repair or _default_cv2_repair

    from yazses.system.opencv_health import uses_cv2

    out: list[DormantFeature] = []
    desktop: bool | None = None
    husk: bool | None = None
    repair: list[str] | None = None
    for feat in features:
        if not _runs_here(feat):
            continue
        absent = tuple(probe(feat.check_modules))
        if not absent:
            if uses_cv2(feat):
                if husk is None:
                    husk = bool(cv2_broken())
                if husk:
                    if repair is None:
                        try:
                            repair = list(repair_for() or ())
                        except Exception:  # noqa: BLE001 - must not hide the finding
                            repair = []
                    out.append(_cv2_finding(feat, repair))
            continue
        if feat.slug in DESKTOP_ONLY:
            if desktop is None:
                desktop = bool(is_graphical())
            if not desktop:
                continue
        reason = why_blocked(tuple(feat.pip_packages))
        command = enable_command(feat)
        remedy = reason if reason else f"Install them with:  {command}"
        out.append(
            DormantFeature(
                slug=feat.slug,
                name=feat.name,
                missing=absent,
                packages=tuple(feat.pip_packages),
                remedy=remedy,
                installable=reason is None,
                command=command,
            )
        )
    return out


def preserved_requirements(
    cfg,
    *,
    features: Sequence | None = None,
    missing: Callable[[Iterable[str]], Sequence[str]] | None = None,
) -> tuple[str, ...]:
    """The requirements an upgrade must keep: enabled features that work *now*.

    Only installed libraries are preserved. An enabled-but-dormant capability is
    not, on purpose: adding it would turn "Install update" into a download of
    whatever that feature needs (gaze is gigabytes), which the user did not ask
    for in that click. Dormant ones are announced instead (:func:`dormant_features`).
    """
    if features is None:
        from yazses.system.features import feature_status

        features = feature_status(cfg)
    probe = missing or _default_missing
    keep: list[str] = []
    for feat in features:
        if not _runs_here(feat):
            continue
        if probe(feat.check_modules):
            continue
        keep.extend(feat.pip_packages)
    return tuple(dict.fromkeys(keep))


def dormant_by_slug(items: Iterable[DormantFeature]) -> Mapping[str, DormantFeature]:
    return {d.slug: d for d in items}
