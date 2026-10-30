"""Bind a spoken demonstrative ("this", "that", "here") to a panel (pure, stdlib only).

Multimodal deixis is the Bolt lineage ("Put-That-There", SIGGRAPH 1980): the pointing
and the word are two channels of one act, so the referent of "this" is whatever was
being pointed at *around the moment the word was spoken*, not at the instant speech
ended or at keyboard focus. GazePointAR (Lee et al., CHI 2024) applies the same idea
to wearable AR: the gaze/pointing history is searched near the word's onset and the
pronoun is resolved against it.

This module is the pure half. The caller ray-casts each pointing sample against the
panels (:mod:`yazses.xr.raycast`) and hands in :class:`PanelObservation` values with
the word's onset time from the recogniser's word timestamps; this module only weighs
them. It never guesses: a wrong action costs more than a refusal (ADR-021), so an
unclear history yields AMBIGUOUS or NONE and the caller asks or falls back.

Evidence is measured in *time*, not in samples: each observation is credited with the
interval it holds, so a panel looked at for 0.1 s counts the same whether the headset
streamed it at 30 Hz or 90 Hz. A binding also needs a minimum amount of evidence
(``min_samples`` usable observations covering ``min_coverage_s`` of the window): one
stray sample has a 100% *share* of nothing, and shares alone cannot refuse it.

The ``lead_s`` / ``lag_s`` / ``max_gap_s`` / ``min_samples`` / ``min_coverage_s``
defaults are starting points to be MEASURED on real headset data. They are not
validated values.

**Evidence beyond the verdict.** A BOUND result also reports the *checkable* facts the
confirm policy (:mod:`yazses.xr.confirm`) needs to tell a safe bind from a risky one,
without this module deciding anything about prompting:

* ``candidates`` — the top two panels by share (the specific choice a prompt can offer);
* ``rival_id`` / ``rival_deg`` — how far (degrees, evidence-weighted) the winning rays
  were from the *nearest other panel*; compared by the policy with a stated angular-error
  budget, because a tracker that is off by that much could have meant the neighbour;
* ``prior_panel`` / ``settled_s`` — another panel the gaze rested on shortly before, and
  how long ago it left it: a gaze that only just arrived cannot say whether the user
  meant the panel they were leaving or the one they reached.

None of these changes *which* panel is chosen or whether the outcome is BOUND.
"""
from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from yazses.xr.geometry import angle_between, cross, dot, sub
from yazses.xr.types import Panel, PanelHit, Ray, Vec3

# Two shares closer than this are a tie, not a lead (float noise, not evidence).
_TIE_EPS = 1e-9


@dataclass(frozen=True)
class PanelObservation:
    """One pointing sample, already ray-cast: which panel it hit (or None) and how sure.

    ``rival_id`` / ``rival_deg`` are optional and come together: the nearest *other*
    panel and the angular distance, in degrees, from this ray to that panel's rectangle
    (see :func:`ray_gap_deg`). Left None they mean "not measured", and no rule that
    needs them can fire — absence of data is not a signal.
    """

    timestamp_s: float
    hit: PanelHit | None
    confidence: float
    rival_id: str | None = None
    rival_deg: float | None = None

    def __post_init__(self) -> None:
        _finite("PanelObservation.timestamp_s", self.timestamp_s)
        if self.timestamp_s < 0:
            raise ValueError("PanelObservation.timestamp_s must be >= 0")
        _finite("PanelObservation.confidence", self.confidence)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"PanelObservation.confidence must be within [0, 1], got {self.confidence!r}")
        if self.hit is not None and not isinstance(self.hit, PanelHit):
            raise ValueError("PanelObservation.hit must be a PanelHit or None")
        if (self.rival_id is None) != (self.rival_deg is None):
            raise ValueError("PanelObservation.rival_id and rival_deg are given together or not at all")
        if self.rival_deg is not None:
            _finite("PanelObservation.rival_deg", self.rival_deg)
            if self.rival_deg < 0:
                raise ValueError("PanelObservation.rival_deg must be >= 0")
            if not isinstance(self.rival_id, str) or not self.rival_id:
                raise ValueError("PanelObservation.rival_id must be a non-empty string")
            if self.hit is not None and self.rival_id == self.hit.panel_id:
                raise ValueError("PanelObservation.rival_id must differ from the panel that was hit")


class BindingOutcome(Enum):
    BOUND = "bound"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


