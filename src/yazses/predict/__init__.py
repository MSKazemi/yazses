"""Predictive dictation completion (ADR-v2-016).

A tiny on-device LLM proposes the rest of a phrase on a pause; you accept by voice.

* ``complete`` -- pure: parse accept/decline phrases, merge an accepted suggestion.
* ``session`` -- pure: the pending-suggestion lifecycle (context, staleness, expiry,
  what the next utterance does to an offer).
* ``generator`` -- the llama.cpp backend, reused from ADR-013 (``llama-cpp-python``,
  the ``slm`` extra), imported lazily on first use.
* ``runtime`` -- the background worker the daemon hands typed bursts to, so
  generation never blocks injection.

Wired from ``core/daemon.py``. OFF by default.
"""
