"""A bounded walk over an accessibility tree, producing :class:`SemanticCandidate` copies.

The one producer behind two consumers (#164): Screen-Grounded Dictation reads the
*labels and text* the walk returns to bias the next burst's vocabulary (ADR-v2-051),
and the Voice Pilot reads the *actionable* candidates to resolve "click Save"
(ADR-v2-007). Both used to need "a producer of the text visible on screen" and neither
had one; this module is the platform-independent half of it, and
``platform/linux/accessibility.py`` is the AT-SPI half.

**Pure, and generic over the toolkit.** Nothing here imports ``pyatspi``, PyObjC or a
Win32 binding. The walk drives a :class:`NodeOps` adapter that knows how to read one
node's facts and list its children; the AT-SPI adapter implements it over ``pyatspi``,
and the tests implement it over plain Python objects. The clock is injected, so every
bound is testable without sleeping.

**Every bound is a hard stop, and the walk says which one it hit.** An accessibility
tree is not small — a spreadsheet exposes every cell, a browser every DOM node — and
the walk runs while the user is holding the key. So it stops at whichever comes first:

* ``max_nodes`` nodes read (children are enumerated through ``islice``, so a list of
  ten thousand rows costs at most the remaining budget, not ten thousand calls);
* ``max_depth`` levels below the window (deeper subtrees are not entered);
* ``budget_s`` seconds of the injected clock since the walk began.

A bound cannot pre-empt one blocked call — a synchronous D-Bus request to a hung
application waits for the bus timeout — which is why the callers also run the walk
under a wall-clock deadline (``grounding/onscreen.py``).

**Hidden subtrees are skipped.** A node the toolkit reports as not showing is neither
emitted nor descended into: a collapsed menu's items and an inactive tab's contents are
not "visible on screen", and biasing dictation toward them, or clicking one by voice,
would be acting on something the user cannot see.

**Copies, never live nodes.** Each candidate is a :class:`SemanticCandidate` (ADR-v2-151's
vocabulary), with an ``entity_id`` that is only valid for this walk. The live node for
each id comes back separately in :attr:`WalkResult.handles`, which the backend keeps to
itself so that ``perform`` can act on exactly the node that was matched.

Nothing is logged here, and in particular no label or text: on-screen text is user
content (the spec's privacy rule), so a debug log carries counts and the stop reason.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from itertools import islice
from typing import Any, Protocol

from yazses.grounding.contracts import SemanticCandidate, SemanticSourceKind

#: What a candidate's ``role`` says when the toolkit reported none. The contract refuses
#: an empty role, and "we do not know" is the truthful value.
UNKNOWN_ROLE = "unknown"

#: Stop reasons, as :attr:`WalkResult.stopped` reports them.
STOP_MAX_NODES = "max_nodes"
STOP_BUDGET = "budget"


@dataclass(frozen=True)
class TreeLimits:
    """The hard bounds of one walk. Validated at construction, never clamped.

    The defaults are starting points chosen for a hold-to-talk burst, not measured
    optima: 600 nodes covers a typical dialog or editor window with its toolbars, and
    0.3 s is short enough to finish while the user is still speaking. ``max_text_chars``
    caps how much of one node's text content is read, so one long document cannot
    crowd out every label around it.
    """

    max_nodes: int = 600
    max_depth: int = 32
    budget_s: float = 0.3
    max_text_chars: int = 400

    def __post_init__(self) -> None:
        for name in ("max_nodes", "max_depth", "max_text_chars"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"TreeLimits.{name} must be a positive integer, got {value!r}")
        if not (self.budget_s > 0.0):  # also refuses NaN, which compares False
            raise ValueError(f"TreeLimits.budget_s must be positive, got {self.budget_s!r}")


@dataclass(frozen=True)
class NodeFacts:
    """What one node told the adapter. ``text`` is empty unless it was safe to read.

    The adapter, not the walk, decides what is safe: the AT-SPI adapter never reads the
    text of a password field or of an editable field, so a secret typed into one can
    never reach a prompt or a match.
    """

    name: str = ""
    role: str = ""
    showing: bool = True
    actions: tuple[str, ...] = ()
    text: str = ""


class NodeOps(Protocol):
    """How the walk reads a toolkit's nodes. Implemented per platform; faked in tests."""

    def facts(self, node: Any, limits: TreeLimits) -> NodeFacts | None:
        """This node's facts, or ``None`` when it is gone or unreadable (skip it)."""
        ...

    def children(self, node: Any) -> Iterable[Any]:
        """This node's children, in reading order. May be lazy; may raise."""
        ...


