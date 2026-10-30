"""Synthetic pointing trajectories for tests and offline evaluation (pure, seeded).

Every generator here is a deterministic function of its arguments: randomness comes
only from a private ``random.Random(seed)``, never the module-level generator, and
nothing reads a clock or a file. The same call twice returns equal samples.

These are *fixtures*, not recordings. No real gaze, hand or voice data ever enters
this module (AGENTS.md: use synthetic fixtures); the numbers describe an invented
user looking at invented panels.

Conventions follow ``yazses.xr.types``: metres, seconds, radians, right-handed with
+Y up and -Z forward. A panel's horizontal axis is ``cross(up, normal)`` — for a
panel facing the user (normal +Z) that is +X, so ``u`` grows to the user's right and
``v`` grows upward (``v=1`` is the top edge), matching ``PanelHit``.

**Noise.** ``noise_rad`` is the *mean angular error* of a ray from its ideal
direction. The error is a 2-D Gaussian in the plane perpendicular to the ray, so its
magnitude is Rayleigh-distributed with mean ``sigma * sqrt(pi / 2)``; ``sigma`` is
scaled so that mean equals ``noise_rad``. ``noise_rad=0`` returns the exact aim.

**Labels: intent versus gaze (read before scoring anything).** A ``Scenario`` carries two
different notions of "the right panel":

* ``truth_panel_id`` is the panel the user *intended* — the trial's design. It is what a
  correct resolver should return even if the eyes have since wandered off.
* ``gaze_panel_at_onset`` is a measurement, not a design: the panel the *generated rays*
  actually strike at the word onset (the last sample at or before ``word_onset_s``, cast
  against the panels; ``None`` when it hits none). It is what a "ray at the word"
  baseline sees.

With ``look_away_prob=0`` (the default) the eyes are still on the intended panel at the
onset in every noise-free trial, so the two agree. With ``look_away_prob>0`` that
fraction of trials deliberately has the eyes move on *before* the word, and noise-free
the two then differ. Under noise a ray can graze an edge, so ``gaze_panel_at_onset`` is
the honest ground truth for what the tracker reported, never a restatement of the label.

**Honest metrics.** Score a resolver against ``truth_panel_id`` (the intent), and report
the look-away cases (``gaze_panel_at_onset != truth_panel_id``) as a separate stratum
rather than pooling them: pooled, the headline number depends on the knob ``look_away_prob``
you happened to pick. A resolver that merely echoes ``gaze_panel_at_onset`` scores 100%
on the aligned stratum and 0% on the look-away one; that gap is the thing to report.
"""
from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace

from yazses.xr.geometry import add, angle_between, cross, dot, normalize, scale, sub
from yazses.xr.raycast import nearest_hit
from yazses.xr.types import Panel, Ray, RaySource, Vec3, XrSample

# A seated user's eye height; every generator takes ``eye`` to override it.
DEFAULT_EYE = Vec3(0.0, 1.6, 0.0)

# Rayleigh mean = sigma * sqrt(pi / 2), so sigma = mean * sqrt(2 / pi).
_MEAN_TO_SIGMA = math.sqrt(2.0 / math.pi)

# Scenario model constants (seconds, and the usable fraction of a panel's extent).
_LOOK_START_RANGE = (0.2, 1.0)   # when the user's gaze first lands on the target
_DWELL_RANGE = (0.3, 0.9)        # how long it stays there before drifting away
_AWAY_MIN_S = 0.3                # minimum time spent on the distractor
_TAIL_S = 0.3                    # samples kept after the word onset
_SACCADE_S = 0.05
_UV_RANGE = (0.15, 0.85)         # keep aim points off the panel edge
_MIN_DWELL_S = 0.1               # shortest fixation a deliberate look-away trial may use
_OFF_PANEL_WIDTHS = 3.0          # where a lone panel's user looks: this many widths to the side


def _require_finite(name: str, value: float) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


def _check_common(start_s: float, duration_s: float, hz: float, noise_rad: float) -> None:
    _require_finite("start_s", start_s)
    _require_finite("duration_s", duration_s)
    _require_finite("hz", hz)
    _require_finite("noise_rad", noise_rad)
    if start_s < 0:
        raise ValueError("start_s must be >= 0")
    if duration_s < 0:
        raise ValueError("duration_s must be >= 0")
    if hz <= 0:
        raise ValueError("hz must be > 0")
    if noise_rad < 0:
        raise ValueError("noise_rad must be >= 0")


