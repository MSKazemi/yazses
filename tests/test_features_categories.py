"""Every capability must belong to exactly one known functional category, so
`yazses features` can cluster the (large) list under headings without drift."""
from __future__ import annotations

from yazses.config import Config
from yazses.system.features import (
    CATEGORY_ORDER,
    _CATEGORIES,
    _registry,
    feature_status,
    grouped_features,
)


def _cfg() -> Config:
    return Config()


def test_every_feature_has_a_known_category() -> None:
    feats = feature_status(_cfg())
    for f in feats:
        assert f.category, f"{f.slug} has no category"
        assert f.category in CATEGORY_ORDER, f"{f.slug} category {f.category!r} not in CATEGORY_ORDER"


def test_category_map_matches_registry_exactly() -> None:
    reg = {d.slug for d in _registry()}
    assert set(_CATEGORIES) == reg, (
        f"category map drifted: missing {reg - set(_CATEGORIES)}, "
        f"extra {set(_CATEGORIES) - reg}"
    )


def test_grouped_features_covers_all_and_preserves_order() -> None:
    cfg = _cfg()
    groups = grouped_features(cfg)
    # categories appear in CATEGORY_ORDER order
    seen = [cat for cat, _blurb, _feats in groups]
    assert seen == [c for c in CATEGORY_ORDER if c in seen]
    # every feature is represented exactly once across the groups
    grouped_slugs = [f.slug for _cat, _b, feats in groups for f in feats]
    all_slugs = [f.slug for f in feature_status(cfg)]
    assert sorted(grouped_slugs) == sorted(all_slugs)
    assert len(grouped_slugs) == len(set(grouped_slugs))


def test_each_group_has_a_blurb() -> None:
    for _cat, blurb, _feats in grouped_features(_cfg()):
        assert blurb, "every rendered category needs a one-line blurb"
