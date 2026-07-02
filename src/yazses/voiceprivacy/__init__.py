"""Corpus Voiceprint Scrub — de-identify stored learning audio (ADR-v2-048).

Speaker-anonymize corpus audio clips before storage so retained recordings preserve what was
said but not an identifiable voice. The ``anonymize`` module is the pure DSP core (pitch/formant
shift); the neural kNN-VC anonymizer is deferred behind the ``voiceprivacy`` extra. OFF by default.
"""
