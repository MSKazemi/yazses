"""Head-Pointer — hands-free cursor via head pose (ADR-v2-052).

Move and click the mouse by head tilt, paired with voice for a fully hands-free desktop. The
``pointer`` module is the pure pose→cursor mapping + dwell-click state machine; the MediaPipe
FaceLandmarker capture is deferred behind the ``headpointer`` extra. OFF by default.
"""