def _count(duration_s: float, hz: float) -> int:
    """Samples in a segment: ``duration_s * hz`` rounded half up."""
    return int(math.floor(duration_s * hz + 0.5))


def _timestamps(start_s: float, n: int, hz: float) -> list[float]:
    """``n`` timestamps on a ``1/hz`` grid; refuses a grid float precision collapses."""
    ts = [start_s + i / hz for i in range(n)]
    if any(b <= a for a, b in zip(ts, ts[1:])):
        raise ValueError("timestamps are not strictly increasing (start_s too large for hz)")
    return ts


def _perpendicular_basis(d: Vec3) -> tuple[Vec3, Vec3]:
    """Two unit vectors that, with unit ``d``, form an orthonormal frame."""
    # Cross with the world axis least aligned with d, which keeps the product well away
    # from zero length.
    axis = min(
        (Vec3(1.0, 0.0, 0.0), Vec3(0.0, 1.0, 0.0), Vec3(0.0, 0.0, 1.0)),
        key=lambda a: abs(dot(a, d)),
    )
    e1 = normalize(cross(d, axis))
    e2 = normalize(cross(d, e1))
    return e1, e2


def _jitter(d: Vec3, rng: random.Random, noise_rad: float) -> Vec3:
    """Tilt unit ``d`` by a Rayleigh-distributed angle (mean ``noise_rad``) at a random azimuth."""
    sigma = noise_rad * _MEAN_TO_SIGMA
    # Always draw both variates so a stream stays aligned whatever the noise level.
    x = rng.gauss(0.0, sigma)
    y = rng.gauss(0.0, sigma)
    r = math.hypot(x, y)
    if r == 0.0:
        return d
    e1, e2 = _perpendicular_basis(d)
    tangent = add(scale(e1, x / r), scale(e2, y / r))
    return normalize(add(scale(d, math.cos(r)), scale(tangent, math.sin(r))))


def _sample(
    t: float, eye: Vec3, d: Vec3, source: RaySource, confidence: float
) -> XrSample:
    return XrSample(timestamp_s=t, source=source, ray=Ray(eye, d), confidence=confidence)


def panel_point(panel: Panel, u: float, v: float) -> Vec3:
    """World position of ``(u, v)`` on ``panel`` (``u`` left→right, ``v`` bottom→top)."""
    _require_finite("u", u)
    _require_finite("v", v)
    right = cross(panel.up, panel.normal)
    offset = add(
        scale(right, (u - 0.5) * panel.width), scale(panel.up, (v - 0.5) * panel.height)
    )
    return add(panel.center, offset)


def _unit_uv(name: str, value: float) -> None:
    _require_finite(name, value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0, 1], got {value!r}")


def fixation(
    panel: Panel,
    u: float,
    v: float,
    *,
    start_s: float,
    duration_s: float,
    hz: float = 90.0,
    noise_rad: float = 0.0,
    seed: int = 0,
    source: RaySource = RaySource.EYE,
    eye: Vec3 = DEFAULT_EYE,
    confidence: float = 1.0,
) -> list[XrSample]:
    """Rays from ``eye`` toward ``(u, v)`` on ``panel`` for ``duration_s`` seconds.

    ``round(duration_s * hz)`` samples at ``start_s + i / hz``, each independently
    jittered by ``noise_rad`` mean angular error. Same arguments, same samples.
    """
    _check_common(start_s, duration_s, hz, noise_rad)
    _unit_uv("u", u)
    _unit_uv("v", v)
    aim = normalize(sub(panel_point(panel, u, v), eye))
    rng = random.Random(seed)
    return [
        _sample(t, eye, _jitter(aim, rng, noise_rad), source, confidence)
        for t in _timestamps(start_s, _count(duration_s, hz), hz)
    ]


def _rotate_toward(a: Vec3, b: Vec3, fraction: float) -> Vec3:
    """Unit vector ``fraction`` of the way from unit ``a`` to unit ``b`` along the arc."""
    omega = angle_between(a, b)
    if omega < 1e-12:
        return a
    if omega > math.pi - 1e-9:
        # Antiparallel: the arc is ambiguous, so choose any fixed perpendicular.
        tangent = _perpendicular_basis(a)[0]
    else:
        residual = sub(b, scale(a, dot(a, b)))
        # Rounding can leave omega ~1e-8 for equal directions with no tangent left to
        # follow (the residual is exactly zero): there is nowhere to rotate to.
        if max(abs(residual.x), abs(residual.y), abs(residual.z)) < 1e-12:
            return a
        tangent = normalize(residual)
    angle = fraction * omega
    return normalize(add(scale(a, math.cos(angle)), scale(tangent, math.sin(angle))))


