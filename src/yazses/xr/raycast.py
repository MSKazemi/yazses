"""Ray / panel intersection — which dictation surface is the user pointing at (pure).

A pointing ray (head, eye, hand or controller) is intersected with each flat
rectangular :class:`~yazses.xr.types.Panel`; the answer is the hit point as panel
coordinates ``(u, v)`` plus the distance travelled, so later stages can ask "which
panel, and where on it" without knowing anything about the headset.

**Panel frame.** Right-handed, matching ``types.py`` (+Y up, -Z forward). Seen from the
*front* (the side ``normal`` points toward, where a viewer stands), the panel's axes are::

    up    = panel.up
    right = up x normal        # a panel at z=-2 with normal +Z, up +Y has right = +X
    u = 0.5 + dot(p - center, right) / width     # 0 = left edge,   1 = right edge
    v = 0.5 + dot(p - center, up)    / height    # 0 = bottom edge, 1 = top edge

``u``/``v`` are always in this panel frame, whichever side was struck: a back-face hit
(only counted with ``allow_back_face=True``) therefore reads mirrored left-right to a
viewer behind the panel. A hit on the boundary counts; the float noise of a ray built
from an exact edge point is absorbed by ``_EDGE_EPS`` and the result is clamped to [0, 1].

Rays parallel to the panel, hits behind the ray origin, and hits past ``max_distance_m``
return nothing. No I/O, no clocks, no state.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from yazses.xr.geometry import cross, dot, sub
from yazses.xr.types import Panel, PanelHit, Ray, Vec3

# |dot(normal, direction)| below this means "parallel": the hit distance would be
# dominated by rounding noise (and a grazing hit is useless for pointing anyway).
_PARALLEL_EPS = 1e-9

# Slack, in panel-normalised units (fractions of width/height), for the edge test.
_EDGE_EPS = 1e-9


def _check_max_distance(max_distance_m: float) -> None:
    if (
        not isinstance(max_distance_m, (int, float))
        or isinstance(max_distance_m, bool)
        or not math.isfinite(max_distance_m)
        or max_distance_m <= 0
    ):
        raise ValueError(f"max_distance_m must be a finite number > 0, got {max_distance_m!r}")


def hit_panel(
    ray: Ray,
    panel: Panel,
    max_distance_m: float = 10.0,
    *,
    allow_back_face: bool = False,
) -> PanelHit | None:
    """Intersect ``ray`` with ``panel``; None on a miss. Pure.

    Misses: ray parallel to the panel plane, plane behind the origin, plane farther than
    ``max_distance_m``, hit outside the rectangle, or a back-face hit while
    ``allow_back_face`` is False. A hit exactly on an edge or corner counts, and so does
    an origin lying on the plane (distance 0).
    """
    _check_max_distance(max_distance_m)
    denom = dot(panel.normal, ray.direction)
    if abs(denom) < _PARALLEL_EPS:
        return None
    # denom < 0: the ray travels against the normal, i.e. it strikes the front face.
    if denom > 0 and not allow_back_face:
        return None
    t = dot(panel.normal, sub(panel.center, ray.origin)) / denom
    # ``not finite`` catches NaN (an origin so large that the arithmetic overflowed),
    # which would otherwise slip through both comparisons below.
    if not math.isfinite(t) or t < 0 or t > max_distance_m:
        return None
    t += 0.0  # normalise -0.0 (origin exactly on the plane) to 0.0

    d = ray.direction
    o = ray.origin
    rel = sub(Vec3(o.x + d.x * t, o.y + d.y * t, o.z + d.z * t), panel.center)
    right = cross(panel.up, panel.normal)
    u = 0.5 + dot(rel, right) / panel.width
    v = 0.5 + dot(rel, panel.up) / panel.height
    if not (-_EDGE_EPS <= u <= 1.0 + _EDGE_EPS and -_EDGE_EPS <= v <= 1.0 + _EDGE_EPS):
        return None
    return PanelHit(
        panel_id=panel.panel_id,
        u=min(1.0, max(0.0, u)),
        v=min(1.0, max(0.0, v)),
        distance_m=t,
    )


def all_hits(
    ray: Ray,
    panels: Sequence[Panel],
    max_distance_m: float = 10.0,
    *,
    allow_back_face: bool = False,
) -> list[PanelHit]:
    """Every panel the ray strikes, nearest first (ties by ``panel_id``). Pure.

    The full list is what occlusion and ambiguity checks need: a second hit a few
    centimetres behind the first is a stacked-panel situation worth confirming.
    """
    _check_max_distance(max_distance_m)
    hits = [
        h
        for p in panels
        if (h := hit_panel(ray, p, max_distance_m, allow_back_face=allow_back_face)) is not None
    ]
    hits.sort(key=lambda h: (h.distance_m, h.panel_id))
    return hits


def nearest_hit(
    ray: Ray,
    panels: Sequence[Panel],
    max_distance_m: float = 10.0,
    *,
    allow_back_face: bool = False,
) -> PanelHit | None:
    """The closest panel the ray strikes, else None. Equal distances break on ``panel_id``."""
    hits = all_hits(ray, panels, max_distance_m, allow_back_face=allow_back_face)
    return hits[0] if hits else None
