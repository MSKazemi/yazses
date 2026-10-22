"""The bounded accessibility-tree walk both #164 consumers share (`grounding/treewalk.py`).

Pure: the tree is plain Python objects behind a fake `NodeOps`, and the clock is a
counter. What is pinned is what makes the walk safe to run while the user holds the key
-- every bound stops it, hidden subtrees are never entered, a node that raises costs only
itself -- and what makes its output usable: reading order, copies not live nodes, and
ids that map back to exactly the node they describe.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import pytest

from yazses.grounding.contracts import SemanticCandidate, SemanticSourceKind
from yazses.grounding.treewalk import (
    STOP_BUDGET,
    STOP_MAX_NODES,
    UNKNOWN_ROLE,
    NodeFacts,
    TreeLimits,
    walk,
)


@dataclass(eq=False)
class N:
    name: str = ""
    role: str = "push button"
    showing: bool = True
    actions: tuple[str, ...] = ()
    text: str = ""
    kids: list = field(default_factory=list)
    boom: bool = False          # facts() raises
    kids_boom: bool = False     # children() raises


class Ops:
    def __init__(self) -> None:
        self.read: list[N] = []
        self.enumerated = 0

    def facts(self, node: N, limits: TreeLimits) -> NodeFacts | None:
        self.read.append(node)
        if node.boom:
            raise RuntimeError("defunct node")
        return NodeFacts(name=node.name, role=node.role, showing=node.showing,
                         actions=node.actions, text=node.text)

    def children(self, node: N):
        if node.kids_boom:
            raise RuntimeError("children vanished")
        for kid in node.kids:
            self.enumerated += 1
            yield kid


class Clock:
    """Advances by *step* on every read, so a budget is crossed after a known count."""

    def __init__(self, step: float = 0.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


def _walk(root, limits=None, clock=None, ops=None):
    return walk(root, ops or Ops(), limits or TreeLimits(), clock=clock or Clock(),
                captured_at_s=12.5)


def _labels(result) -> list[str]:
    return [c.label for c in result.candidates]


# ---- output shape ------------------------------------------------------------------------


def test_labelled_nodes_come_back_in_reading_order():
    root = N("Window", role="frame", kids=[
        N("File", kids=[N("Open"), N("Save")]),
        N("Body", role="panel", kids=[N("Aoife")]),
    ])
    assert _labels(_walk(root)) == ["Window", "File", "Open", "Save", "Body", "Aoife"]


def test_every_candidate_is_an_accessibility_copy_with_the_callers_timestamp():
    result = _walk(N("Save", actions=("click",)))
    (only,) = result.candidates
    assert isinstance(only, SemanticCandidate)
    assert only.source is SemanticSourceKind.ACCESSIBILITY
    assert only.captured_at_s == 12.5
    assert only.actions == ("click",)
    assert only.role == "push button"


def test_each_id_maps_back_to_exactly_the_node_it_describes():
    save, cancel = N("Save"), N("Cancel")
    result = _walk(N("Dialog", kids=[save, cancel]))
    by_label = {c.label: result.handles[c.entity_id] for c in result.candidates}
    assert by_label["Save"] is save
    assert by_label["Cancel"] is cancel
    assert len({c.entity_id for c in result.candidates}) == len(result.candidates)


def test_a_node_with_no_name_is_labelled_by_its_text_and_unlabelled_nodes_are_skipped():
    root = N("", role="panel", kids=[N("", role="paragraph", text="Hello  Nguyen\nthere"),
                                     N("", role="filler")])
    assert _labels(_walk(root)) == ["Hello Nguyen there"]


def test_text_is_cut_at_the_per_node_limit():
    root = N("", role="paragraph", text="x" * 50)
    (only,) = _walk(root, TreeLimits(max_text_chars=10)).candidates
    assert only.label == "x" * 10


def test_an_empty_role_is_reported_as_unknown_not_refused():
    (only,) = _walk(N("Save", role="  ")).candidates
    assert only.role == UNKNOWN_ROLE


# ---- what is not on screen ----------------------------------------------------------------


def test_a_hidden_node_and_everything_under_it_is_skipped():
    menu = N("Edit menu", showing=False, kids=[N("Delete everything")])
    root = N("Window", kids=[menu, N("Save")])
    ops = Ops()
    assert _labels(_walk(root, ops=ops)) == ["Window", "Save"]
    assert all(n.name != "Delete everything" for n in ops.read), "a hidden subtree was read"


def test_the_root_is_read_even_when_it_reports_not_showing():
    """The caller chose it as the window to look at; some toolkits never set SHOWING on it."""
    root = N("Window", showing=False, kids=[N("Save")])
    assert _labels(_walk(root)) == ["Window", "Save"]


# ---- the bounds ---------------------------------------------------------------------------


def test_the_node_bound_stops_the_walk_and_says_so():
    root = N("root", kids=[N(f"b{i}") for i in range(50)])
    result = _walk(root, TreeLimits(max_nodes=10))
    assert result.visited <= 10
    assert result.stopped == STOP_MAX_NODES


def test_the_node_bound_also_caps_how_many_children_are_enumerated():
    """Enumerating a child is a call into the toolkit; ten thousand rows must not cost that."""
    ops = Ops()
    root = N("table", kids=[N(f"row {i}") for i in range(10_000)])
    _walk(root, TreeLimits(max_nodes=20), ops=ops)
    assert ops.enumerated <= 20


def test_the_depth_bound_does_not_descend_further():
    deep = N("level 0")
    node = deep
    for i in range(1, 10):
        child = N(f"level {i}")
        node.kids.append(child)
        node = child
    labels = _labels(_walk(deep, TreeLimits(max_depth=3)))
    assert labels == ["level 0", "level 1", "level 2", "level 3"]


def test_the_time_budget_stops_the_walk_and_says_so():
    root = N("root", kids=[N(f"b{i}") for i in range(100)])
    # Each clock read advances 0.05 s; a 0.3 s budget is spent after a handful of nodes.
    result = _walk(root, TreeLimits(budget_s=0.3), clock=Clock(step=0.05))
    assert result.stopped == STOP_BUDGET
    assert result.visited < 10


def test_a_tree_inside_every_bound_reports_no_stop():
    assert _walk(N("only")).stopped is None


def test_a_pathological_depth_does_not_hit_the_recursion_limit():
    deep = N("0")
    node = deep
    for i in range(5_000):
        child = N(str(i + 1))
        node.kids.append(child)
        node = child
    result = _walk(deep, TreeLimits(max_nodes=10_000, max_depth=10_000))
    assert result.visited == 5_001


# ---- failure is local --------------------------------------------------------------------


def test_a_node_that_raises_is_skipped_with_its_subtree_and_the_walk_continues():
    root = N("Window", kids=[N("gone", boom=True, kids=[N("under gone")]), N("Save")])
    assert _labels(_walk(root)) == ["Window", "Save"]


def test_children_that_raise_end_that_branch_only():
    root = N("Window", kids=[N("broken", kids_boom=True), N("Save")])
    assert _labels(_walk(root)) == ["Window", "broken", "Save"]


def test_none_children_are_ignored():
    root = N("Window", kids=[None, N("Save")])
    assert _labels(_walk(root)) == ["Window", "Save"]


# ---- the limits themselves ----------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"max_nodes": 0}, {"max_depth": -1}, {"max_text_chars": 0},
        {"budget_s": 0.0}, {"budget_s": float("nan")}, {"max_nodes": 2.5},
    ],
)
def test_nonsense_limits_are_refused_at_construction(bad):
    with pytest.raises(ValueError):
        TreeLimits(**bad)


def test_limits_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        TreeLimits().max_nodes = 5  # type: ignore[misc]


def test_the_walk_imports_no_platform_binding_and_reads_no_clock():
    """Pure: the AT-SPI half lives in `platform/linux/atspi_tree.py`."""
    import ast
    from pathlib import Path

    import yazses.grounding.treewalk as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {"pyatspi", "gi", "time", "threading", "socket", "os"}
