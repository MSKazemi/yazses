"""Confirm policy for XR-targeted actions (pure) — when a ray-chosen target must be confirmed.

A guard is judged on how *rarely* it fires (AGENTS.md rule 9, ADR-021): one that
interrupts a clean bind teaches the user to dismiss it, and a dismissed guard costs
attention and catches nothing. So this policy holds only on a *specific, checkable*
signal, never a heuristic, and the release is one word. Every signal is a number
the caller can read off the binder and compare with a stated threshold:

* the binder said the ray touched two panels about equally (``ambiguous``);
* the winning rays landed within the stated angular-error budget of a *neighbouring*
  panel (``NEAR_PANEL_EDGE``): a tracker that wrong could have meant the neighbour. The
  rule is silent wherever panels are farther apart than the budget;
* the gaze reached the bound panel only an instant before the word, coming from another
  panel it had rested on (``RECENT_PANEL_SWITCH``): "the panel I was leaving" and "the
  panel I reached" are both plausible referents and gaze cannot choose between them;
* the gaze has *stayed* on a different panel for ``min_departure_s`` at the end of the
  utterance (``TARGET_CHANGED_DURING_UTTERANCE``) — a rested look, not a passing glance;
* the action is destructive and its target came from a ray — the same rule as
  ``gaze.route.needs_confirm``, because webcam gaze is coarse (~1-2 degrees) and a
  headset ray is not exact either (ADR-v2-010);
* the binder's own confidence, margin or top share sits under a published threshold.

The common path — a bound, confident, non-destructive target on an unchanged panel — is
silent. An ``outcome`` of ``"none"`` means no ray target exists at all: that is not a
prompt, it is the documented ``NO_TARGET`` result, and the caller falls back to the
keyboard focus exactly as ``gaze.route.route_target`` does.

**A prompt is specific and cheap.** ``ConfirmDecision.candidates`` names the panels the
prompt should offer ("this one, or B?"), so the answer is one word and not a hunt. A
prompt with candidates is the cheaper error than a silent wrong bind (the cost model is in
``design/research/2026-10-30-xr-synthetic-evaluation.md``), but only when it is rare.

**What this policy cannot see.** If the eyes rested on the intended panel, left it long
before the word and settled elsewhere, the gaze record says the user meant where they are
now; no rule here can tell otherwise. See the research note for what stays unsolved.

``outcome`` is a plain string ("bound" | "ambiguous" | "none") so this module never
imports the binder; the integrator maps the binder's result onto it and onto
:class:`Evidence`.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

OUTCOMES = frozenset({"bound", "ambiguous", "none"})


class ConfirmReason(Enum):
    """Why a confirmation is (or is not) required. Closed; a new reason is a reviewed diff."""

    NONE = "none"                    # bound, confident, safe, steady: type it, say nothing
    NO_TARGET = "no_target"          # no ray target; fall back to keyboard focus, no prompt
    AMBIGUOUS_PANELS = "ambiguous_panels"
    LOW_CONFIDENCE = "low_confidence"
    DESTRUCTIVE_ACTION = "destructive_action"
    TARGET_CHANGED_DURING_UTTERANCE = "target_changed_during_utterance"
    NEAR_PANEL_EDGE = "near_panel_edge"
    RECENT_PANEL_SWITCH = "recent_panel_switch"


# Reasons that do NOT stop the action for a prompt.
_SILENT = frozenset({ConfirmReason.NONE, ConfirmReason.NO_TARGET})


@dataclass(frozen=True)
class ConfirmDecision:
    """Whether to hold the action, why, the single word that releases it, and what to offer.

    ``candidates`` are the panel ids a prompt should put to the user, best first (the bound
    panel, then the other plausible one). Empty when the reason names no specific
    alternative (a destructive action, a weak bind) or when nothing is held.
    """

    confirm: bool
    reason: ConfirmReason
    release_word: str = "yes"
    candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # confirm and reason must agree, so a caller can trust either one alone.
        if self.confirm == (self.reason in _SILENT):
            raise ValueError(f"confirm={self.confirm} contradicts reason {self.reason.name}")
        if not self.release_word or not self.release_word.isprintable() or len(self.release_word.split()) != 1:
            raise ValueError("release_word must be exactly one printable word")
        if len(self.candidates) > 2 or len(set(self.candidates)) != len(self.candidates):
            raise ValueError("candidates holds at most two distinct panel ids")
        if self.candidates and not self.confirm:
            raise ValueError("a silent decision offers no candidates")
        for c in self.candidates:
            if not isinstance(c, str) or not c or len(c) > 128 or not c.isprintable():
                raise ValueError("candidates must be printable, non-empty ids up to 128 characters")


@dataclass(frozen=True)
class Evidence:
    """The binder's checkable facts, as plain values. Every field defaults to "not measured".

    A field left None can never trigger its rule: absence of data is not a signal.
    ``panel_id`` is the bound panel; ``top_share`` its share of the weighted pointing mass;
    ``runner_up`` the second panel by share; ``rival_id`` / ``rival_deg`` the nearest
    other panel and the evidence-weighted angle (degrees) of the winning rays from it;
    ``prior_panel`` / ``settled_s`` the other panel the gaze left most recently and the
    seconds since it left; ``departure_s`` the seconds the gaze has rested on a different
    panel at the end of the utterance (0.0 = it has not left). ``departure_s`` None means
    the caller did not measure it, and the instantaneous onset-versus-end comparison is
    used instead (the pre-redesign behaviour, kept for callers that have no duration).
    """

    panel_id: str | None = None
    top_share: float | None = None
    runner_up: str | None = None
    rival_id: str | None = None
    rival_deg: float | None = None
    prior_panel: str | None = None
    settled_s: float | None = None
    departure_s: float | None = None
    departure_panel: str | None = None

    def __post_init__(self) -> None:
        for name in ("top_share", "rival_deg", "settled_s", "departure_s"):
            v = getattr(self, name)
            if v is not None:
                _finite(f"Evidence.{name}", v)
                if v < 0:
                    raise ValueError(f"Evidence.{name} must be >= 0, got {v!r}")
        if self.top_share is not None and self.top_share > 1.0 + 1e-9:
            raise ValueError(f"Evidence.top_share must be within [0, 1], got {self.top_share!r}")


@dataclass(frozen=True)
class ConfirmPolicy:
    """The published thresholds of the evidence rules. Defaults are starting points to MEASURE.

    ``min_top_share`` — a bind whose top panel holds less than this share of the pointing
    mass is held (the binder's own ``min_share`` normally keeps this from firing; it is the
    belt to that pair of braces and the property the tests pin).
    ``error_budget_deg`` — the angular error the policy assumes the tracker can have; a
    bind whose rays sit closer than this to another panel is held. 0 turns the rule off.
    ``settle_s`` — a gaze that reached the bound panel less than this long before the word,
    from another panel it had rested on, is held. 0 turns the rule off.
    ``min_departure_s`` — a gaze that has rested on another panel this long at the end of
    the utterance counts as a changed target. A fixation is ~0.2-0.3 s; this asks for twice.
    """

    min_top_share: float = 0.6
    error_budget_deg: float = 3.0
    settle_s: float = 0.3
    min_departure_s: float = 0.5

    def __post_init__(self) -> None:
        for name in ("min_top_share", "error_budget_deg", "settle_s", "min_departure_s"):
            v = getattr(self, name)
            _finite(f"ConfirmPolicy.{name}", v)
            if v < 0:
                raise ValueError(f"ConfirmPolicy.{name} must be >= 0, got {v!r}")
        if self.min_top_share > 1.0:
            raise ValueError("ConfirmPolicy.min_top_share must be within [0, 1]")


def _finite(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


def _pair(*ids: str | None) -> tuple[str, ...]:
    """Distinct non-None ids in order, at most two."""
    out: list[str] = []
    for i in ids:
        if i is not None and i not in out:
            out.append(i)
    return tuple(out[:2])


def decide(
    *,
    outcome: str,
    margin: float,
    confidence: float,
    destructive: bool,
    panel_at_onset: str | None,
    panel_at_end: str | None,
    min_confidence: float = 0.35,
    min_margin: float = 0.25,
    evidence: Evidence | None = None,
    policy: ConfirmPolicy | None = None,
) -> ConfirmDecision:
    """Decide whether an XR-targeted action needs the user to confirm. Pure.

    Checked in this order, first match wins (the order only picks the *reported*
    reason; any match holds the action):

    1. ``outcome == "none"`` -> ``NO_TARGET``, no prompt (use keyboard focus). A target
       that never came from a ray cannot be misrouted by one, so even a destructive
       action does not prompt here — the same stance as ``needs_confirm`` for focus
       fallbacks.
    2. ``outcome == "ambiguous"`` -> ``AMBIGUOUS_PANELS``.
    3. ``evidence.settled_s < policy.settle_s`` with a ``prior_panel`` ->
       ``RECENT_PANEL_SWITCH`` (offers the bound panel and the prior one).
    4. ``evidence.rival_deg < policy.error_budget_deg`` -> ``NEAR_PANEL_EDGE`` (offers the
       bound panel and the neighbour).
    5. a changed target -> ``TARGET_CHANGED_DURING_UTTERANCE``. With ``evidence.departure_s``
       measured: the gaze has rested on a different panel for at least
       ``policy.min_departure_s``. Without it: both panels known and different. A missing
       observation (``None``) is *not* a change: absence of data is not a signal.
    6. ``destructive`` -> ``DESTRUCTIVE_ACTION``. ``bound`` means the target came from a ray.
    7. ``confidence < min_confidence``, ``margin < min_margin`` or
       ``evidence.top_share < policy.min_top_share`` -> ``LOW_CONFIDENCE``.
       The thresholds are inclusive on the passing side: a value *equal* to its
       threshold is confident, matching ``route_target``'s ``>=``.

    ``confidence`` is within [0, 1]; ``margin`` is the binder's lead of the best panel over
    the runner-up (>= 0). Bad numbers raise ``ValueError`` — they are a bug at the seam.
    Every rule is monotone: more of the signal never removes a hold.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")
    for name, value in (("margin", margin), ("confidence", confidence),
                        ("min_confidence", min_confidence), ("min_margin", min_margin)):
        _finite(name, value)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be within [0, 1], got {confidence!r}")
    if margin < 0.0:
        raise ValueError(f"margin must be >= 0, got {margin!r}")
    if min_confidence < 0.0 or min_margin < 0.0:
        raise ValueError("min_confidence and min_margin must be >= 0")
    ev = evidence if evidence is not None else Evidence()
    pol = policy if policy is not None else ConfirmPolicy()

    if outcome == "none":
        return ConfirmDecision(False, ConfirmReason.NO_TARGET)
    if outcome == "ambiguous":
        return ConfirmDecision(True, ConfirmReason.AMBIGUOUS_PANELS,
                               candidates=_pair(ev.panel_id, ev.runner_up))
    if ev.prior_panel is not None and ev.settled_s is not None and ev.settled_s < pol.settle_s:
        return ConfirmDecision(True, ConfirmReason.RECENT_PANEL_SWITCH,
                               candidates=_pair(ev.panel_id, ev.prior_panel))
    if ev.rival_deg is not None and ev.rival_deg < pol.error_budget_deg:
        return ConfirmDecision(True, ConfirmReason.NEAR_PANEL_EDGE,
                               candidates=_pair(ev.panel_id, ev.rival_id))
    if ev.departure_s is not None:
        changed = ev.departure_s >= pol.min_departure_s and ev.departure_s > 0.0
    else:
        changed = panel_at_onset is not None and panel_at_end is not None and panel_at_onset != panel_at_end
    if changed:
        return ConfirmDecision(True, ConfirmReason.TARGET_CHANGED_DURING_UTTERANCE,
                               candidates=_pair(ev.panel_id, ev.departure_panel or panel_at_end))
    if destructive:
        return ConfirmDecision(True, ConfirmReason.DESTRUCTIVE_ACTION, candidates=_pair(ev.panel_id))
    if (confidence < min_confidence or margin < min_margin
            or (ev.top_share is not None and ev.top_share < pol.min_top_share)):
        return ConfirmDecision(True, ConfirmReason.LOW_CONFIDENCE, candidates=_pair(ev.panel_id, ev.runner_up))
    return ConfirmDecision(False, ConfirmReason.NONE)


def expected_prompt_rate(decisions: Iterable[ConfirmDecision]) -> float:
    """Fraction of ``decisions`` that hold for a confirmation; 0.0 for an empty input.

    ``NO_TARGET`` is not a prompt (the caller falls back to keyboard focus), so it counts
    as silent. This measures the firing rate of the *thresholds on whatever mix is passed
    in*. The tests feed it a SYNTHETIC mix, so the "< 5%" they assert is a property of
    these defaults on that invented data, not a measured rate of real users — re-measure
    on real sessions before trusting it (a guard that fired on every realistic burst has
    shipped in this project once already).
    """
    total = 0
    held = 0
    for d in decisions:
        total += 1
        held += d.confirm
    return held / total if total else 0.0
