"""Pronunciation Feedback — L2 practice mode (ADR-v2-041).

Dictate a target phrase and get per-phoneme goodness-of-pronunciation feedback. The ``score``
module is the pure classification/aggregation core; the wav2vec2 GOP model is lazy behind the
``pronunciation`` extra. OFF by default.
"""
