"""Involuntary-Vocalization Auto-Excision (ADR-v2-102).

Detect and delete cough/throat-clear/sneeze from the dictation stream. The ``excise`` module is the
pure detector + span-removal; the acoustic classifier is the lazy extra. OFF by default.
"""
