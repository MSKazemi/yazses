"""Sign-Language Input — SLR (ADR-v2-054).

Deaf/HoH signers dictate by signing to the webcam; ASL is recognized on-device and injected as
text. The ``segment`` module is the pure hand-presence + sign-burst boundary detector; the
SignGemma/Uni-Sign model + MediaPipe Hands are lazy behind the ``sign`` extra. OFF by default.
"""
