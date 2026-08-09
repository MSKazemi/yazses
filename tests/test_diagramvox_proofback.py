"""Diagrams-as-Code (ADR-v2-107) + Interruptible Read-Back Proofreading (ADR-v2-108) — pure cores."""
from __future__ import annotations

from yazses.diagramvox.graph import Edge, parse_graph_utterance
from yazses.proofback.align import Span, build_schedule, resolve_target, word_at

# ---- diagrams-as-code ------------------------------------------------------

def test_parse_graph_utterance():
    g = parse_graph_utterance("flowchart: start goes to login; login goes to dashboard if success")
    assert g.nodes == ["start", "login", "dashboard"]
    assert Edge("start", "login", "") in g.edges
    assert Edge("login", "dashboard", "success") in g.edges


def test_parse_graph_multi_edge_fanout_and_clauses():
    g = parse_graph_utterance("A goes to B and C, B goes to D")
    assert g.nodes == ["A", "B", "C", "D"]
    assert Edge("A", "B", "") in g.edges
    assert Edge("A", "C", "") in g.edges
    assert Edge("B", "D", "") in g.edges
    assert len(g.edges) == 3


def test_parse_graph_multi_source_fanin():
    g = parse_graph_utterance("A and B goes to C")
    assert Edge("A", "C", "") in g.edges and Edge("B", "C", "") in g.edges


def test_parse_graph_chained_and_clause_without_comma():
    g = parse_graph_utterance("A goes to B and C goes to D")
    assert Edge("A", "B", "") in g.edges
    assert Edge("C", "D", "") in g.edges
    # The chained clause must not jump the queue: nodes come back in spoken order.
    assert g.nodes == ["A", "B", "C", "D"]


def test_parse_graph_lone_chain_links_through_and_keeps_the_source():
    # "A goes to B goes to C" has no "and", so it is one chain, not two statements.
    # The source must never be dropped — an entry point silently vanishing from a
    # dictated flowchart is worse than a clumsy parse.
    g = parse_graph_utterance("start goes to login goes to dashboard")
    assert g.nodes == ["start", "login", "dashboard"]
    assert g.edges == [Edge("start", "login", ""), Edge("login", "dashboard", "")]


def test_parse_graph_comma_then_and_is_a_separator_not_a_node_name():
    g = parse_graph_utterance("A goes to B, and C goes to D")
    assert g.nodes == ["A", "B", "C", "D"]
    assert g.edges == [Edge("A", "B", ""), Edge("C", "D", "")]


def test_parse_graph_comma_inside_a_label_is_kept():
    # A comma only splits when what follows starts a new clause, so a label keeps its
    # punctuation instead of being truncated into a spurious isolated node.
    g = parse_graph_utterance("start goes to login labeled sign in, please")
    assert g.nodes == ["start", "login"]
    assert g.edges == [Edge("start", "login", "sign in, please")]


def test_parse_graph_fan_in_keeps_spoken_node_order():
    g = parse_graph_utterance("A and B goes to C")
    assert g.nodes == ["A", "B", "C"]


def test_parse_graph_deep_chain_is_bounded():
    # A pathological utterance must not blow the stack.
    g = parse_graph_utterance(" goes to ".join(f"N{i}" for i in range(200)))
    assert g.nodes[:3] == ["N0", "N1", "N2"]


def test_parse_graph_and_separated_isolated_nodes():
    g = parse_graph_utterance("A and B")
    assert g.nodes == ["A", "B"] and g.edges == []


def test_parse_graph_isolated_node():
    g = parse_graph_utterance("orphan")
    assert g.nodes == ["orphan"] and g.edges == []


def test_parse_graph_skips_empty_clauses():
    g = parse_graph_utterance("A goes to B;; ")          # trailing/double separators → empty clauses
    assert g.nodes == ["A", "B"] and len(g.edges) == 1


def test_to_mermaid_and_dot():
    g = parse_graph_utterance("A goes to B if yes; C")
    mer = g.to_mermaid()
    assert mer.startswith("flowchart TD")
    assert "A[A] -->|yes| B[B]" in mer
    assert "C[C]" in mer                                  # isolated node rendered
    dot = g.to_dot()
    assert dot.startswith("digraph G {") and dot.endswith("}")
    assert '"A" -> "B" [label="yes"];' in dot
    assert '"C";' in dot                                  # isolated node


# ---- interruptible read-back proofreading ----------------------------------

def test_build_schedule_scalar_and_list():
    sched = build_schedule(["the", "cat", "sat"], 200)
    assert sched == [Span(0, 0.0, 200.0), Span(1, 200.0, 400.0), Span(2, 400.0, 600.0)]
    sched2 = build_schedule(["a", "b"], [100, 300])
    assert sched2[1] == Span(1, 100.0, 400.0)
    assert build_schedule([], 200) == []


def test_word_at_and_clamp():
    sched = build_schedule(["the", "cat", "sat"], 200)
    assert word_at(sched, 250) == 1
    assert word_at(sched, 0) == 0
    assert word_at(sched, -50) == 0                       # before start → clamp to first
    assert word_at(sched, 9999) == 2                      # past end → clamp to last
    assert word_at([], 100) == -1


def test_resolve_target():
    assert resolve_target(2) == {"word_index": 2, "intent": "replace"}
    assert resolve_target(0, "delete") == {"word_index": 0, "intent": "delete"}


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "diagramvox" in slugs and "proofback" in slugs
    assert Config().diagramvox.enabled is False and Config().proofback.enabled is False
