"""Voice-Driven Document-Wide Find-and-Replace (ADR-v2-068).

Edit the whole document by voice, not just the last utterance. The ``parse`` module is the pure
command parser + apply preview; the AT-SPI text-range editing backend is deferred. OFF by default.
"""
