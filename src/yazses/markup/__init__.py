"""Structured-Markup Dictation (ADR-v2-067).

Speak document structure and get Markdown/org markup instead of a run-on paragraph. The ``render``
module is the pure parse + emit core; an optional LLM for messy free-form tables is deferred. OFF
by default.
"""
