# ADR-v2-107 — Diagrams-as-Code by Voice (Mermaid/Graphviz)

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** markup (linear Markdown), [[adr-v2-091-spoken-table-csv]] (tabular), [[adr-011]]

## Context

Wave M research (#3) — "flowchart: start goes to login; login goes to dashboard if success, else to
error" → valid Mermaid/DOT source injected into the doc. Draw a flowchart/graph without ever touching
a mouse or canvas. Structured-Markup Dictation and Spoken Table Entry are linear/tabular; this is the
first **2-D graph** authoring path. Drawing tools are the least accessible software category for
motor- and vision-impaired users — text-to-diagram sidesteps the canvas entirely. Anchor: Mermaid
"diagrams as code" (used natively in GitHub/Obsidian); CHI'24 accessible-visualization *authoring*
work (TADA, Umwelt) points to text-first diagram construction as the accessible route.

## Decision

Add an opt-in **Diagrams-as-Code**: `[diagramvox] enabled=false`. Pure cores in
`diagramvox/graph.py`: `parse_graph_utterance(text)` → a `Graph(nodes, edges, direction)` from
"X goes to/points to Y [if LABEL]" clauses (split on `;`/newline), and `Graph.to_mermaid()` /
`Graph.to_dot()` renderers. Pure grammar + string rendering; no model, no drawing backend. OFF by
default.

## Consequences

- Hands-free 2-D diagram authoring for motor/vision-impaired engineers and students.
- Pure parse + render → fully testable.
- Distinct from Structured-Markup (2-D graph vs linear) and Spoken Table (graph vs grid).
- Privacy (ADR-011): local text only.
- Caveat: flowchart/graph subset (sequence/class diagrams are a later tier); off by default.
