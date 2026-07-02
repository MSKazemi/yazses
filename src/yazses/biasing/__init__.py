"""Hard Contextual Biasing (ADR-v2-069).

Bias decoding toward the user's names/jargon with a prefix trie, retraining-free. The ``trie``
module is the pure trie + N-best rescorer; the in-decoder logit-biasing hook (sherpa-onnx/WFST)
is deferred behind a ``biasing`` extra. OFF by default.
"""
