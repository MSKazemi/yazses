"""Pure settings-window model, built from the feature registry + live config.

No Qt import here — ``app.py`` renders this, ``controller.py`` mutates the config
it describes. Grouping, labels, and the toggleable/experimental rules all come
straight from ``system/features.py`` (the single source of truth also used by
``yazses features`` and ``yazses features enable/disable``), so the window can
never drift into a hand-maintained list that disagrees with the CLI.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.system.features import EXPERIMENTAL, Feature, grouped_features


@dataclass(frozen=True)
class SettingRow:
    """One feature as a row in the settings window."""

    slug: str
    label: str
    tier_label: str
    enabled: bool
    # False for core features (can't be turned off) and for designed-but-unwired
    # ones (toggling would write a config key nothing reads) — shown, not clickable.
    toggleable: bool
    # True = flipping it ON must go through a confirmation dialog first.
    experimental: bool
    why: str


@dataclass(frozen=True)
class SettingsGroup:
    """One functional category (as `yazses features` groups them) + its rows."""

    category: str
    blurb: str
    rows: tuple[SettingRow, ...]


@dataclass(frozen=True)
class SettingsModel:
    groups: tuple[SettingsGroup, ...]


def build_settings_model(cfg) -> SettingsModel:
    """Build the settings window model from the feature registry + *cfg*.

    Mirrors ``yazses features``: same categories, same order, same on/off state.
    """
    groups = tuple(
        SettingsGroup(category=category, blurb=blurb, rows=tuple(_row(f) for f in feats))
        for category, blurb, feats in grouped_features(cfg)
    )
    return SettingsModel(groups=groups)


def _row(f: Feature) -> SettingRow:
    return SettingRow(
        slug=f.slug,
        label=f.name,
        tier_label=f.tier_label,
        enabled=f.on,
        toggleable=f.toggleable and f.wired,
        experimental=f.tier == EXPERIMENTAL,
        why=f.why,
    )
