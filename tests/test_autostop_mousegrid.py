"""Semantic Auto-Stop (ADR-v2-029) + Voice Mouse Grid (ADR-v2-030) — pure cores."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from yazses.endpoint.autostop import should_stop
from yazses.mousegrid.grid import resolve_point, subdivide

# ---- auto-stop -------------------------------------------------------------

@dataclass
class _AsCfg:
    enabled: bool = True
    mode: str = "silence"
    silence_timeout_ms: int = 800
    max_duration_ms: int = 30000


def test_disabled_never_stops():
    assert should_stop(9999, 9999, _AsCfg(enabled=False)) is False


def test_stops_on_silence_timeout():
    assert should_stop(900, 5000, _AsCfg()) is True
    assert should_stop(700, 5000, _AsCfg()) is False


def test_stops_on_max_duration_cap():
    assert should_stop(0, 30000, _AsCfg()) is True


def test_max_duration_zero_disables_cap():
    assert should_stop(0, 999999, _AsCfg(max_duration_ms=0)) is False


# ---- mouse grid ------------------------------------------------------------

def test_subdivide_center_cell():
    # cell 5 of a 3x3 over a 300x300 region at origin → center block (100,100,100,100)
    assert subdivide((0, 0, 300, 300), 5) == (100.0, 100.0, 100.0, 100.0)


def test_subdivide_corners():
    assert subdivide((0, 0, 300, 300), 1) == (0.0, 0.0, 100.0, 100.0)
    assert subdivide((0, 0, 300, 300), 9) == (200.0, 200.0, 100.0, 100.0)


def test_subdivide_out_of_range_raises():
    with pytest.raises(ValueError):
        subdivide((0, 0, 300, 300), 10)
    with pytest.raises(ValueError):
        subdivide((0, 0, 300, 300), 0)


def test_subdivide_bad_dims_raises():
    with pytest.raises(ValueError):
        subdivide((0, 0, 300, 300), 1, cols=0)


def test_resolve_point_empty_path_is_region_center():
    assert resolve_point((0, 0, 300, 300), []) == (150.0, 150.0)


def test_resolve_point_recursive_zoom():
    # zoom into center cell 5 then its center cell 5 → center of the 100x100 block
    pt = resolve_point((0, 0, 300, 300), [5, 5])
    assert pt == (150.0, 150.0)


def test_resolve_point_corner_zoom():
    # top-left cell then top-left again over 300x300 → center of a ~33x33 block near origin
    x, y = resolve_point((0, 0, 300, 300), [1, 1])
    assert 0 < x < 60 and 0 < y < 60


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "autostop" in slugs and "mousegrid" in slugs
    assert Config().autostop.enabled is False and Config().mousegrid.enabled is False
