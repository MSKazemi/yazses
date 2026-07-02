"""Entity Inverse Text Normalization (ADR-v2-045).

Rewrite correctly-heard-but-wrongly-written spoken entities into written form with no command
words: "john dot doe at gmail dot com" → john.doe@gmail.com, "version two point one" → v2.1.
The ``normalize`` module is a pure, conservative stdlib rule set; the neural context-aware ITN
LM (for URLs/dates/currency) is deferred behind the ``itn`` extra. OFF by default.
"""
