"""Mood Ledger — speech-sentiment journal (ADR-v2-040).

Tag each dictation burst with an emotion label and build a private, local mood-over-time
view. The ``ledger`` module is the pure aggregation/trend core; the emotion2vec/SenseVoice SER
model is lazy behind the ``sentiment`` extra. Affective labels live only in the encrypted
corpus. OFF by default.
"""