@dataclass(frozen=True)
class BindingResult:
    """The verdict. ``panel_id`` is set only for BOUND.

    ``margin`` is top share minus runner-up share and ``top_share`` the top panel's share
    of the weighted pointing mass; both are the real values even for AMBIGUOUS or NONE
    (0.0 only when there was no usable evidence at all). ``confidence`` is the weighted
    mean tracking confidence of the winning panel's evidence, 0.0 unless BOUND; it is the
    input :func:`yazses.xr.confirm.decide` needs.

    The remaining fields are evidence for the confirm policy and never change the verdict:
    ``candidates`` are the top two panel ids by share (best first; one id or none when
    fewer panels were seen). ``rival_id`` / ``rival_deg`` (BOUND only, None when not
    measured) are the nearest other panel and the evidence-weighted angular distance of
    the winning rays from it. ``prior_panel`` / ``settled_s`` (BOUND only) name another
    panel the gaze rested on in the ``history_s`` before the onset and the seconds since
    the gaze last touched it; both None when there is no such panel.
    """

    outcome: BindingOutcome
    panel_id: str | None
    margin: float
    reason: str
    confidence: float = 0.0
    top_share: float = 0.0
    candidates: tuple[str, ...] = ()
    rival_id: str | None = None
    rival_deg: float | None = None
    prior_panel: str | None = None
    settled_s: float | None = None

    def __post_init__(self) -> None:
        if (self.outcome is BindingOutcome.BOUND) != (self.panel_id is not None):
            raise ValueError("BindingResult.panel_id is set exactly when the outcome is BOUND")
        for name in ("confidence", "top_share"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0.0 <= v <= 1.0 + 1e-9:
                raise ValueError(f"BindingResult.{name} must be within [0, 1], got {v!r}")
        if self.outcome is not BindingOutcome.BOUND and self.confidence != 0.0:
            raise ValueError("BindingResult.confidence is 0.0 unless the outcome is BOUND")
        if len(self.candidates) > 2 or len(set(self.candidates)) != len(self.candidates):
            raise ValueError("BindingResult.candidates holds at most two distinct panel ids")
        if self.outcome is BindingOutcome.BOUND and self.candidates and self.candidates[0] != self.panel_id:
            raise ValueError("BindingResult.candidates must start with the bound panel")
        if (self.rival_id is None) != (self.rival_deg is None):
            raise ValueError("BindingResult.rival_id and rival_deg are given together or not at all")
        if (self.prior_panel is None) != (self.settled_s is None):
            raise ValueError("BindingResult.prior_panel and settled_s are given together or not at all")
        for name in ("rival_deg", "settled_s"):
            v = getattr(self, name)
            if v is not None:
                _finite(f"BindingResult.{name}", v)
                if v < 0:
                    raise ValueError(f"BindingResult.{name} must be >= 0")
        if self.outcome is not BindingOutcome.BOUND and (self.rival_id or self.prior_panel):
            raise ValueError("BindingResult rival and prior evidence is set only for BOUND")


def _finite(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


def ray_gap_deg(ray: Ray, panel: Panel, max_distance_m: float = 10.0) -> float | None:
    """Angle, in degrees, from ``ray`` to the nearest point of ``panel``'s rectangle. Pure.

    0.0 when the ray strikes the panel. Otherwise the ray is carried to the panel's plane,
    the point is clamped into the rectangle, and the angle between the ray and the
    direction to that clamped point is returned. None when no such angle exists: the ray
    is parallel to the plane, the plane lies behind the origin or beyond ``max_distance_m``,
    or the ray comes from behind the panel (a back-face approach is never "pointing at" it).

    This is the number the confirm policy compares with its angular-error budget: a ray
    that lands ``g`` degrees from a neighbouring panel could have meant that panel if the
    tracker is off by ``g`` or more.
    """
    denom = dot(panel.normal, ray.direction)
    if denom >= -1e-9:
        return None
    t = dot(panel.normal, sub(panel.center, ray.origin)) / denom
    if not math.isfinite(t) or t < 0 or t > max_distance_m:
        return None
    d = ray.direction
    p = Vec3(ray.origin.x + d.x * t, ray.origin.y + d.y * t, ray.origin.z + d.z * t)
    rel = sub(p, panel.center)
    right = cross(panel.up, panel.normal)
    a = dot(rel, right)
    b = dot(rel, panel.up)
    qa = min(panel.width / 2.0, max(-panel.width / 2.0, a))
    qb = min(panel.height / 2.0, max(-panel.height / 2.0, b))
    if qa == a and qb == b:
        return 0.0
    to_q = sub(
        Vec3(
            panel.center.x + right.x * qa + panel.up.x * qb,
            panel.center.y + right.y * qa + panel.up.y * qb,
            panel.center.z + right.z * qa + panel.up.z * qb,
        ),
        ray.origin,
    )
    if to_q.x == 0.0 and to_q.y == 0.0 and to_q.z == 0.0:
        return 0.0
    return math.degrees(angle_between(d, to_q))


def nearest_rival(ray: Ray, hit_id: str | None, panels: Sequence[Panel],
                  max_distance_m: float = 10.0) -> tuple[str, float] | None:
    """``(panel_id, degrees)`` of the nearest panel other than ``hit_id``, else None. Pure.

    Ties on the angle break on ``panel_id``. Panels the ray cannot reach (see
    :func:`ray_gap_deg`) are skipped. This is how the caller fills
    ``PanelObservation.rival_id`` / ``rival_deg``.
    """
    best: tuple[float, str] | None = None
    for panel in panels:
        if panel.panel_id == hit_id:
            continue
        gap = ray_gap_deg(ray, panel, max_distance_m)
        if gap is None:
            continue
        if best is None or (gap, panel.panel_id) < best:
            best = (gap, panel.panel_id)
    return None if best is None else (best[1], best[0])


def _time_weight(dt: float, lead_s: float, lag_s: float) -> float | None:
    """Triangular weight over ``dt = t - onset``: 1 at the onset, 0 at either window edge.

    None when ``dt`` lies outside ``[-lead_s, +lag_s]`` (both edges inclusive; an edge
    sample is inside the window but carries zero weight, so it can never decide a binding).
    """
    if dt < -lead_s or dt > lag_s:
        return None
    if dt < 0:
        return 1.0 + dt / lead_s  # lead_s > 0 here, because dt < 0 and dt >= -lead_s
    if dt > 0:
        return 1.0 - dt / lag_s  # lag_s > 0 here, because 0 < dt <= lag_s
    return 1.0


def _hold_cells(times: list[float], max_gap_s: float) -> dict[float, tuple[float, float]]:
    """The interval each distinct timestamp holds: ``(start, end)`` around that timestamp.

    A sample holds the time up to the midpoint to each neighbour, but never more than
    ``max_gap_s / 2`` per side, so a dropout does not credit a stale panel for the whole
    silence. The first/last sample mirrors its one known side; a lone timestamp has no
    gap information and holds nothing. ``times`` is sorted and distinct.
    """
    cells: dict[float, tuple[float, float]] = {}
    half = max_gap_s / 2.0
    n = len(times)
    for i, t in enumerate(times):
        prev = min(t - times[i - 1], max_gap_s) / 2.0 if i > 0 else None
        nxt = min(times[i + 1] - t, max_gap_s) / 2.0 if i + 1 < n else None
        if prev is None and nxt is None:
            prev = nxt = 0.0
        elif prev is None:
            prev = nxt
        elif nxt is None:
            nxt = prev
        assert prev is not None and nxt is not None  # for the type checker
        cells[t] = (t - min(prev, half), t + min(nxt, half))
    return cells


def _weighted_rival(items: list[tuple[float, str | None, float | None]]) -> tuple[str | None, float | None]:
    """Evidence-weighted mean rival distance and the heaviest rival id, over measured items."""
    measured = [(m, rid, deg) for m, rid, deg in items if rid is not None and deg is not None]
    weight = math.fsum(m for m, _, _ in measured)
    if not measured or weight <= 0.0:
        return None, None
    by_id: dict[str, float] = {}
    for m, rid, _ in measured:
        assert rid is not None
        by_id[rid] = by_id.get(rid, 0.0) + m
    heaviest = min(by_id, key=lambda r: (-by_id[r], r))
    mean = math.fsum(m * deg for m, _, deg in measured if deg is not None) / weight
    return heaviest, mean


def bind_demonstrative(
    observations: Sequence[PanelObservation],
    word_onset_s: float,
    *,
    lead_s: float = 0.4,
    lag_s: float = 0.2,
    min_share: float = 0.6,
    min_confidence: float = 0.3,
    min_mass: float = 0.0,
    max_gap_s: float = 0.1,
    min_samples: int = 3,
    min_coverage_s: float = 0.05,
    history_s: float = 1.5,
    min_prior_dwell_s: float = 0.15,
) -> BindingResult:
    """Resolve the demonstrative spoken at ``word_onset_s`` to a panel, or refuse. Pure.

    Each observation inside ``[onset - lead_s, onset + lag_s]`` is credited with the time
    interval it holds (to its neighbours, at most ``max_gap_s`` across a dropout, clipped
    to the window), times ``confidence`` times ``triangle(t - onset)``, the triangle
    peaking at the onset. Weighting by time rather than by sample makes the verdict
    independent of the sampling rate. Observations below ``min_confidence`` are dropped.
    Samples that hit no panel still count in the denominator: looking at empty space for
    most of the window must not let a brief glance at a panel claim the word.

    * BOUND: enough evidence (at least ``min_samples`` usable observations covering at
      least ``min_coverage_s`` seconds, and total mass at least ``min_mass``), and the top
      panel holds at least ``min_share`` of the weighted mass and leads the runner-up (a
      tie is never a binding).
    * AMBIGUOUS: another panel is plausible too; the caller should ask, not pick. The
      result still carries the real ``margin`` and ``top_share``.
    * NONE: no usable evidence (nothing in the window, all low confidence), too little of
      it ("insufficient evidence": a single stray sample has a 100% share of nothing), or
      mostly empty space.

    Input order does not matter. ``min_mass`` (seconds-weighted, default 0 = off) is
    superseded by ``min_samples`` / ``min_coverage_s`` and kept as an extra floor.

    ``history_s`` and ``min_prior_dwell_s`` only shape the ``prior_panel`` / ``settled_s``
    evidence of a BOUND result (see the module docstring); they never change the verdict.
    """
    _finite("word_onset_s", word_onset_s)
    for name, value in (("lead_s", lead_s), ("lag_s", lag_s)):
        _finite(name, value)
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value!r}")
    _finite("min_share", min_share)
    if not 0.0 < min_share <= 1.0:
        raise ValueError(f"min_share must be within (0, 1], got {min_share!r}")
    _finite("min_confidence", min_confidence)
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be within [0, 1], got {min_confidence!r}")
    _finite("min_mass", min_mass)
    if min_mass < 0:
        raise ValueError(f"min_mass must be >= 0, got {min_mass!r}")
    _finite("max_gap_s", max_gap_s)
    if max_gap_s <= 0:
        raise ValueError(f"max_gap_s must be > 0, got {max_gap_s!r}")
    for name, value in (("history_s", history_s), ("min_prior_dwell_s", min_prior_dwell_s)):
        _finite(name, value)
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value!r}")
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 1:
        raise ValueError(f"min_samples must be an integer >= 1, got {min_samples!r}")
    _finite("min_coverage_s", min_coverage_s)
    if min_coverage_s < 0:
        raise ValueError(f"min_coverage_s must be >= 0, got {min_coverage_s!r}")

    if not observations:
        return BindingResult(BindingOutcome.NONE, None, 0.0, "no pointing observations")

    ordered = sorted(observations, key=lambda o: o.timestamp_s)
    times = sorted({o.timestamp_s for o in ordered})
    cells = _hold_cells(times, max_gap_s)
    sharing: dict[float, int] = {}
    for o in ordered:
        sharing[o.timestamp_s] = sharing.get(o.timestamp_s, 0) + 1
    win_lo, win_hi = word_onset_s - lead_s, word_onset_s + lag_s

    in_window = 0
    low_confidence = 0
    # (panel or None, duration, time weight, confidence, rival id, rival degrees) per usable observation.
    usable: list[tuple[str | None, float, float, float, str | None, float | None]] = []
    for obs in ordered:
        weight = _time_weight(obs.timestamp_s - word_onset_s, lead_s, lag_s)
        if weight is None:
            continue
        in_window += 1
        if obs.confidence < min_confidence:
            low_confidence += 1
            continue
        start, end = cells[obs.timestamp_s]
        # Simultaneous observations split their shared interval between them.
        duration = max(0.0, min(end, win_hi) - max(start, win_lo)) / sharing[obs.timestamp_s]
        if weight * obs.confidence > 0.0:
            usable.append((obs.hit.panel_id if obs.hit is not None else None,
                           duration, weight, obs.confidence, obs.rival_id, obs.rival_deg))

    if in_window == 0:
        return BindingResult(BindingOutcome.NONE, None, 0.0, "no observation inside the binding window")
    if not usable:
        why = "all in-window observations below min_confidence" if low_confidence == in_window \
            else "only zero-weight observations at the window edge"
        return BindingResult(BindingOutcome.NONE, None, 0.0, why)

    total = math.fsum(d * w * c for _, d, w, c, _, _ in usable)
    coverage = math.fsum(d for _, d, _, _, _, _ in usable)
    if len(usable) < min_samples or coverage < min_coverage_s or total < min_mass or total <= 0.0:
        return BindingResult(
            BindingOutcome.NONE, None, 0.0,
            f"insufficient evidence ({len(usable)} usable samples, need {min_samples}; "
            f"{coverage:.3f}s covered, need {min_coverage_s:.3f}s)",
        )

    by_panel: dict[str, list[tuple[float, float, float]]] = {}
    rivals: dict[str, list[tuple[float, str | None, float | None]]] = {}
    for pid, d, w, c, rid, rdeg in usable:
        if pid is not None:
            by_panel.setdefault(pid, []).append((d, w, c))
            rivals.setdefault(pid, []).append((d * w * c, rid, rdeg))
    if not by_panel:
        return BindingResult(BindingOutcome.NONE, None, 0.0, "pointing at no panel")

    def mass(items: list[tuple[float, float, float]]) -> float:
        return math.fsum(d * w * c for d, w, c in items)

    # Highest share first; panel id breaks exact ties so the verdict is deterministic.
    ranked = sorted(((mass(v) / total, pid) for pid, v in by_panel.items()),
                    key=lambda sp: (-sp[0], sp[1]))
    top_share, top_id = ranked[0]
    top_share = min(top_share, 1.0)
    second_share = ranked[1][0] if len(ranked) > 1 else 0.0
    margin = top_share - second_share
    candidates = tuple(pid for _, pid in ranked[:2])

    if top_share >= min_share and margin > _TIE_EPS:
        items = by_panel[top_id]
        weight_sum = math.fsum(d * w for d, w, _ in items)
        confidence = min(1.0, mass(items) / weight_sum) if weight_sum > 0 else 0.0
        rival_id, rival_deg = _weighted_rival(rivals[top_id])
        prior_panel, settled_s = _prior_context(
            ordered, cells, sharing, top_id, word_onset_s, history_s, min_prior_dwell_s, min_confidence)
        return BindingResult(
            BindingOutcome.BOUND, top_id, margin,
            f"{top_id!r} holds {top_share:.0%} of pointing mass (margin {margin:.2f})",
            confidence, top_share, candidates, rival_id, rival_deg, prior_panel, settled_s,
        )
    if len(ranked) > 1:
        return BindingResult(
            BindingOutcome.AMBIGUOUS, None, margin,
            f"{ranked[0][1]!r} {top_share:.0%} vs {ranked[1][1]!r} {second_share:.0%}: "
            f"no panel reaches {min_share:.0%} with a clear lead",
            0.0, top_share, candidates,
        )
    return BindingResult(
        BindingOutcome.NONE, None, margin,
        f"only {top_share:.0%} of pointing mass on {top_id!r}; the rest at empty space",
        0.0, top_share, candidates,
    )