@dataclass(frozen=True)
class WalkResult:
    """The walk's output. ``handles`` maps each candidate's id to its live node.

    ``handles`` must never leave the backend that walked: a live node is exactly what
    ADR-v2-151 forbids in a value that crosses a seam. It is here only so the backend
    can keep it for ``perform``.
    """

    candidates: tuple[SemanticCandidate, ...] = ()
    handles: dict[str, Any] = field(default_factory=dict)
    visited: int = 0
    stopped: str | None = None


def _label(facts: NodeFacts, limits: TreeLimits) -> str:
    """The node's name, else the start of its text, else ``""``. Whitespace-collapsed."""
    raw = facts.name or facts.text[: limits.max_text_chars]
    return " ".join((raw or "").split())


def walk(
    root: Any,
    ops: NodeOps,
    limits: TreeLimits,
    *,
    clock: Callable[[], float],
    captured_at_s: float,
    id_prefix: str = "n",
) -> WalkResult:
    """Walk *root*'s subtree in reading order (pre-order), within *limits*. Pure.

    Emits one candidate per showing node that has a label. *root* itself is always
    read, even if it reports not showing, because the caller chose it as the window
    to look at. Never raises: a node that raises while being read is skipped with its
    subtree, which is what a node that vanished mid-walk looks like.

    *id_prefix* lets a backend make ids unique across its own snapshots, so an id kept
    from an older walk can never name a node of a newer one.
    """
    start = clock()
    candidates: list[SemanticCandidate] = []
    handles: dict[str, Any] = {}
    visited = 0
    stopped: str | None = None
    truncated = False
    # Explicit stack instead of recursion: a pathological tree must not reach
    # Python's recursion limit, and the depth bound must be the only depth limit.
    stack: list[tuple[Any, int]] = [(root, 0)]
    while stack:
        if visited >= limits.max_nodes:
            stopped = STOP_MAX_NODES
            break
        if clock() - start >= limits.budget_s:
            stopped = STOP_BUDGET
            break
        node, depth = stack.pop()
        visited += 1
        try:
            facts = ops.facts(node, limits)
        except Exception:
            facts = None
        if facts is None:
            continue
        if depth > 0 and not facts.showing:
            continue  # neither this node nor anything under it is on screen
        label = _label(facts, limits)
        if label:
            entity_id = f"{id_prefix}{len(candidates)}"
            try:
                candidates.append(SemanticCandidate(
                    source=SemanticSourceKind.ACCESSIBILITY,
                    entity_id=entity_id,
                    role=(facts.role or "").strip() or UNKNOWN_ROLE,
                    captured_at_s=captured_at_s,
                    confidence=1.0,
                    label=label,
                    actions=tuple(a for a in facts.actions if isinstance(a, str) and a),
                ))
                handles[entity_id] = node
            except ValueError:
                pass  # a value the contract refuses is skipped, never coerced
        if depth >= limits.max_depth:
            continue
        # Siblings already waiting on the stack count against the bound, so the number
        # of children ever *enumerated* -- each one a call into the toolkit -- stays
        # within ``max_nodes`` plus one look-ahead per node read. In a window whose top
        # level alone holds hundreds of nodes that favours breadth over depth, which is
        # the right side to err on. The look-ahead is how a cut is noticed: a walk that
        # silently dropped children would report itself complete.
        remaining = limits.max_nodes - visited - len(stack)
        try:
            raw = list(islice(ops.children(node), max(remaining, 0) + 1))
        except Exception:
            raw = []
        if len(raw) > remaining:
            truncated = True
            raw = raw[: max(remaining, 0)]
        kids = [k for k in raw if k is not None]
        # Reversed onto the stack so the first child is popped first: reading order.
        for kid in reversed(kids):
            stack.append((kid, depth + 1))
    if stopped is None and truncated:
        stopped = STOP_MAX_NODES
    return WalkResult(
        candidates=tuple(candidates), handles=handles, visited=visited, stopped=stopped,
    )


__all__ = [
    "STOP_BUDGET",
    "STOP_MAX_NODES",
    "UNKNOWN_ROLE",
    "NodeFacts",
    "NodeOps",
    "TreeLimits",
    "WalkResult",
    "walk",
]
