"""On-Device Condense (ADR-v2-062).

Speak a rambling paragraph; a condense variant inserts a tightened summary instead of the
verbatim transcript. The ``extract`` module is the pure extractive-summary core; the abstractive
small-LLM is deferred behind the ``llm_cleanup`` extra. OFF by default.
"""