def _prior_context(
    ordered: list[PanelObservation],
    cells: dict[float, tuple[float, float]],
    sharing: dict[float, int],
    bound_id: str,
    onset_s: float,
    history_s: float,
    min_prior_dwell_s: float,
    min_confidence: float,
) -> tuple[str | None, float | None]:
    """``(prior_panel, settled_s)``: the other panel the gaze most recently rested on.

    Looks at ``[onset - history_s, onset]``. A panel other than ``bound_id`` qualifies when
    the gaze held it for at least ``min_prior_dwell_s`` there (a saccade grazing a panel
    holds it for tens of milliseconds and does not). The most recently touched qualifying
    panel is returned with the seconds between the last touch and the onset. ``(None,
    None)`` when no other panel qualifies. Pure and order-independent.
    """
    lo = onset_s - history_s
    dwell: dict[str, float] = {}
    last: dict[str, float] = {}
    for o in ordered:
        t = o.timestamp_s
        if t < lo or t > onset_s or o.confidence < min_confidence or o.hit is None:
            continue
        start, end = cells[t]
        held = max(0.0, min(end, onset_s) - max(start, lo)) / sharing[t]
        pid = o.hit.panel_id
        dwell[pid] = dwell.get(pid, 0.0) + held
        last[pid] = max(last.get(pid, t), t)
    qualifying = [(last[p], dwell[p], p) for p in dwell if p != bound_id and dwell[p] >= min_prior_dwell_s]
    if not qualifying:
        return None, None
    qualifying.sort(key=lambda x: (-x[0], -x[1], x[2]))
    seen_at, _, panel = qualifying[0]
    return panel, max(0.0, onset_s - seen_at)


