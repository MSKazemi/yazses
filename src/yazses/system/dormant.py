"""Enabled features whose optional libraries are missing — found, named, and remedied.

A capability that needs an optional extra can end up switched on with nothing to
run it, by routes no single command sees:

* the user edited ``config.toml`` by hand, or copied it from another machine;
* `features enable` ran, and its install failed (the config key stands by design —
  see ``settingsui/deps.py`` and ``docs/architecture.md``);
* `features enable --no-install`, or the settings window with auto-install off;
* an upgrade or reinstall rebuilt the environment without the extra
  (``uv tool upgrade``, ``pipx reinstall``, ``uv tool install --force``).

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
    #: False when this environment can never install them (a snap, a frozen bundle,
    #: the system Python): no surface may then offer an "Install now" that refuses.
    installable: bool = True
    command: str = ""             # the exact `yazses features enable …` that fixes it

    def describe(self) -> str:
        """One line for a log, a toast or a doctor row."""
        return (
            f"{self.name} is on, but {', '.join(self.missing)} "
            f"{'is' if len(self.missing) == 1 else 'are'} not installed, so it "
            f"does nothing. {self.remedy}"
        )


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
) -> list[DormantFeature]:
    """Every enabled capability in *cfg* whose optional libraries are not importable.

    Derived from the registry (``features.feature_status``), so a capability added
    with a ``_FEATURE_DEPS`` entry is covered with no edit here. An unwired
    capability is skipped — it cannot run whatever is installed, and `features`
    already marks it — as is a desktop-only one when there is no desktop.

    When the environment can never install the libraries (a snap, a frozen
    ``.app``/``.exe``), the remedy is that reason rather than a command that would
    refuse.
    """
    if features is None:
        from yazses.system.features import feature_status

        features = feature_status(cfg)
    probe = missing or _default_missing
    why_blocked = blocked or _default_blocked
    is_graphical = graphical or _default_graphical

    out: list[DormantFeature] = []
    desktop: bool | None = None
    for feat in features:
        if not _runs_here(feat):
            continue
        absent = tuple(probe(feat.check_modules))
        if not absent:
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
