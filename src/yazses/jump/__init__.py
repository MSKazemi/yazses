"""Voice Jump-to-Symbol / Structural Hop (ADR-v2-081).

Resolve a spoken navigation target to an editor motion. The ``target`` module is the pure resolver
+ fuzzy picker + motion planner; the live LSP symbol list is deferred. OFF by default.
"""