def sustained_departure(
    observations: Sequence[PanelObservation],
    panel_id: str,
    onset_s: float,
    end_s: float,
    *,
    min_confidence: float = 0.3,
    max_gap_s: float = 0.1,
) -> tuple[str | None, float]:
    """``(panel, seconds)``: how long the gaze has rested on one *other* panel at ``end_s``. Pure.

    Looks at the observations in ``(onset_s, end_s]``. If the last of them does not hit a
    panel other than ``panel_id``, nothing has departed and the answer is ``(None, 0.0)``.
    Otherwise the run of consecutive hits on that other panel (neighbours at most
    ``max_gap_s`` apart) that ends at the last observation is measured first-to-last
    sample. A brief glance, a saccade across a panel, or a return to ``panel_id`` all
    read as short or zero; only a gaze that has *stayed* reads long. The confirm policy
    compares the seconds with its ``min_departure_s``.
    """
    _finite("onset_s", onset_s)
    _finite("end_s", end_s)
    _finite("max_gap_s", max_gap_s)
    seq = sorted(
        (o for o in observations if onset_s < o.timestamp_s <= end_s and o.confidence >= min_confidence),
        key=lambda o: (o.timestamp_s, "" if o.hit is None else o.hit.panel_id),
    )
    if not seq:
        return None, 0.0
    # Simultaneous observations at the last instant: if any of them is on the bound panel
    # or on no panel the gaze has not demonstrably left (the conservative, order-free
    # reading); otherwise the smallest other panel id is the one followed.
    run_end = run_start = seq[-1].timestamp_s
    final = [o for o in seq if o.timestamp_s == run_end]
    if any(o.hit is None or o.hit.panel_id == panel_id for o in final):
        return None, 0.0
    other = min(o.hit.panel_id for o in final if o.hit is not None)
    for o in reversed([o for o in seq if o.timestamp_s < run_end]):
        if o.hit is None or o.hit.panel_id != other or run_start - o.timestamp_s > max_gap_s:
            break
        run_start = o.timestamp_s
    return other, run_end - run_start