def saccade(
    from_dir: Vec3,
    to_dir: Vec3,
    *,
    start_s: float,
    duration_s: float = _SACCADE_S,
    hz: float = 90.0,
    noise_rad: float = 0.0,
    seed: int = 0,
    source: RaySource = RaySource.EYE,
    eye: Vec3 = DEFAULT_EYE,
    confidence: float = 1.0,
) -> list[XrSample]:
    """The fast jump between two fixations: rays swept along the arc ``from_dir → to_dir``.

    Only the *interior* of the jump is emitted (fractions ``(i+1)/(n+1)``), so the two
    fixations around it keep their own endpoint samples. A smoothstep ease gives the
    bell-shaped speed profile of a real saccade. Directions need not be unit length.
    """
    _check_common(start_s, duration_s, hz, noise_rad)
    a = normalize(from_dir)
    b = normalize(to_dir)
    n = _count(duration_s, hz)
    rng = random.Random(seed)
    out: list[XrSample] = []
    for i, t in enumerate(_timestamps(start_s, n, hz)):
        f = (i + 1) / (n + 1)
        eased = f * f * (3.0 - 2.0 * f)
        d = _jitter(_rotate_toward(a, b, eased), rng, noise_rad)
        out.append(_sample(t, eye, d, source, confidence))
    return out


def sweep_between(
    panel_a: Panel,
    panel_b: Panel,
    *,
    start_s: float,
    dwell_a_s: float,
    dwell_b_s: float,
    saccade_s: float = _SACCADE_S,
    a_uv: tuple[float, float] = (0.5, 0.5),
    b_uv: tuple[float, float] = (0.5, 0.5),
    hz: float = 90.0,
    noise_rad: float = 0.0,
    seed: int = 0,
    source: RaySource = RaySource.EYE,
    eye: Vec3 = DEFAULT_EYE,
    confidence: float = 1.0,
) -> list[XrSample]:
    """Fixate ``panel_a``, saccade, fixate ``panel_b`` — one gapless ``1/hz`` timeline."""
    _check_common(start_s, dwell_a_s, hz, noise_rad)
    _check_common(start_s, dwell_b_s, hz, noise_rad)
    _check_common(start_s, saccade_s, hz, noise_rad)
    n_a = _count(dwell_a_s, hz)
    n_s = _count(saccade_s, hz)
    n_b = _count(dwell_b_s, hz)
    rng = random.Random(seed)
    seeds = [rng.getrandbits(32) for _ in range(3)]
    dir_a = normalize(sub(panel_point(panel_a, *a_uv), eye))
    dir_b = normalize(sub(panel_point(panel_b, *b_uv), eye))
    out = fixation(panel_a, *a_uv, start_s=start_s, duration_s=dwell_a_s, hz=hz,
                   noise_rad=noise_rad, seed=seeds[0], source=source, eye=eye,
                   confidence=confidence)
    out += saccade(dir_a, dir_b, start_s=start_s + n_a / hz, duration_s=saccade_s, hz=hz,
                   noise_rad=noise_rad, seed=seeds[1], source=source, eye=eye,
                   confidence=confidence)
    out += fixation(panel_b, *b_uv, start_s=start_s + (n_a + n_s) / hz,
                    duration_s=dwell_b_s, hz=hz, noise_rad=noise_rad, seed=seeds[2],
                    source=source, eye=eye, confidence=confidence)
    if len(out) != n_a + n_s + n_b or any(
        b.timestamp_s <= a.timestamp_s for a, b in zip(out, out[1:])
    ):
        raise ValueError("sweep timestamps are not strictly increasing (start_s too large for hz)")
    return out


def dropout(samples: Sequence[XrSample], start_s: float, end_s: float) -> list[XrSample]:
    """Tracking loss: drop exactly the samples with ``start_s <= timestamp_s < end_s``."""
    _require_finite("start_s", start_s)
    _require_finite("end_s", end_s)
    if end_s < start_s:
        raise ValueError("end_s must be >= start_s")
    return [s for s in samples if not start_s <= s.timestamp_s < end_s]


