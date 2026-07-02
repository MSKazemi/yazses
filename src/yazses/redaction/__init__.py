"""Redaction Ink — mask secrets at injection time (ADR-v2-046).

Detect PII/secrets in the transcript before it is typed and mask or hold them. The ``scrub``
module is the pure, dependency-free detector set (regex + Luhn); free-form PII via GLiNER is
deferred behind the ``pii`` extra. OFF by default.
"""