# --- whole-utterance command grammar -------------------------------------------------


class DemonstrativeAction(Enum):
    DICTATE = "dictate"   # "type here": send the following dictation to the bound panel
    PLACE = "place"       # "put it there": move the current object/selection to the bound panel


@dataclass(frozen=True)
class DemonstrativeCommand:
    """A parsed demonstrative command.

    ``deictic_words`` lists, in spoken order, the words that point and so each need a
    :func:`bind_demonstrative` call at their own onset. Anaphoric "it" is not one.
    """

    action: DemonstrativeAction
    deictic_words: tuple[str, ...]
    raw_text: str


_DICTATE = re.compile(r"^(?:type|dictate|write)\s+(?P<dest>here|there)$")
_PLACE = re.compile(r"^(?:put|send)\s+(?P<obj>it|this|that)\s+(?P<dest>here|there)$")


def parse_demonstrative_command(text: str) -> DemonstrativeCommand | None:
    """Parse a whole-utterance demonstrative command, else None. Pure.

    Accepts only "type/dictate/write here|there" and "put/send it|this|that here|there".
    Anything else, including any longer sentence that merely contains "this" or "that",
    stays ordinary dictation. Outer punctuation is stripped, as the other grammars do.
    """
    cleaned = " ".join(text.strip().strip(".,!?;:").strip().lower().split())
    m = _DICTATE.match(cleaned)
    if m is not None:
        return DemonstrativeCommand(DemonstrativeAction.DICTATE, (m.group("dest"),), text)
    m = _PLACE.match(cleaned)
    if m is not None:
        obj = m.group("obj")
        words = (m.group("dest"),) if obj == "it" else (obj, m.group("dest"))
        return DemonstrativeCommand(DemonstrativeAction.PLACE, words, text)
    return None
