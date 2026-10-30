"""XR ray observations as grounding targets (the XR sibling of ``gaze/grounded.py``).

ADR-025 keeps spatial devices outside the Grounded Interaction Kernel: a headset may
only enter as *observations*. This module is that entry point and nothing more. It turns
one pointing sample plus the panel hit the raycaster found into the kernel's own
:class:`~yazses.grounding.contracts.TargetSnapshot`, so the unchanged
:class:`~yazses.grounding.resolver.TargetResolver` can ask a semantic source what is
under the ray. The kernel gains no XR type; ``TargetSource.XR_RAY`` is the only trace.

What the mapping decides, and why:

* **Confidence is the sample's, never raised.** The device's own tracking confidence is
  the only evidence about how well the ray was aimed. A ray that landed squarely on a
  panel says where it landed, not that the aim was good, so a hit adds nothing — the
  resolver's rule that "low-confidence input never gains confidence" starts here.
* **Geometry is a point in a named panel space.** The hit's ``(u, v)`` becomes
  ``Point(u, 1 - v)``: ``v`` grows upward in XR, screen ``y`` grows downward, and every
  rectangle a semantic source publishes for this panel uses the screen convention. The
  space is named by the caller (:func:`panel_space` is the conventional spelling), and a
  source publishing in any other space makes the resolver abstain with
  ``SEMANTIC_SPACE_MISMATCH`` instead of comparing two unrelated grids.
* **No hit is a legitimate input.** A ray that struck nothing yields a snapshot carrying
  only a confidence, which the resolver answers ``UNRESOLVED`` (``TARGET_GEOMETRY_MISSING``).
  Inventing a point to avoid that would be a guess about where the user looked.
* **The window comes from the caller's table.** A panel that mirrors a desktop window is
  mapped to its id by the integrator; an unmapped panel simply leaves ``window_id`` unset.

What it does not do: no OpenXR, no clock (the sample carries its own timestamp), no
semantic lookup and no action. Whether the answer may be clicked stays downstream.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from yazses.grounding.contracts import (
    CoordinateSpace,
    Point,
    TargetSnapshot,
    TargetSource,
)
from yazses.xr.types import Panel, PanelHit, XrSample


def panel_space(panel_id: str, version: int = 0) -> CoordinateSpace:
    """The coordinate space of one XR panel: ``xr-panel:<id>``.

    ``version`` is the invalidation half of ADR-v2-149: a panel that moved or resized
    gets a new version, and a snapshot taken before the move then compares unequal to a
    candidate captured after it, instead of grounding against geometry that is gone.
    """
    if not panel_id:
        raise ValueError("panel_id must not be empty")
    return CoordinateSpace(f"xr-panel:{panel_id}", version)


def to_target_snapshot(
    sample: XrSample,
    hit: PanelHit | None,
    panel: Panel | None,
    *,
    space: CoordinateSpace,
    window_for_panel: Mapping[str, str] | None = None,
) -> TargetSnapshot:
    """One pointing sample and its panel hit as a :class:`TargetSnapshot`. Pure.

    ``panel`` is the panel the raycaster resolved ``hit`` against. It is optional only
    because the snapshot needs nothing from it beyond identity; when both are given they
    must agree, because a hit paired with the wrong panel would ground ``(u, v)`` in
    another surface's layout — a wrong-target error with no visible symptom.

    With no ``hit`` the result has a confidence and nothing else, whatever ``panel`` is.
    """
    if hit is None:
        return TargetSnapshot(
            source=TargetSource.XR_RAY,
            timestamp_s=sample.timestamp_s,
            confidence=sample.confidence,
        )
    if panel is not None and panel.panel_id != hit.panel_id:
        raise ValueError(
            f"hit is on panel {hit.panel_id!r} but panel {panel.panel_id!r} was supplied"
        )
    window = window_for_panel.get(hit.panel_id) if window_for_panel is not None else None
    return TargetSnapshot(
        source=TargetSource.XR_RAY,
        timestamp_s=sample.timestamp_s,
        confidence=sample.confidence,
        space=space,
        # ``1 - v``: XR's v grows upward, a screen's y grows downward.
        point=Point(hit.u, 1.0 - hit.v),
        # An empty string is not a usable window id (the contract refuses it); treat a
        # blank table entry as "unmapped" rather than failing the whole sample.
        window_id=window or None,
    )


def snapshot_series(
    samples: Sequence[XrSample],
    hits: Sequence[PanelHit | None],
    panels: Mapping[str, Panel] | None = None,
    *,
    space: CoordinateSpace | None = None,
    versions: Mapping[str, int] | None = None,
    window_for_panel: Mapping[str, str] | None = None,
) -> tuple[TargetSnapshot, ...]:
    """:func:`to_target_snapshot` over aligned sequences, in order.

    ``hits[i]`` is the raycaster's answer for ``samples[i]``; unequal lengths are a
    caller bug and raise, since silently truncating would pair a ray with another
    instant's hit. ``panels`` maps ``panel_id`` to its :class:`Panel` for the identity
    check (a hit naming a panel absent from the table is passed through unchecked).

    **Spaces.** Left ``None``, each hit is placed in its own panel's
    :func:`panel_space`, versioned by ``versions[panel_id]`` (default 0). Pass the
    current version of every panel that can move or resize: a snapshot taken before the
    move then compares unequal to one taken after it, instead of grounding against
    geometry that is gone. Without ``versions`` the version is always 0 and a moved
    panel invalidates nothing.

    ``space`` forces one space for every snapshot, and is valid only when all hits lie
    on a single panel; a series whose hits name more than one panel raises
    :class:`ValueError`, because labelling panel *b*'s ``(u, v)`` with panel *a*'s space
    would ground geometry in the wrong surface with no visible symptom. ``space`` and
    ``versions`` are mutually exclusive (an explicit space already carries a version).
    """
    if len(samples) != len(hits):
        raise ValueError(
            f"samples and hits must align one-to-one, got {len(samples)} and {len(hits)}"
        )
    if space is not None:
        if versions is not None:
            raise ValueError("pass either space or versions, not both")
        hit_panels = {h.panel_id for h in hits if h is not None}
        if len(hit_panels) > 1:
            raise ValueError(
                "an explicit space is only valid for hits on one panel, but the hits "
                f"name {sorted(hit_panels)}; omit space to use per-panel spaces"
            )
    out: list[TargetSnapshot] = []
    for sample, hit in zip(samples, hits, strict=True):
        panel = panels.get(hit.panel_id) if panels is not None and hit is not None else None
        if space is not None:
            chosen = space
        elif hit is not None:
            version = versions.get(hit.panel_id, 0) if versions is not None else 0
            chosen = panel_space(hit.panel_id, version)
        else:
            chosen = panel_space("none")  # unused: a miss carries no geometry
        out.append(
            to_target_snapshot(
                sample, hit, panel, space=chosen, window_for_panel=window_for_panel
            )
        )
    return tuple(out)
