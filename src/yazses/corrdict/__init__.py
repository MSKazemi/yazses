"""Self-Learning Correction Dictionary (ADR-v2-079).

Mine recurring ASR-output→edit pairs into a high-precision auto find→replace. The ``mine`` module
is the pure miner + applier; the corpus/EditWatcher supplies events and a seq-tagger is deferred.
OFF by default.
"""