def with_confidence_ramp(
    samples: Sequence[XrSample],
    start_s: float,
    end_s: float,
    from_confidence: float,
    to_confidence: float,
) -> list[XrSample]:
    """Linearly ramp ``confidence`` over ``[start_s, end_s]``; samples outside are untouched.

    Models a tracker degrading (or recovering): eye-tracking confidence falls as the
    pupil is lost to a blink or glare, and everything downstream should weight on it.
    """
    _require_finite("start_s", start_s)
    _require_finite("end_s", end_s)
    _unit_uv("from_confidence", from_confidence)
    _unit_uv("to_confidence", to_confidence)
    if end_s <= start_s:
        raise ValueError("end_s must be > start_s")
    out: list[XrSample] = []
    for s in samples:
        if start_s <= s.timestamp_s <= end_s:
            f = (s.timestamp_s - start_s) / (end_s - start_s)
            c = from_confidence + f * (to_confidence - from_confidence)
            s = replace(s, confidence=min(1.0, max(0.0, c)))
        out.append(s)
    return out


@dataclass(frozen=True)
class Scenario:
    """One labelled trial: a trajectory, the moment "this" was spoken, and the right answer.

    ``truth_panel_id`` is the panel the user *intended* (the trial's design).
    ``gaze_panel_at_onset`` is the panel the generated rays actually hit at the word
    onset, or ``None`` if they hit none — or if the scenario was built by hand without
    it. They differ exactly in look-away trials. See the module docstring.
    """

    samples: tuple[XrSample, ...]
    word_onset_s: float
    truth_panel_id: str
    gaze_panel_at_onset: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "samples", tuple(self.samples))
        _require_finite("Scenario.word_onset_s", self.word_onset_s)
        if self.word_onset_s < 0:
            raise ValueError("Scenario.word_onset_s must be >= 0")
        if not isinstance(self.truth_panel_id, str) or not self.truth_panel_id:
            raise ValueError("Scenario.truth_panel_id must be a non-empty string")
        if self.gaze_panel_at_onset is not None and (
            not isinstance(self.gaze_panel_at_onset, str) or not self.gaze_panel_at_onset
        ):
            raise ValueError("Scenario.gaze_panel_at_onset must be None or a non-empty string")


def _gaze_panel_at(
    samples: Sequence[XrSample], onset_s: float, panels: Sequence[Panel]
) -> str | None:
    """Panel struck by the last sample at or before ``onset_s`` (None: no sample, or a miss)."""
    current: XrSample | None = None
    for s in samples:
        if s.timestamp_s <= onset_s:
            current = s
        else:
            break
    if current is None:
        return None
    hit = nearest_hit(current.ray, panels)
    return hit.panel_id if hit is not None else None


def _hold(
    direction: Vec3,
    *,
    start_s: float,
    duration_s: float,
    hz: float,
    noise_rad: float,
    seed: int,
    source: RaySource,
    eye: Vec3,
) -> list[XrSample]:
    """A fixation on an arbitrary unit direction (``fixation`` aims only at panel points)."""
    rng = random.Random(seed)
    return [
        _sample(t, eye, _jitter(direction, rng, noise_rad), source, 1.0)
        for t in _timestamps(start_s, _count(duration_s, hz), hz)
    ]


