"""Spoken Temporal Normalizer (ADR-v2-057).

Resolve spoken relative/absolute date expressions against the clock ("next Friday" → a concrete
date). The ``resolve`` module is the pure stdlib-datetime core (now injected); the neural SCATE
model + dateparser for messy phrasing are deferred behind a ``temporal`` extra. OFF by default.
"""
