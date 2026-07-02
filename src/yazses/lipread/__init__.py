"""Silent Lip-Reading Input — VSR (ADR-v2-053).

Dictate with no audible voice: a webcam reads your lips. The ``gate`` module is the pure mouth
open/active detector that gates the heavy VSR model; the VSR conformer + MediaPipe face mesh are
lazy behind the ``vsr`` extra. Frames stay in-RAM. OFF by default.
"""
