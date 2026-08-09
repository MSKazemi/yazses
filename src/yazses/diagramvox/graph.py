"""Spoken graph parsing + Mermaid/DOT rendering (pure) — ADR-v2-107.

Parse "X goes to Y [if LABEL]" clauses into a graph and render it as Mermaid or Graphviz DOT. Pure
grammar + string rendering; no model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_EDGE = re.compile(
    r"^(.*?)\s+(?:goes to|points to|connects to|leads to|->)\s+(.+?)"
    r"(?:\s+(?:if|when|on|labeled|labelled)\s+(.+))?$", re.IGNORECASE)

_AND = re.compile(r"\s+and\s+", re.IGNORECASE)
_LEADING_AND = re.compile(r"^and\s+", re.IGNORECASE)
# An edge connector anywhere in a fragment — used to tell "a comma that starts a new
# clause" apart from "a comma inside a label or a node name".
_CONNECTOR = re.compile(r"\b(?:goes to|points to|connects to|leads to)\b|->", re.IGNORECASE)
# A dictated utterance is a sentence, not a nested expression; this only bounds a
# pathological input so the parser can never blow the stack.
_MAX_CHAIN_DEPTH = 32


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _nid(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", name) or "n"


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    label: str = ""


@dataclass
class Graph:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    direction: str = "TD"

    def _isolated(self):
        connected = {e.src for e in self.edges} | {e.dst for e in self.edges}
        return [n for n in self.nodes if n not in connected]

    def to_mermaid(self) -> str:
        lines = [f"flowchart {self.direction}"]
        for e in self.edges:
            arrow = f"-->|{e.label}|" if e.label else "-->"
            lines.append(f"    {_nid(e.src)}[{e.src}] {arrow} {_nid(e.dst)}[{e.dst}]")
        for n in self._isolated():
            lines.append(f"    {_nid(n)}[{n}]")
        return "\n".join(lines)

    def to_dot(self) -> str:
        lines = ["digraph G {"]
        for e in self.edges:
            attr = f' [label="{e.label}"]' if e.label else ""
            lines.append(f'  "{e.src}" -> "{e.dst}"{attr};')
        for n in self._isolated():
            lines.append(f'  "{n}";')
        lines.append("}")
        return "\n".join(lines)


def _split_clauses(s: str):
    """Split an utterance into clauses on ";", a newline, and a clause-starting comma.

    A comma only separates when what follows starts a new clause — it carries an edge
    connector, or the conjunction that introduces one. Otherwise it belongs to the text it
    sits in, so a label keeps its punctuation ("... labeled sign in, please") instead of
    being truncated into a spurious node.
    """
    for chunk in re.split(r"[;\n]", s):
        parts = chunk.split(",")
        buf = parts[0]
        for part in parts[1:]:
            if _CONNECTOR.search(part) or _LEADING_AND.match(part.strip()):
                yield buf
                buf = part
            else:
                buf = f"{buf},{part}"
        yield buf


def parse_graph_utterance(text: str) -> Graph:
    """Parse a dictated flowchart into a :class:`Graph`. Pure.

    A clause is one edge ("A goes to B") or one bare node name, separated by ";", a newline,
    or a comma that starts a new clause. Within a clause, "and" fans out to multiple sources
    and/or destinations ("A and B goes to C" / "A goes to B and C"); an "and"-separated
    destination that is itself a full edge ("... and C goes to D") is a separate statement,
    while a lone one ("A goes to B goes to C") is a chain and links through (A→B, B→C).

    Nodes come back in the order they are spoken.
    """
    s = re.sub(r"^\s*(?:flowchart|graph|diagram)\s*[:\-]?\s*", "", (text or "").strip(),
               flags=re.IGNORECASE)
    nodes = []
    edges = []

    def add_node(n):
        if n and n not in nodes:
            nodes.append(n)

    def add_edge(src, dst, label):
        add_node(src)
        add_node(dst)
        edges.append(Edge(src, dst, label))

    def handle_clause(clause, depth=0):
        if depth > _MAX_CHAIN_DEPTH:
            return
        # A comma split can leave the conjunction stranded at the front
        # ("A goes to B, and C goes to D") — it is a separator, not part of the name.
        c = _LEADING_AND.sub("", clause.strip()).strip()
        if not c:
            return
        m = _EDGE.match(c)
        if not m:
            for n in _AND.split(c):
                add_node(_norm(n))
            return
        srcs = [_norm(p) for p in _AND.split(m.group(1)) if _norm(p)]
        label = _norm(m.group(3) or "")
        # Declare the sources before anything a chained clause adds, so the node order
        # follows the order they were spoken in.
        for src in srcs:
            add_node(src)

        parts = [p.strip() for p in _AND.split(m.group(2))]
        # A lone destination that parses as an edge is a *chain* ("A goes to B goes to C"):
        # link the sources through to its own sources, then let it emit its own edge. Only an
        # "and"-separated one is an independent statement, so the sources are never dropped.
        if len(parts) == 1 and _EDGE.match(parts[0]):
            inner = _EDGE.match(parts[0])
            entries = [_norm(p) for p in _AND.split(inner.group(1)) if _norm(p)]
            for src in srcs:
                for entry in entries:
                    add_edge(src, entry, label)
            handle_clause(parts[0], depth + 1)
            return

        dsts, chained = [], []
        for part in parts:
            if _EDGE.match(part):
                chained.append(part)   # "... and C goes to D" — its own statement
            else:
                dsts.append(_norm(part))
        for src in srcs:
            for dst in dsts:
                add_edge(src, dst, label)
        for part in chained:
            handle_clause(part, depth + 1)

    for clause in _split_clauses(s):
        handle_clause(clause)
    return Graph(nodes=nodes, edges=edges)
