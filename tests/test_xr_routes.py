"""The route registry agrees with the device table, the docs and the modules it names."""
from __future__ import annotations

from pathlib import Path

import pytest

from yazses.xr import devices, routes
from yazses.xr.types import RaySource

REPO = Path(__file__).resolve().parent.parent


def test_keys_are_unique_and_lookup_round_trips() -> None:
    assert len(set(routes.keys())) == len(routes.keys())
    for key in routes.keys():
        assert routes.get(key).key == key


def test_unknown_route_lists_the_valid_ones() -> None:
    with pytest.raises(KeyError, match="openxr"):
        routes.get("nope")
    with pytest.raises(KeyError):
        routes.get(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("key", routes.keys())
def test_every_route_points_at_real_devices_and_a_real_guide(key: str) -> None:
    route = routes.get(key)
    for device in route.devices:
        devices.get(device)  # KeyError if the table does not know it
    assert (REPO / "docs" / route.guide).is_file()
    assert route.module.__name__.startswith("yazses.xr.")
    assert route.ray_sources and all(isinstance(s, RaySource) for s in route.ray_sources)
    assert len(route.caveat) >= 40


def test_every_guide_is_in_the_docs_nav() -> None:
    nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
    for key in routes.keys():
        assert routes.get(key).guide in nav, f"{key}: guide missing from mkdocs.yml"
    assert "xr-engines.md" in nav


def test_a_pinch_time_only_route_is_never_called_continuous() -> None:
    # The binder needs a ray history; visionOS gives one ray at the pinch.
    assert routes.get("visionos").continuous_pointing is False
    assert routes.get("openxr").continuous_pointing is True


def test_routes_for_device() -> None:
    assert {r.key for r in routes.routes_for_device("vision-pro")} == {"webxr", "visionos"}
    assert routes.routes_for_device("phone-companion") == ()
    assert routes.routes_for_device("no-such-device") == ()


def test_the_engine_converters_are_not_a_route() -> None:
    assert "engines" not in routes.keys()
    assert routes.ENGINE_CONVERTERS.__name__ == "yazses.xr.engines"