def make_scenarios(
    panels: Sequence[Panel],
    n: int,
    seed: int = 0,
    noise_rad: float = 0.0,
    lead_s_range: tuple[float, float] = (0.2, 0.8),
    *,
    hz: float = 90.0,
    source: RaySource = RaySource.EYE,
    eye: Vec3 = DEFAULT_EYE,
    look_away_prob: float = 0.0,
) -> list[Scenario]:
    """``n`` trials of "look at panel X, say 'this' a moment later" (pure, seeded).

    The user's gaze lands on a random target panel at ``t0`` (= ``samples[0]``) and the
    word onset is ``t0 + lead`` with ``lead`` drawn from ``lead_s_range``. The target is
    the intent: ``truth_panel_id``.

    * Default (``look_away_prob=0``): the fixation is stretched, if need be, to outlast the
      lead, so the eyes are still on the target at the onset and ``gaze_panel_at_onset ==
      truth_panel_id`` in every noise-free trial. The eyes drift to another panel
      only afterwards.
    * With probability ``look_away_prob`` per trial the eyes move on *before* the word:
      a short fixation (at most 0.9 s, at least 0.1 s), a saccade, and the gaze is settled
      on a different panel (a point off to the side of a lone panel) at the onset, so noise-free
      ``gaze_panel_at_onset != truth_panel_id``. The lead of such a trial is lifted to the
      minimum that makes this physically possible (about 0.2 s), so ``lead_s_range`` is a
      floor there, not an exact draw. This is the case a naive "ray at the word" resolver
      gets wrong.

    ``gaze_panel_at_onset`` is always measured from the generated rays (see the module
    docstring), so it stays truthful under noise too.
    """
    _require_finite("noise_rad", noise_rad)
    if noise_rad < 0:
        raise ValueError("noise_rad must be >= 0")
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise ValueError("n must be a non-negative integer")
    if not panels:
        raise ValueError("make_scenarios needs at least one panel")
    ids = [p.panel_id for p in panels]
    if len(set(ids)) != len(ids):
        raise ValueError("panel ids must be unique")
    lo, hi = lead_s_range
    _require_finite("lead_s_range[0]", lo)
    _require_finite("lead_s_range[1]", hi)
    if lo < 0 or hi < lo:
        raise ValueError("lead_s_range must satisfy 0 <= lo <= hi")
    _require_finite("hz", hz)
    if hz <= 0:
        raise ValueError("hz must be > 0")
    _unit_uv("look_away_prob", look_away_prob)

    n_sacc = _count(_SACCADE_S, hz)
    # Slack (s) that keeps the onset clear of fixation boundaries after sample rounding.
    margin = (n_sacc + 2) / hz
    min_away_lead = _MIN_DWELL_S + margin

    rng = random.Random(seed)
    out: list[Scenario] = []
    for _ in range(n):
        target = rng.choice(list(panels))
        others = [p for p in panels if p.panel_id != target.panel_id]
        distractor = rng.choice(others) if others else None
        t0 = rng.uniform(*_LOOK_START_RANGE)
        dwell = rng.uniform(*_DWELL_RANGE)
        lead = rng.uniform(lo, hi)
        target_uv = (rng.uniform(*_UV_RANGE), rng.uniform(*_UV_RANGE))
        trial_seed = rng.getrandbits(32)
        look_away = rng.random() < look_away_prob
        if look_away:
            lead = max(lead, min_away_lead)
            dwell = min(dwell, lead - margin)
        else:
            dwell = max(dwell, lead + 2.0 / hz)
        onset = t0 + lead
        away_start = t0 + dwell + _SACCADE_S
        away_s = max(_AWAY_MIN_S, onset + _TAIL_S - away_start)
        if distractor is None:
            if not look_away:
                samples = fixation(
                    target, *target_uv, start_s=t0, duration_s=max(dwell, lead + _TAIL_S),
                    hz=hz, noise_rad=noise_rad, seed=trial_seed, source=source, eye=eye,
                )
            else:
                sub_rng = random.Random(trial_seed)
                seeds = [sub_rng.getrandbits(32) for _ in range(3)]
                right = cross(target.up, target.normal)
                off_point = add(target.center, scale(right, -_OFF_PANEL_WIDTHS * target.width))
                dir_off = normalize(sub(off_point, eye))
                dir_a = normalize(sub(panel_point(target, *target_uv), eye))
                n_a = _count(dwell, hz)
                samples = fixation(
                    target, *target_uv, start_s=t0, duration_s=dwell, hz=hz,
                    noise_rad=noise_rad, seed=seeds[0], source=source, eye=eye,
                )
                samples += saccade(
                    dir_a, dir_off, start_s=t0 + n_a / hz, hz=hz, noise_rad=noise_rad,
                    seed=seeds[1], source=source, eye=eye,
                )
                samples += _hold(
                    dir_off, start_s=t0 + (n_a + n_sacc) / hz, duration_s=away_s, hz=hz,
                    noise_rad=noise_rad, seed=seeds[2], source=source, eye=eye,
                )
        else:
            away_uv = (rng.uniform(*_UV_RANGE), rng.uniform(*_UV_RANGE))
            samples = sweep_between(
                target, distractor, start_s=t0, dwell_a_s=dwell, dwell_b_s=away_s,
                a_uv=target_uv, b_uv=away_uv, hz=hz, noise_rad=noise_rad,
                seed=trial_seed, source=source, eye=eye,
            )
        out.append(
            Scenario(
                tuple(samples), onset, target.panel_id,
                gaze_panel_at_onset=_gaze_panel_at(samples, onset, panels),
            )
        )
    return out
