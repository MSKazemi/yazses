"""The hands-free recovery hierarchy as a testable rule (pure) -- ADR-v2-148, roadmap Phase 6.

When the signal an action preferred fails, what may stand in for it? The roadmap's answer is an
ordered list, and its last line is the one that matters:

1. the high-confidence preferred signal;
2. a lower-risk alternate modality the user *named* (a spoken target, the pointer already on it);
3. the focused / current target;
4. an explicit "cannot act" -- with feedback, never silence.

"Never silently switch from a failed gaze route to a destructive action on another window." This
module is that sentence as code: :func:`recover` takes what is known and returns where the action
goes, or that it goes nowhere and what to tell the user.

Three rules, each pinned by a test:

* **A fallback never raises the consequence.** The action is an input and an output of nothing:
  recovery chooses a *target*, never a different action, so a failed route cannot turn a focus into
  a close.
* **A destructive action only recovers onto a target the user chose.** An inferred stand-in -- the
  focused window -- is exactly "another window" that gaze did not pick, so it is refused. An
  alternate modality qualifies only when it is ``explicit`` (the user said or pointed at the
  target), and even then the existing confirmation policy still applies.
* **Degradation is explained, and "cannot act" is a message.** Any result that is not the
  preferred route carries non-empty ``feedback``; a refusal says what failed and what to do.

The consequence vocabulary is :class:`yazses.activation.confirm.Consequence`, the project's
existing reversible/irreversible classification, not a second one. Pure and dependency-free
beyond that pure module (AGENTS.md rule 5).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from yazses.activation.confirm import Consequence

__all__ = ["Recovery", "Route", "Signal", "recover"]


class Route(Enum):
    """Which rung of the hierarchy the action will use."""

    PREFERRED = "preferred"
    ALTERNATE = "alternate"
    FOCUSED = "focused"
    NONE = "none"  # cannot act


@dataclass(frozen=True)
class Signal:
    """One way of naming the target. Names and a target handle only -- never a sample value."""

    name: str
    target: Any = None
    #: Healthy and confident enough to act on, as the owning component judged it.
    usable: bool = False
    #: The user chose this target (said it, or pointed at it) rather than it being inferred.
    explicit: bool = False


@dataclass(frozen=True)
class Recovery:
    """Where an action goes, or why it goes nowhere."""

    route: Route
    target: Any
    via: str
    #: The preferred signal was not the one used. Always comes with ``feedback``.
    degraded: bool
    #: The existing confirmation policy applies (every irreversible action, on every route).
    requires_confirmation: bool
    feedback: str

    @property
    def acts(self) -> bool:
        """Does the action go ahead at all?"""
        return self.route is not Route.NONE


def recover(
    consequence: Consequence,
    preferred: Signal,
    alternates: Sequence[Signal] = (),
    focused: Any = None,
) -> Recovery:
    """Choose a target for an action, or refuse it. Pure and total.

    ``preferred`` is the signal the action was meant to use (gaze for "close this"); ``alternates``
    are other modalities in the order to try them; ``focused`` is the current focused target or
    ``None``. ``consequence`` is the action's own classification and is never changed.
    """
    irreversible = consequence is Consequence.IRREVERSIBLE
    confirm = irreversible

    if preferred.usable and preferred.target is not None:
        return Recovery(Route.PREFERRED, preferred.target, preferred.name, False, confirm, "")

    for alt in alternates:
        if not (alt.usable and alt.target is not None):
            continue
        if irreversible and not alt.explicit:
            continue  # an inferred stand-in is not a choice the user made
        return Recovery(
            Route.ALTERNATE, alt.target, alt.name, True, confirm,
            f"{preferred.name} could not choose a target, so this used {alt.name} instead.",
        )

    if focused is not None and not irreversible:
        return Recovery(
            Route.FOCUSED, focused, "focused target", True, False,
            f"{preferred.name} could not choose a target, so this went to the focused one.",
        )

    if irreversible:
        why = (
            f"{preferred.name} could not tell which target you meant, and this cannot be undone, "
            "so nothing was done. Say or point at the target and try again."
        )
    else:
        why = f"{preferred.name} could not choose a target and there is no focused one, so nothing was done."
    return Recovery(Route.NONE, None, "", True, False, why)
