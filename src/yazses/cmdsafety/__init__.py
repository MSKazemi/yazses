"""Terminal Command Safety Gate (ADR-v2-065).

Hold a destructive shell command until spoken confirmation when dictation targets a terminal. The
``classify`` module is the pure risk ruleset + confirm state machine; focus-is-a-terminal
detection and a fuzzy classifier are deferred. OFF by default.
"""
