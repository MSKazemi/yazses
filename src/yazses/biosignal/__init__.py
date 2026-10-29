"""Bio-signal switches: artifact-grade EEG/EMG/EOG detectors behind the activation seam.

Scope is deliberately narrow (ADR-v2-152): the *reliable* signals an electrode can give a
computer — muscle bursts, blinks, jaw clenches — measured against an explicit
false-positive budget. Decoding "thoughts" stays rejected (ADR-v2-129).

Everything here is dormant until ``[biosignal] enabled`` is set; see ``types.py`` for the
contract every module in this package shares.
"""
