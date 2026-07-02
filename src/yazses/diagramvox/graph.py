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


def parse_graph_utterance(text: str) -> Graph:
    """Parse a dictated flowchart into a :class:`Graph`. Pure."""
    s = re.sub(r"^\s*(?:flowchart|graph|diagram)\s*[:\-]?\s*", "", (text or "").strip(),
               flags=re.IGNORECASE)
    nodes = []
    edges = []

    def add_node(n):
        if n and n not in nodes:
            nodes.append(n)

    for clause in re.split(r"[;\n]", s):
        c = clause.strip()
        if not c:
            continue
        m = _EDGE.match(c)
        if m:
            src, dst, label = _norm(m.group(1)), _norm(m.group(2)), _norm(m.group(3) or "")
            add_node(src)
            add_node(dst)
            edges.append(Edge(src, dst, label))
        else:
            add_node(_norm(c))
    return Graph(nodes=nodes, edges=edges)
