"""Smart-Paste Format Adaptation (ADR-v2-036).

Adapt injected syntax to the target surface (markdown/code/email/terminal/rich): bullets,
URL autolinking, prose vs code casing. The ``adapt`` module is the pure classifier + policy
over local window metadata; no model needed. OFF by default.
"""
