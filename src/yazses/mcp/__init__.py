"""MCP server surface (ADR-020): exactly two tools, over stdio, never HTTP.

ADR-020 decided YazSes may be called by another agent, and drew the boundary
tightly. The genuinely novel thing on offer is not transcription — it is **a
human**: an agent stuck on a decision only a person can make currently has to put
text on a screen and wait for someone to notice, read and type. Voice is the
cheapest interrupt a working person can service, because it needs neither their
eyes nor their hands.

Stdio only. YazSes's own IPC is a Unix socket, which is unreachable from another
machine *by construction* rather than by configuration; an HTTP surface would
trade that structural guarantee for "we bound to 127.0.0.1", on a daemon holding a
live microphone that can type into any focused window.
"""
