"""Speaking Coach — private on-device speech analytics (ADR-v2-035).

Communication-style metrics over your own dictation: filler-word rate, words-per-minute,
vocabulary diversity. The ``analytics`` module is the pure stats core (no new dependency);
aggregation/trends draw from the opt-in encrypted corpus. Distinct from Vocal-Strain Guard
(physiology) and Confidence Ink (STT confidence). OFF by default.
"""
