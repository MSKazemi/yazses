"""Spoken Shell Pipeline Builder (ADR-v2-082).

Speak pipeline stages → render a shell pipeline as text (never executed until confirmed). The
``build`` module is the pure parser + renderer + dry-run wrapper; an NL2Bash SLM is deferred.
OFF by default.
"""
